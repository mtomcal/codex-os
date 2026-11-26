# How a wakeup works

Codex selects a project and runs its local instructions. The bot calls the fleet CLI once for the requested routine. Each bot owns an inbox, a private SQLite database, a compact memory index, and a reports directory. The fleet registry is the set of published bot manifests. The shared SQLite mailbox contains explicitly assigned work and evidence references.

An approved producer publishes a snapshot under a registered filename. The heartbeat checks a bounded number of sources, validates fields, and compares the normalized report with the last accepted observation. It commits checkpoints, findings, and due reminders in one local transaction. A replay sees the committed state. Overlapping invocations serialize on SQLite's writer lock and time out if another writer cannot finish.

The operational loop reports immediate findings and reminders. A briefing joins monitored measurements to the workloads that reference their source IDs. The strategic loop selects eligible unfinished work and records which revision it reviewed. The reflective loop archives expired records and surfaces feedback for judgment. Codex interprets evidence, writes a concise report when warranted, and ends the turn.

The Chief of Staff can propose a specialist project and put bounded work in its mailbox. The specialist publishes an evidence reference. The chief verifies the outcome before closing a commitment. A mailbox entry or a local manifest change cannot start a Codex project or activate a schedule.

Use local disk for the fleet. Each private database holds its own bot's observations and commitments. Only the mailbox needs coordination between bots. After replacing a chat, the new conversation recovers from the same files. A native routine running against a detached copy needs access to the correct durable project before it can take over monitoring.
