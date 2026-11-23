from wave.quality.windows import WindowRequest
from wave.quality.selection import select_windows
from wave.quality.reducers import reduce_selection
from wave.quality.results import WindowResult, WindowBatch, validate_result_batch


def compute_windows(repository, task_id, windows):
    request = WindowRequest(windows)
    with repository.transaction():
        snapshot = repository.read_waveform(task_id)
        if not snapshot.sealed:
            raise ValueError("window metrics require a sealed waveform")
        selections = select_windows(snapshot.points, request.windows)
        results = tuple(
            WindowResult(task_id, snapshot.source_id, ordinal, selection.window,
                         *reduce_selection(selection))
            for ordinal, selection in enumerate(selections))
        validate_result_batch(task_id, snapshot.source_id, results)
        batch_id = repository.save_window_batch(
            task_id, snapshot.source_id,
            [[window.start, window.stop] for window in request.windows],
            [result.record() for result in results])
    return WindowBatch(batch_id, task_id, snapshot.source_id, results)


def read_window_results(repository, batch_id):
    task_id, source_id, request, records = repository.load_window_batch(batch_id)
    results = tuple(WindowResult.from_record(record) for record in records)
    if [list((result.window.start, result.window.stop)) for result in results] != request:
        raise ValueError("stored window request and results disagree")
    return WindowBatch(batch_id, task_id, source_id, results)
