from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_rational
from wave.catalog.timegrid import reachable_phases


@dataclass(frozen=True)
class PhaseKernel:
    phase: Fraction
    weights: tuple

    def __post_init__(self):
        phase = require_rational(self.phase)
        if not 0 <= phase < 1:
            raise ValueError("phase outside [0,1)")
        weights = []
        seen = set()
        for offset, coefficient in self.weights:
            if type(offset) is not int or offset in seen:
                raise ValueError("offset must be a unique integer")
            seen.add(offset)
            weights.append((offset, require_rational(coefficient)))
        if not weights:
            raise ValueError("phase requires finite nonempty weights")
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "weights", tuple(sorted(weights)))


@dataclass(frozen=True)
class FilterSpec:
    kernels: tuple

    def __post_init__(self):
        kernels = tuple(self.kernels)
        if not kernels or any(not isinstance(k, PhaseKernel) for k in kernels):
            raise ValueError("filter requires phase kernels")
        if len({k.phase for k in kernels}) != len(kernels):
            raise ValueError("duplicate phase")
        object.__setattr__(self, "kernels", tuple(sorted(kernels, key=lambda k: k.phase)))

    def weights_for_phase(self, phase):
        phase = require_rational(phase)
        for kernel in self.kernels:
            if kernel.phase == phase:
                return kernel.weights
        raise ValueError("missing filter phase")


def build_filter(spec):
    if isinstance(spec, FilterSpec):
        return spec
    try:
        return FilterSpec(tuple(PhaseKernel(item["phase"], item["weights"]) for item in spec))
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("invalid phase table") from error


def validate_phase_coverage(spec, grid):
    spec = build_filter(spec)
    available = {kernel.phase for kernel in spec.kernels}
    if not set(reachable_phases(grid)).issubset(available):
        raise ValueError("filter does not cover reachable phases")
    return spec


EXAMPLE_FILTER = FilterSpec((
    PhaseKernel(Fraction(0), ((-1, Fraction(1, 4)), (0, Fraction(1, 2)), (1, Fraction(1, 4)))),
    PhaseKernel(Fraction(1, 2), ((-1, Fraction(0)), (0, Fraction(1, 2)), (1, Fraction(1, 2)))),
))
