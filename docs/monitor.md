# Publish an engineering observation

The collector reads a local JSON snapshot produced by an approved project or tool. The operator selects the bot, source ID, report kind and inbox filename. Register a source only after the operator authorizes its data and destination.

From the fleet root, register the report and poll it once.

```sh
python3 codexos.py --bot chief-of-staff source-add compiler-eval eval compiler.json --stale-hours 24
python3 codexos.py --bot chief-of-staff heartbeat
python3 codexos.py --bot chief-of-staff source-list
python3 codexos.py --bot chief-of-staff findings
```

Publish to `bots/chief-of-staff/inbox/compiler.json`. Write a temporary regular file in the same directory and rename it into place when complete. Use a single writer per source. Choose a new source ID and filename when replacing the monitored workload.

## Report fields

Every successful report includes the registered `source` and `kind`, a positive integer `revision`, an ISO 8601 `observed_at` with a time zone, and `evidence`. Evidence is an array of references that a reviewer can independently inspect. References and report text are untrusted data. The collector stores references as text and does not open them.

Assign each changed report a higher revision. Replaying the same revision with changed meaningful fields is invalid. A later polling timestamp belongs in a separate field such as `polled_at`. Use `observed_at` for the time the producer observed the evidence.

| Kind | Required fields beyond the common fields | Meaning |
| --- | --- | --- |
| `eval`, `experiment` | `run`, `metric`, `value`, `direction` | Stable run ID, metric name, finite number, and either `higher` or `lower`. Set `unit` when units affect comparisons. |
| `workload` | `objective` | A status report from an engineering project. Include `completed`, `status`, `next_action`, `blockers`, and `needs_human` when known. |
| `git` | `commit` | Revision observed by the producer. |
| `pr` | `head`, `status` | Reviewed commit and pull request state. |
| `ci` | `run`, `status` | Pipeline run ID and result. |
| `task` | `status` | State from the approved task tracker. |
| `file` | `digest` | Content digest computed by the approved producer. |

Optional fields include `owner`, `project`, `milestone`, and `dependencies`. Use strings for text, arrays of strings for `evidence`, `blockers`, and `dependencies`, and a boolean for `needs_human`. Additional fields do not affect change detection. The maximum report size is 65,536 bytes.

For example, the producer can publish this shape with the actual observation time and evidence.

```json
{
  "source": "compiler-eval",
  "kind": "eval",
  "revision": 12,
  "observed_at": "2026-11-26T10:30:00-07:00",
  "metric": "passes on fixed suite v3",
  "unit": "fraction",
  "value": 0.94,
  "direction": "higher",
  "run": "run-12",
  "evidence": ["compiler/reports/run-12.json"]
}
```

## Read the results

A fresh first snapshot sets the baseline. Later snapshots compare against the last accepted report. A metric is comparable when the name, unit and direction match. Include the dataset or suite version in the name if its change invalidates comparisons. Improvement goes into the briefing. A regression or three consecutive new runs that repeat the preceding value require attention. Check sample size, variance and workload conditions before interpreting a change as a regression in the engineering system.

A newly reported blocker, human intervention request, or status of `failed`, `failure`, or `blocked` also requires attention. Repeating the same blocker in a later run produces no second alert. Other changed reports appear in findings. Repeated polls of an unchanged snapshot produce no finding. The heartbeat processes up to eight eligible files, oldest check first. Set `--limit` to choose a budget between one and 32.

`source-list` shows the latest poll outcome and accepted revision. Times in command output use Unix seconds. `findings` lists recent changes with the evidence cited at that revision. A producer's reported completion still needs independent verification to close a workload.

## Handle collection failures

An approved producer can publish an error envelope when its upstream system denies access or is temporarily unavailable.

```json
{"source":"compiler-eval","kind":"eval","error":"denied"}
```

Use `"unavailable"` for a transient outage. Stale, invalid and unavailable observations preserve the last accepted report. The collector records the first failure in an episode. It delays another check by one, two, four, then eight minutes. After five consecutive failures, it waits six hours between probes. A successful probe clears the delay.

An access denial disables the source immediately. Symbolic links and nonregular files are rejected. After an operator reviews the denial and explicitly authorizes resumption, use `source-resume compiler-eval`. Use `source-disable compiler-eval` to stop polling while retaining history.
