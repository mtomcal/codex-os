# Verify a published pull request

1. In a clean checkout of the exact commit, run `python3 acceptance/run.py --results results/PR-42`. Preserve the results and record the full commit and tree IDs.
2. Choose the independent review for that commit. Check the material intended for publication for private information. Follow the repository's authorization, review, and branch rules.
3. Save a private JSON artifact with each result when it is verified. Each artifact records `kind` (`acceptance`, `review`, or `privacy`), the full `head` commit ID, and `result: "passed"`. In the acceptance artifact, record `tree` as well. Include the supporting observations or a reference to them. Each artifact must be a regular file of at most 64 KiB. Keep the original files for their original commits.
4. Save a private JSON receipt in the coordinator bot's `evidence/` directory. Set each `evidence` field to that artifact's path relative to the receipt directory, or use an absolute path. Record the SHA-256 of the exact file bytes. Use the fetch URL from `git remote get-url origin` and keep credentials in the Git credential store.

```json
{
  "pr": 42,
  "repository": "https://github.com/example/project.git",
  "head": "1111111111111111111111111111111111111111",
  "acceptance": {
    "head": "1111111111111111111111111111111111111111",
    "tree": "2222222222222222222222222222222222222222",
    "result": "passed",
    "evidence": "PR-42-acceptance.json",
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
  }
}
```

5. After publication, run the verifier from the checkout. Use the Git remote that owns the PR and save the output alongside the receipt. Use a new output filename for each observation you retain.

```sh
python3 codexos.py release verify bots/chief-of-staff/evidence/pr-42.json --remote origin --pr 42
```

The verifier reads the current `refs/pull/42/head` from the selected remote and resolves the commit's tree locally. It checks each artifact's SHA-256, kind, result, and commit. It checks the acceptance artifact's tree as well. The output records the publication observed at that time and the SHA-256 of the input receipt. If the published head changes, gather fresh evidence for that commit, even when its tree matches the prior tree.

The coordinator verifies the results, who produced them, and review independence. GitHub and the operator govern approvals and merge status.
