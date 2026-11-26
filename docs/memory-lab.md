# Replay the native Memory Lab trial

Run this trial after changing chat startup, instruction retrieval, heartbeat routing, or scheduling. The driver copies the current fleet code and templates into a new run directory. It invokes the public factory to create a Memory Lab project. The two seed projects in that copy provide the factory context. Only the lab needs native registration.

Use a scratch parent on an approved local disk. Keep the evidence you want to retain outside the run directory. The commands below start in the fleet root.

```sh
mkdir -p work/native-trials
LAB=$(python3 acceptance/lab.py prepare work/native-trials)
python3 acceptance/lab.py baseline "$LAB"
python3 acceptance/lab.py status "$LAB"
python3 acceptance/lab.py prompts "$LAB"
```

The driver creates fresh synthetic session, durable-memory, and standing-instruction tokens. The `prompts` output is the operator’s script. Send each subject only the named prompt for its current phase. Keep the ownership record and expected tokens outside the bot project. The approved test code is trusted; sibling bot folders are an organizational boundary, not a sandbox.

## Drive the chats and scheduler

Use the Codex desktop tools in a coordination chat with authorization to create, message, and remove the test resources. Include the run ID in the project’s chat and routine names so overlapping trials can be distinguished. Bind each ID as soon as Codex returns it. The following examples use `ID` for the actual ID from the native tool.

1. Open the project with `codex app "$LAB/fleet/bots/memory-lab"`. Call `list_projects` and match the exact canonical project path. Run `python3 acceptance/lab.py bind "$LAB" project ID`.
2. Use `create_thread` with the project ID, a local environment, explicit model `gpt-6.2-sol`, and the **seed** prompt. Bind the resulting chat as `primary`. Wait for completion using `wait_threads`. Send **recall** to the same chat with `send_message_to_thread`. Wait for its completed reply.
3. Create a separate chat in the same project with **fresh** as its initial prompt and Sol explicitly selected. Bind the chat as `fresh` and wait for the reply. Send **teach** to this chat and wait for the durable preference write.
4. Run `python3 acceptance/lab.py publish "$LAB"` once. Create an ACTIVE native heartbeat using `automation_update`, the primary chat as `targetThreadId`, the **pulse** prompt unchanged, and an interval of one minute. Bind its ID as `pulse`. Wait for two completed turns whose triggering item is the native heartbeat. The first should notify with evidence `lab-run-2`. Its unchanged successor should request silence.
5. Create an ACTIVE native heartbeat named “Memory Lab reflective check” followed by the run ID, targeting the same chat at two-minute intervals. Use **reflection** as the exact prompt and bind its ID as `reflection`. Wait for its first completed native turn. Run `python3 acceptance/lab.py receipt "$LAB"` to inspect the calibration, evidence, and feedback IDs it actually read.
6. Create a third chat in that project with **behavior** as its first prompt. Bind the chat as `behavior`. After its reply, send **corrected** to that same chat. Save both replies. Check the arithmetic and the exact operator footer. A count difference alone does not identify individual failed cases.

Use `wait_threads` cursors to wait for a *new* completed turn and verify its source. A manual message containing the routine prompt does not establish scheduler dispatch.

## Export and grade the evidence

Before deleting the chats, call `read_thread` for each with `includeOutputs: true`, `turnLimit: 10`, `itemLimit: 100`, and `maxOutputCharsPerItem: 14000`. Save the returned JSON objects from the tool's text content into scratch storage. Follow older-turn and item cursors when a target turn or its triggering item is missing. Each saved file must contain `thread.id`, `turns`, and the selected completed turn with its actual tool calls and final reply.

Create a JSON capture index next to those files. In `thread_settings`, record the primary chat's actual native model from the supported `thread/read` metadata API. The recorded model describes that chat's setting. A separate per-turn model witness can be unknown. Replace each identifier below with the actual observed value.

```json
{
  "thread_settings": [{"id": "primary-chat-id", "model": "gpt-6.2-sol"}],
  "turns": {
    "seed": {"file":"primary.json","id":"seed-turn"},
    "recall": {"file":"primary.json","id":"recall-turn"},
    "fresh": {"file":"fresh.json","id":"fresh-turn"},
    "teach": {"file":"fresh.json","id":"teach-turn"},
    "behavior": {"file":"behavior.json","id":"behavior-turn"},
    "corrected": {"file":"behavior.json","id":"corrected-turn"},
    "wake": {"file":"primary.json","id":"first-scheduled-pulse"},
    "repeat": {"file":"primary.json","id":"unchanged-scheduled-pulse"},
    "reflection": {"file":"primary.json","id":"first-scheduled-reflection"}
  }
}
```

