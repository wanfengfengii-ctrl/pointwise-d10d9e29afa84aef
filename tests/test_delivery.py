from fractions import Fraction as F
from pathlib import Path
import sqlite3
import sys
import tempfile
from wave import (ArchiveRepository, SampleBlock, GapEvent, EndEvent, push_event,
                  export_waveform, compute_windows)
from wave.archive.schema import ensure_schema
from wave.archive.codec import decode_record
from tests import BusinessCase, new_task, seal, rows, direct_reference


class TestDelivery(BusinessCase):
    def test_end_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix="wave-test-") as directory:
            path = str(Path(directory) / "day.sqlite")
            with ArchiveRepository(path) as repository:
                new_task(repository, input_start=F(1, 3))
                snapshot = seal(repository)
                expected = direct_reference([2, 4, 6, 8, 10], input_start=F(1, 3))
                self.assertEqual(rows(snapshot), expected)
                exported = export_waveform(repository, "day")
                batch = compute_windows(repository, "day", [(F(1, 3), 2)])
                state = repository.connection.serialize()
                ensure_schema(repository.connection)
                self.assertEqual(repository.connection.serialize(), state)
                from wave import FilterSpec, PhaseKernel
                identity = FilterSpec((PhaseKernel(0, ((0, 1),)),))
                new_task(repository, "thirds", input_start=F(1, 3), output_start=F(1, 3),
                         output_rate=3, spec=identity)
                seal(repository, "thirds", (3, 6))
                thirds_export = export_waveform(repository, "thirds")
                self.assertEqual([p["time"] for p in decode_record(thirds_export)["points"]],
                                 [[1, 3], [2, 3]])
                new_task(repository, "empty")
                empty = seal(repository, "empty", ())
                self.assertEqual(empty.points, ())
                self.assertTrue(empty.sealed)
                self.assertEqual(decode_record(export_waveform(repository, "empty"))["points"], [])
            calls = []
            def observe(frame, event, argument):
                if event == "call":
                    module = frame.f_globals.get("__name__", "")
                    if module in {"wave.conversion.kernel", "wave.conversion.processor",
                                  "wave.conversion.support"}:
                        calls.append((module, frame.f_code.co_name))
            previous_profile = sys.getprofile()
            try:
                sys.setprofile(observe)
                with ArchiveRepository(path) as repository:
                    self.assertEqual(rows(repository.read_waveform("day")), expected)
                    self.assertEqual(export_waveform(repository, "day"), exported)
                    self.assertEqual(export_waveform(repository, "thirds"), thirds_export)
                    from wave import read_window_results
                    self.assertEqual(read_window_results(repository, batch.batch_id), batch)
            finally:
                sys.setprofile(previous_profile)
            self.assertEqual(calls, [])
            document = decode_record(exported)
            self.assertEqual([point["time"] for point in document["points"]],
                             [[1, 2], [1, 1], [3, 2]])

    def test_event_publish_rollback(self):
        triggers = [
            "CREATE TEMP TRIGGER fail AFTER INSERT ON events BEGIN SELECT RAISE(ABORT,'event SQL failure'); END",
            "CREATE TEMP TRIGGER fail BEFORE INSERT ON waveform WHEN NEW.m=1 BEGIN SELECT RAISE(ABORT,'point SQL failure'); END",
            "CREATE TEMP TRIGGER fail BEFORE UPDATE ON delivery BEGIN SELECT RAISE(ABORT,'cursor SQL failure'); END",
        ]
        for trigger in triggers:
            with self.subTest(trigger=trigger), ArchiveRepository() as repository:
                new_task(repository)
                session_event = SampleBlock(0, (2, 4, 6, 8, 10))
                repository.connection.execute(trigger).close()
                before = repository.connection.serialize()
                from wave import CaptureSession
                session = CaptureSession(repository, "day")
                with self.assertRaises(sqlite3.IntegrityError):
                    session.push_event(session_event)
                self.assertFalse(repository.connection.in_transaction)
                self.assertEqual(repository.connection.serialize(), before)
                self.assertEqual(repository.load_delivery_state("day").event_count, 0)
                self.assertEqual(repository.load_timeline("day").frontier, 0)
                self.assertEqual(repository.read_waveform("day").points, ())
                repository.connection.execute("DROP TRIGGER fail").close()
                self.assertEqual([p.value for p in session.push_event(session_event)], [2, 5, 8])
                push_event(repository, "day", EndEvent(5))
                self.assertEqual(rows(repository.read_waveform("day")),
                                 direct_reference([2, 4, 6, 8, 10]))

    def test_after_end_and_close(self):
        first = seal(self.repo)
        new_task(self.repo, "other")
        other = seal(self.repo, "other", (20, 40, 60, 80, 100))
        for event in (SampleBlock(5, (99,)), GapEvent(5, 1), EndEvent(5)):
            with self.assertRaises(ValueError):
                push_event(self.repo, "day", event)
            self.assertEqual(self.repo.read_waveform("day"), first)
        iterator = self.repo.iter_waveform("day")
        self.assertEqual(next(iterator), first.points[0])
        iterator.close()
        new_task(self.repo, "active")
        push_event(self.repo, "active", SampleBlock(0, (7, 8)))
        for task_id, expected in (("other", other), ("day", first), ("other", other)):
            self.assertEqual(self.repo.read_waveform(task_id), expected)
            self.assertEqual(decode_record(export_waveform(self.repo, task_id))["source_id"],
                             expected.source_id)
        self.assertEqual(self.repo.read_waveform("other", 1, 2).points, other.points[1:2])
        with self.assertRaises(KeyError):
            self.repo.read_waveform("absent")
        with self.assertRaises(ValueError):
            export_waveform(self.repo, "active")

    def test_end_domain_and_finite_failure(self):
        push_event(self.repo, "day", SampleBlock(0, (2, 4)))
        self.assertEqual(len(self.repo.read_waveform("day").points), 1)
        self.repo.connection.execute(
            "CREATE TEMP TRIGGER fail_end BEFORE UPDATE ON delivery WHEN NEW.ended=1 "
            "BEGIN SELECT RAISE(ABORT,'end SQL failure'); END").close()
        before_end = self.repo.connection.serialize()
        with self.assertRaises(sqlite3.IntegrityError):
            push_event(self.repo, "day", EndEvent(2))
        self.assertEqual(self.repo.connection.serialize(), before_end)
        self.assertFalse(self.repo.read_waveform("day").sealed)
        self.repo.connection.execute("DROP TRIGGER fail_end").close()
        push_event(self.repo, "day", EndEvent(2))
        self.assertEqual(rows(self.repo.read_waveform("day")), direct_reference([2, 4]))
        self.assertEqual(self.repo.read_waveform("day").next_index, 2)
        from wave import FilterSpec, PhaseKernel
        huge = FilterSpec((PhaseKernel(0, ((0, 10 ** 400),)),))
        new_task(self.repo, "overflow", output_rate=3, spec=huge)
        before = self.repo.connection.serialize()
        with self.assertRaises(ValueError):
            push_event(self.repo, "overflow", SampleBlock(0, (2,)))
        self.assertEqual(self.repo.connection.serialize(), before)
