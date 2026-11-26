# Memory consolidation

Proposed trigger: Daily after the end-of-day review. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py reflect
```

Inspect the memory changes returned by the command. Check at most three recent observations or feedback records for a durable lesson. Keep the source, evidence, date, scope, confidence and superseded record when correcting a fact. Preserve competing claims if evidence is inconclusive. Use project memory for private records. Propose policy or instruction changes to the operator.

Expected result: A corrected memory, archived expired record or grounded proposal. If there is nothing to consolidate, finish quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.
