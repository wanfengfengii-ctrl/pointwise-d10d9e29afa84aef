from dataclasses import dataclass
from wave.assembly.events import SampleBlock, GapEvent, EndEvent, validate_event
from wave.catalog.validation import require_index


@dataclass(frozen=True)
class SampleSegment:
    start: int
    values: tuple

    def __post_init__(self):
        block = SampleBlock(self.start, self.values)
        object.__setattr__(self, "values", block.values)

    @property
    def stop(self):
        return self.start + len(self.values)


@dataclass(frozen=True)
class GapSegment:
    start: int
    length: int

    def __post_init__(self):
        GapEvent(self.start, self.length)

    @property
    def stop(self):
        return self.start + self.length


@dataclass(frozen=True)
class TimelineSnapshot:
    segments: tuple = ()
    frontier: int = 0
    ended: bool = False

    def __post_init__(self):
        require_index(self.frontier)
        if type(self.ended) is not bool:
            raise ValueError("ended must be boolean")
        segments = tuple(self.segments)
        frontier = 0
        for segment in segments:
            if not isinstance(segment, (SampleSegment, GapSegment)):
                raise ValueError("unknown segment")
            if segment.start != frontier or segment.stop <= segment.start:
                raise ValueError("timeline must contain ordered contiguous intervals")
            frontier = segment.stop
        if frontier != self.frontier:
            raise ValueError("timeline frontier mismatch")
        object.__setattr__(self, "segments", segments)


def append_segment(snapshot, event):
    validate_event(event)
    if snapshot.ended:
        raise ValueError("input already ended")
    if event.start != snapshot.frontier:
        raise ValueError("event must start at the committed frontier")
    if isinstance(event, EndEvent):
        return finish_timeline(snapshot, event.start)
    if isinstance(event, SampleBlock):
        segment = SampleSegment(event.start, event.values)
    else:
        segment = GapSegment(event.start, event.length)
    return TimelineSnapshot(snapshot.segments + (segment,), segment.stop, False)


def finish_timeline(snapshot, end):
    require_index(end)
    if snapshot.ended or end != snapshot.frontier:
        raise ValueError("end must uniquely close the current frontier")
    return TimelineSnapshot(snapshot.segments, snapshot.frontier, True)
