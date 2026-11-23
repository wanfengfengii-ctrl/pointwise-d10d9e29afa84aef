from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_identifier, require_index, require_rational, require_finite_sample
from wave.quality.windows import TimeWindow


@dataclass(frozen=True)
class WindowResult:
    task_id: str
    source_id: str
    ordinal: int
    window: TimeWindow
    total: int
    valid_count: int
    coverage: Fraction
    rms: float | None

    def __post_init__(self):
        require_identifier(self.task_id)
        require_identifier(self.source_id)
        require_index(self.ordinal)
        require_index(self.total)
        require_index(self.valid_count)
        if not isinstance(self.window, TimeWindow):
            raise ValueError("window result requires a time window")
        if self.valid_count > self.total:
            raise ValueError("valid count exceeds total")
        expected = Fraction(self.valid_count, self.total) if self.total else Fraction(0)
        object.__setattr__(self, "coverage", require_rational(self.coverage))
        if self.coverage != expected:
            raise ValueError("coverage and counts disagree")
        if self.valid_count == 0:
            if self.rms is not None:
                raise ValueError("empty valid set requires null RMS")
        else:
            value = require_finite_sample(self.rms)
            if value < 0:
                raise ValueError("RMS must be nonnegative")
            object.__setattr__(self, "rms", value)

    def record(self):
        return {
            "task_id": self.task_id, "source_id": self.source_id, "ordinal": self.ordinal,
            "window": [self.window.start, self.window.stop], "total": self.total,
            "valid_count": self.valid_count, "coverage": self.coverage, "rms": self.rms,
        }

    @classmethod
    def from_record(cls, record):
        values = dict(record)
        values["window"] = TimeWindow(*values["window"])
        return cls(**values)


@dataclass(frozen=True)
class WindowBatch:
    batch_id: int
    task_id: str
    source_id: str
    results: tuple

    def __post_init__(self):
        require_index(self.batch_id)
        object.__setattr__(self, "results", tuple(self.results))
        validate_result_batch(self.task_id, self.source_id, self.results)


def validate_result_batch(task_id, source_id, results):
    require_identifier(task_id)
    require_identifier(source_id)
    for ordinal, result in enumerate(results):
        if (result.task_id != task_id or result.source_id != source_id
                or result.ordinal != ordinal):
            raise ValueError("window batch source or order mismatch")
    return results
