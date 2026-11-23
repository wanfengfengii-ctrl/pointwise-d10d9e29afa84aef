from dataclasses import dataclass
from wave.catalog.validation import require_index, require_finite_sample


@dataclass(frozen=True)
class SampleBlock:
    start: int
    values: tuple

    def __post_init__(self):
        require_index(self.start)
        try:
            values = tuple(require_finite_sample(value) for value in self.values)
        except TypeError as error:
            raise ValueError("sample block requires values") from error
        if not values:
            raise ValueError("empty sample block")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True)
class GapEvent:
    start: int
    length: int

    def __post_init__(self):
        require_index(self.start)
        if require_index(self.length) == 0:
            raise ValueError("gap must have positive length")


@dataclass(frozen=True)
class EndEvent:
    start: int

    def __post_init__(self):
        require_index(self.start)


def validate_event(event):
    if not isinstance(event, (SampleBlock, GapEvent, EndEvent)):
        raise ValueError("unknown event")
    return event


def parse_event(record):
    if isinstance(record, (SampleBlock, GapEvent, EndEvent)):
        return validate_event(record)
    if not isinstance(record, dict):
        raise ValueError("event must be an object")
    constructors = {
        "samples": (SampleBlock, {"kind", "start", "values"}),
        "gap": (GapEvent, {"kind", "start", "length"}),
        "end": (EndEvent, {"kind", "start"}),
    }
    kind = record.get("kind")
    if not isinstance(kind, str) or kind not in constructors:
        raise ValueError("unknown event kind")
    constructor, fields = constructors[kind]
    if set(record) != fields:
        raise ValueError("unexpected event fields")
    return constructor(**{key: record[key] for key in fields if key != "kind"})


def event_record(event):
    validate_event(event)
    if isinstance(event, SampleBlock):
        return {"kind": "samples", "start": event.start, "values": event.values}
    if isinstance(event, GapEvent):
        return {"kind": "gap", "start": event.start, "length": event.length}
    return {"kind": "end", "start": event.start}
