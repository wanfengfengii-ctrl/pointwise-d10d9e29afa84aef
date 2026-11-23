from dataclasses import dataclass
from enum import Enum
from wave.assembly.coverage import PositionKind, lookup_positions


class SupportStatus(Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class SupportDecision:
    status: SupportStatus
    taps: tuple
    values: tuple


def resolve_support(snapshot, taps):
    taps = tuple(tap for tap in taps if tap.coefficient != 0)
    states = lookup_positions(snapshot, (tap.index for tap in taps))
    if any(state.kind is PositionKind.UNKNOWN for state in states):
        return SupportDecision(SupportStatus.PENDING, taps, ())
    if any(state.kind is PositionKind.GAP for state in states):
        return SupportDecision(SupportStatus.INVALID, taps, ())
    return SupportDecision(SupportStatus.VALID, taps, tuple(state.value for state in states))
