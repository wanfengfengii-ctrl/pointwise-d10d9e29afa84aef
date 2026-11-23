from fractions import Fraction as F
import unittest
from wave import (ArchiveRepository, register_channel, create_task, EXAMPLE_FILTER,
                  SampleBlock, EndEvent, push_event)
from wave.archive.codec import canonical_json


def new_task(repository, task_id="day", channel_id="sensor", input_start=0,
             output_start=0, input_rate=3, output_rate=2, spec=EXAMPLE_FILTER, unit="m/s²"):
    register_channel(repository, channel_id, unit, input_rate)
    return create_task(repository, task_id, channel_id, input_start, output_start, output_rate, spec)


def seal(repository, task_id="day", values=(2, 4, 6, 8, 10)):
    if values:
        push_event(repository, task_id, SampleBlock(0, values))
    push_event(repository, task_id, EndEvent(len(values)))
    return repository.read_waveform(task_id)


def direct_reference(values, gaps=(), input_start=F(0), output_start=F(0)):
    # Independent whole-record oracle: no production grid, taps, support or processor calls.
    count = len(values)
    rows = []
    m = 0
    while output_start + F(m, 2) < input_start:
        m += 1
    while output_start + F(m, 2) < input_start + F(count, 3):
        time = output_start + F(m, 2)
        coordinate = (time - input_start) * 3
        base = coordinate.numerator // coordinate.denominator
        phase = coordinate - base
        weights = {-1: F(1, 4), 0: F(1, 2), 1: F(1, 4)} if phase == 0 else {
            -1: F(0), 0: F(1, 2), 1: F(1, 2)}
        assert phase in (0, F(1, 2))
        used = [(base + offset, weight) for offset, weight in weights.items() if weight]
        valid = not any(index in gaps for index, weight in used)
        value = float(sum((weight * F(values[index]) for index, weight in used
                           if 0 <= index < count), F(0))) if valid else None
        rows.append((m, time, value, valid))
        m += 1
    return rows


def rows(snapshot):
    return [(point.index, point.time, point.value, point.valid) for point in snapshot.points]


def scenario(case_id, input_data, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print("POINTWISE_SCENARIO " + canonical_json({
        "case_id": case_id, "input": input_data, "expected": expected, "actual": actual,
        "downstream_expected": downstream_expected, "downstream_actual": downstream_actual,
        "code_paths": paths, "oracle": oracle,
    }))


class BusinessCase(unittest.TestCase):
    def setUp(self):
        self.repo = ArchiveRepository()
        self.addCleanup(self.repo.close)
        new_task(self.repo)
