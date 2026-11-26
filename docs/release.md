# Verify a published pull request

1. In a clean checkout of the exact commit, run `python3 acceptance/run.py --results results/PR-42`. Preserve the results and record the full commit and tree IDs.
2. Choose the independent review for that commit. Check the material intended for publication for private information and keep a reference to the result. Follow the repository's authorization, review, and branch rules for publication.
3. Save a private JSON receipt in the coordinator bot's `evidence/` directory. Replace the example values with the observed repository URL, commit and tree IDs, and evidence references. Use the fetch URL from `git remote get-url origin` and keep credentials in the Git credential store.

```json
{
  "pr": 42,
  "repository": "https://github.com/example/project.git",
  "head": "1111111111111111111111111111111111111111",
  "acceptance": {
    "head": "1111111111111111111111111111111111111111",
    "tree": "2222222222222222222222222222222222222222",
    "result": "passed",
    "evidence": "results/PR-42/summary.json"
  },
  "review": {
    "head": "1111111111111111111111111111111111111111",
    "result": "passed",
    "evidence": "reference to the chosen independent review"
  },
  "privacy": {
    "head": "1111111111111111111111111111111111111111",
    "result": "passed",
    "evidence": "reference to the publication privacy check"
  }
}
```

4. After publication, run the verifier from the checkout. Use the Git remote that owns the PR and save successful output alongside the receipt. Use a new output filename for each observation you retain.

```sh
python3 codexos.py release verify bots/chief-of-staff/evidence/pr-42.json --remote origin --pr 42
```

The verifier resolves the commit's tree locally and reads the current `refs/pull/42/head` from the selected remote. The output records the publication observed at that time and the SHA-256 of the input receipt. If the published head changes, gather fresh acceptance, review, and privacy evidence for that commit, even when its tree matches the prior tree.

Inspect the referenced evidence before writing the receipt. The verifier checks the associations and publication ref. The coordinator verifies the referenced results and review independence. GitHub and the operator govern approvals and merge status.
