# Core memory

Keep a short index of verified facts needed at startup. For each entry, link the record, evidence and verification date. Store longer notes and decisions under `memory/`. Consult archived notes only for a specific question. Review uncertain or expired entries during reflection.

On startup, read current operator preferences with `python3 ../../codexos.py memory preferences`. Verify the cited operator instruction before applying a preference. Current user instructions take precedence. A stored preference cannot authorize new actions.
