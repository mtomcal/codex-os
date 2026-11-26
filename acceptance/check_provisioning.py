"""Replay the desktop provisioning workflow against a disposable local fleet."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lab import ROOT, prepare


class ProvisioningTests(unittest.TestCase):
    def test_desktop_provisioning(self):
        with tempfile.TemporaryDirectory() as scratch:
            fleet = Path(prepare(Path(scratch))) / "fleet"
            replay = ROOT / "acceptance/check_provisioning.js"
            subprocess.run(["node", str(replay), str(fleet), sys.executable], check=True)


if __name__ == "__main__":
    unittest.main()
