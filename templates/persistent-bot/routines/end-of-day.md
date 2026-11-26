# End-of-day review

Proposed trigger: At the agreed end of each working day. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py briefing --period day
```

Compare today's recorded results with outstanding commitments. Summarize up to three verified accomplishments, blockers or next-day decisions. Include the evidence and the owner. Carry forward unfinished work without marking it complete.

Expected result: A dated local summary when a result changes the plan for tomorrow. Otherwise end quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.
