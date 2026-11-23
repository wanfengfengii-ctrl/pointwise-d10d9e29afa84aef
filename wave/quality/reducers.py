from fractions import Fraction
import math
from wave.catalog.validation import require_finite_sample


def coverage_ratio(selection):
    total = len(selection.points)
    return Fraction(len(selection.valid_points), total) if total else Fraction(0)


def valid_rms(selection):
    values = tuple(point.value for point in selection.valid_points)
    if not values:
        return None
    scale = max(abs(value) for value in values)
    if scale == 0:
        return 0.0
    mean_square = math.fsum((value / scale) ** 2 for value in values) / len(values)
    return require_finite_sample(scale * math.sqrt(min(1.0, mean_square)))


def reduce_selection(selection):
    return (len(selection.points), len(selection.valid_points),
            coverage_ratio(selection), valid_rms(selection))
