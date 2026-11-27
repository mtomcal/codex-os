# Keep the primary chat available

The primary chat owns intake, coordination, review, delivery, and cleanup. It answers short questions and handles bounded reads itself. Delegate implementation and other substantial work to a native worker that can keep running after the primary turn ends. Use the approved worker scope and Codex permissions. If the client cannot launch a detached subagent, use an authorized temporary project chat. The worker receives one assignment and the evidence required to review it.

## Dispatch

1. Capture the objective, allowed project and files, work limits, acceptance criteria, and delivery location. Preserve the user's original scope. Include the authorization for any writes in the worker brief. Assign a stable key and check it with `dispatch show KEY` when recovering intake.
2. Before reserving a new worker, run `python3 ../../codexos.py dispatch list --active`. Compare the objective, project, files, permitted actions and delivery constraints against the new requirement. If a bound worker clearly covers the addition, confirm its current turn is active on the recorded host and follow [Reuse a bound worker](#reuse-a-bound-worker). If the requirement is independent, outside scope, or the fit is unclear, reserve a separate dispatch.
3. Complete [permission preflight](#permission-preflight) after scoping and before claiming a launch. From the coordinator project, run the following example. The result includes the saved dispatch and a boolean named `launch`.

   ```sh
   python3 ../../codexos.py dispatch reserve parser-fix \
       --objective 'Correct the empty-input parser result and show the focused test passing' \
       --scope 'Approved parser project only: parser.py and its focused test'
   ```

4. When `launch` is true, submit one native worker to the correct project. Include the dispatch key in its title and brief for recovery. Use a separate worktree when the user has requested one. For workers sharing a checkout that can contend on tracked files, staging, or commits, identify the predecessor in the new brief. The new worker can read and draft privately, then waits for the predecessor to finish and checks the checkout before writing. Instruct the worker to preserve evidence and end after its bounded assignment. If an authorized revision arrives, ask it to identify the parent and requirement keys in its response and explain how the result addresses the revision.
5. Record the returned worker ID with `dispatch bind parser-fix THREAD_ID --host local`. If setup is still pending, keep its native launch reference for reconciliation and bind the actual thread ID once available. Acknowledge the dispatch in the primary chat and end the intake turn. The worker continues independently.

`launch_issued: 0` means preflight is still open and no launch has been claimed. Resume with the same key, objective and scope. After the first `launch: true`, repeat reservations return `launch: false`. If interrupted after the claim, look up the native worker by key and project and bind its existing ID. If the native service confirms no worker exists, record that evidence with `dispatch abandon KEY --evidence TEXT` and reconcile cleanup. A new attempt uses a new key. Leave an ambiguous reservation visible when native absence cannot be verified.

## Permission preflight

1. Inventory the foreseeable actions that need permission. Capture each action, its exact target or data scope, and whether it is required for the work. Check the original human instruction or native grant for each existing approval against the actual action, scope and destination. A prior denial ends that path. For completion messaging, use the registered primary chat and the payload described below. Mark it optional when heartbeat delivery is sufficient.
2. With a nonempty plan, first run the same dispatch reservation with `--prepare --plan JSON`. For an existing workload, run `workload permissions ID --plan JSON` before starting or resuming it. Reused worker reservations accept the same plan. The plan is a JSON array. Use stable IDs.

   ```json
   [
     {"id":"read-report","action":"Read the approved report","target":"Release project, test summary only","required":true},
     {"id":"notify-chief","action":"Send one completion notice","target":"Chief chat THREAD_ID. Dispatch key, outcome and concise verification only.","required":false}
   ]
   ```

3. Record decisions already verified with `--decisions JSON` on the same command when available. For the remaining choices, present one concise intake request listing the action, target or data, and required or optional status of each. Give the operator a way to approve all or select a subset. Record the explicit decisions together using `dispatch permissions KEY --decisions JSON` or `workload permissions ID --decisions JSON`. Cite the exact human message or native decision. Leave unanswered requests pending and preserve the decisions already recorded. A decision has this form.

   ```json
   {"read-report":{"decision":"approved","evidence":"Codex chat CHAT_ID, turn TURN_ID, user message ITEM_ID"}}
   ```

4. Inspect the saved plan with `dispatch permissions KEY` or `workload permissions ID`. Start or resume through the normal command when required decisions are approved. Omit optional actions without verified approval. Pending required decisions leave the work pending. A denied required decision stops that path. With an empty plan, use the normal command directly.
5. Give the worker the verified references and the approved subset in its brief. Use Codex's ordinary sandbox and action-time confirmation for each protected action. The plan records decisions and supplies a workflow gate. Authority comes from the cited grant and the tool. Verify newly discovered permissions before the corresponding action and bundle newly known requests if more than one is missing.

## Reuse a bound worker

1. Reserve a stable key for the requirement. Use the original dispatch's exact objective and scope. Check that the change fits the original authorization. Use `--required` when completing the parent assignment depends on this change.

   ```sh
   python3 ../../codexos.py dispatch reserve parser-whitespace \
       --reuse parser-fix \
       --objective 'Correct the empty-input parser result and show the focused test passing' \
       --scope 'Approved parser project only: parser.py and its focused test' \
       --requirement 'Exercise whitespace-only input in the focused test' --required
   ```

2. Use the returned `host` and `worker`. The reservation returns `launch: false`. If the worker finishes before reservation succeeds, reassess the route. Complete the addition's permission preflight and verify separate authorization to message the exact bound worker. Run `dispatch handoff parser-whitespace --claim AUTHORIZATION_REFERENCE`. Send only if the response has `send: true`. Target the saved host and worker with `send_message_to_thread`. Include the parent key, requirement key, authorized revision, and delivery location. Ask the worker to acknowledge the revision in that chat and identify the revised result and verification. Reserve a separate dispatch for independent or out-of-scope work.
3. Record a confirmed send with `dispatch handoff parser-whitespace --sent EVIDENCE`. If the send is uncertain, read the exact bound chat and look for the handoff with both keys. Keep it in `sending` while the outcome is unknown. A repeated claim returns `send: false`. Use `--reset EVIDENCE` only after confirming the previous attempt ended without sending. If permission is absent or denied, keep the requirement open and tell the operator. Record a preflight denial in the permission plan. If the native tool denies a claimed send, record it with `dispatch handoff parser-whitespace --denied EVIDENCE`. The requirement stays open and the denied send cannot be retried.
4. For a required change, read the exact bound chat for a worker-authored response to the handoff. Inspect the message sequence, including older item pages if needed. Check that the response follows the handoff, identifies both keys, and commits to applying the change or explains how it was applied. An active turn or the handoff message alone establishes no acknowledgement. Record the response's turn and message reference. Use the observed host and chat ID.

   ```sh
   python3 ../../codexos.py dispatch handoff parser-whitespace \
       --acknowledged 'Worker response ITEM_ID confirms the parser-whitespace change' \
       --host local --worker THREAD_ID --turn TURN_ID
   ```

5. Use `dispatch show` with either key to inspect the handoff. The heartbeat lists unfinished sends and required handoffs awaiting acknowledgement in `pending_handoffs`. Keep an unresolved change visible, even if the original turn has ended. Retry with the same key and options to recover the recorded route. Native delivery can occur during the current turn or in a later turn. Check the worker response and the revised result before closing the assignment.

## Monitor one checkpoint on an active dispatch

If an assignment has a checkpoint with one expected value, register it on the original dispatch. Use a short lowercase identifier for the expected value. Record a correction already covered by the dispatch's approved scope.

```sh
python3 ../../codexos.py dispatch monitor parser-fix --expected synthetic-fixture \
    --correction 'Run the parser check against the approved synthetic fixture and retain its result'
```

Ask the worker to publish a commentary item with the value it actually used, for example `CodexOS checkpoint parser-fix synthetic-fixture`. Use the checkpoint for a concrete choice, such as the fixture or target actually used. The desktop operational heartbeat reads up to 20 recent items from the current turn of each monitored active worker in its usual rotation. It matches the native host, chat and turn before looking for the latest checkpoint for that assignment. Silence or an unavailable snapshot leaves the dispatch open.

On a conflicting checkpoint, the heartbeat records its native turn and item reference and queues one required correction on the original dispatch. The pulse lists the new entry under `worker_checkpoints` and later ticks continue to expose any pending handoff. The coordinator checks the evidence and uses the normal reuse procedure to record a verified send approval with `dispatch permissions CORRECTION_KEY` before claiming the handoff. After the worker receives the correction, ask it to include the correction key as a fourth field in its checkpoint, for example `CodexOS checkpoint parser-fix synthetic-fixture CORRECTION_KEY`. Verify and record acknowledgement of the handoff using the same procedure as for other required changes. The heartbeat can then record the matching recovery checkpoint while the worker is active. Check the actual deliverable through normal dispatch review. Use the worker chat and the saved turn and item reference to resolve any discrepancy.

## Notify the Chief when work finishes

During setup, the operator can authorize a worker to send one completion message to the registered primary chat. Record the exact chat, turn and user message in the local manifest as `completion_authorization`. At intake, verify the cited human instruction covers this destination and payload. Give the worker that reference, the dispatch key and the exact destination from `primary_thread`. Establish the same details in the intake request when the grant is missing.

Save the result and evidence in the approved local receipt first. Once work is finished, verify the cited human authorization and send one short notice with the native `send_message_to_thread` tool. Include only the dispatch key, outcome and a concise verification summary. Keep private paths, raw logs, transcript data and deliverables in the local receipt or worker result. If messaging is unavailable or denied, leave the outcome in the worker chat for heartbeat reconciliation and end the turn.

The completion message starts a coordinator turn. Match the native sender to the worker bound to the key and check the current dispatch state. If binding is still pending, reconcile the existing reservation first. Ignore an unrelated sender or an already cleaned key. Recover the receipt from the agreed delivery location or read the result in the exact bound worker chat. Verify the result independently, post the verdict and deliverable in the primary chat, then record delivery. The heartbeat handles local worker archival. Leave an interrupted review or cleanup open for reconciliation.

## Carry authorized review findings through delivery

When independent review finds a blocker, check the outcome and the assignment's approved scope. Keep the release workload open and record the blocker, the reviewed commit, the evidence, and the next action. If the correction fits an active implementation dispatch, use the required handoff procedure above. If that worker has ended, reconcile its result and reserve a follow-up under the existing authorization. Route fresh acceptance and independent review to the revised commit. Complete authorized delivery after those checks pass. Ask the operator only for a specific missing grant or consequential decision. A review finding does not grant new authority or substitute for independent review.

## Review, deliver, and clean up

Use `dispatch show KEY` for a status question and `dispatch list` for bounded coordinator reconciliation. On each desktop heartbeat, review `workers_to_review` even when no completion notice arrived. The script takes one immediate native snapshot for bound, undelivered workers in the CLI's rotated `workers_to_check` list of up to three dispatches. It returns the bound worker and host with the latest terminal turn ID and status when the exact chat is idle. Read the receipt or the result in that worker chat and verify the outcome. A terminal turn establishes that execution ended. Active, unavailable, mismatched and incomplete snapshots leave the dispatch open for another pass. Checkpoint monitoring on active workers is opt-in. Use raw `workers_to_check` candidates only for CLI-only recovery. In that case, check those bound chats through the native status interface before beginning review. On confirmed failure, record `dispatch abandon KEY --evidence TEXT` and tell the operator which work remains.

When the worker finishes, preserve its deliverable and evidence in the approved project. Run `dispatch report KEY --evidence TEXT` with a durable reference to the exact result, such as a commit or versioned artifact. For each required change, record the worker acknowledgement first and confirm that this result covers it. Add `--covers REQUIREMENT_KEY` once per required change. If the original result predates the revision, keep the dispatch open and look for the revised result.

Inspect the recorded result against the original objective and its additions. Execute the applicable validation. Run `dispatch review KEY --decision accept --evidence TEXT` or `--decision reject`. For acceptance, add `--verified REQUIREMENT_KEY` for each required change you verified in the reported artifact. Include the exact artifact and validation result in the review evidence. The CLI checks the recorded acknowledgements and requirement keys. The coordinator checks the worker messages and the artifact. If a required change cannot be completed, report the outstanding work and use the failure procedure above. Present the verdict and evidence in the primary chat.

After posting the result in the primary chat, run `dispatch delivered KEY --evidence TEXT` with the delivered result or its message reference. A visible progress message can deliver the result before the CLI call. If interrupted between posting and recording, inspect the primary chat to recover the delivery receipt. Execute the desktop heartbeat from `routines/heartbeat.md` once for immediate cleanup. Each scheduled heartbeat also picks up pending receipts, including after a restart. The fleet CLI selects delivered dispatches. The checked-in `heartbeat.js` script checks the latest native turn, archives the exact idle worker through the desktop tools, verifies its ID in archived history, and records cleanup. A shell-only `codexos.py heartbeat` returns the candidates for inspection. A running worker, missing delivery or unavailable Codex service leaves the record open. An already archived worker needs only confirmation. The archive step requires the desktop code-mode runtime with native chat tools. For remote workers, verify archival on the bound host and use `dispatch cleaned` with that evidence. An unbound reservation needs native confirmation that no worker was launched before recording cleanup. Never select a worker for archival by title alone.

Each bot owns its dispatch records in its own SQLite state. Codex starts the worker, enforces the existing project and sandbox boundaries, and owns its runtime lifecycle. A record in this ledger grants no additional access.
