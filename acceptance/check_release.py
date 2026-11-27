"""Exercise release verification with a disposable Git checkout and bare remote."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from run import standard_jobs

CLI = Path(__file__).resolve().parents[1] / "codexos.py"
RUNNER = Path(__file__).with_name("run.py").resolve()


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
        self.install_runner_fixture()
        self.commit("Tested change")
        self.publish()
        self.head = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.record = {
            "pr": 42, "repository": str(self.remote), "head": self.head,
            **{
                kind: self.write_artifact(kind, self.head) for kind in ("acceptance", "review", "privacy")
            },
        }

    def install_runner_fixture(self):
        # Run the real runner with fast local jobs to avoid recursively running this test.
        (self.checkout / "acceptance").mkdir()
        (self.checkout / "tests").mkdir()
        (self.checkout / "tests/test_fixture.py").write_text(
            "import unittest\n\nclass Fixture(unittest.TestCase):\n    def test_pass(self):\n        pass\n",
            encoding="utf-8")
        shutil.copyfile(RUNNER, self.checkout / "acceptance/run.py")
        for _, command in standard_jobs(self.checkout):
            if command[0].startswith("acceptance/"):
                path = self.checkout / command[0]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pass\n", encoding="utf-8")
        self.git("add", "acceptance", "tests")

    def run_acceptance(self, suffix):
        output = self.receipt.parent / f"results-{suffix}"
        run = subprocess.run([sys.executable, "acceptance/run.py", "--results", str(output)],
                             cwd=self.checkout, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return output / "release-acceptance.json"

    def write_artifact(self, kind, head, **changes):
        artifact = {"kind": kind, "head": head, "result": "passed"}
        name = f"{kind}-{head}.json"
        path = self.receipt.parent / name
        if kind == "acceptance":
            artifact["tree"] = self.tree
            content = path.read_bytes() if changes else self.run_acceptance(head).read_bytes()
            if changes:
                content = json.dumps({**json.loads(content), **changes}).encode()
        else:
            data = {**artifact, "source": f"fixture-{kind}", "observation": "Observed a passing result"}
            content = json.dumps({**data, **changes}).encode()
        path.write_bytes(content)
        return {key: value for key, value in artifact.items() if key != "kind"} | {
            "evidence": name, "sha256": hashlib.sha256(content).hexdigest(),
        }

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
            self.assertEqual(observed[kind], self.record[kind]["evidence"])

        self.commit("New PR head with the same tree")
        self.publish()
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), self.tree)
        self.assert_rejected("Published PR head differs from the receipt head")

        new_head = self.git("rev-parse", "HEAD")
        saved = {kind: self.record[kind].copy() for kind in ("acceptance", "review", "privacy")}
        self.record["head"] = new_head
        for kind in ("acceptance", "review", "privacy"):
            self.record[kind]["head"] = new_head
        old_file = self.receipt.parent / saved["acceptance"]["evidence"]
        old_bytes = old_file.read_bytes()
        self.record.update({kind: self.write_artifact(kind, new_head) for kind in ("review", "privacy")})
        self.assert_rejected("Acceptance artifact names a different head")
        relabeled = {**json.loads(old_bytes), "head": new_head}
        tampered = old_file.with_name("relabeled-acceptance.json")
        tampered.write_text(json.dumps(relabeled), encoding="utf-8")
        self.record["acceptance"].update(evidence=tampered.name, sha256=hashlib.sha256(tampered.read_bytes()).hexdigest())
        self.assert_rejected("Acceptance runner must start and finish on the same clean receipt head and tree")

        self.record.update(saved)
        for kind in ("acceptance", "review", "privacy"):
            self.assert_rejected(f"{kind.capitalize()} evidence must name the exact receipt head")
            self.record[kind] = {**saved[kind], "head": new_head}
        self.record.update(saved)
        for kind in ("acceptance", "review", "privacy"):
            self.record[kind]["head"] = new_head
        for kind in ("acceptance", "review", "privacy"):
            self.assert_rejected(f"{kind.capitalize()} artifact names a different head")
            self.record[kind] = self.write_artifact(kind, new_head)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["publication"]["head"], new_head)

    def test_artifacts_must_exist_match_their_digests_and_record_success(self):
        path = self.receipt.parent / self.record["review"]["evidence"]
        path.unlink()
        self.assert_rejected("Cannot read review evidence file")
        path.write_text("{}", encoding="utf-8")
        self.assert_rejected("Review artifact SHA-256 differs")
        self.record["review"] = self.write_artifact("review", self.head, result="failed")
        self.assert_rejected("Review artifact must record a passing review result")
        self.record["review"] = self.write_artifact("review", self.head, source="")
        self.assert_rejected("Review attestation must name its source and observation")
        self.record["review"] = self.write_artifact("review", self.head)
        self.record["acceptance"] = self.write_artifact("acceptance", self.head, tree=self.head)
        self.assert_rejected("Acceptance artifact names a different tree")

    def test_runner_requires_a_clean_checkout_for_release_and_records_the_full_run(self):
        path = self.receipt.parent / self.record["acceptance"]["evidence"]
        clean = json.loads(path.read_bytes())
        self.assertEqual(clean["start"], {"head": self.head, "tree": self.tree, "clean": True})
        self.assertEqual(clean["start"], clean["end"])
        self.assertEqual(len(clean["checks"]), len(standard_jobs(self.checkout)))
        self.assertTrue(all(check["exit"] == 0 for check in clean["checks"]))
        self.record["acceptance"] = self.write_artifact("acceptance", self.head, checks=clean["checks"][:-1])
        self.assert_rejected("Acceptance artifact must show all required checks passed")
        (self.checkout / "acceptance/check_cleanup.py").write_text("# local edit\n", encoding="utf-8")
        dirty = json.loads(self.run_acceptance("dirty").read_bytes())
        self.assertFalse(dirty["start"]["clean"])
        self.assertFalse(dirty["end"]["clean"])
        self.assertEqual(dirty["result"], "failed")

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
