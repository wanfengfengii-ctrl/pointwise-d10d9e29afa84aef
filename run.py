import argparse
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from wave import ArchiveRepository
from wave.archive.codec import canonical_json
from wave.archive.export import export_waveform
from wave.assembly.replay import load_recording, run_workday
from wave.quality.service import read_window_results

ROOT = Path(__file__).resolve().parent


def verify():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def demo_at(path):
    gap = load_recording(ROOT / "samples" / "day.json")
    clean = copy.deepcopy(gap)
    clean["task"]["task_id"] = "vibration-clean"
    clean["events"] = [
        {"kind": "samples", "start": 0, "values": [2, 4]},
        {"kind": "samples", "start": 2, "values": [6, 8, 10]},
        {"kind": "end", "start": 5},
    ]
    reports = []
    with ArchiveRepository(path) as repository:
        for recording in (clean, gap):
            task_id = recording["task"]["task_id"]
            try:
                state = repository.load_delivery_state(task_id)
            except KeyError:
                continue
            if state.event_count or state.ended:
                raise ValueError("demo task already has progress: " + task_id)
        for recording in (clean, gap):
            report = run_workday(repository, recording)
            reports.append(report)
            for event, points in zip(recording["events"], report.deliveries):
                print(canonical_json({
                    "event": event, "task_id": report.task_id,
                    "new_points": [{"index": p.index, "time": [p.time.numerator, p.time.denominator],
                                    "value": p.value, "valid": p.valid} for p in points]}))
            print(report.exported)
            print(canonical_json({"task_id": report.task_id, "window_batch": report.windows.batch_id,
                                  "windows": [r.record() for r in report.windows.results]}))
    with ArchiveRepository(path) as repository:
        for report in reports:
            if export_waveform(repository, report.task_id) != report.exported:
                raise AssertionError("reopened waveform differs")
            if read_window_results(repository, report.windows.batch_id) != report.windows:
                raise AssertionError("reopened metrics differ")
            print(canonical_json({"task_id": report.task_id, "reopen_equal": True}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline vibration capture and quality review")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--db", help="new archive path, or archive without these demo tasks")
    arguments = parser.parse_args(argv)
    if arguments.command == "verify":
        return verify()
    try:
        if arguments.db:
            return demo_at(arguments.db)
        with tempfile.TemporaryDirectory(prefix="wave-demo-") as directory:
            return demo_at(str(Path(directory) / "workday.sqlite"))
    except Exception as error:
        print(canonical_json({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
