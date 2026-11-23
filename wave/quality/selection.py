from dataclasses import dataclass
from wave.quality.windows import TimeWindow, validate_windows


@dataclass(frozen=True)
class WindowSelection:
    window: TimeWindow
    points: tuple
    valid_points: tuple


def select_window(points, window):
    if not isinstance(window, TimeWindow):
        window = TimeWindow(*window)
    selected = tuple(point for point in points if window.start <= point.time < window.stop)
    valid = tuple(point for point in selected if point.valid and point.value is not None)
    return WindowSelection(window, selected, valid)


def select_windows(points, windows):
    points = tuple(points)
    return tuple(select_window(points, window) for window in validate_windows(windows))
