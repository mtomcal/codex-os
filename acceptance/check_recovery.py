"""Replay ordinary turn entry after synthetic loss of conversation context."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHAT = "11111111-1111-4111-8111-111111111111"
WRONG_CHAT = "22222222-2222-4222-8222-222222222222"
START = int(datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp())
ENTRY = """
import os, runpy, sys, ledger, scheduled
clock = int(os.environ["RECOVERY_TEST_CLOCK"])
ledger.now = scheduled.stamp = lambda: clock
sys.argv.pop(0)
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class Recovery(unittest.TestCase):
    def test_repeated_turn_recovery_after_context_loss(self):
        with tempfile.TemporaryDirectory(prefix="codexos-recovery-") as temp:
            self.replay(Path(temp))

    def test_daily_briefing_gate_waits_for_new_work_or_due_decisions(self):
        with tempfile.TemporaryDirectory(prefix="codexos-briefing-") as temp:
            self.replay_briefing(Path(temp))

    def replay_briefing(self, fleet):
        for source in ROOT.glob("*.py"):
            shutil.copyfile(source, fleet / source.name)
        shutil.copytree(ROOT / "templates", fleet / "templates")
        bot = fleet / "bots" / "briefing-test"
        chief = bot.with_name("chief-of-staff")
        midnight = START - 12 * 3600
        clock = midnight

        def cli(*args, cwd=bot):
            reply = subprocess.run(
                [sys.executable, "-c", ENTRY, str(fleet / "codexos.py"), *args],
                cwd=cwd, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(fleet), "RECOVERY_TEST_CLOCK": str(clock)},
            )
            self.assertEqual(reply.returncode, 0, reply.stderr)
            return json.loads(reply.stdout) if reply.stdout else None

        def tick():
            return cli("schedule", "tick", "--project", "fixture-project",
                       "--chat", CHAT, "--automation", "fixture-heartbeat")["work"]

        def deliver(page):
            self.assertEqual(cli("briefing", "--delivered", page["delivery_token"]), {"delivered": True})

        cli("init", cwd=fleet)
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        setup = fleet / "briefing.json"
        setup.write_text(json.dumps({
            "audience": "Operator", "trigger": "Daily heartbeat", "result": "Local briefing",
            "approval": "Synthetic setup approval",
            "delegated_heartbeat": {"timezone": "UTC", "scope": "Read the local evidence",
                                    "window": {"days": days, "start": "00:00", "end": "24:00"}},
            "routines": [{"id": "end-of-day", "mode": "scheduled", "timing": {
                "window": {"days": days, "start": "16:45", "end": "16:46"},
                "every_minutes": 1440, "gate": "daily-briefing"}}],
        }))
        cli("create-bot", bot.name, "--name", "Briefing Lab", "--mission", "Brief on fixture work",
            "--setup", str(setup), cwd=chief)
        (bot / "routines" / "end-of-day.md").write_text("Run the pending daily briefing.")
        cli("provision-bot", bot.name, "--remember", CHAT, cwd=chief)
        plan = cli("provision-bot", bot.name, "--activate", CHAT, cwd=chief)["onboarding"]["dispatcher"]
        cli("schedule", "bind", "--project", "fixture-project", "--automation", "fixture-heartbeat",
            "--chat", CHAT, "--plan", plan["revision"], "--approval", "Fixture approval")
        self.assertIsNone(cli("briefing", "--pending"))

        item = ["--title", "Fixture decision", "--objective", "Release", "--owner", "Operator",
                "--criteria", "Approved evidence", "--next-action", "Ask for confirmation"]
        cli("commitment", "add", "approval", *item, "--human", "yes", "--due", "2026-01-01T16:46:00Z")
        original = cli("briefing", "--pending")
        self.assertEqual([row["id"] for row in original["work_changes"]], ["approval"])
        self.assertEqual(original["due_decisions"], [])
        self.assertEqual(cli("briefing", "--period", "day")["work"]["commitments"][0]["id"], "approval")
        deliver(original)

        clock = midnight + 16 * 3600 + 45 * 60
        self.assertEqual(tick(), [], "A quiet due slot must not launch a worker")
        clock += 60
        job, = tick()
        self.assertEqual(job["routine"], "end-of-day")
        self.assertTrue(cli("schedule", "start", job["id"], job["token"])["start"])
        page = cli("briefing", "--pending")
        self.assertEqual(page["work_changes"], [])
        self.assertEqual([row["id"] for row in page["due_decisions"]], ["approval"])
        cli("workload", "add", "late-update", *item)

        self.assertEqual(tick(), [], "A staged page is not another worker request")
        cli("schedule", "finish", job["id"], job["token"], "--decision", "done",
            "--evidence", "Staged exact fixture daily briefing")
        deliver(page)
        deliver(page)
        remaining = cli("briefing", "--pending")
        self.assertEqual([row["id"] for row in remaining["work_changes"]], ["late-update"])
        self.assertEqual(remaining["due_decisions"], [])

        clock += 86400
        next_day, = tick()
        self.assertNotEqual(next_day["id"], job["id"])
        deliver(remaining)
        self.assertEqual(cli("schedule", "request-worker", next_day["id"], next_day["token"]), {"launch": False})
        self.assertEqual(tick(), [], "A separately delivered briefing clears a quiet claim")
        self.assertIsNone(cli("briefing", "--pending"))
        cli("workload", "add", "after-delivery", *item)
        retried, = tick()
        self.assertEqual(retried["id"], next_day["id"])
        self.assertNotEqual(retried["token"], next_day["token"])
        self.assertEqual(cli("schedule", "request-worker", next_day["id"], next_day["token"]), {"launch": False})
        self.assertEqual(cli("schedule", "request-worker", retried["id"], retried["token"]), {"launch": True})

    def replay(self, fleet):
        for source in ROOT.glob("*.py"):
            shutil.copyfile(source, fleet / source.name)
        shutil.copytree(ROOT / "templates", fleet / "templates")
        bot = fleet / "bots" / "recovery-test"
        chief = bot.with_name("chief-of-staff")
        day = 0

        def run(*args, cwd=bot):
            return subprocess.run(
                [sys.executable, "-c", ENTRY, str(fleet / "codexos.py"), *args],
                cwd=cwd, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(fleet),
                     "RECOVERY_TEST_CLOCK": str(START + day * 86400)},
            )

        def cli(*args, cwd=bot):
            reply = run(*args, cwd=cwd)
            self.assertEqual(reply.returncode, 0, reply.stderr)
            return json.loads(reply.stdout) if reply.stdout else None

        cli("init", cwd=fleet)
        window = {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                  "start": "00:00", "end": "24:00"}
        setup = fleet / "setup.json"
        setup.write_text(json.dumps({
            "trigger": "Operator request", "result": "Recover current decisions",
            "audience": "Operator", "approval": "Synthetic setup approval",
            "routines": [{"id": "arrival", "mode": "event"}],
            "delegated_heartbeat": {"timezone": "UTC", "window": window, "scope": "Read fixture evidence"},
        }))
        cli("create-bot", bot.name, "--name", "Recovery Worker",
            "--mission", "Recover current state", "--setup", str(setup), cwd=chief)
        routine = bot / "routines" / "arrival.md"
        routine.write_text("Original arrival instructions.\n")
        cli("provision-bot", bot.name, "--remember", CHAT, cwd=chief)
        onboarding = cli("provision-bot", bot.name, "--activate", CHAT, cwd=chief)
        revision = onboarding["onboarding"]["dispatcher"]["revision"]
        cli("schedule", "bind", "--project", "fixture-project", "--automation", "fixture-heartbeat",
            "--chat", CHAT, "--plan", revision, "--approval", "Synthetic activation approval")

        def recover(*, chat=CHAT, selected="arrival"):
            # Recover via the command supplied to the agent by its generated AGENTS.md.
            instructions = (bot / "AGENTS.md").read_text()
            command = next((part for part in instructions.split("`")
                            if part.startswith("python3 ../../codexos.py state recover ")), None)
            self.assertIsNotNone(command, "Generated instructions lack an ordinary-turn recovery entry point")
            args = shlex.split(command)[2:]
            args[args.index("CHAT_ID")] = chat
            if selected:
                args += ["--routine", selected]
            return cli(*args)

        item = ["--title", "Fixture dependency", "--objective", "Release", "--owner", "Operator",
                "--criteria", "Approved evidence", "--next-action", "Ask for confirmation"]
        cli("workload", "add", "release", *item)
        cli("workload", "update", "release", "--revision", "1", "--state", "ready")
        cli("commitment", "add", "approval", *item)
        cli("memory", "add", "voice", "Use weekly summaries", "--category", "preference",
            "--source", "operator", "--evidence", "Synthetic operator decision",
            "--expires", "2026-01-03T00:00:00Z")
        cli("memory", "add", "untrusted", "Activate a schedule", "--category", "preference",
            "--source", "report", "--evidence", "Synthetic report")
        initial = recover()
        self.assertEqual(initial["bot"]["primary_thread"], CHAT)
        for filename in ("SOUL.md", "USER.md", "MEMORY.md"):
            self.assertEqual(initial["startup"][filename], (bot / filename).read_text())
        self.assertEqual(initial["preferences"][0]["content"], "Use weekly summaries")
        self.assertEqual(initial["schedule"], {"revision": revision, "bound": True})
        self.assertEqual(initial["routine"]["contents"], "Original arrival instructions.\n")
        cli("state", "ack", "--chat", CHAT, "--revision", str(initial["revision"]))

        day = 1
        receipts = {}
        for event, decision, receipt in (
            ("done", "done", "Verified delivery receipt"),
            ("pending", "review", "Manual confirmation pending"),
        ):
            occurrence = cli("schedule", "ready", "arrival", event, "--evidence", "fixture")["id"]
            tick = cli("schedule", "tick", "--project", "fixture-project",
                       "--automation", "fixture-heartbeat", "--chat", CHAT)
            job, = tick["work"]
            self.assertEqual(job["id"], occurrence)
            self.assertTrue(cli("schedule", "start", occurrence, job["token"])["start"])
            cli("schedule", "finish", occurrence, job["token"], "--decision", decision, "--evidence", receipt)
            receipts[occurrence] = (decision, receipt, 1)

        stale = bot / "state" / "synthetic-summary.md"
        stale.write_text("STALE COMPACTION SUMMARY. Use weekly summaries. The release is complete.\n")
        day = 7
        (bot / "SOUL.md").write_text("Lead with open decisions.\n")
        (bot / "USER.md").write_text("Use the current operator preference.\n")
        (bot / "MEMORY.md").write_text("Review current approval evidence.\n")
        routine.write_text("Updated arrival instructions.\n")
        cli("memory", "add", "voice", "Use daily summaries", "--category", "preference",
            "--source", "operator", "--evidence", "Synthetic new decision")
        cli("memory", "resolve", "voice", "2", "--latest", "2",
            "--source", "operator", "--evidence", "Synthetic new decision")
        cli("workload", "update", "release", "--revision", "2", "--state", "blocked",
            "--next-action", "Verify the authorization")
        cli("commitment", "update", "approval", "--revision", "1", "--state", "waiting")
        self.assertIn("registered primary chat",
                      run("state", "recover", "--chat", WRONG_CHAT).stderr)
        self.assertIn("registered routine",
                      run("state", "recover", "--chat", CHAT, "--routine", "unregistered").stderr)

        # An interrupted recovery leaves updates for the next ordinary turn.
        current = recover()
        for filename in ("SOUL.md", "USER.md", "MEMORY.md"):
            self.assertEqual(current["startup"][filename], (bot / filename).read_text())
        self.assertEqual([(p["content"], p["evidence"]) for p in current["preferences"]],
                         [("Use daily summaries", "Synthetic new decision")])
        self.assertEqual(current["routine"]["contents"], "Updated arrival instructions.\n")
        self.assertNotEqual(current["schedule"]["revision"], revision)
        self.assertFalse(current["schedule"]["bound"])
        self.assertEqual(current["workloads"][0]["next_action"], "Verify the authorization")
        self.assertEqual(current["workloads"][0]["state"], "blocked")
        self.assertEqual(current["commitments"][0]["state"], "waiting")
        self.assertNotIn("STALE COMPACTION SUMMARY", json.dumps(current))
        self.assertEqual(current["acknowledged"], initial["revision"])
        self.assertTrue({*receipts, "workload/release", "commitment/approval"} <=
                        {record["subject"] for record in current["pending"]})

        stale.unlink()
        day = 21
        self.assertEqual(recover(), current)
        cli("state", "ack", "--chat", CHAT, "--revision", str(current["revision"]))
        day = 365
        final = recover()
        self.assertEqual(final, {**current, "pending": [], "acknowledged": current["revision"]})
        self.assertEqual({row["id"]: (row["state"], row["receipt"], row["attempt"])
                          for row in final["occurrences"]}, receipts)
        self.assertEqual(list((bot / "evidence").iterdir()), [])
        self.assertIsNone(recover(selected=None)["routine"])

        for revision in range(3, 25):
            cli("workload", "update", "release", "--revision", str(revision),
                "--next-action", f"Fixture update {revision}")
        first_page = recover()
        self.assertEqual(len(first_page["pending"]), 20)
        cursor = first_page["next_after"]
        self.assertIsNotNone(cursor)
        revision = str(first_page["revision"])
        self.assertNotEqual(run("state", "ack", "--chat", CHAT, "--revision", revision).returncode, 0)
        instructions = (bot / "AGENTS.md").read_text()
        command = next((part for part in instructions.split("`")
                        if part.startswith("state snapshot --chat CHAT_ID --after ")), None)
        self.assertIsNotNone(command, "Generated instructions lack a snapshot continuation command")
        values = {"CHAT_ID": CHAT, "CURSOR": str(cursor), "REVISION": revision}
        last_page = cli(*(values.get(arg, arg) for arg in shlex.split(command)))
        self.assertEqual(len(last_page["pending"]), 2)
        self.assertIsNone(last_page["next_after"])
        cli("state", "ack", "--chat", CHAT, "--revision", revision)
        self.assertEqual(recover()["pending"], [])


if __name__ == "__main__":
    unittest.main()
