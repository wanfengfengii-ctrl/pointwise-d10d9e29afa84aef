from dataclasses import dataclass
from wave.catalog.channels import get_channel
from wave.catalog.filters import build_filter, validate_phase_coverage
from wave.catalog.timegrid import TimeGrid
from wave.catalog.validation import require_identifier


@dataclass(frozen=True)
class TaskBinding:
    task_id: str
    channel_id: str
    unit: str
    grid: TimeGrid
    filter_spec: object


def canonical_task_binding(task):
    return {
        "task_id": task.task_id, "channel_id": task.channel_id, "unit": task.unit,
        "input_start": task.grid.input_start, "input_rate": task.grid.input_rate,
        "output_start": task.grid.output_start, "output_rate": task.grid.output_rate,
        "filter": [{"phase": kernel.phase, "weights": kernel.weights}
                   for kernel in task.filter_spec.kernels],
    }


def _from_record(record):
    grid = TimeGrid(record["input_start"], record["input_rate"],
                    record["output_start"], record["output_rate"])
    spec = validate_phase_coverage(build_filter(record["filter"]), grid)
    return TaskBinding(record["task_id"], record["channel_id"], record["unit"], grid, spec)


def create_task(repository, task_id, channel_id, input_start, output_start,
                output_rate, filter_spec):
    task_id = require_identifier(task_id)
    channel_id = require_identifier(channel_id)
    with repository.transaction():
        channel = get_channel(repository, channel_id)
        grid = TimeGrid(input_start, channel.input_rate, output_start, output_rate)
        spec = validate_phase_coverage(build_filter(filter_spec), grid)
        task = TaskBinding(task_id, channel_id, channel.unit, grid, spec)
        record = canonical_task_binding(task)
        try:
            previous = get_task(repository, task_id)
        except KeyError:
            repository.insert_task(task_id, channel_id, record, grid.first_output_index())
        else:
            if canonical_task_binding(previous) != record:
                raise ValueError("task binding conflict")
            return previous
    return task


def get_task(repository, task_id):
    return _from_record(repository.load_task(require_identifier(task_id)))
