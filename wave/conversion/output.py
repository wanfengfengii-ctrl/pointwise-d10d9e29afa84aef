from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_index, require_rational, require_finite_sample


@dataclass(frozen=True)
class OutputPoint:
    index: int
    time: Fraction
    value: float | None
    valid: bool

    def __post_init__(self):
        require_index(self.index)
        object.__setattr__(self, "time", require_rational(self.time))
        if type(self.valid) is not bool:
            raise ValueError("valid must be boolean")
        if self.valid:
            object.__setattr__(self, "value", require_finite_sample(self.value))
        elif self.value is not None:
            raise ValueError("invalid point must have null value")


@dataclass(frozen=True)
class DeliveryBatch:
    points: tuple
    next_index: int
    sealed: bool

    def __post_init__(self):
        object.__setattr__(self, "points", tuple(self.points))
        require_index(self.next_index)
        if type(self.sealed) is not bool:
            raise ValueError("sealed must be boolean")


def validate_delivery_batch(grid, start, batch):
    require_index(start)
    if batch.next_index != start + len(batch.points):
        raise ValueError("delivery cursor mismatch")
    for index, point in enumerate(batch.points, start):
        if not isinstance(point, OutputPoint):
            raise ValueError("delivery requires output points")
        if point.index != index or point.time != grid.output_time(index):
            raise ValueError("delivery must follow the absolute grid")
    return batch
