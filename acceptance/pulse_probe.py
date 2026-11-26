"""Publish one synthetic revision and wait for the registered Memory Lab to process it."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
import tempfile

import lab


def read_cli(bot, command, *args):
    result = subprocess.run([sys.executable, "../../codexos.py", command, *args],
                            cwd=bot, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def exercise(bot, timeout):
    path = bot / "inbox" / "lab.json"
    report = json.loads(path.read_text())
    source = next(s for s in read_cli(bot, "source-list") if s["id"] == "lab")
    if not source["enabled"] or source["revision"] != report["revision"]:
        raise ValueError("Wait for the pending lab revision or review the source status.")
    previous = report["value"]
    if previous < 1:
        raise ValueError("Start a fresh synthetic trial before reducing the pass count further.")
    revision = report["revision"] + 1
    run_id = f"lab-run-{revision}"
    report.update(revision=revision, run=run_id, evidence=[run_id], value=previous-1,
                  observed_at=datetime.now(timezone.utc).isoformat())
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        json.dump(report, stream)
    Path(stream.name).replace(path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        source = next(s for s in read_cli(bot, "source-list") if s["id"] == "lab")
        if source["revision"] == revision and source["outcome"] == "unchanged":
            hits = [f for f in read_cli(bot, "findings", "--limit", "100")
                    if f["source_id"] == "lab" and f["revision"] == revision]
            passed = (len(hits) == 1 and hits[0]["kind"] == "regression" and
                      hits[0]["evidence"] == [run_id] and source["checked"] > hits[0]["created"])
            return dict(passed=passed, run=run_id, previous_value=previous,
                        published=report, findings=hits, subsequent_checkpoint=source)
        time.sleep(2)
    return dict(passed=False, run=run_id, published=report, last_source=source,
                error="No subsequent unchanged checkpoint before the timeout")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="the disposable workspace from lab.py prepare")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--out", type=Path, help="optional JSON evidence destination")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("timeout must be positive")
    try:
        lab.load(args.run)
        bot = lab.lab(args.run)
        with (bot / "state/probe.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = exercise(bot, args.timeout)
        output = json.dumps(result, indent=2) + "\n"
        if args.out:
            args.out.write_text(output)
        print(output, end="")
        sys.exit(0 if result["passed"] else 1)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Probe failed: {exc}")
