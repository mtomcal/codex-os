# Operational heartbeat

Proposed trigger: Every 30 minutes within the operator's agreed work window. The operator reviews the schedule and selects the time zone before activation.

Run the checked-in desktop heartbeat from this bot directory using the Codex code-mode tool. It calls the fleet CLI, checks native worker status, and performs the archive and confirmation steps. Use the actual bot directory for `workdir` if the chat runs elsewhere.

```js
const script = await tools.exec_command({cmd: "cat ../../heartbeat.js"});
if (script.exit_code !== 0) throw Error("Could not read the fleet heartbeat");
const pulse = await eval(script.output)(tools);
if (pulse) text(pulse);
```

Read the registered local producer artifacts in inbox/ and previous checkpoints. The collector updates observations, failure counters and alert history. Inspect up to three new findings. Verify evidence before recommending an intervention. If a producer is stale, state its last observation time. A first sample establishes the baseline.

Expected result: One evidence-backed alert for each new actionable condition. A baseline, recovery without action or unchanged state can end quietly. Keep any secondary report inside `reports/`. Only the CLI may update operational records. On an access denial, stop the affected operation and identify the restricted source. On transient failure, preserve the last verified state and end this wakeup. Finish after one pass.

Check new mailbox entries returned by the heartbeat. A specialist reviews its assigned objective within its approved scope and returns evidence through the mailbox. The chief verifies new replies. On interruption, use `mailbox list` to recover the assignment.

Review each entry in `workers_to_review` using ../../docs/dispatch.md. The desktop heartbeat checks the CLI's rotated list of up to three dispatches and identifies idle bound workers whose latest turn ended, including workers that sent no completion notice. Use this batched status result for desktop review. Query raw `workers_to_check` candidates only when recovering with the fleet CLI alone. Read the worker outcome, verify the evidence and publish the result before recording `dispatch delivered KEY --evidence TEXT`. The desktop heartbeat retries archival of delivered local workers automatically. Leave active workers, unverified snapshots and pending cleanup open for the next pass.
