from fractions import Fraction as F
from pathlib import Path
import sqlite3
import tempfile
from wave import (ArchiveRepository, SampleBlock, EndEvent, push_event, export_waveform,
                  read_window_results)
from wave.archive.codec import canonical_json, decode_record, encode_rational
from wave.archive.schema import ensure_schema
from wave.assembly.replay import load_recording, run_workday
from tests import BusinessCase, new_task, rows, direct_reference


class TestArchive(BusinessCase):
    def test_codec_and_schema(self):
        record = {"time": F(-2, 6), "nested": [F(8, 10), None, True, 2.5]}
        self.assertEqual(decode_record(canonical_json(record)), record)
        self.assertEqual(encode_rational(F(-2, 6)), [-1, 3])
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                canonical_json({"value": value})
        with self.assertRaises(ValueError):
            decode_record('{"value":NaN}')
        before = self.repo.connection.serialize()
        ensure_schema(self.repo.connection)
        self.assertEqual(self.repo.connection.serialize(), before)
        self.repo.connection.execute("UPDATE metadata SET value=99 WHERE key='version'").close()
        with self.assertRaises(ValueError):
            ensure_schema(self.repo.connection)
        self.assertEqual(self.repo.connection.execute(
            "SELECT value FROM metadata WHERE key='version'").fetchone(), (99,))
        with sqlite3.connect(":memory:", isolation_level=None) as foreign:
            foreign.execute("CREATE TABLE unrelated(value)").close()
            with self.assertRaises(ValueError):
                ensure_schema(foreign)

    def test_disk_rollback_retry(self):
        with tempfile.TemporaryDirectory(prefix="wave-retry-") as directory:
            path = str(Path(directory) / "archive.sqlite")
            with ArchiveRepository(path) as repository:
                new_task(repository)
                repository.connection.execute(
                    "CREATE TEMP TRIGGER fail BEFORE UPDATE ON delivery "
                    "BEGIN SELECT RAISE(ABORT,'disk publication SQL failure'); END").close()
                with self.assertRaises(sqlite3.IntegrityError):
                    push_event(repository, "day", SampleBlock(0, (2, 4, 6, 8, 10)))
                self.assertEqual(repository.load_delivery_state("day").event_count, 0)
            with ArchiveRepository(path) as repository:
                self.assertEqual(repository.read_waveform("day").points, ())
                push_event(repository, "day", SampleBlock(0, (2, 4, 6, 8, 10)))
                push_event(repository, "day", EndEvent(5))
                self.assertEqual(rows(repository.read_waveform("day")),
                                 direct_reference([2, 4, 6, 8, 10]))
                saved = export_waveform(repository, "day")
            with ArchiveRepository(path) as repository:
                self.assertEqual(export_waveform(repository, "day"), saved)

    def test_offline_workday(self):
        recording = load_recording(Path(__file__).resolve().parents[1] / "samples" / "day.json")
        report = run_workday(self.repo, recording)
        snapshot = self.repo.read_waveform(report.task_id)
        self.assertEqual(rows(snapshot), direct_reference([2, 4, 0, 8, 10], {2}))
        self.assertEqual(report.exported, export_waveform(self.repo, report.task_id))
        self.assertEqual([len(batch) for batch in report.deliveries], [1, 1, 1, 1])
        mixed = report.windows.results[1]
        self.assertEqual((mixed.total, mixed.valid_count, mixed.coverage, mixed.rms),
                         (3, 1, F(1, 3), 2.0))
        self.assertEqual(read_window_results(self.repo, report.windows.batch_id), report.windows)
        before = self.repo.connection.serialize()
        with self.assertRaises(ValueError):
            run_workday(self.repo, recording)
        self.assertEqual(self.repo.connection.serialize(), before)
        from tests import scenario
        scenario("v8.demo_metrics", recording["events"],
                 [2.0, None, None, 5.0], [p.value for p in snapshot.points],
                 {"coverage": F(1, 3), "rms": 2.0},
                 {"coverage": mixed.coverage, "rms": mixed.rms},
                 ["wave/assembly/replay.py", "wave/archive/export.py",
                  "wave/quality/selection.py", "wave/quality/reducers.py",
                  "wave/quality/service.py"],
                 "explicit four-point waveform and independent valid-count/RMS arithmetic")
