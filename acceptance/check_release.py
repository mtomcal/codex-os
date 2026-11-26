"""Exercise release verification with a disposable Git checkout and bare remote."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / "codexos.py"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codexos-release-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        self.remote = root / "remote.git"
        self.receipt = root / "release.json"

        self.git("init", "--quiet", "--object-format=sha1")
        self.git("init", "--quiet", "--bare", "--object-format=sha1", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.commit("Tested change")
        self.publish()
        self.head = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.record = {
            "pr": 42, "repository": str(self.remote), "head": self.head,
            **{
                kind: {"head": self.head, "result": "passed", "evidence": f"fixture-{kind}"}
                for kind in ("acceptance", "review", "privacy")
            },
        }
        self.record["acceptance"]["tree"] = self.tree

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.checkout, capture_output=True, text=True,
                              check=True).stdout.strip()

    def commit(self, message):
        self.git("-c", "user.name=Release Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "--allow-empty", "-m", message)

    def publish(self):
        self.git("-C", str(self.remote), "fetch", "--quiet", str(self.checkout), "+HEAD:refs/pull/42/head")

    def verify(self):
        self.receipt.write_text(json.dumps(self.record), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(CLI), "release", "verify", str(self.receipt), "--remote", "origin", "--pr", "42"],
            cwd=self.checkout, capture_output=True, text=True,
        )

    def assert_rejected(self, message):
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def test_current_publication_is_verified_and_a_new_head_invalidates_saved_success(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["result"], "verified")
        self.assertEqual(observed["head"], self.head)
        self.assertEqual(observed["tree"], self.tree)
        self.assertEqual(observed["receipt_sha256"], hashlib.sha256(self.receipt.read_bytes()).hexdigest())
        self.assertEqual(observed["publication"]["repository"], str(self.remote))
        self.assertEqual(observed["publication"]["ref"], "refs/pull/42/head")
        self.assertEqual(observed["publication"]["head"], self.head)
        for kind in ("acceptance", "review", "privacy"):
            self.assertEqual(observed[kind], f"fixture-{kind}")

        self.commit("New PR head with the same tree")
        self.publish()
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), self.tree)
        self.assert_rejected("Published PR head differs from the receipt head")

        new_head = self.git("rev-parse", "HEAD")
        self.record["head"] = new_head
        for kind in ("acceptance", "review", "privacy"):
            self.assert_rejected(f"{kind.capitalize()} evidence must name the exact receipt head")
            self.record[kind].update(head=new_head, evidence=f"refreshed-fixture-{kind}")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["publication"]["head"], new_head)

    def test_tree_and_repository_must_match_and_pr_ref_must_exist(self):
        self.record["acceptance"]["tree"] = self.head
        self.assert_rejected("Acceptance evidence does not match the receipt head tree")
        self.record["acceptance"]["tree"] = self.tree

        self.record["repository"] = "different repository"
        self.assert_rejected("Release receipt names a different Git repository")
        self.record["repository"] = str(self.remote)

        self.git("-C", str(self.remote), "update-ref", "-d", "refs/pull/42/head")
        self.assert_rejected("Cannot read the published PR head")


if __name__ == "__main__":
    unittest.main()
