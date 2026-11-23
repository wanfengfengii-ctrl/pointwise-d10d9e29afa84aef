from wave.assembly.segments import append_segment
from wave.conversion.output import validate_delivery_batch


def validate_append(task, previous, before, candidate, event, batch):
    if before.ended or previous.sealed:
        raise ValueError("cannot append to a sealed task")
    if before.frontier != previous.frontier or before.ended != previous.ended:
        raise ValueError("stale input state")
    if append_segment(before, event) != candidate:
        raise ValueError("candidate does not represent the submitted event")
    validate_delivery_batch(task.grid, previous.next_index, batch)
    stop = task.grid.output_stop(candidate.frontier)
    if batch.next_index > stop:
        raise ValueError("delivery outside task time range")
    if batch.sealed != candidate.ended:
        raise ValueError("end and seal must be committed together")
    if candidate.ended and batch.next_index != stop:
        raise ValueError("sealed delivery must cover the complete domain")
    return batch


def publish_event(repository, task, before, candidate, event, batch):
    with repository.transaction():
        previous = repository.load_delivery_state(task.task_id)
        if repository.load_timeline(task.task_id) != before:
            raise ValueError("input changed before publication")
        validate_append(task, previous, before, candidate, event, batch)
        repository.append_delivery(task.task_id, event, candidate, batch, previous)
    return batch
