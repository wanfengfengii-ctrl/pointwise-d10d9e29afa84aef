from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import sqlite3
from wave.archive.schema import ensure_schema
from wave.archive.codec import canonical_json, decode_record
from wave.catalog.validation import require_identifier, require_index
from wave.assembly.events import parse_event, event_record
from wave.assembly.segments import TimelineSnapshot, append_segment
from wave.conversion.output import OutputPoint


@dataclass(frozen=True)
class DeliveryState:
    frontier: int
    ended: bool
    next_index: int
    sealed: bool
    event_count: int


@dataclass(frozen=True)
class WaveformSnapshot:
    task_id: str
    points: tuple
    sealed: bool
    next_index: int
    source_id: str


class ArchiveRepository:
    def __init__(self, path=":memory:"):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self._depth = 0
        self._savepoint = 0
        try:
            ensure_schema(self.connection)
        except BaseException:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    @contextmanager
    def transaction(self):
        outer = self._depth == 0
        self._savepoint += 1
        name = "wave_sp_" + str(self._savepoint)
        self.connection.execute("BEGIN IMMEDIATE" if outer else "SAVEPOINT " + name).close()
        self._depth += 1
        try:
            yield self
            if outer:
                self.connection.commit()
            else:
                self.connection.execute("RELEASE SAVEPOINT " + name).close()
        except BaseException:
            if outer:
                self.connection.rollback()
            else:
                self.connection.execute("ROLLBACK TO SAVEPOINT " + name).close()
                self.connection.execute("RELEASE SAVEPOINT " + name).close()
            raise
        finally:
            self._depth -= 1

    def _one(self, sql, arguments=()):
        cursor = self.connection.execute(sql, arguments)
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _all(self, sql, arguments=()):
        cursor = self.connection.execute(sql, arguments)
        try:
            return cursor.fetchall()
        finally:
            cursor.close()

    def _write(self, sql, arguments=()):
        if not self.connection.in_transaction:
            raise ValueError("business writes require a transaction")
        cursor = self.connection.execute(sql, arguments)
        try:
            return cursor.lastrowid
        finally:
            cursor.close()

    def load_channel(self, channel_id):
        row = self._one("SELECT payload FROM channels WHERE id=?", (channel_id,))
        if row is None:
            raise KeyError(channel_id)
        return decode_record(row[0])

    def insert_channel(self, channel_id, record):
        self._write("INSERT INTO channels VALUES(?,?)", (channel_id, canonical_json(record)))

    def load_task(self, task_id):
        row = self._one("SELECT payload FROM tasks WHERE id=?", (task_id,))
        if row is None:
            raise KeyError(task_id)
        return decode_record(row[0])

    def insert_task(self, task_id, channel_id, record, first_index):
        self._write("INSERT INTO tasks VALUES(?,?,?)",
                    (task_id, channel_id, canonical_json(record)))
        self._write("INSERT INTO delivery VALUES(?,0,0,?,0,0)", (task_id, first_index))

    def load_delivery_state(self, task_id):
        row = self._one(
            "SELECT frontier,ended,next_index,sealed,event_count FROM delivery WHERE task_id=?",
            (task_id,))
        if row is None:
            raise KeyError(task_id)
        return DeliveryState(row[0], bool(row[1]), row[2], bool(row[3]), row[4])

    def load_timeline(self, task_id):
        state = self.load_delivery_state(task_id)
        rows = self._all("SELECT seq,payload FROM events WHERE task_id=? ORDER BY seq", (task_id,))
        snapshot = TimelineSnapshot()
        for expected, (sequence, payload) in enumerate(rows):
            if sequence != expected:
                raise ValueError("stored event sequence is not contiguous")
            snapshot = append_segment(snapshot, parse_event(decode_record(payload)))
        if (len(rows) != state.event_count or snapshot.frontier != state.frontier
                or snapshot.ended != state.ended):
            raise ValueError("input and delivery state disagree")
        return snapshot

    def append_delivery(self, task_id, event, candidate, batch, previous):
        self._write("INSERT INTO events VALUES(?,?,?)",
                    (task_id, previous.event_count, canonical_json(event_record(event))))
        for point in batch.points:
            self._write("INSERT INTO waveform VALUES(?,?,?,?,?)",
                        (task_id, point.index, canonical_json(point.time), point.value, int(point.valid)))
        self._write(
            "UPDATE delivery SET frontier=?,ended=?,next_index=?,sealed=?,event_count=? WHERE task_id=?",
            (candidate.frontier, int(candidate.ended), batch.next_index,
             int(batch.sealed), previous.event_count + 1, task_id))

    def read_waveform(self, task_id, start=None, stop=None):
        task_id = require_identifier(task_id)
        if start is not None:
            require_index(start)
        if stop is not None:
            require_index(stop)
        if start is not None and stop is not None and start > stop:
            raise ValueError("reversed output range")
        # One SELECT gives metadata and points from the same SQLite read snapshot.
        rows = self._all(
            "SELECT t.payload,d.sealed,d.next_index,w.m,w.time,w.value,w.valid "
            "FROM tasks t JOIN delivery d ON d.task_id=t.id "
            "LEFT JOIN waveform w ON w.task_id=t.id "
            "WHERE t.id=? ORDER BY w.m", (task_id,))
        if not rows:
            raise KeyError(task_id)
        binding, sealed, next_index = rows[0][:3]
        all_points = tuple(OutputPoint(row[3], decode_record(row[4]), row[5], bool(row[6]))
                           for row in rows if row[3] is not None)
        evidence = {"binding": decode_record(binding), "sealed": bool(sealed),
                    "next_index": next_index,
                    "points": [(p.index, p.time, p.value, p.valid) for p in all_points]}
        source_id = hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
        selected = tuple(p for p in all_points
                         if (start is None or p.index >= start) and (stop is None or p.index < stop))
        return WaveformSnapshot(task_id, selected, bool(sealed), next_index, source_id)

    def iter_waveform(self, task_id, start=None, stop=None):
        snapshot = self.read_waveform(task_id, start, stop)
        return (point for point in snapshot.points)

    def save_window_batch(self, task_id, source_id, request, records):
        batch_id = self._write(
            "INSERT INTO window_batches(task_id,source_id,request) VALUES(?,?,?)",
            (task_id, source_id, canonical_json(request)))
        for ordinal, record in enumerate(records):
            self._write("INSERT INTO window_results VALUES(?,?,?)",
                        (batch_id, ordinal, canonical_json(record)))
        return batch_id

    def load_window_batch(self, batch_id):
        batch_id = require_index(batch_id)
        row = self._one("SELECT task_id,source_id,request FROM window_batches WHERE id=?", (batch_id,))
        if row is None:
            raise KeyError(batch_id)
        records = self._all("SELECT payload FROM window_results WHERE batch_id=? ORDER BY ordinal",
                            (batch_id,))
        return row[0], row[1], decode_record(row[2]), tuple(decode_record(r[0]) for r in records)


def read_waveform(repository, task_id, start=None, stop=None):
    return repository.read_waveform(task_id, start, stop)
