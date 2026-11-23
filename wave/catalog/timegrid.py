from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_rational, require_positive_rate, require_index


def _ceil(value):
    return -((-value.numerator) // value.denominator)


@dataclass(frozen=True)
class TimeGrid:
    input_start: Fraction
    input_rate: Fraction
    output_start: Fraction
    output_rate: Fraction

    def __post_init__(self):
        for name in ("input_start", "output_start"):
            object.__setattr__(self, name, require_rational(getattr(self, name)))
        for name in ("input_rate", "output_rate"):
            object.__setattr__(self, name, require_positive_rate(getattr(self, name)))

    def output_time(self, index):
        return self.output_start + require_index(index) / self.output_rate

    def input_coordinate(self, index):
        return (self.output_time(index) - self.input_start) * self.input_rate

    def first_output_index(self):
        return max(0, _ceil((self.input_start - self.output_start) * self.output_rate))

    def output_stop(self, frontier):
        end = self.input_start + require_index(frontier) / self.input_rate
        return max(self.first_output_index(), _ceil((end - self.output_start) * self.output_rate))


def reachable_phases(grid):
    step = grid.input_rate / grid.output_rate
    start = grid.input_coordinate(grid.first_output_index())
    return tuple(sorted({(start + offset * step) % 1
                         for offset in range(step.denominator)}))
