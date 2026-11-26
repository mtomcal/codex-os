"""Run the fleet acceptance suite; save optional results outside disposable test fleets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="create a new directory for this replay's evidence")
    parser.add_argument("--evidence-dir", type=Path, help="grade both native evidence bundles captured in this directory")
    parser.add_argument("--notification-evidence", type=Path, help="grade a captured worker completion message and review")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codexos-replay-") as tmp:
        out = Path(tmp)
        if args.results:
            out = args.results.resolve()
            out.mkdir(parents=True, exist_ok=False)
        jobs = [
            ("Fleet unit and integration tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("Disposable bot creation and teardown", ["acceptance/check_cleanup.py"]),
            ("Delegated worker archive requirements", ["acceptance/check_worker_archive.py"]),
            ("Fresh fleet CLI replay", ["acceptance/replay.py", "--output", str(out/"fleet.json")]),
            ("Fleet Maintainer candidate comparison", ["acceptance/maintainer/review.py", "--output", str(out/"review.json")]),
            ("Memory evaluator on synthetic input", ["acceptance/grade_live.py", "acceptance/fixtures/memory.json", "--out", str(out/"memory.json")]),
            ("Dispatch evaluator on synthetic input", ["acceptance/grade_dispatch.py", "acceptance/fixtures/dispatch.json"]),
        ]
        if args.evidence_dir:
            evidence = args.evidence_dir.resolve()
            jobs.extend([
                ("Captured native memory trial", ["acceptance/grade_live.py", str(evidence/"live-evidence.json"), "--out", str(out/"native-memory.json")]),
                ("Captured native worker trial", ["acceptance/grade_dispatch.py", str(evidence/"dispatch-evidence.json")]),
            ])
        if args.notification_evidence:
            jobs.append(("Worker completion notification", ["acceptance/grade_notification.py", str(args.notification_evidence.resolve())]))
        result = []
        for index, (label, argv) in enumerate(jobs, 1):
            run = subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True,
                                 env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            log = out / f"{index}.txt"
            log.write_text(run.stdout + run.stderr)
            print(f"{'PASS' if run.returncode == 0 else 'FAIL'}  {label}", flush=True)
            if run.returncode:
                print(log.read_text()[-3000:], file=sys.stderr)
            result.append({"check": label, "exit": run.returncode, "log": log.name})
        (out/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
        return int(any(check["exit"] for check in result))


if __name__ == "__main__":
    sys.exit(main())
