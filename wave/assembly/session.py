from wave.catalog.tasks import get_task
from wave.assembly.events import parse_event
from wave.assembly.segments import append_segment
from wave.conversion.processor import compute_available_prefix
from wave.archive.publish import publish_event


class CaptureSession:
    def __init__(self, repository, task_id):
        self.repository = repository
        self.task_id = get_task(repository, task_id).task_id

    def push_event(self, event):
        event = parse_event(event)
        with self.repository.transaction():
            task = get_task(self.repository, self.task_id)
            before = self.repository.load_timeline(self.task_id)
            state = self.repository.load_delivery_state(self.task_id)
            candidate = append_segment(before, event)
            batch = compute_available_prefix(task, candidate, state.next_index)
            publish_event(self.repository, task, before, candidate, event, batch)
        return batch.points


def push_event(repository, task_id, event):
    return CaptureSession(repository, task_id).push_event(event)
