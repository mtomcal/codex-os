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
    entry = receipt.get(kind)
    if not isinstance(entry, dict) or entry.get("head") != head:
        raise ValueError(f"{kind.capitalize()} evidence must name the exact receipt head")
    reference = entry.get("evidence")
    if entry.get("result") != "passed" or not isinstance(reference, str) or not reference.strip():
        raise ValueError(f"{kind.capitalize()} requires a passing result and an evidence file")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"{kind.capitalize()} requires the SHA-256 of its evidence file")
    return entry


def verify_artifact(folder, kind, entry, head, tree):
    name = kind.capitalize()
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
    if not isinstance(artifact, dict) or artifact.get("kind") != kind or artifact.get("result") != "passed":
        raise ValueError(f"{name} artifact must record a passing {kind} result")
    if artifact.get("head") != head:
        raise ValueError(f"{name} artifact names a different head")
    if kind == "acceptance" and artifact.get("tree") != tree:
        raise ValueError("Acceptance artifact names a different tree")


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

    for kind, entry in (("acceptance", acceptance), ("review", review), ("privacy", privacy)):
        verify_artifact(args.receipt.parent, kind, entry, head, tree)

    url = git("remote", "get-url", "--", args.remote, failure="Cannot resolve the selected Git remote")
    if receipt.get("repository") != url:
        raise ValueError("Release receipt names a different Git repository")
    ref = f"refs/pull/{args.pr}/head"
    published = git("ls-remote", "--exit-code", "--refs", "--", args.remote, ref,
                    failure="Cannot read the published PR head from the selected remote")
    if published != f"{head}\t{ref}":
        raise ValueError("Published PR head differs from the receipt head. Refresh evidence for the current head.")

    return {
        "result": "verified", "pr": args.pr, "head": head, "tree": tree,
        "acceptance": acceptance["evidence"], "review": review["evidence"], "privacy": privacy["evidence"],
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "publication": {"remote": args.remote, "repository": url, "ref": ref, "head": head,
                        "observed_at": datetime.now(timezone.utc).isoformat()},
    }
