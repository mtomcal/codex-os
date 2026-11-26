"""Exercise the archive condition in both worker graders using synthetic receipts."""
import json
import shutil
import subprocess
from pathlib import Path
import unittest

import grade_dispatch
import grade_notification


class WorkerArchiveTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required to replay the desktop JavaScript adapter")
    def test_heartbeat_recovers_missed_notifications_and_lost_archive_receipts(self):
        subprocess.run(["node", str(Path(__file__).with_name("check_heartbeat.js"))], check=True)

    def test_dispatch_requires_archived_worker(self):
        fixture = Path(__file__).parent / "fixtures/dispatch.json"
        evidence = json.loads(fixture.read_text())
        self.assertTrue(all(grade_dispatch.checks(evidence).values()))
        for receipt in (None, evidence["intake"]["thread"]):
            with self.subTest(receipt=receipt):
                evidence["archived_id"] = receipt
                self.assertFalse(all(grade_dispatch.checks(evidence).values()))

    def test_notification_requires_native_archive_lookup(self):
        evidence = {
            "chief": "chief", "worker": "worker", "trigger": {"type": "userMessage"}, "sends": [],
            "source_reads": [], "retained_report": "17 29 46", "delivery": "",
            "ledger": {"state": "cleaned", "cleanup": "recorded", "worker": "worker", "host": "local"},
            "archive": {"tool": "set_thread_archived", "status": "completed",
                        "arguments": {"archived": True, "threadId": "worker"}},
        }
        for lookup, expected in [
            (None, False),
            ({"id": "chief", "hostId": "local"}, False),
            ({"id": "worker", "hostId": "other"}, False),
            ({"id": "worker", "hostId": "local"}, True),
        ]:
            with self.subTest(lookup=lookup):
                evidence["archive_lookup"] = lookup
                result = grade_notification.checks(evidence)
                self.assertEqual(expected, result["Chief archived the bound worker and retained the report"])


if __name__ == "__main__":
    unittest.main()
