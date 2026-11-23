from wave.archive.codec import canonical_json, encode_rational
from wave.catalog.tasks import get_task, canonical_task_binding


def build_export_document(repository, task_id):
    task = get_task(repository, task_id)
    snapshot = repository.read_waveform(task_id)
    if not snapshot.sealed:
        raise ValueError("export requires a sealed waveform")
    binding = canonical_task_binding(task)
    binding["input_start"] = encode_rational(task.grid.input_start)
    binding["input_rate"] = encode_rational(task.grid.input_rate)
    binding["output_start"] = encode_rational(task.grid.output_start)
    binding["output_rate"] = encode_rational(task.grid.output_rate)
    binding["filter"] = [
        {"phase": encode_rational(kernel.phase),
         "weights": [[offset, encode_rational(weight)] for offset, weight in kernel.weights]}
        for kernel in task.filter_spec.kernels]
    return {
        "task": binding, "sealed": True, "source_id": snapshot.source_id,
        "next_index": snapshot.next_index,
        "points": [{"index": point.index, "time": encode_rational(point.time),
                    "value": point.value, "valid": point.valid} for point in snapshot.points],
    }


def export_waveform(repository, task_id):
    return canonical_json(build_export_document(repository, task_id))
