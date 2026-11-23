import argparse
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from wave import (ArchiveRepository, EXAMPLE_FILTER, EndEvent, GapEvent, SampleBlock,
                  compute_windows, create_task, export_waveform, push_event,
                  read_waveform, register_channel)
from wave.archive.codec import canonical_json

TASK = "bearing-handoff"
CHANNEL = "north-bearing"
WINDOWS = [(0, 10), (1, 2)]
ASSERT = TestCase()


def point(index, value, time=None):
    return (index, F(index if time is None else time), value, value is not None)


def rows(points):
    return tuple((p.index, p.time, p.value, p.valid) for p in points)


@dataclass(frozen=True)
class Case:
    name: str
    input_rate: int
    output_rate: int
    input_start: F
    spec: object
    history: tuple
    frontier: int
    cursor: int
    prefix: tuple
    old_positions: tuple
    events: tuple
    deliveries: tuple


def kernel(*offsets):
    return [{"phase": 0, "weights": [[offset, 1] for offset in offsets]}]


SPARSE = Case("sparse", 2, 1, F(0), kernel(-3, 1),
              (SampleBlock(0, [2, 4, 6, 8, 10, 12]),), 6, 3,
              (point(0, 4), point(1, 8), point(2, 16)), (3, 5),
              (SampleBlock(6, [14, 16, 18, 20]), EndEvent(10)),
              ((point(3, 24), point(4, 32)), ()))
CASES = (
    SPARSE,
    replace(SPARSE, name="end-at-cut", events=(EndEvent(6),), deliveries=((),)),
    replace(SPARSE, name="gap-and-pending",
            history=(SampleBlock(0, [2, 4, 6]), GapEvent(3, 1), SampleBlock(4, [10, 12])),
            prefix=(point(0, 4), point(1, None), point(2, 16)),
            events=(SampleBlock(6, [14]), SampleBlock(7, [16]), EndEvent(8)),
            deliveries=((), (point(3, None),), ())),
    Case("phase-and-tail", 3, 2, F(1, 3), EXAMPLE_FILTER,
         (GapEvent(0, 1), SampleBlock(1, [4, 6, 8])), 4, 3,
         (point(1, None, F(1, 2)), point(2, 6, 1)), (3,),
         (EndEvent(4),), ((point(3, 4, F(3, 2)),),)),
    Case("cancellation", 2, 1, F(0), kernel(-2, -1, 1),
         (SampleBlock(0, [10**16, 1]),), 2, 1, (point(0, 1),), (0, 1),
         (SampleBlock(2, [0, -10**16]), EndEvent(4)), ((point(1, 1),), ())),
)


def prepare(repo, case):
    register_channel(repo, CHANNEL, "m/s²", case.input_rate)
    create_task(repo, TASK, CHANNEL, case.input_start, 0, case.output_rate, case.spec)
    for event in case.history:
        push_event(repo, TASK, event)
    prefix = read_waveform(repo, TASK)
    ASSERT.assertEqual(rows(prefix.points), case.prefix)
    ASSERT.assertFalse(prefix.sealed)
    ASSERT.assertEqual((repo.load_delivery_state(TASK).frontier, prefix.next_index),
                       (case.frontier, case.cursor))
    return prefix


def advance(repo, case):
    batches = tuple(rows(push_event(repo, TASK, event)) for event in case.events)
    ASSERT.assertEqual(batches, case.deliveries)
    snapshot = read_waveform(repo, TASK)
    ASSERT.assertTrue(snapshot.sealed)
    ASSERT.assertEqual(rows(snapshot.points), case.prefix + tuple(row for batch in batches for row in batch))
    report = compute_windows(repo, TASK, WINDOWS)
    return batches, export_waveform(repo, TASK), report.results


def digest_of(packet):
    return sha256(canonical_json(packet).encode("utf-8")).hexdigest()


def reference(case):
    with ArchiveRepository() as repo:
        prefix = prepare(repo, case)
        with ASSERT.assertRaises(ValueError):
            export_waveform(repo, TASK)
        batches, _, metrics = advance(repo, case)
        print(canonical_json({"case": case.name, "v1_export_active": "rejected",
                              "prefix": rows(prefix.points), "new_batches": batches,
                              "windows": [metric.record() for metric in metrics]}))


def reject_bad_transfers(repo, accept, packet, digest):
    before = repo.connection.serialize()
    for bad, expected in [(packet, "0" * 64),
                          ({**packet, "basis": []}, None),
                          ({**packet, "next_index": packet["next_index"] + 1}, None)]:
        with ASSERT.assertRaises(ValueError):
            accept(repo, bad, expected if expected is not None else digest_of(bad))
        ASSERT.assertEqual(repo.connection.serialize(), before)

    connection = repo.connection
    denied = []

    def fail_commit(action, detail, *_):
        if action == sqlite3.SQLITE_TRANSACTION and detail == "COMMIT":
            denied.append(detail)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(fail_commit)
    try:
        with ASSERT.assertRaises(sqlite3.Error):
            accept(repo, packet, digest)
    finally:
        connection.set_authorizer(None)
    ASSERT.assertEqual(denied, ["COMMIT"])
    ASSERT.assertFalse(connection.in_transaction)
    ASSERT.assertEqual(connection.serialize(), before)


def handoff(case, issue, accept, check_rejections=False):
    with ArchiveRepository() as source:
        prefix = prepare(source, case)
        packet, digest = issue(source, TASK)
        packet = json.loads(canonical_json(packet))
        ASSERT.assertEqual(digest, digest_of(packet))
        ASSERT.assertEqual((packet["frontier"], packet["next_index"]), (case.frontier, case.cursor))
        positions = sorted({entry["input_index"] for entry in packet["basis"]})
        ASSERT.assertEqual(positions, list(case.old_positions))
        expected = advance(source, case)

    with TemporaryDirectory(prefix="wave-handoff-") as directory:
        path = Path(directory) / "receiver.sqlite"
        with ArchiveRepository(path) as target:
            if check_rejections:
                reject_bad_transfers(target, accept, packet, digest)
            ASSERT.assertEqual(accept(target, deepcopy(packet), digest), prefix)
            if check_rejections:
                with ASSERT.assertRaises(ValueError):
                    accept(target, packet, digest)
                ASSERT.assertEqual(read_waveform(target, TASK), prefix)
        with ArchiveRepository(path) as target:
            ASSERT.assertEqual(read_waveform(target, TASK), prefix)
            actual = advance(target, case)
            ASSERT.assertEqual(actual, expected)
    batches, _, metrics = actual
    print(canonical_json({"case": case.name, "basis_positions": positions,
                          "reopened_prefix": rows(prefix.points), "new_batches": batches,
                          "windows": [metric.record() for metric in metrics]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("reference", "verify", "demo"))
    mode = parser.parse_args().mode
    if mode == "reference":
        for case in CASES:
            reference(case)
        return 0
    if mode == "verify":
        from run import verify
        if verify():
            return 1
    from wave import accept_handoff, export_handoff
    for case in CASES if mode == "verify" else (SPARSE,):
        handoff(case, export_handoff, accept_handoff,
                check_rejections=mode == "verify" and case is SPARSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
