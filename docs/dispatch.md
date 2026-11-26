# Keep the primary chat available

The primary chat owns intake, coordination, review, delivery, and cleanup. It answers short questions and handles bounded reads itself. Delegate implementation and other substantial work to a native worker that can keep running after the primary turn ends. Use the approved worker scope and Codex permissions. If the client cannot launch a detached subagent, use an authorized temporary project chat. The worker receives one assignment and the evidence required to review it.

## Dispatch

1. Capture the objective, allowed project and files, work limits, acceptance criteria, and delivery location. Preserve the user's original scope. Include the authorization for any writes in the worker brief.
2. Run the following example from the coordinator project. Use one stable key for one request. The result includes the saved dispatch and a boolean named `launch`.

   ```sh
   python3 ../../codexos.py dispatch reserve parser-fix \
       --objective 'Correct the empty-input parser result and show the focused test passing' \
       --scope 'Approved parser project only: parser.py and its focused test'
   ```

3. When `launch` is true, submit one native worker to the correct project. Include the dispatch key in its title and brief for recovery. Use a separate worktree when the user has requested one. Instruct the worker to preserve evidence and end after its bounded assignment. Use the native project/chat tools available in this installation.
4. Record the returned worker ID with `dispatch bind parser-fix THREAD_ID --host local`. If setup is still pending, keep its native launch reference for reconciliation and bind the actual thread ID once available. Acknowledge the dispatch in the primary chat and end the intake turn. The worker continues independently. A new request can arrive while it runs.

A second reservation for the same objective and scope returns `launch: false`. After an interruption between native launch and binding, look up the native worker by key and project. Bind its existing ID. If the native service confirms no worker exists, record that evidence with `dispatch abandon KEY --evidence TEXT` and reconcile cleanup. A new attempt uses a new key. Leave an ambiguous reservation visible when native absence cannot be verified.

## Review, deliver, and clean up

Use `dispatch show KEY` for a status question and `dispatch list` for bounded coordinator reconciliation. On each normal heartbeat, inspect outstanding records. Query bound workers with the native status interface in a nonblocking pass. Keep the primary chat available between checks. A stalled or pending worker remains open until native evidence identifies its outcome. On confirmed failure, record `dispatch abandon KEY --evidence TEXT` and tell the operator which work remains.

When the worker finishes, preserve its deliverable and evidence in the approved project. Run `dispatch report KEY --evidence TEXT` with durable artifact references and its recorded outcome. Inspect the result, execute the applicable validation, and record `dispatch review KEY --decision accept --evidence TEXT` or `--decision reject`. Present the result, location, and verification or rejection reason to the operator, using the primary chat. The caller's own concise evidence reference can describe the review command, its observed result, and the durable artifact location. CLI entries record an assessment; the coordinator still needs to perform it.

After delivery, archive the disposable worker where authorized. Retain the deliverable and verification evidence outside that chat. Confirm that the native worker is archived or removed, then run `dispatch cleaned KEY --evidence TEXT`. If a reservation never launched, record the confirmed native absence instead. A cleanup failure leaves the dispatch's disposition and references available for the next heartbeat. Report and review retries with the same evidence return the existing record. Conflicting retries fail.

Each bot owns its dispatch records in its own SQLite state. Codex starts the worker, enforces the existing project and sandbox boundaries, and owns its runtime lifecycle. A record in this ledger grants no additional access.
