"""活动任务接班件的发行与异库验收。

packet 是可经 JSON 往返的字典，固定键为 task、frontier、next_index、points、
basis_kind、basis。task 与封存导出的 task 结构相同（通道、单位、两套时间网格
及固定相位权重，时间与系数均显式编码为 [分子, 分母] 数组）；points 沿用原导出
的点记录 {"index", "time", "value", "valid"}，按绝对输出位排列；frontier 是原
输入的下一接收位置，next_index 是下一可交付输出的绝对位置，两者都是非负整数。

basis_kind 固定为 "positions"：basis 按绝对输入位升序，每条精确覆盖一个旧输入
位置，编码为 {"input_index": i, "kind": "sample", "value": v}（已提交样本，v 为
有限双精度实数）或 {"input_index": i, "kind": "gap"}（设备明确报告的缺测）。
该集合恰为 [0, frontier) 内被某个未发布输出位（m >= next_index）的非零抽头
引用的位置；集合由固定口径、frontier 与 next_index 唯一决定，发行端与验收端
各自独立计算并逐项核对。只影响已发布点的位置、零系数引用和起始补零位置不交接。
"""
import hashlib
from wave.archive.codec import canonical_json
from wave.archive.export import point_document, task_binding_document
from wave.assembly.coverage import PositionKind, lookup_position
from wave.assembly.events import GapEvent, SampleBlock
from wave.catalog.channels import Channel, get_channel
from wave.catalog.filters import build_filter, validate_phase_coverage
from wave.catalog.tasks import TaskBinding, canonical_task_binding, get_task
from wave.catalog.timegrid import TimeGrid
from wave.catalog.validation import (require_finite_sample, require_identifier,
                                     require_index, require_positive_rate,
                                     require_rational, require_unit)
from wave.conversion.kernel import support_taps
from wave.conversion.output import OutputPoint

BASIS_KIND = "positions"
_PACKET_KEYS = {"task", "frontier", "next_index", "points", "basis_kind", "basis"}
_TASK_KEYS = {"task_id", "channel_id", "unit", "input_start", "input_rate",
              "output_start", "output_rate", "filter"}
_POINT_KEYS = {"index", "time", "value", "valid"}
_KERNEL_KEYS = {"phase", "weights"}
_SAMPLE_KEYS = {"input_index", "kind", "value"}
_GAP_KEYS = {"input_index", "kind"}


def handoff_positions(task, frontier, next_index):
    """[0, frontier) 内被未发布输出位非零抽头引用的全部输入位置。"""
    frontier = require_index(frontier)
    next_index = require_index(next_index)
    grid = task.grid
    if next_index < grid.first_output_index():
        raise ValueError("handoff cursor precedes task grid")
    if next_index > grid.output_stop(frontier):
        raise ValueError("handoff cursor exceeds confirmed time range")
    offsets = [offset for kernel in task.filter_spec.kernels
               for offset, weight in kernel.weights if weight != 0]
    positions = set()
    if not offsets:
        return positions
    min_offset = min(offsets)
    index = next_index
    while True:
        coordinate = grid.input_coordinate(index)
        base = coordinate.numerator // coordinate.denominator
        if base + min_offset >= frontier:
            return positions
        for tap in support_taps(task, index):
            if 0 <= tap.index < frontier:
                positions.add(tap.index)
        index += 1


def export_handoff(repository, task_id):
    task = get_task(repository, task_id)
    state = repository.load_delivery_state(task.task_id)
    if state.sealed:
        raise ValueError("cannot issue a handoff for a sealed task")
    snapshot = repository.read_waveform(task.task_id)
    timeline = repository.load_timeline(task.task_id)
    basis = []
    for index in sorted(handoff_positions(task, state.frontier, state.next_index)):
        fact = lookup_position(timeline, index)
        if fact.kind is PositionKind.SAMPLE:
            basis.append({"input_index": index, "kind": "sample", "value": fact.value})
        elif fact.kind is PositionKind.GAP:
            basis.append({"input_index": index, "kind": "gap"})
        else:
            raise ValueError("committed input position is not resolvable")
    packet = {
        "task": task_binding_document(task),
        "frontier": state.frontier,
        "next_index": state.next_index,
        "points": [point_document(point) for point in snapshot.points],
        "basis_kind": BASIS_KIND,
        "basis": basis,
    }
    digest = hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()
    return packet, digest


def accept_handoff(other_repository, packet, expected_digest):
    if not isinstance(expected_digest, str):
        raise ValueError("expected digest must be hexadecimal text")
    digest = hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()
    if digest != expected_digest:
        raise ValueError("handoff digest mismatch")
    task, frontier, next_index, points, facts = _validate_packet(packet)
    events = _synthesize_events(frontier, facts)
    record = canonical_task_binding(task)
    channel = Channel(task.channel_id, task.unit, task.grid.input_rate)
    with other_repository.transaction():
        try:
            existing = get_channel(other_repository, channel.channel_id)
        except KeyError:
            other_repository.insert_channel(channel.channel_id, channel.record())
        else:
            if existing != channel:
                raise ValueError("channel binding conflict")
        try:
            other_repository.load_task(task.task_id)
        except KeyError:
            pass
        else:
            raise ValueError("task already exists in target archive")
        other_repository.insert_handoff(task.task_id, task.channel_id, record,
                                        frontier, next_index, events, points)
    return other_repository.read_waveform(task.task_id)


