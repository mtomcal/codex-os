"""Replay reviewed local monitor code in disposable fleets and report the comparison."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

DIRECTORY = Path(__file__).resolve().parent
FLEET = DIRECTORY.parents[1]
CASE_FILE = DIRECTORY / "cases-v1.json"
CASE_SHA256 = "e619952a5603b9e83aad323e1f73c03ce01ed2b0110f9599ec0d1bfe9b7f2623"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def invoke(folder, *args):
    result = subprocess.run(
        [sys.executable, str(folder / "codexos.py"), *args], cwd=folder,
        text=True, capture_output=True, timeout=20, check=True,
    )
    return json.loads(result.stdout) if result.stdout else None


def silence_review(did_poll, active_work, repeated_idle_runs):
    """Recommend cadence review only for repeated verified idle runs."""
    if did_poll or active_work or repeated_idle_runs < 3:
        return None
    return "Review cadence with operator"


def replay(root, suite, timestamp):
    invoke(root, "init")
    source = suite["source"]
    invoke(root, "source-add", source, "eval", "observation.json")
    invoke(root, "workload", "add", "release-check", "--title", "Release check",
           "--owner", "fixture", "--objective", "Measure release tests",
           "--criteria", "Release reviewed", "--next-action", "Review next run",
           "--source", source)
    invoke(root, "workload", "update", "release-check", "--revision", "1", "--state", "ready")
    invoke(root, "workload", "update", "release-check", "--revision", "2", "--state", "running")
    results = []
    snapshot = root / "bots/chief-of-staff/inbox/observation.json"
    for step in suite["steps"]:
        revision = step["revision"]
        obs = dict(kind="eval", source=source, run=f"run-{revision}", revision=revision,
                   value=step["score"], metric=suite["metric"], direction="higher",
                   unit="percent", blockers=step["blockers"], observed_at=timestamp,
                   evidence=[f"fixture/run-{revision}"])
        snapshot.write_text(json.dumps(obs))
        before, = invoke(root, "source-list")
        raw = invoke(root, "heartbeat")
        after, = invoke(root, "source-list")
        alerts = [{k: row[k] for k in ("kind", "revision", "evidence")}
                  for row in (raw or {}).get("findings", [])]
        expected = {"silent": not step["expect"], "alerts": step["expect"], "outcome": step["outcome"]}
        actual = {"silent": raw is None, "alerts": alerts, "outcome": after["outcome"]}
        if "expected_change" in step:
            detail = " ".join(row["detail"] for row in (raw or {}).get("findings", []))
            expected["change_named"] = True
            actual["change_named"] = all(part in detail for part in step["expected_change"])
        if "expected_proposal" in step:
            workload = invoke(root, "workload", "show", "release-check")
            active = workload["state"] == "running"
            polled = after["checked"] > before["checked"] and after["revision"] == revision
            actual["polled_active_workload"] = polled and active
            expected["polled_active_workload"] = True
            actual["proposal"] = silence_review(polled, active, repeated_idle_runs=0)
            expected["proposal"] = step["expected_proposal"]
        results.append({"case": step["id"], "expected": expected, "actual": actual,
                        "pass": actual == expected, "heartbeat": raw})
    actual_proposal = silence_review(False, False, 3)
    results.append({"case": "review-three-confirmed-idle-runs", "expected": suite["idle_control"],
                    "actual": actual_proposal, "pass": actual_proposal == suite["idle_control"]})
    return results


def compare(suite, timestamp, candidate):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for filename in ("codexos.py", "fleet.py", "ledger.py", "monitor.py", "dispatch.py", "permission_plan.py"):
            shutil.copy(FLEET / filename, root / filename)
        for directory in ("templates", "tests"):
            shutil.copytree(FLEET / directory, root / directory,
                            ignore=shutil.ignore_patterns("__pycache__"))
        (root / "monitor.py").write_bytes(candidate)
        try:
            results = replay(root, suite, timestamp)
        except (subprocess.SubprocessError, ValueError, KeyError, TypeError, OSError) as exc:
            results = [{"case": "replay-execution", "pass": False, "error": str(exc),
                        "stderr": getattr(exc, "stderr", None)}]
        unit = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                              text=True, capture_output=True, cwd=root, timeout=120)
        return {"monitor_sha256": sha(candidate), "cases": results,
                "fleet_suite": {"exit_code": unit.returncode, "transcript": unit.stderr},
                "pass": all(case["pass"] for case in results) and unit.returncode == 0}


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("The negative-control fixture needs review for this monitor version")
    return source.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-monitor", type=Path, help="Human-reviewed local monitor.py")
    parser.add_argument("--output", type=Path, help="Save the JSON evidence packet")
    args = parser.parse_args()
    case_bytes = CASE_FILE.read_bytes()
    if sha(case_bytes) != CASE_SHA256:
        parser.error("v1 cases changed. Review a new fixture version before replay.")
    suite = json.loads(case_bytes)
    timestamp = datetime.now(timezone.utc).isoformat()
    current = (FLEET / "monitor.py").read_bytes()
    if args.candidate_monitor:
        candidate = args.candidate_monitor.read_bytes()
        label = "reviewed candidate"
    else:
        candidate = replace_once(current, b'priority = "briefing" if better else "attention"',
                                  b'priority = "briefing"')
        candidate = replace_once(candidate, b'if any(blocker) and blocker != blocker_signature(previous):',
                                  b'if any(blocker) and changed:')
        label = "synthetic negative control"
    before = compare(suite, timestamp, current)
    after = compare(suite, timestamp, candidate)
    failed = [r["case"] for r in after["cases"] if not r["pass"]]
    default_control_passed = (failed == ["regression", "repeated-blocker"] and after["fleet_suite"]["exit_code"] != 0)
    result = {
        "case_version": suite["version"], "case_sha256": sha(case_bytes), "observed_at_utc": timestamp,
        "candidate": label, "current": before, "proposed": after,
        "diff": "".join(difflib.unified_diff(current.decode().splitlines(True), candidate.decode().splitlines(True),
                                              fromfile="current/monitor.py", tofile="candidate/monitor.py")),
        "failed_candidate_cases": failed, "decision": "eligible for operator review" if after["pass"] else "reject candidate",
        "changes_applied": False,
    }
    if not args.candidate_monitor:
        result["negative_control_detected_as_expected"] = default_control_passed
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    if args.candidate_monitor:
        return int(not after["pass"])
    return int(not (before["pass"] and default_control_passed))


if __name__ == "__main__":
    sys.exit(main())
