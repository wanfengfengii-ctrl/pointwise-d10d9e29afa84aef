from dataclasses import dataclass
from pathlib import Path
from wave.archive.codec import decode_record
from wave.catalog.channels import register_channel
from wave.catalog.tasks import create_task
from wave.catalog.filters import EXAMPLE_FILTER
from wave.assembly.events import parse_event
from wave.assembly.session import CaptureSession
from wave.archive.export import export_waveform
from wave.quality.service import compute_windows


@dataclass(frozen=True)
class ReplayReport:
    task_id: str
    deliveries: tuple
    exported: str
    windows: object


def load_recording(path):
    document = decode_record(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"channel", "task", "events", "windows"}:
        raise ValueError("recording requires channel, task, events, windows")
    if not isinstance(document["events"], list):
        raise ValueError("recording events must be finite")
    return document


def replay_events(repository, task_id, events):
    state = repository.load_delivery_state(task_id)
    if state.event_count or state.frontier or state.ended:
        raise ValueError("recording already has accepted progress")
    session = CaptureSession(repository, task_id)
    deliveries = []
    for event in events:
        deliveries.append(session.push_event(parse_event(event)))
    return tuple(deliveries)


def run_workday(repository, recording):
    if not isinstance(recording, dict):
        raise ValueError("recording must be an object")
    try:
        channel = recording["channel"]
        task = recording["task"]
        task_id = task["task_id"]
        events = recording["events"]
        windows = recording["windows"]
    except (KeyError, TypeError) as error:
        raise ValueError("incomplete recording") from error
    try:
        state = repository.load_delivery_state(task_id)
    except KeyError:
        pass
    else:
        if state.event_count or state.frontier or state.ended:
            raise ValueError("cannot replay an existing recording")
    register_channel(repository, channel["channel_id"], channel["unit"], channel["input_rate"])
    create_task(repository, task_id, channel["channel_id"],
                task["input_start"], task["output_start"], task["output_rate"],
                task.get("filter", EXAMPLE_FILTER))
    deliveries = replay_events(repository, task_id, events)
    exported = export_waveform(repository, task_id)
    metrics = compute_windows(repository, task_id, windows)
    return ReplayReport(task_id, deliveries, exported, metrics)
