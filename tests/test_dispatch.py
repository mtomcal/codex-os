"""Drive worker coordination through the public CLI across process boundaries."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DispatchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        for module in ROOT.glob("*.py"):
            shutil.copy(module, self.root)
        shutil.copytree(ROOT / "templates", self.root / "templates")
        self.cli("init")
        self.request = ("reserve", "parser", "--objective", "Fix empty input",
                        "--scope", "Approved fixture parser and test only")

    def cli(self, *args, rejected=False):
        result = subprocess.run([sys.executable, str(self.root / "codexos.py"), *args],
                                cwd=self.root, capture_output=True, text=True)
        if rejected:
            self.assertNotEqual(result.returncode, 0)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def dispatch(self, *args, **kwargs):
        return self.cli("dispatch", *args, **kwargs)

    def test_concurrent_intake_crash_and_reconciliation(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            received = list(pool.map(lambda _: self.dispatch(*self.request), range(3)))
        self.assertEqual(sum(row["launch"] for row in received), 1)
        self.assertFalse(self.dispatch(*self.request)["launch"])
        self.assertEqual(self.dispatch("show", "parser")["state"], "reserved")
        self.dispatch(*self.request[:-1], "Different permitted files", rejected=True)
        self.dispatch("bind", "parser", "worker-1")
        self.assertEqual(self.dispatch("bind", "parser", "worker-1")["worker"], "worker-1")
        self.dispatch("bind", "parser", "worker-2", rejected=True)
        self.assertEqual(self.cli("--bot", "eval-monitor", "dispatch", "list"), [])

    def test_running_job_is_visible_until_review_delivery_and_cleanup(self):
        self.dispatch(*self.request)
        self.dispatch("bind", "parser", "worker-1")
        self.assertEqual(self.dispatch("list")[0]["state"], "running")
        self.dispatch("review", "parser", "--decision", "accept", "--evidence", "unverified", rejected=True)
        self.dispatch("report", "parser", "--evidence", "Parser patch and focused test log")
        self.dispatch("cleaned", "parser", "--evidence", "not reviewed", rejected=True)
        self.dispatch("review", "parser", "--decision", "accept", "--evidence", "Verified test in project")
        cleaned = self.dispatch("cleaned", "parser", "--evidence", "Native worker archived after delivery")
        self.assertEqual((cleaned["decision"], cleaned["state"]), ("accepted", "cleaned"))
        self.assertEqual(cleaned["report"], "Parser patch and focused test log")
        self.assertEqual(cleaned, self.dispatch("cleaned", "parser", "--evidence", cleaned["cleanup"]))
        self.assertEqual(cleaned, self.dispatch("report", "parser", "--evidence", cleaned["report"]))
        self.dispatch("report", "parser", "--evidence", "Changed claim", rejected=True)
        self.assertFalse(self.dispatch(*self.request)["launch"])

    def test_absent_worker_keeps_failure_disposition(self):
        self.dispatch(*self.request)
        self.dispatch("abandon", "parser", "--evidence", "No worker exists after native lookup")
        result = self.dispatch("cleaned", "parser", "--evidence", "Confirmed no worker resources")
        self.assertEqual(result["decision"], "abandoned")
        self.assertIsNone(result["report"])
        self.assertFalse(self.dispatch(*self.request)["launch"])
