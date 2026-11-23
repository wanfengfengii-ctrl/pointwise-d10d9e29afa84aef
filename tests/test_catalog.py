from fractions import Fraction as F
from wave import (register_channel, create_task, get_channel, get_task, SampleBlock,
                  push_event, FilterSpec, PhaseKernel, EXAMPLE_FILTER)
from wave.catalog.filters import build_filter
from wave.catalog.timegrid import TimeGrid, reachable_phases
from wave.catalog.validation import require_rational, require_index
from wave.assembly.events import parse_event
from tests import BusinessCase


class TestCatalog(BusinessCase):
    def test_channel_registry_and_binding(self):
        self.assertEqual(register_channel(self.repo, "sensor", "m/s²", [6, 2]),
                         get_channel(self.repo, "sensor"))
        before = self.repo.connection.serialize()
        for unit, rate in (("g", 3), ("m/s²", 4), ("", 3), ("m/s²", True),
                           ("m/s²", 0), ("m/s²", [1, 0])):
            with self.assertRaises(ValueError):
                register_channel(self.repo, "sensor", unit, rate)
            self.assertEqual(self.repo.connection.serialize(), before)
        push_event(self.repo, "day", SampleBlock(0, (2, 4)))
        before = self.repo.connection.serialize()
        self.assertEqual(create_task(self.repo, "day", "sensor", [0, 2], 0, [4, 2],
                                     EXAMPLE_FILTER), get_task(self.repo, "day"))
        self.assertEqual(self.repo.connection.serialize(), before)
        with self.assertRaises(ValueError):
            create_task(self.repo, "day", "sensor", 1, 0, 2, EXAMPLE_FILTER)
        with self.assertRaises(KeyError):
            create_task(self.repo, "missing-channel-task", "absent", 0, 0, 2, EXAMPLE_FILTER)
        self.assertEqual(self.repo.connection.serialize(), before)

    def test_phase_table_and_scalar_validation(self):
        grid = TimeGrid(F(1, 3), 3, 0, 2)
        self.assertEqual(reachable_phases(grid), (F(0), F(1, 2)))
        self.assertEqual(grid.first_output_index(), 1)
        self.assertEqual(grid.output_stop(5), 4)
        incomplete = FilterSpec((PhaseKernel(0, ((0, 1),)),))
        with self.assertRaises(ValueError):
            create_task(self.repo, "incomplete", "sensor", 0, 0, 2, incomplete)
        with self.assertRaises(ValueError):
            FilterSpec((PhaseKernel(0, ((0, 1),)), PhaseKernel(0, ((0, 2),))))
        with self.assertRaises(ValueError):
            PhaseKernel(0, ((0, 1), (0, 2)))
        with self.assertRaises(ValueError):
            build_filter([{"phase": True, "weights": [[0, 1]]}])
        for value in (True, 0.5, [1, 0], [True, 2], "1/2"):
            with self.assertRaises(ValueError):
                require_rational(value)
        for value in (True, -1, 1.0):
            with self.assertRaises(ValueError):
                require_index(value)
        for record in ({"kind": "samples", "start": 0, "values": []},
                       {"kind": "gap", "start": 0, "length": 0},
                       {"kind": "end", "start": 0, "extra": 1}, {"kind": "other"}):
            with self.assertRaises(ValueError):
                parse_event(record)
        self.assertEqual(EXAMPLE_FILTER.weights_for_phase(F(1, 2))[0], (-1, F(0)))

    def test_general_finite_phase_orbit(self):
        grid = TimeGrid(F(1, 7), F(5, 2), F(-2, 9), F(7, 3))
        phases = reachable_phases(grid)
        self.assertEqual(len(phases), 14)
        kernels = FilterSpec(tuple(PhaseKernel(phase, ((0, F(1, 3)), (1, F(2, 3))))
                                   for phase in phases))
        register_channel(self.repo, "rational", "m/s²", F(5, 2))
        task = create_task(self.repo, "orbit", "rational", F(1, 7), F(-2, 9), F(7, 3), kernels)
        data = tuple(range(1, 12))
        for index, value in enumerate(data):
            push_event(self.repo, "orbit", SampleBlock(index, (value,)))
        from wave import EndEvent
        push_event(self.repo, "orbit", EndEvent(len(data)))
        for point in self.repo.read_waveform("orbit").points:
            time = F(-2, 9) + F(point.index, 1) / F(7, 3)
            coordinate = (time - F(1, 7)) * F(5, 2)
            base = coordinate.numerator // coordinate.denominator
            expected = F(data[base], 3)
            if base + 1 < len(data):
                expected += F(2 * data[base + 1], 3)
            self.assertEqual(point.time, time)
            self.assertAlmostEqual(point.value, float(expected), delta=1e-12)
            self.assertTrue(point.valid)
        self.assertEqual(task, get_task(self.repo, "orbit"))
