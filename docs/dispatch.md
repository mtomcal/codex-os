# Keep the primary chat available

The primary chat owns intake, coordination, review, delivery, and cleanup. It answers short questions and handles bounded reads itself. Delegate implementation and other substantial work to a native worker that can keep running after the primary turn ends. Use the approved worker scope and Codex permissions. If the client cannot launch a detached subagent, use an authorized temporary project chat. The worker receives one assignment and the evidence required to review it.

## Dispatch

1. Capture the objective, allowed project and files, work limits, acceptance criteria, and delivery location. Preserve the user's original scope. Include the authorization for any writes in the worker brief. Assign a stable key and check it with `dispatch show KEY` when recovering intake.
2. Before reserving a new worker, run `python3 ../../codexos.py dispatch list --active`. Compare the objective, project, files, permitted actions and delivery constraints against the new requirement. If a bound worker clearly covers the addition, confirm its current turn is active on the recorded host and follow [Reuse a bound worker](#reuse-a-bound-worker). If the requirement is independent, outside scope, or the fit is unclear, reserve a separate dispatch.
3. Run the following example from the coordinator project. The result includes the saved dispatch and a boolean named `launch`.

   ```sh
   python3 ../../codexos.py dispatch reserve parser-fix \
       --objective 'Correct the empty-input parser result and show the focused test passing' \
       --scope 'Approved parser project only: parser.py and its focused test'
   ```

4. When `launch` is true, submit one native worker to the correct project. Include the dispatch key in its title and brief for recovery. Use a separate worktree when the user has requested one. For workers sharing a checkout that can contend on tracked files, staging, or commits, identify the predecessor in the new brief. The new worker can read and draft privately, then waits for the predecessor to finish and checks the checkout before writing. Instruct the worker to preserve evidence and end after its bounded assignment.
5. Record the returned worker ID with `dispatch bind parser-fix THREAD_ID --host local`. If setup is still pending, keep its native launch reference for reconciliation and bind the actual thread ID once available. Acknowledge the dispatch in the primary chat and end the intake turn. The worker continues independently.

A second reservation with the same key, objective and scope returns `launch: false`. After an interruption between native launch and binding, look up the native worker by key and project. Bind its existing ID. If the native service confirms no worker exists, record that evidence with `dispatch abandon KEY --evidence TEXT` and reconcile cleanup. A new attempt uses a new key. Leave an ambiguous reservation visible when native absence cannot be verified.

## Reuse a bound worker

1. Reserve the stable key for the new requirement with the original dispatch's exact objective and scope. Include only the additional work in `--requirement`. The exact match guards against selecting the wrong dispatch. The coordinator still verifies the requirement is covered by the original authorization.

   ```sh
   python3 ../../codexos.py dispatch reserve parser-whitespace \
       --reuse parser-fix \
       --objective 'Correct the empty-input parser result and show the focused test passing' \
       --scope 'Approved parser project only: parser.py and its focused test' \
       --requirement 'Exercise whitespace-only input in the focused test'
   ```

2. The reservation returns `launch: false` and the bound `host` and `worker`. If the worker finishes before reservation succeeds, reassess the route for the requirement. With operator authorization to message the bound worker, run `dispatch handoff parser-whitespace --claim AUTHORIZATION_REFERENCE`. Proceed with the send only when the response has `send: true`. Use the native `send_message_to_thread` tool with the saved host and worker. Include the parent dispatch key, requirement key, authorized addition and delivery location. Ask the worker to account for the requirement in its normal result.
3. Record a confirmed send with `dispatch handoff parser-whitespace --sent EVIDENCE`. A repeated claim returns `send: false` while delivery is in progress or confirmed. If the send result is uncertain, look for the requirement key in the exact worker chat. Record a confirmed delivery or leave it visible as `sending` while the outcome is unknown. Use `--reset EVIDENCE` only after confirming the tool did not send and the prior attempt has ended. If permission is absent or denied, leave the handoff pending and tell the operator.
4. Use `dispatch show` with either key to inspect the addition. The heartbeat exposes `pending_handoffs` even after the original worker finishes. Keep the requirement visible if the handoff cannot be completed and report it as outstanding. A retry with the same key recovers its recorded route even if the parent has since closed.

## Notify the Chief when work finishes

During setup, the operator can authorize a worker to send one completion message to the registered primary chat. Record a reference to that human instruction in the local manifest as `completion_authorization`. Give the worker that reference, the dispatch key and the exact destination from `primary_thread`. A launch message from the Chief alone does not authorize a reply.

Once the result or failure evidence is durable and all task work is finished, the worker checks the operator authorization and uses the native `send_message_to_thread` tool to notify that primary chat. Include the dispatch key, outcome and evidence location. For a chat-only result include the actual deliverable or its retrievable reference. End the worker turn after sending. If messaging is unavailable or denied, leave the outcome in the worker chat for heartbeat reconciliation.

The completion message starts a coordinator turn. Match the native sender to the worker bound to the key and check the current dispatch state. If binding is still pending, reconcile the existing reservation first. Ignore an unrelated sender or an already cleaned key. Verify the result independently, post the verdict and deliverable in the primary chat, then record delivery. The heartbeat handles local worker archival. Leave an interrupted review or cleanup open for reconciliation.

## Review, deliver, and clean up

Use `dispatch show KEY` for a status question and `dispatch list` for bounded coordinator reconciliation. On each normal heartbeat, inspect outstanding records. Query bound workers with the native status interface in a nonblocking pass. Keep the primary chat available between checks. A stalled or pending worker remains open until native evidence identifies its outcome. On confirmed failure, record `dispatch abandon KEY --evidence TEXT` and tell the operator which work remains.

When the worker finishes, preserve its deliverable and evidence in the approved project. Run `dispatch report KEY --evidence TEXT` with durable artifact references and its recorded outcome. Inspect the result against the original objective and any additions sent to the worker, execute the applicable validation, and record `dispatch review KEY --decision accept --evidence TEXT` or `--decision reject`. Present the result, location, and verification or rejection reason to the operator, using the primary chat. The caller's own concise evidence reference can describe the review command, its observed result, and the durable artifact location. CLI entries record an assessment; the coordinator still needs to perform it.

After posting the result in the primary chat, run `dispatch delivered KEY --evidence TEXT` with the delivered result or its message reference. A visible progress message can deliver the result before the CLI call. If interrupted between posting and recording, inspect the primary chat to recover the delivery receipt. Execute the desktop heartbeat from `routines/heartbeat.md` once for immediate cleanup. Each scheduled heartbeat also picks up pending receipts, including after a restart. The fleet CLI selects delivered dispatches. The checked-in `heartbeat.js` script checks the latest native turn, archives the exact idle worker through the desktop tools, verifies its ID in archived history, and records cleanup. A shell-only `codexos.py heartbeat` returns the candidates for inspection. A running worker, missing delivery or unavailable Codex service leaves the record open. An already archived worker needs only confirmation. The archive step requires the desktop code-mode runtime with native chat tools. For remote workers, verify archival on the bound host and use `dispatch cleaned` with that evidence. An unbound reservation needs native confirmation that no worker was launched before recording cleanup. Never select a worker for archival by title alone.

Each bot owns its dispatch records in its own SQLite state. Codex starts the worker, enforces the existing project and sandbox boundaries, and owns its runtime lifecycle. A record in this ledger grants no additional access.
