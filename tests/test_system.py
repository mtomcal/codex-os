"""Run the public CLI in a disposable copy of the fleet."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


class BotSession(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        for module in ROOT.glob("*.py"):
            shutil.copy(module, self.folder)
        shutil.copytree(ROOT / "templates", self.folder / "templates")
        self.call("init")
        self.chief = self.folder / "bots" / "chief-of-staff"
        self.specialist = self.folder / "bots" / "eval-monitor"

    def call(self, *args, cwd=None):
        process = subprocess.run([sys.executable, str(self.folder / "codexos.py"), *args],
                                 cwd=cwd or self.folder, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout) if process.stdout else None

    def test_watch_and_restart(self):
        self.call("source-add", "suite", "eval", "suite.json", cwd=self.chief)
        self.call("workload", "add", "release", "--title", "Release suite",
                  "--criteria", "All cases pass", "--owner", "qa", "--objective", "Check cases",
                  "--next-action", "Read the next suite result", "--source", "suite", cwd=self.chief)
        def publish(rev, score):
            data = dict(source="suite", kind="eval", run=str(rev), value=score, unit="percent",
                        metric="pass-rate", direction="higher", evidence=[f"run-{rev}"],
                        revision=rev, observed_at=datetime.now(timezone.utc).isoformat())
            (self.chief / "inbox" / "suite.json").write_text(json.dumps(data))
        publish(1, 90)
        self.assertIsNone(self.call("heartbeat", cwd=self.chief))
        publish(2, 80)
        cli = [sys.executable, "../../codexos.py", "heartbeat"]
        children = [subprocess.Popen(cli, cwd=self.chief, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True) for _ in range(3)]
        alerts = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
            if stdout:
                alerts.extend(json.loads(stdout)["findings"])
        self.assertEqual([alert["kind"] for alert in alerts], ["regression"])
        summary = self.call("briefing", "--period", "week", cwd=self.chief)
        data = summary["work"]["workloads"][0]["observation"]
        self.assertEqual([data["baseline"]["value"], data["latest"]["value"]], [90, 80])
        self.assertEqual(summary["findings"][0]["evidence"], ["run-2"])
        self.assertEqual(self.call("findings", cwd=self.specialist), [])

    def test_mailbox_survives_new_process_and_retry(self):
        self.call("mailbox", "assign", "eval-monitor", "check-score", "Check run 17", cwd=self.chief)
        self.call("mailbox", "assign", "eval-monitor", "check-score", "Check run 17", cwd=self.chief)
        self.assertEqual(len(self.call("mailbox", "list", cwd=self.specialist)), 1)
        self.assertEqual(self.call("heartbeat", cwd=self.specialist)["mailbox"][0]["key"], "check-score")
        self.assertIsNone(self.call("heartbeat", cwd=self.specialist))
        self.call("mailbox", "report", "check-score", "run-17/result.json", cwd=self.specialist)
        self.assertEqual(self.call("heartbeat", cwd=self.chief)["mailbox"][0]["evidence"], "run-17/result.json")
        self.assertIsNone(self.call("heartbeat", cwd=self.chief))
        self.assertEqual(self.call("mailbox", "list", cwd=self.chief)[0]["evidence"], "run-17/result.json")
