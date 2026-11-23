from fractions import Fraction as F
from itertools import product
from wave import (ArchiveRepository, SampleBlock, GapEvent, EndEvent, push_event)
from wave.assembly.replay import replay_events
from tests import BusinessCase, new_task, rows, direct_reference, scenario


class TestCapture(BusinessCase):
    def test_rational_grid(self):
        first = push_event(self.repo, "day", SampleBlock(0, (2, 4)))
        self.assertEqual([(p.index, p.value) for p in first], [(0, 2.0)])
        middle = push_event(self.repo, "day", SampleBlock(2, (6, 8, 10)))
        self.assertEqual([p.value for p in middle], [5.0, 8.0])
        tail = push_event(self.repo, "day", EndEvent(5))
        self.assertEqual([p.value for p in tail], [5.0])
        expected = [(0, F(0), 2.0, True), (1, F(1, 2), 5.0, True),
                    (2, F(1), 8.0, True), (3, F(3, 2), 5.0, True)]
        actual = rows(self.repo.read_waveform("day"))
        self.assertEqual(actual, expected)
        self.assertEqual(actual, direct_reference([2, 4, 6, 8, 10]))
        scenario("v1", [2, 4, 6, 8, 10], expected, actual, [1, 2, 1],
                 [len(first), len(middle), len(tail)],
                 ["wave/catalog/timegrid.py", "wave/conversion/kernel.py",
                  "wave/conversion/processor.py", "wave/archive/publish.py"],
                 "published rational coefficients and independent exact whole-record sum")
        new_task(self.repo, "offset", input_start=F(1, 3))
        push_event(self.repo, "offset", SampleBlock(0, (2, 4, 6, 8, 10)))
        push_event(self.repo, "offset", EndEvent(5))
        self.assertEqual(rows(self.repo.read_waveform("offset")),
                         direct_reference([2, 4, 6, 8, 10], input_start=F(1, 3)))
        self.assertEqual([p.index for p in self.repo.read_waveform("offset").points], [1, 2, 3])

    def test_chunk_invariance(self):
        values = [2, 4, 6, 8, 10]
        expected = direct_reference(values)
        # All 16 ordered partitions of the five-sample recording.
        for boundaries in product((False, True), repeat=4):
            with self.subTest(boundaries=boundaries), ArchiveRepository() as repository:
                new_task(repository)
                ends = [i + 1 for i, cut in enumerate(boundaries) if cut] + [5]
                previous = ()
                start = 0
                for stop in ends:
                    delivered = push_event(repository, "day", SampleBlock(start, values[start:stop]))
                    current = repository.read_waveform("day")
                    self.assertEqual(current.points[:len(previous)], previous)
                    self.assertEqual(current.points[len(previous):], delivered)
                    previous = current.points
                    start = stop
                push_event(repository, "day", EndEvent(5))
                self.assertEqual(rows(repository.read_waveform("day")), expected)
        for size in (1, 2, 3, 7):
            with ArchiveRepository() as repository:
                new_task(repository)
                data = [(-1) ** i * (i + 2) for i in range(13)]
                for start in range(0, len(data), size):
                    push_event(repository, "day", SampleBlock(start, data[start:start + size]))
                push_event(repository, "day", EndEvent(len(data)))
                self.assertEqual(rows(repository.read_waveform("day")), direct_reference(data))

    def test_overlap_rejected(self):
        push_event(self.repo, "day", SampleBlock(0, (2, 4)))
        before = self.repo.connection.serialize()
        for event in (SampleBlock(1, (9,)), GapEvent(1, 2),
                      SampleBlock(3, (9,)), GapEvent(3, 1), EndEvent(1)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                push_event(self.repo, "day", event)
            self.assertEqual(self.repo.connection.serialize(), before)
        for value in (float("nan"), float("inf"), -float("inf"), True, "6"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                push_event(self.repo, "day", {"kind": "samples", "start": 2, "values": [6, value]})
            self.assertEqual(self.repo.connection.serialize(), before)

    def test_read_ranges_and_offline_replay(self):
        events = [SampleBlock(0, (2, 4)), SampleBlock(2, (6, 8, 10)), EndEvent(5)]
        batches = replay_events(self.repo, "day", events)
        self.assertEqual([len(batch) for batch in batches], [1, 2, 1])
        self.assertEqual([p.index for p in self.repo.read_waveform("day", 1, 3).points], [1, 2])
        self.assertEqual(self.repo.read_waveform("day", 7, 9).points, ())
        with self.assertRaises(ValueError):
            self.repo.read_waveform("day", 3, 2)
        with self.assertRaises(ValueError):
            self.repo.read_waveform("day", True)
        with self.assertRaises(ValueError):
            replay_events(self.repo, "day", events)
        with ArchiveRepository() as repository:
            new_task(repository)
            for event in events:
                push_event(repository, "day", event)
            self.assertEqual(rows(repository.read_waveform("day")), rows(self.repo.read_waveform("day")))
