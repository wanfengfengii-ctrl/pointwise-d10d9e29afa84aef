from dataclasses import dataclass
from fractions import Fraction
import math
from wave.catalog.validation import require_finite_sample


@dataclass(frozen=True)
class WeightedTap:
    index: int
    coefficient: Fraction


def support_taps(task, output_index):
    coordinate = task.grid.input_coordinate(output_index)
    base = coordinate.numerator // coordinate.denominator
    phase = coordinate - base
    return tuple(WeightedTap(base + offset, weight)
                 for offset, weight in task.filter_spec.weights_for_phase(phase)
                 if weight != 0)


def evaluate_fir(taps, values):
    if len(taps) != len(values):
        raise ValueError("support and values must align")
    try:
        total = math.fsum(float(tap.coefficient) * value
                          for tap, value in zip(taps, values))
    except (OverflowError, ValueError) as error:
        raise ValueError("FIR result is not finite") from error
    return require_finite_sample(total)
