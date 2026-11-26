# Test a change

From the repository root, run:

```sh
python3 acceptance/run.py
```

The harness creates disposable bots, exercises the public CLI, and checks that cleanup removes only the test run. The candidate evaluator tries a deliberately broken monitor and must catch both a missed regression and a duplicate alert. The memory and dispatch graders also run against synthetic examples. Every run checks that the worker graders reject missing or mismatched archive evidence even when the ledger says cleanup succeeded. For a live callback trial, use `--notification-evidence results/notification-evidence.json`. A failing stage exits nonzero.

For new evidence from the desktop app, follow the [live Memory Lab guide](memory-lab.md). To grade captured runs as part of the same suite, supply a directory containing `live-evidence.json` and `dispatch-evidence.json` with `--evidence-dir`. To save the test reports, add `--results results/trial-1` with a new output path.
