# Fleet Maintainer replay

Use this offline check to decide whether a proposed monitoring change deserves operator review. It runs a Chief of Staff project in a disposable local fleet. Each heartbeat and state read starts a fresh process. The comparison uses the same approved inputs and existing test suite for both implementations.

## Reproduce the negative control

From the fleet root, run the following command. It writes the diff, expected and actual decisions, evidence references, and suite results to a local JSON file.

```sh
python3 acceptance/maintainer/review.py --output acceptance/maintainer/proof-v1.json
```

The negative control deliberately hides regressions from the heartbeat and repeats existing blockers when a new revision arrives. A successful harness run exits zero when the current fleet passes and the candidate fails exactly those two replay cases and the existing test suite.

Inspect the generated `proof-v1.json` for the two decisions, their evidence and the candidate diff.

## Evaluate a proposed change

Use a human-reviewed local copy of `monitor.py` as the candidate. The runner executes that code under the current operating system account. Source snapshots and bot mail are data inputs.

```sh
python3 acceptance/maintainer/review.py --candidate-monitor /path/to/reviewed/monitor.py
```

A candidate that passes the incident cases and ordinary suite becomes eligible for review. The candidate command exits nonzero if any candidate case or test fails. The operator selects any change to apply. Rerun the case against later comparable evidence to check for recurrence.

## Review the expectations

The versioned [case file](../acceptance/maintainer/cases-v1.json) defines the inputs, expected findings, evidence references, and silence conditions. The runner pins its digest before evaluating either version. Both versions receive the same tests from the current fleet. Review a changed expectation on its own and record it under a new version before evaluating a candidate.

The first self-check observes an actual quiet heartbeat on a running workload, reads the source checkpoint before and after, and checks that the reviewer made no waste proposal. A separate synthetic positive control feeds three confirmed idle runs to the review rule. This comparison covers local decisions and CLI output. It uses synthetic incidents and does not measure live desktop notification delivery, token costs, or later real-world recurrence.
