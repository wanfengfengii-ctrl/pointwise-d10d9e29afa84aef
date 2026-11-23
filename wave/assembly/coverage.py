from dataclasses import dataclass
from enum import Enum
from wave.assembly.segments import SampleSegment


class PositionKind(Enum):
    SAMPLE = "sample"
    GAP = "gap"
    UNKNOWN = "unknown"
    BOUNDARY = "boundary"


@dataclass(frozen=True)
class PositionState:
    index: int
    kind: PositionKind
    value: float | None


def lookup_position(snapshot, index):
    if type(index) is not int:
        raise ValueError("support position must be an integer")
    if index < 0 or (snapshot.ended and index >= snapshot.frontier):
        return PositionState(index, PositionKind.BOUNDARY, 0.0)
    if index >= snapshot.frontier:
        return PositionState(index, PositionKind.UNKNOWN, None)
    for segment in snapshot.segments:
        if segment.start <= index < segment.stop:
            if isinstance(segment, SampleSegment):
                return PositionState(index, PositionKind.SAMPLE,
                                     segment.values[index - segment.start])
            return PositionState(index, PositionKind.GAP, None)
    raise ValueError("corrupt input coverage")


def lookup_positions(snapshot, indices):
    return tuple(lookup_position(snapshot, index) for index in indices)
