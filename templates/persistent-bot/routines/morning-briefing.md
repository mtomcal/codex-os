# Morning briefing

Proposed trigger: At the agreed start of each working day. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py briefing --period day
```

Read this day's briefing and due commitments. Rank up to three decisions by urgency and impact. For each decision, give the owner, evidence and next action. Identify items waiting on another team by their recorded dependency.

Expected result: One local briefing. If there are no decisions or developments, end quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.
