# Test a change

Install Node.js for the desktop replay checks. From the repository root, run:

```sh
python3 acceptance/run.py
```

The harness creates disposable bots, exercises the public CLI, and checks that cleanup removes only the test run. The candidate evaluator tries a deliberately broken monitor and must catch both a missed regression and a duplicate alert. The memory and dispatch graders also run against synthetic examples. Every run checks that the worker graders reject missing or mismatched archive evidence even when the ledger says cleanup succeeded. For a live callback trial, use `--notification-evidence results/notification-evidence.json`. A failing stage exits nonzero.

For new evidence from the desktop app, follow the [live Memory Lab guide](memory-lab.md). To grade captured runs as part of the same suite, supply a directory containing `live-evidence.json` and `dispatch-evidence.json` with `--evidence-dir`. To save the test reports, add `--results results/trial-1` with a new output path.

With Node installed, the archive check also drives the desktop heartbeat through a running worker, a lost archive acknowledgement, and a retry. To replay a real missed cleanup, leave a reviewed worker unarchived after `dispatch delivered`, execute the heartbeat routine once, and compare the dispatch record and native archive before and after.

The desktop provisioning check uses Node, fake native Codex tools, and a disposable fleet with the real CLI. It covers the registration pause, launch recovery, startup verification, and persisted activation. Run it on its own with `python3 acceptance/check_provisioning.py`.
