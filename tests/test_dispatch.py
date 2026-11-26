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

    def test_add_requirement_reuses_the_bound_worker(self):
        allocations = []

        def allocate(reservation):
            if reservation["launch"]:
                worker_id = f"worker-{len(allocations) + 1}"
                allocations.append(self.dispatch("bind", reservation["key"], worker_id)["worker"])

        allocate(self.dispatch(*self.request))
        active, = self.dispatch("list", "--active")
        extra = ("reserve", "parser-whitespace", *self.request[2:],
                 "--reuse", active["key"], "--requirement", "Cover whitespace-only input")
        with ThreadPoolExecutor(max_workers=3) as pool:
            reservations = list(pool.map(lambda _: self.dispatch(*extra), range(3)))
        for reservation in reservations:
            allocate(reservation)
            self.assertEqual((reservation["parent"], reservation["worker"]), ("parser", "worker-1"))
        self.assertEqual(allocations, ["worker-1"])
        self.assertEqual(len(self.dispatch("list")), 1)
        self.assertEqual(self.dispatch("show", "parser")["additions"][0]["requirement"],
                         "Cover whitespace-only input")
        self.assertEqual(self.cli("heartbeat")["pending_handoffs"][0]["handoff"], "pending")

        claim = ("handoff", "parser-whitespace", "--claim", "Operator message authorizing reuse")
        with ThreadPoolExecutor(max_workers=3) as pool:
            claims = list(pool.map(lambda _: self.dispatch(*claim), range(3)))
        self.assertEqual(sum(row["send"] for row in claims), 1)
        self.assertEqual({(row["host"], row["worker"]) for row in claims}, {("local", "worker-1")})
        self.assertEqual(self.cli("heartbeat")["pending_handoffs"][0]["handoff"], "sending")
        self.dispatch("handoff", "parser-whitespace", "--reset", "Native tool confirmed no send")
        self.assertTrue(self.dispatch(*claim)["send"])
        sent = ("handoff", "parser-whitespace", "--sent", "Confirmed in worker-1")
        self.assertEqual(self.dispatch(*sent), self.dispatch(*sent))
        self.assertFalse(self.dispatch(*claim)["send"])
        self.assertEqual(self.cli("heartbeat")["pending_handoffs"], [])
        self.dispatch("report", "parser", "--evidence", "Verified both parser inputs")
        self.assertFalse(self.dispatch(*extra)["launch"])
        self.assertEqual(self.dispatch("show", "parser-whitespace")["handoff"], "sent")
        self.dispatch(*extra[:-1], "Different requirement", rejected=True)
        self.dispatch(*extra[:6], rejected=True)

    def test_nonmatching_scope_reserves_a_separate_worker(self):
        first = self.dispatch(*self.request)
        self.assertEqual(self.dispatch("list", "--active"), [])
        second_request = ("reserve", "parser-config", "--objective", "Fix empty input",
                          "--scope", "Approved config fixture only")
        attempted_reuse = (*second_request, "--reuse", "parser",
                           "--requirement", "Change the config fixture")
        self.assertIn("bound worker", self.dispatch(*attempted_reuse, rejected=True))
        self.dispatch("bind", first["key"], "worker-1")
        self.assertIn("exact objective and scope", self.dispatch(*attempted_reuse, rejected=True))
        second = self.dispatch(*second_request)
        self.dispatch("bind", second["key"], "worker-2")
        self.assertEqual(sum(row["launch"] for row in (first, second, self.dispatch(*second_request))), 2)
        self.assertEqual({row["worker"] for row in self.dispatch("list", "--active")},
                         {"worker-1", "worker-2"})
        self.assertEqual(self.cli("heartbeat")["pending_handoffs"], [])

    def test_pending_handoff_survives_worker_completion(self):
        self.dispatch(*self.request)
        self.dispatch("bind", "parser", "worker-1")
        extra = ("reserve", "parser-whitespace", *self.request[2:],
                 "--reuse", "parser", "--requirement", "Cover whitespace-only input")
        self.dispatch(*extra)
        self.dispatch("report", "parser", "--evidence", "Original result")
        self.dispatch("review", "parser", "--decision", "accept", "--evidence", "Verified original result")
        self.dispatch("cleaned", "parser", "--evidence", "Worker archived")
        on_retry = self.dispatch(*extra)
        self.assertEqual((on_retry["launch"], on_retry["worker"], on_retry["handoff"]),
                         (False, "worker-1", "pending"))
        self.assertEqual(self.dispatch("list", "--active"), [])
        self.assertIn("no longer running", self.dispatch(
            "handoff", "parser-whitespace", "--claim", "Operator message", rejected=True))
        self.assertEqual(self.cli("heartbeat")["pending_handoffs"], [{
            "key": "parser-whitespace", "parent": "parser", "handoff": "pending",
            "state": "cleaned", "host": "local", "worker": "worker-1",
        }])

    def test_absent_worker_keeps_failure_disposition(self):
        self.dispatch(*self.request)
        self.dispatch("abandon", "parser", "--evidence", "No worker exists after native lookup")
        result = self.dispatch("cleaned", "parser", "--evidence", "Confirmed no worker resources")
        self.assertEqual(result["decision"], "abandoned")
        self.assertIsNone(result["report"])
        self.assertFalse(self.dispatch(*self.request)["launch"])
