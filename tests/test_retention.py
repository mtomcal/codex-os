"""Exercise memory retention across process restarts with a controlled ledger clock."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = """
import json, sys
from pathlib import Path
import codexos, ledger
ledger.now = lambda: int(sys.argv[2])
print(json.dumps(codexos.main(sys.argv[3:], root=Path(sys.argv[1]).resolve())))
"""


class Retention(unittest.TestCase):
    def test_year_later_startup_and_expired_preferences(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "templates").symlink_to(ROOT / "templates", target_is_directory=True)
            start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())

            def cli(days, *args):
                text = subprocess.check_output([sys.executable, "-c", DRIVER, raw,
                    str(start + days * 86400), *args], cwd=ROOT, text=True)
                return json.loads(text)

            cli(0, "init")
            for key, source, options in [
                ("lasting", "operator", []),
                ("temporary", "operator", ["--expires", "2026-02-01T00:00:00Z"]),
                ("imported", "issue-comment", []),
            ]:
                cli(0, "memory", "add", key, key, "--category", "preference",
                    "--source", source, "--evidence", "synthetic-trial", *options)
            self.assertEqual({r["key"] for r in cli(0, "memory", "preferences")},
                             {"lasting", "temporary"})
            self.assertEqual([r["key"] for r in cli(365, "memory", "preferences")], ["lasting"])
            archived = cli(365, "reflect")["archived"]
            self.assertEqual([r["key"] for r in archived], ["temporary"])
            self.assertIsNone(cli(365, "reflect"))
            history = cli(365, "memory", "list", "--all", "--key", "temporary")
            self.assertEqual(history[0]["status"], "archived")
