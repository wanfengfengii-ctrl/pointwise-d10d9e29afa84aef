from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_rational


@dataclass(frozen=True)
class TimeWindow:
    start: Fraction
    stop: Fraction

    def __post_init__(self):
        object.__setattr__(self, "start", require_rational(self.start))
        object.__setattr__(self, "stop", require_rational(self.stop))
        if self.start > self.stop:
            raise ValueError("reversed time window")


@dataclass(frozen=True)
class WindowRequest:
    windows: tuple

    def __post_init__(self):
        object.__setattr__(self, "windows", validate_windows(self.windows))


def validate_windows(windows):
    if isinstance(windows, WindowRequest):
        return windows.windows
    try:
        result = []
        for window in windows:
            if isinstance(window, TimeWindow):
                result.append(window)
            else:
                if not isinstance(window, (tuple, list)) or len(window) != 2:
                    raise ValueError("window must contain two rational endpoints")
                result.append(TimeWindow(*window))
        return tuple(result)
    except TypeError as error:
        raise ValueError("windows must be a finite iterable") from error
