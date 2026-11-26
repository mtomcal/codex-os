import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import ledger


class LedgerCommands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bot = Path(self.temp.name)
        (self.bot / "evidence").mkdir()
        self.db = sqlite3.connect(self.bot / "state.db")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.parser = argparse.ArgumentParser()
        ledger.commands(self.parser.add_subparsers(dest="command"))
        ledger.install(self.db)
        self.stamp = 1800000000
        clock = patch.object(ledger, "now", side_effect=lambda: self.stamp)
        clock.start()
        self.addCleanup(clock.stop)

    def command(self, *args):
        with self.db:
            return ledger.run(self.db, self.parser.parse_args(args), self.bot.parent, self.bot)

    def add(self, kind, key, *extra):
        return self.command(kind, "add", key, "--title", "Check suite", "--objective", "Ship the change",
                            "--owner", "engineering", "--criteria", "suite passes",
                            "--next-action", "review results", *extra)

    def advance(self, kind, key, state, *extra):
        revision = self.command(kind, "show", key)["revision"]
        return self.command(kind, "update", key, "--revision", str(revision), "--state", state, *extra)

    def complete_workload(self):
        self.advance("workload", "build", "ready")
        self.advance("workload", "build", "running")
        receipt = self.bot / "evidence" / "ci.json"
        receipt.write_text(json.dumps({"schema": 1, "kind": "workload", "id": "build", "result": "passed",
                                       "criteria": "suite passes", "run_id": "ci-28"}))
        return self.advance("workload", "build", "completed", "--receipt", receipt.name)

    def test_state_and_independent_completion_evidence(self):
        self.add("workload", "build")
        with self.assertRaisesRegex(ValueError, "invalid transition"):
            self.advance("workload", "build", "completed")
        result = self.complete_workload()
        proof = json.loads(result["evidence"])
        self.assertEqual(proof["run_id"], "ci-28")
        self.assertEqual(len(proof["sha256"]), 64)
        self.assertEqual(self.command("workload", "list")[0]["state"], "completed")
        self.assertEqual(ledger.summary(self.db)["workloads"], [])
        self.command("workload", "update", "build", "--revision", "4", "--owner", "maintainer")
        outcomes = ledger.recent(self.db, self.stamp)
        self.assertEqual([(r["id"], r["state"]) for r in outcomes], [("build", "completed")])
        self.assertEqual(outcomes[0]["evidence"]["run_id"], "ci-28")

    def test_wrong_missing_and_symlink_receipts_preserve_state(self):
        self.add("commitment", "review")
        with self.assertRaisesRegex(ValueError, "receipt"):
            self.advance("commitment", "review", "completed")
        path = self.bot / "evidence" / "wrong.json"
        path.write_text('{"kind": "workload"}')
        with self.assertRaisesRegex(ValueError, "does not verify"):
            self.advance("commitment", "review", "completed", "--receipt", path.name)
        (path.parent / "link.json").symlink_to(path)
        with self.assertRaises(OSError):
            self.advance("commitment", "review", "completed", "--receipt", "link.json")
        self.assertEqual(self.command("commitment", "show", "review")["revision"], 1)

    def test_strategic_respects_dependency_and_quiet_retries(self):
        self.add("workload", "build")
        self.add("commitment", "review", "--dependency", "build")
        self.advance("commitment", "review", "waiting")
        self.assertEqual([r["id"] for r in self.command("strategic")], ["build"])
        self.assertIsNone(self.command("strategic"))
        self.complete_workload()
        self.assertEqual([r["id"] for r in self.command("strategic")], ["review"])
        self.assertIsNone(self.command("strategic"))

    def test_deadlines_and_wait_until(self):
        self.add("commitment", "today", "--due", "2025-01-01T12:00Z")
        self.add("commitment", "later", "--due", "2025-01-01T12:00Z", "--review", "2099-01-01T00:00Z")
        self.assertEqual([r["id"] for r in ledger.due(self.db)], ["today"])
        self.assertEqual(ledger.due(self.db), [])
        self.assertEqual([r["id"] for r in self.command("strategic")], ["today"])
        self.advance("commitment", "today", "parked")
        self.assertIsNone(self.command("strategic"))

    def test_concurrency_and_cycle(self):
        self.add("workload", "a")
        self.add("workload", "b", "--dependency", "a")
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.command("workload", "update", "a", "--revision", "1", "--dependency", "b")
        self.advance("workload", "a", "ready")
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.command("workload", "update", "a", "--revision", "1", "--owner", "different")
        self.assertEqual(self.command("workload", "show", "a")["owner"], "engineering")

    def test_memory_revision_conflict_and_historical_provenance(self):
        base = ["memory", "add", "release", "Thursday", "--source", "calendar", "--evidence", "entry 40"]
        self.command(*base)
        self.command(*base)
        self.assertEqual(len(self.command("memory", "list")), 1)
        self.command("memory", "add", "release", "Friday", "--source", "planning", "--evidence", "record 42")
        self.assertEqual([r["status"] for r in self.command("memory", "list")], ["disputed", "disputed"])
        with self.assertRaisesRegex(ValueError, "revision conflict"):
            self.command("memory", "resolve", "release", "2", "--latest", "1", "--source", "user", "--evidence", "confirmed")
        self.command("memory", "resolve", "release", "2", "--latest", "2", "--source", "user", "--evidence", "confirmed")
        records = self.command("memory", "list", "--all")
        self.assertEqual([r["status"] for r in records], ["active", "archived", "archived"])
        self.assertEqual(records[0]["supersedes"], 2)
        self.assertEqual(records[0]["evidence"], "confirmed")

    def test_reflection_archives_expiry_and_routes_feedback_once(self):
        self.command("memory", "add", "temp", "Feature enabled", "--source", "report", "--evidence", "run 16",
                     "--expires", "2025-01-01T00:00Z")
        fb = ["feedback", "observation-1", "--subject", "daily alert", "--outcome", "unnecessary", "--evidence", "operator response"]
        self.command(*fb)
        self.command(*fb)
        result = self.command("reflect")
        self.assertEqual(result["archived"], [{"key": "temp", "rev": 1}])
        self.assertEqual(result["feedback_for_review"][0]["subject"], "daily alert")
        self.assertIsNone(self.command("reflect"))
        self.assertEqual(self.command("memory", "list"), [])


if __name__ == "__main__":
    unittest.main()
