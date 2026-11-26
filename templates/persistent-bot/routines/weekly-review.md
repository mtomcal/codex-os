# Weekly engineering review

Proposed trigger: Friday during the agreed work window. The operator reviews the schedule and selects the time zone before activation.

From this bot directory, run one command.

```sh
python3 ../../codexos.py briefing --period week
```

Select the week's three most consequential outcomes or risks. Use local records, evidence, changes in measurements and human decisions. Label unverified interpretations. Check if a repeated investigation warrants a proposed specialist. Keep pending commitments open.

Expected result: A dated local weekly report with outcomes, evidence and next actions. If the week has no recorded developments, end quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.