Write a new proof bundle per trial. The driver extracts the trigger and executed commands from the captured native records. It retrieves private memory and the reflection receipt from the test bot.

```sh
python3 acceptance/lab.py bundle "$LAB" "$CAPTURE_INDEX" > "$EVIDENCE_DIR/live-evidence.json"
python3 acceptance/grade_live.py "$EVIDENCE_DIR/live-evidence.json" --out "$EVIDENCE_DIR/live-results.json"
```

A grading failure is evidence. Preserve that result and clean the run. The local `prepare`, `baseline`, `publish`, and `clean` lifecycle can also run without native resources for a CLI-only smoke check.

## Clean the trial on success or failure

1. Inspect `python3 acceptance/lab.py status "$LAB"`. Reconcile its native IDs with the app, including any resource created just before an interruption.
2. Delete both native schedules with `automation_update` in delete mode. Verify removal. Record each confirmed removal with `python3 acceptance/lab.py release "$LAB" pulse ID` or the `reflection` role.
3. Delete the three test chats using the native `delete_thread` action and its confirmation flow. Confirm each removal, then release the corresponding `primary`, `fresh`, and `behavior` IDs.
4. Remove the exact disposable project registration using Codex's project controls. Verify the project list and release the `project` ID. If a client lacks the removal control, record the pending registration and finish this step through the desktop project picker. Local release records are operator attestations; the driver cannot inspect the app independently.
5. Supply the run ID printed by `status` to `python3 acceptance/lab.py clean "$LAB" --confirm RUN_ID`. The driver checks the ownership marker, canonical path, and recorded native releases before removing its run directory. Check that the directory is gone. Remove the scratch raw chat exports after retaining the synthetic evidence bundle and results in approved storage.

## Replay the nonblocking worker lifecycle

Use the same disposable project after the memory interviews and before teardown. The coordinator and worker are separate native chats. Bind both IDs with `lab.py bind` under roles `coordinator` and `worker`. The following sequence tests genuine overlap.

1. Register the fresh Sol coordinator’s chat ID in the disposable project’s `bot.json` as `primary_thread` before sending the assignment. Give it an ordinary implementation request, for example “Implement `double(x)` in `reports/lab_double.py`, check that 21 gives 42, and wait up to ten minutes for `state/release-worker.ok` before delivery.” Only the harness creates the release marker. Leave the routing decision to the coordinator. Check that it reserved a dispatch, launched and bound a worker, and ended intake before doing any implementation or waiting. Record an inline attempt as a failure.
2. After the intake turn completes, send an unrelated memory question to the coordinator. Capture the completed answer and the worker's ongoing native turn. If the worker finished early, record a failure.
3. Create the release marker. Wait for the worker to finish. Invoke one coordinator heartbeat, or observe the next scheduled reconciliation if that routine targets the coordinator. Verify the returned work, accepted ledger disposition, and native worker archival. Check the executable result from the retained artifact after archival.
4. Capture the relevant turn times and replies, dispatch ledger entry and archive lookup before removing the test chats. Use `grade_dispatch.py` and the synthetic example in acceptance/fixtures/dispatch.json as the evidence schema. Delete and release the archived worker and the coordinator during cleanup.

To exercise another real scheduler pass after the memory checks, run `python3 acceptance/pulse_probe.py "$LAB"`. It publishes a fresh revision and waits for the lab to observe it twice. It never calls the heartbeat on the bot's behalf.

## Replay a worker completion message

Use a registered Chief with operator authorization for completion messages and scheduled checks off. Create two files in its `inbox/notification-test/` directory. Put `Restored records: 17` in `north.txt` and `Restored records: 29` in `south.txt`. Ask the Chief to compare them and save the counts and total in `reports/notification-trial.md`. After intake, observe both chats without sending another message.

Save the following evidence from the native chats in a local JSON file under `results/`. Use `chief` and `worker` for the chat IDs and `sends` for the worker’s outbound completion tool calls. From the Chief’s review turn, capture its first item as `trigger`, its successful command items reading the two source counts as `source_reads`, its final answer text as `delivery`, and its archive call as `archive`. Capture the final dispatch record as `ledger` and read the saved report after archival as `retained_report`. Run the evaluator from the repository root.

```sh
python3 acceptance/grade_notification.py results/notification-evidence.json
```

A passing trial requires a worker-originated turn, independent review, delivery in the primary chat and archival of the same worker. As a negative control, replace the captured trigger with a manual user message in a copy and confirm the evaluator exits nonzero.
