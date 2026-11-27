# Verify a pull request before merge

1. In a clean checkout of the exact commit, run `python3 acceptance/run.py --results results/PR-42`. Use its `release-acceptance.json` as the acceptance artifact. Preserve the original bytes and keep the stage logs from the same run. Use an ignored output directory inside the checkout, such as `results/`, or an output directory outside it.
2. Choose the independent review for that commit. Check the material intended for publication for private information. Follow the repository's authorization, review, and branch rules.
3. Review the candidate diff and identify which changed behaviors depend on native Codex interactions. For each applicable behavior, run a bounded live trial on the exact candidate using authorized disposable chats, projects, or automation scope. For example, exercise launch, binding, re-steering, or compaction recovery when the change affects those flows. Observe a native scheduler wake when the change affects that behavior. Record the changed behaviors, expected and observed outcomes, and reviewed evidence references privately. Keep raw histories and unapproved side effects out of the trial record. When no live trial applies, record why the changes leave native behavior unaffected. A read-only or deterministic change may qualify after review. A tool outage or missing authorization for an applicable trial blocks the merge.
4. Record the review and privacy results in separate private JSON attestations. In each file, set `kind` to `review` or `privacy`, `head` to the full commit ID, and `result` to `passed` after verification. Include the producer as `source` and the evidence reference as `observation`. Each artifact must be a regular file of at most 64 KiB. Keep the original files for their original commits.
5. Record the live-check decision in a separate private JSON attestation, with `kind` set to `live_checks` and `head` set to the full candidate commit ID. Set `result` to `passed` after all applicable trials pass, or `not_applicable` after verifying and documenting why none apply. Use `source` for the producer and `observation` for the evidence references or rationale. Use a regular file of at most 64 KiB. Hold the merge and report the specific gap if any applicable trial fails, is blocked, or is unavailable.
6. Save a private JSON receipt in the coordinator bot's `evidence/` directory. Set each `evidence` field to that artifact's path relative to the receipt directory, or use an absolute path. Record the SHA-256 of the exact file bytes. Use the fetch URL from `git remote get-url origin` and keep credentials in the Git credential store.

```json
{
  "pr": 42,
  "repository": "https://github.com/example/project.git",
  "head": "1111111111111111111111111111111111111111",
  "acceptance": {
    "head": "1111111111111111111111111111111111111111",
    "tree": "2222222222222222222222222222222222222222",
    "result": "passed",
    "evidence": "release-acceptance.json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "review": {
    "head": "1111111111111111111111111111111111111111",
    "result": "passed",
    "evidence": "PR-42-review.json",
    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "privacy": {
    "head": "1111111111111111111111111111111111111111",
    "result": "passed",
    "evidence": "PR-42-privacy.json",
    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "live_checks": {
    "head": "1111111111111111111111111111111111111111",
    "result": "passed",
    "evidence": "PR-42-live-checks.json",
    "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  }
}
```

7. After publication, run the verifier with `--for-merge` from the checkout. Use the Git remote that owns the PR and save the output alongside the receipt. Use a new output filename for each observation you retain.

```sh
python3 codexos.py release verify bots/chief-of-staff/evidence/pr-42.json --remote origin --pr 42 --for-merge
```

The verifier reads the current `refs/pull/42/head` from the selected remote and resolves the commit's tree locally. It checks each required artifact's SHA-256, kind, result, and commit. It requires the acceptance runner's original start and end commit and tree, a clean checkout at both checkpoints, and a passing result for all required stages. Verification without `--for-merge` supports historical receipts and leaves the live-check decision unverified. The output records the publication observed at that time and the SHA-256 of the input receipt. If the published head changes, hold the merge until the new exact head has fresh evidence, including the live-check decision and any applicable trials, even when its tree matches the prior tree.

The coordinator verifies who produced each file, the observations behind the review, privacy, and live-check attestations, and review independence. The hashes detect file changes against the receipt. Producer authenticity and trial applicability are the coordinator’s responsibility. GitHub and the operator govern approvals and merge status.
