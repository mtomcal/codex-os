import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile
import unittest

import fleet


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        template_root = next(p / "templates" for p in Path(fleet.__file__).resolve().parents
                             if (p / "templates/persistent-bot").is_dir())
        shutil.copytree(template_root, self.root / "templates")
        self.parser = argparse.ArgumentParser()
        fleet.commands(self.parser.add_subparsers(dest="command"))
        fleet.bootstrap(self.root)

    def cli(self, bot, *arguments):
        return fleet.run(None, self.parser.parse_args(arguments), self.root, self.root / "bots" / bot)

    def test_bootstrap_preserves_reviewed_identity(self):
        chief = self.root / "bots" / fleet.CHIEF
        (chief / "USER.md").write_text("An operator preference\n")
        fleet.bootstrap(self.root)
        self.assertEqual((chief / "USER.md").read_text(), "An operator preference\n")
        records = self.cli(fleet.CHIEF, "fleet-list")
        self.assertEqual(["chief-of-staff", "eval-monitor"], [r["id"] for r in records])
        for record in records:
            self.assertEqual(record["lifecycle"], "proposed")
            self.assertIsNone(record["primary_thread"])
            self.assertFalse(record["approved_sources"])
            project = self.root / "bots" / record["id"]
            for routine in record["routines"]:
                self.assertTrue((project / routine["file"]).is_file())
            self.assertTrue((project / "evidence").is_dir())
            self.assertEqual(record["model"], "gpt-6.2-sol")
            self.assertEqual((project / ".codex/config.toml").read_text().strip(), 'model = "gpt-6.2-sol"')
        self.assertEqual(len(records[0]["routines"]), 6)
        self.assertFalse((self.root / "bots/eval-monitor/.agents/skills/create-bot").exists())

    def test_concurrent_factory_preserves_existing_files(self):
        def create():
            return self.cli(fleet.CHIEF, "create-bot", "delivery", "--name", "Delivery", "--mission", "Track milestones")
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(*list(pool.map(lambda _: create(), range(2))))
        self.assertEqual(create()["id"], "delivery")
        with self.assertRaises(ValueError):
            self.cli(fleet.CHIEF, "create-bot", "delivery", "--name", "Delivery", "--mission", "Changed")
        with self.assertRaises(ValueError):
            self.cli(fleet.CHIEF, "create-bot", "../outside", "--name", "X", "--mission", "Y")
        with self.assertRaises(ValueError):
            self.cli("eval-monitor", "create-bot", "new-bot", "--name", "X", "--mission", "Y")

    def test_mailbox_delivers_to_the_named_specialist_once(self):
        task = ("mailbox", "assign", "eval-monitor", "inspect-eval", "Locate a verified measurement")
        first = self.cli(fleet.CHIEF, *task)
        self.assertEqual(first, self.cli(fleet.CHIEF, *task))
        self.assertEqual([first], self.cli("eval-monitor", "mailbox", "list"))
        with self.assertRaises(ValueError):
            self.cli(fleet.CHIEF, "mailbox", "report", "inspect-eval", "unverified")
        reply = ("mailbox", "report", "inspect-eval", "Run 102, local receipt with pass counts.")
        report = self.cli("eval-monitor", *reply)
        self.assertEqual(report, self.cli("eval-monitor", *reply))
        self.assertEqual([report], self.cli(fleet.CHIEF, "mailbox", "list"))
        with self.assertRaises(ValueError):
            self.cli("eval-monitor", "mailbox", "report", "inspect-eval", "A different report")


if __name__ == "__main__":
    unittest.main()
