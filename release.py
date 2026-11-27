"""Verify local release evidence against the current published pull request head."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from receipt_store import directory, read_file

OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
SHA256 = re.compile(r"[0-9a-f]{64}")


def positive_number(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Use a positive PR number")
    return number


def commands(sub):
    operations = sub.add_parser("release", help=__doc__).add_subparsers(dest="operation", required=True)
    verify = operations.add_parser("verify", help="Check a local receipt against a published PR head")
    verify.add_argument("receipt", type=Path)
    verify.add_argument("--remote", required=True, help="Approved Git remote name in the current checkout")
    verify.add_argument("--pr", type=positive_number, required=True, help="Pull request number on that remote")
    verify.add_argument("--for-merge", action="store_true", help="Require the live Codex check attestation")


def git(*args, failure):
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", *args], capture_output=True, text=True, timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"{failure} (Git timed out)") from None
    if result.returncode:
        raise ValueError(failure)
    return result.stdout.strip()


def evidence(receipt, kind, head):
    name = kind.replace("_", " ").capitalize()
    entry = receipt.get(kind)
    if not isinstance(entry, dict) or entry.get("head") != head:
        raise ValueError(f"{name} evidence must name the exact receipt head")
    reference = entry.get("evidence")
    allowed_results = ("passed", "not_applicable") if kind == "live_checks" else ("passed",)
    if entry.get("result") not in allowed_results or not isinstance(reference, str) or not reference.strip():
        requirement = "a passing result or a not_applicable decision" if kind == "live_checks" else "a passing result"
        raise ValueError(f"{name} requires {requirement} and an evidence file")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"{name} requires the SHA-256 of its evidence file")
    return entry


def verify_artifact(folder, kind, entry, head, tree):
    name = kind.replace("_", " ").capitalize()
    path = folder / entry["evidence"]
    try:
        with directory(path.parent) as source:
            data = read_file(source, path.name)
    except OSError:
        raise ValueError(f"Cannot read {kind} evidence file") from None
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"{name} artifact SHA-256 differs from the release receipt")
    try:
        artifact = json.loads(data)
    except ValueError:
        raise ValueError(f"{name} artifact must be valid JSON") from None
    if not isinstance(artifact, dict) or artifact.get("kind") != kind or artifact.get("result") != entry["result"]:
        if kind == "live_checks":
            raise ValueError("Live checks artifact must match the receipt decision")
        raise ValueError(f"{name} artifact must record a passing {kind} result")
    if artifact.get("head") != head:
        raise ValueError(f"{name} artifact names a different head")
    if kind == "acceptance":
        verify_acceptance(artifact, head, tree)
    elif any(not isinstance(artifact.get(field), str) or not artifact[field].strip()
             for field in ("source", "observation")):
        raise ValueError(f"{name} attestation must name its source and observation")


def verify_acceptance(artifact, head, tree):
    from acceptance.run import standard_jobs

    if artifact.get("tree") != tree:
        raise ValueError("Acceptance artifact names a different tree")
    expected = {"head": head, "tree": tree, "clean": True}
    for checkpoint in ("start", "end"):
        observed = artifact.get(checkpoint)
        if observed != expected or observed["clean"] is not True:
            raise ValueError("Acceptance runner must start and finish on the same clean receipt head and tree")
    checks = artifact.get("checks")
    required = [name for name, _ in standard_jobs(Path())]
    if (not isinstance(checks, list) or any(not isinstance(check, dict)
            or type(check.get("exit")) is not int or check["exit"] != 0 for check in checks)
            or [check.get("check") for check in checks[:len(required)]] != required):
        raise ValueError("Acceptance artifact must show all required checks passed")


def verify(args):
    raw = args.receipt.read_bytes()
    receipt = json.loads(raw)
    if not isinstance(receipt, dict):
        raise ValueError("Release receipt must be a JSON object")
    head = receipt.get("head")
    if not isinstance(head, str) or not OBJECT_ID.fullmatch(head):
        raise ValueError("Release receipt must name a full Git commit ID")
    if type(receipt.get("pr")) is not int or receipt["pr"] != args.pr:
        raise ValueError("Release receipt names a different PR number")

    acceptance = evidence(receipt, "acceptance", head)
    review = evidence(receipt, "review", head)
    privacy = evidence(receipt, "privacy", head)
    if git("rev-parse", "--verify", f"{head}^{{commit}}",
           failure="Receipt head is unavailable in the local Git checkout") != head:
        raise ValueError("Release receipt head must be a commit")
    tree = git("rev-parse", "--verify", f"{head}^{{tree}}", failure="Cannot resolve the receipt head tree")
    if acceptance.get("tree") != tree:
        raise ValueError("Acceptance evidence does not match the receipt head tree")

    entries = {"acceptance": acceptance, "review": review, "privacy": privacy}
    if args.for_merge:
        entries["live_checks"] = evidence(receipt, "live_checks", head)
    for kind, entry in entries.items():
        verify_artifact(args.receipt.parent, kind, entry, head, tree)

    url = git("remote", "get-url", "--", args.remote, failure="Cannot resolve the selected Git remote")
    if receipt.get("repository") != url:
        raise ValueError("Release receipt names a different Git repository")
    ref = f"refs/pull/{args.pr}/head"
    published = git("ls-remote", "--exit-code", "--refs", "--", args.remote, ref,
                    failure="Cannot read the published PR head from the selected remote")
    if published != f"{head}\t{ref}":
        raise ValueError("Published PR head differs from the receipt head. Refresh evidence for the current head.")

    result = {
        "result": "verified", "pr": args.pr, "head": head, "tree": tree,
        "acceptance": acceptance["evidence"], "review": review["evidence"], "privacy": privacy["evidence"],
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "publication": {"remote": args.remote, "repository": url, "ref": ref, "head": head,
                        "observed_at": datetime.now(timezone.utc).isoformat()},
    }
    if args.for_merge:
        live_checks = entries["live_checks"]
        result["live_checks"] = {"result": live_checks["result"], "evidence": live_checks["evidence"]}
    return result
