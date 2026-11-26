"""Drive the live harness lifecycle locally, including refusals to delete the wrong run."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

DRIVER = Path(__file__).with_name("lab.py")


def call(*args, reject=False):
    proc = subprocess.run([sys.executable, str(DRIVER), *map(str,args)], capture_output=True, text=True)
    if (proc.returncode != 0) != reject:
        raise RuntimeError(f"Unexpected exit {proc.returncode}: {proc.stdout} {proc.stderr}")
    return proc.stdout.strip()


with tempfile.TemporaryDirectory() as tmp:
    parent = Path(tmp).resolve()
    keep = parent/"unrelated.txt"
    keep.write_text("preserve")
    run = Path(call("prepare", parent))
    run_id = json.loads(call("status", run))["run"]
    call("baseline", run)
    call("publish", run)
    call("bind", run, "worker", "synthetic-worker-id")
    call("clean", run, "--confirm", run_id, reject=True)
    call("release", run, "worker", "wrong-worker-id", reject=True)
    call("release", run, "worker", "synthetic-worker-id")
    call("clean", run, "--confirm", "wrong-run", reject=True)
    call("clean", run, "--confirm", run_id)
    if run.exists() or keep.read_text() != "preserve":
        raise RuntimeError("Cleanup did not remove exactly the test run")
    print("Factory created a new bot, partial cleanup was refused, owned run removed, sibling retained.")
