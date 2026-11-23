from wave.conversion.kernel import support_taps, evaluate_fir
from wave.conversion.support import resolve_support, SupportStatus
from wave.conversion.output import OutputPoint, DeliveryBatch, validate_delivery_batch
from wave.catalog.validation import require_index


class PrefixProcessor:
    def __init__(self, task):
        self.task = task

    def advance(self, snapshot, next_index):
        next_index = require_index(next_index)
        grid = self.task.grid
        if next_index < grid.first_output_index():
            raise ValueError("cursor precedes task grid")
        stop = grid.output_stop(snapshot.frontier)
        if next_index > stop:
            raise ValueError("cursor exceeds confirmed time range")
        points = []
        cursor = next_index
        while cursor < stop:
            decision = resolve_support(snapshot, support_taps(self.task, cursor))
            if decision.status is SupportStatus.PENDING:
                break
            valid = decision.status is SupportStatus.VALID
            value = evaluate_fir(decision.taps, decision.values) if valid else None
            points.append(OutputPoint(cursor, grid.output_time(cursor), value, valid))
            cursor += 1
        sealed = snapshot.ended and cursor == stop
        if snapshot.ended and not sealed:
            raise ValueError("ended timeline left unresolved support")
        return validate_delivery_batch(grid, next_index,
                                       DeliveryBatch(tuple(points), cursor, sealed))


def compute_available_prefix(task, snapshot, next_index):
    return PrefixProcessor(task).advance(snapshot, next_index)