def _validate_packet(packet):
    if not isinstance(packet, dict) or set(packet) != _PACKET_KEYS:
        raise ValueError("handoff packet structure mismatch")
    if packet["basis_kind"] != BASIS_KIND:
        raise ValueError("unsupported handoff basis kind")
    frontier = require_index(packet["frontier"])
    next_index = require_index(packet["next_index"])
    task = _decode_task(packet["task"])
    points = _decode_points(packet["points"], task.grid, next_index)
    required = handoff_positions(task, frontier, next_index)
    facts = _decode_basis(packet["basis"])
    if set(facts) != required:
        raise ValueError("handoff basis does not match the required positions")
    return task, frontier, next_index, points, facts


def _decode_task(record):
    if not isinstance(record, dict) or set(record) != _TASK_KEYS:
        raise ValueError("handoff task binding mismatch")
    table = record["filter"]
    if not isinstance(table, list):
        raise ValueError("handoff filter table must be a list")
    grid = TimeGrid(require_rational(record["input_start"]),
                    require_positive_rate(record["input_rate"]),
                    require_rational(record["output_start"]),
                    require_positive_rate(record["output_rate"]))
    spec = validate_phase_coverage(
        build_filter([_decode_kernel(item) for item in table]), grid)
    return TaskBinding(require_identifier(record["task_id"]),
                       require_identifier(record["channel_id"]),
                       require_unit(record["unit"]), grid, spec)


def _decode_kernel(item):
    if not isinstance(item, dict) or set(item) != _KERNEL_KEYS:
        raise ValueError("handoff filter entry mismatch")
    weights = item["weights"]
    if not isinstance(weights, list):
        raise ValueError("handoff filter weights must be a list")
    decoded = []
    for pair in weights:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("handoff weight entry mismatch")
        decoded.append((pair[0], require_rational(pair[1])))
    return {"phase": require_rational(item["phase"]), "weights": decoded}


def _decode_points(records, grid, next_index):
    first = grid.first_output_index()
    if next_index < first:
        raise ValueError("handoff cursor precedes task grid")
    if not isinstance(records, list) or len(records) != next_index - first:
        raise ValueError("handoff points do not form the committed prefix")
    points = []
    for position, record in enumerate(records, first):
        if not isinstance(record, dict) or set(record) != _POINT_KEYS:
            raise ValueError("handoff point record mismatch")
        if type(record["index"]) is not int or record["index"] != position:
            raise ValueError("handoff points must follow the absolute output order")
        time = require_rational(record["time"])
        if time != grid.output_time(position):
            raise ValueError("handoff point time breaks the task grid")
        valid = record["valid"]
        if type(valid) is not bool:
            raise ValueError("handoff point validity must be boolean")
        value = record["value"]
        if valid:
            value = require_finite_sample(value)
        elif value is not None:
            raise ValueError("handoff invalid point carries a value")
        points.append(OutputPoint(position, time, value, valid))
    return tuple(points)


def _decode_basis(records):
    if not isinstance(records, list):
        raise ValueError("handoff basis must be a list")
    facts = {}
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError("handoff basis entry mismatch")
        kind = entry.get("kind")
        if kind == "sample":
            if set(entry) != _SAMPLE_KEYS:
                raise ValueError("handoff sample entry mismatch")
            fact = ("sample", require_finite_sample(entry["value"]))
        elif kind == "gap":
            if set(entry) != _GAP_KEYS:
                raise ValueError("handoff gap entry mismatch")
            fact = ("gap",)
        else:
            raise ValueError("unknown handoff basis entry kind")
        index = require_index(entry["input_index"])
        if index in facts:
            raise ValueError("duplicate handoff basis position")
        facts[index] = fact
    return facts


def _synthesize_events(frontier, facts):
    """把旧依据重建为连续输入时间线；无交接资格的位置以缺测段占位。"""
    events = []
    index = 0
    while index < frontier:
        fact = facts.get(index)
        if fact is not None and fact[0] == "sample":
            start = index
            values = []
            while index < frontier:
                fact = facts.get(index)
                if fact is None or fact[0] != "sample":
                    break
                values.append(fact[1])
                index += 1
            events.append(SampleBlock(start, tuple(values)))
        else:
            start = index
            while index < frontier:
                fact = facts.get(index)
                if fact is not None and fact[0] == "sample":
                    break
                index += 1
            events.append(GapEvent(start, index - start))
    return tuple(events)
