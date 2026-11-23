from fractions import Fraction as F
import math
import sqlite3
from wave import (SampleBlock, GapEvent, EndEvent, push_event, compute_windows,
                  read_window_results, FilterSpec, PhaseKernel)
from tests import BusinessCase, new_task, seal


class TestQuality(BusinessCase):
    def test_fixed_windows(self):
        before = self.repo.connection.serialize()
        with self.assertRaises(ValueError):
            compute_windows(self.repo, "day", [(0, 1)])
        self.assertEqual(self.repo.connection.serialize(), before)
        seal(self.repo)
        batch = compute_windows(self.repo, "day", [(0, 1), (1, 2), (2, 2), (8, 9), (0, 1)])
        a, b, empty, outside, repeated = batch.results
        self.assertEqual((a.total, a.valid_count, a.coverage), (2, 2, F(1)))
        self.assertAlmostEqual(a.rms, math.sqrt(F(29, 2)), delta=1e-10)
        self.assertAlmostEqual(b.rms, math.sqrt(F(89, 2)), delta=1e-10)
        self.assertEqual((empty.total, empty.coverage, empty.rms), (0, F(0), None))
        self.assertEqual((outside.total, outside.coverage, outside.rms), (0, F(0), None))
        self.assertEqual(repeated.rms, a.rms)
        self.assertEqual(read_window_results(self.repo, batch.batch_id), batch)
        new_task(self.repo, "gap")
        push_event(self.repo, "gap", SampleBlock(0, (2, 4)))
        push_event(self.repo, "gap", GapEvent(2, 1))
        push_event(self.repo, "gap", SampleBlock(3, (8, 10)))
        push_event(self.repo, "gap", EndEvent(5))
        result = compute_windows(self.repo, "gap", [(0, F(3, 2)), (F(1, 2), F(3, 2))])
        mixed, invalid = result.results
        self.assertEqual((mixed.total, mixed.valid_count, mixed.coverage, mixed.rms),
                         (3, 1, F(1, 3), 2.0))
        self.assertEqual((invalid.total, invalid.valid_count, invalid.coverage, invalid.rms),
                         (2, 0, F(0), None))
        self.assertNotEqual(batch.source_id, result.source_id)
        self.assertEqual(read_window_results(self.repo, batch.batch_id), batch)

    def test_half_open_source_and_stability(self):
        identity = FilterSpec((PhaseKernel(0, ((0, 1),)),))
        new_task(self.repo, "exact", input_start=F(1, 3), output_start=F(1, 3),
                 output_rate=3, spec=identity)
        seal(self.repo, "exact", (3, 4, 0))
        result = compute_windows(self.repo, "exact", [
            (F(1, 3), F(2, 3)), (F(2, 3), 1), (1, F(4, 3))])
        self.assertEqual([(r.total, r.rms) for r in result.results], [(1, 3.0), (1, 4.0), (1, 0.0)])
        new_task(self.repo, "large", output_rate=3, spec=identity)
        seal(self.repo, "large", (1e300, -1e300))
        large = compute_windows(self.repo, "large", [(0, 1)]).results[0]
        self.assertEqual(large.rms, 1e300)
        new_task(self.repo, "small", output_rate=3, spec=identity)
        seal(self.repo, "small", (1e-300, -1e-300))
        self.assertEqual(compute_windows(self.repo, "small", [(0, 1)]).results[0].rms, 1e-300)

    def test_batch_rollback(self):
        seal(self.repo)
        existing = compute_windows(self.repo, "day", [(0, 1)])
        before = self.repo.connection.serialize()
        for windows in ([(0, 1), (2, 1)], [(0, 1), (False, 2)], [(0, float("nan"))]):
            with self.assertRaises(ValueError):
                compute_windows(self.repo, "day", windows)
            self.assertEqual(self.repo.connection.serialize(), before)
        self.repo.connection.execute(
            "CREATE TEMP TRIGGER fail BEFORE INSERT ON window_results WHEN NEW.ordinal=1 "
            "BEGIN SELECT RAISE(ABORT,'window SQL failure'); END").close()
        with self.assertRaises(sqlite3.IntegrityError):
            compute_windows(self.repo, "day", [(0, 1), (1, 2), (2, 3)])
        self.assertEqual(self.repo.connection.serialize(), before)
        self.repo.connection.execute("DROP TRIGGER fail").close()
        self.assertEqual(read_window_results(self.repo, existing.batch_id), existing)
        retry = compute_windows(self.repo, "day", [(0, 1), (1, 2)])
        self.assertEqual(len(retry.results), 2)
        empty = compute_windows(self.repo, "day", [])
        self.assertEqual(read_window_results(self.repo, empty.batch_id), empty)
        with self.assertRaises(KeyError):
            compute_windows(self.repo, "absent", [(0, 1)])
