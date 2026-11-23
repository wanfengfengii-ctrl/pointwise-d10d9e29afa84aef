from fractions import Fraction as F
from wave import (SampleBlock, GapEvent, EndEvent, push_event, compute_windows)
from wave.assembly.coverage import lookup_position, PositionKind
from tests import BusinessCase, new_task, rows, direct_reference, scenario


class TestSupport(BusinessCase):
    def test_pending_then_gap(self):
        self.assertEqual(push_event(self.repo, "day", SampleBlock(0, (2,))), ())
        first = push_event(self.repo, "day", SampleBlock(1, (4,)))
        self.assertEqual([(p.index, p.value) for p in first], [(0, 2.0)])
        saved = self.repo.read_waveform("day").points
        gap_batch = push_event(self.repo, "day", GapEvent(2, 1))
        self.assertEqual([(p.index, p.value, p.valid) for p in gap_batch], [(1, None, False)])
        more = push_event(self.repo, "day", SampleBlock(3, (8, 10)))
        self.assertEqual([(p.index, p.value, p.valid) for p in more], [(2, None, False)])
        self.assertEqual(self.repo.read_waveform("day").points[:len(saved)], saved)
        push_event(self.repo, "day", EndEvent(5))
        expected = direct_reference([2, 4, 0, 8, 10], gaps={2})
        actual = rows(self.repo.read_waveform("day"))
        self.assertEqual(actual, expected)
        metrics = compute_windows(self.repo, "day", [(0, F(3, 2))]).results[0]
        self.assertEqual((metrics.total, metrics.valid_count, metrics.coverage, metrics.rms),
                         (3, 1, F(1, 3), 2.0))
        scenario("v3", {"values": [2, 4, None, 8, 10], "gap": [2, 3]},
                 expected, actual, {"coverage": F(1, 3), "rms": 2.0},
                 {"coverage": metrics.coverage, "rms": metrics.rms},
                 ["wave/assembly/coverage.py", "wave/conversion/support.py",
                  "wave/conversion/processor.py", "wave/quality/service.py"],
                 "explicit nonzero support and hand-calculated three-point window")

    def test_zero_weight_and_boundaries(self):
        new_task(self.repo, "zero")
        push_event(self.repo, "zero", GapEvent(0, 1))
        result = push_event(self.repo, "zero", SampleBlock(1, (4, 6)))
        self.assertEqual([(p.index, p.value, p.valid) for p in result],
                         [(0, None, False), (1, 5.0, True)])
        snapshot = self.repo.load_timeline("zero")
        self.assertEqual(lookup_position(snapshot, -1).kind, PositionKind.BOUNDARY)
        self.assertEqual(lookup_position(snapshot, 0).kind, PositionKind.GAP)
        self.assertEqual(lookup_position(snapshot, 1).kind, PositionKind.SAMPLE)
        self.assertEqual(lookup_position(snapshot, 3).kind, PositionKind.UNKNOWN)
        push_event(self.repo, "zero", EndEvent(3))
        snapshot = self.repo.load_timeline("zero")
        self.assertEqual(lookup_position(snapshot, 3).kind, PositionKind.BOUNDARY)
        self.assertEqual(lookup_position(snapshot, 0).kind, PositionKind.GAP)

    def test_gap_does_not_short_circuit_unknown(self):
        # Invalidity is already knowable, but the complete support is still unresolved.
        self.assertEqual(push_event(self.repo, "day", GapEvent(0, 1)), ())
        result = push_event(self.repo, "day", SampleBlock(1, (4,)))
        self.assertEqual([(p.index, p.valid) for p in result], [(0, False)])
        self.assertEqual(push_event(self.repo, "day", SampleBlock(2, (6,)))[0].value, 5.0)
