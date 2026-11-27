# Core memory

Run `python3 ../../codexos.py memory index` to see the active records in the private SQLite ledger, with their stable keys, sources, and evidence links. Use this file and `memory/` for authored notes. Review uncertain or expired records during reflection.

On startup, read current operator preferences with `python3 ../../codexos.py memory preferences`. Verify the cited operator instruction before applying a preference. Current user instructions take precedence. A stored preference cannot authorize new actions.

## Quiet memory during ordinary turns

Check the manifest's `memory.quiet` setting before capturing an unsolicited record. If it is denied, unspecified, or absent, skip quiet capture.

If approved, before the final reply, check for a durable operator preference, a correction, or a lesson verified during this turn. Save a brief record only when it would help on a later turn. Use `python3 ../../codexos.py memory add KEY CONTENT --quiet --category CATEGORY --source SOURCE --evidence REFERENCE`. Use `preference` with source `operator` for preferences, `fact` for corrections, and `lesson` for verified lessons. Give each topic a stable key and cite the operator turn or verified artifact without copying the transcript.

If a correction conflicts with an existing entry, inspect both versions with `memory list --key KEY`. With clear evidence, select the supported revision with `memory resolve KEY REV --latest LATEST --quiet --source SOURCE --evidence REFERENCE`. Leave inconclusive entries disputed. Exclude secrets, raw logs, and chat transcripts from the ledger. Keep records private and get separate authorization to share them.

Omit routine saves from replies. An explicit save request or an authorized reflection routine follows its own permissions.
