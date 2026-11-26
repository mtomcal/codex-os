# Operational heartbeat

Proposed trigger: Every 30 minutes within the operator's agreed work window. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py heartbeat
```

Read the registered local producer artifacts in inbox/ and previous checkpoints. The collector updates observations, failure counters and alert history. Inspect up to three new findings. Verify evidence before recommending an intervention. If a producer is stale, state its last observation time. A first sample establishes the baseline.

Expected result: One evidence-backed alert for each new actionable condition. A baseline, recovery without action or unchanged state can end quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.

Check new mailbox entries returned by the heartbeat. A specialist reviews its assigned objective within its approved scope and returns evidence through the mailbox. The chief verifies new replies. On interruption, use `mailbox list` to recover the assignment.

For each entry in `workers_to_check` returned by the heartbeat, follow ../../DISPATCH.md. The CLI rotates up to three open dispatches per wakeup. A worker still running requires no operator alert. Use immediate native status snapshots. Publish verified deliverables, record failures, and clean up settled worker chats. End the turn while active workers continue independently.
