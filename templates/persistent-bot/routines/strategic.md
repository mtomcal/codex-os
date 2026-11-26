# Strategic initiative

Proposed trigger: Twice during the agreed working day. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py strategic
```

Review up to three eligible commitments returned by the command. The review checkpoint prevents repeat reminders. Verify a dependency or follow-up first. Respect active follow-ups, parked work and prior reviews. Propose one bounded action within the bot's remit. Recurring manual reviews can justify proposing an inactive specialist.

Expected result: One recommendation for each eligible item that can advance. Keep unchanged or unactionable items quiet. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.
