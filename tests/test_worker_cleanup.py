import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from dispatch import cleanup_candidates


class CleanupTest(unittest.TestCase):
    def test_only_delivered_bound_local_workers_are_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chief, worker = str(uuid4()), str(uuid4())
            bot = root / "bots/chief"
            bot.mkdir(parents=True)
            (bot / "bot.json").write_text(json.dumps({"primary_thread": chief}))
            job = dict(key="demo", state="accepted", delivery="posted", worker=worker, host="local")
            self.assertEqual(worker, cleanup_candidates(root, [job])[0]["worker"])
            for changes in [dict(state="running"), dict(delivery=None), dict(worker=chief),
                            dict(worker="invalid"), dict(host="remote")]:
                with self.subTest(changes=changes):
                    self.assertEqual([], cleanup_candidates(root, [dict(job, **changes)]))
