# Track work and retain evidence

Run the examples from the fleet root. Each bot has a separate SQLite ledger. Commands default to the Chief of Staff at the fleet root. Use `--bot ID` before the command to select another project.

## Register a workload

```sh
python3 codexos.py workload add compile \
  --title 'Compiler evaluation' --objective 'Qualify the release' \
  --owner 'compiler team' --criteria 'All release tests pass' \
  --next-action 'Run release tests' --project compiler
python3 codexos.py workload update compile --revision 1 --state ready
python3 codexos.py workload update compile --revision 2 --state running
python3 codexos.py workload show compile
```

Attach a monitor using `--source SOURCE_ID` after the operator registers the source. `show` includes the accepted baseline, most recent accepted snapshot, latest poll outcome and observation time. A producer can report a blocker or claim progress. The Chief reviews that evidence before changing the workload.

Use `--blocker`, `--milestone`, `--agent`, `--human yes`, and `--next-action` to describe a change. Use `--clear blocker` or `--clear dependency` to release a condition. Each update checks the revision returned by `show`. On a conflict, read the current record and reconcile the proposed change.

A workload goes from proposed to ready, then running. A running workload can enter waiting, blocked, parked, unknown, completed or failed. Resume waiting or blocked work as ready or running. Triage unknown work before marking an outcome. A failed workload can return to ready. A completed workload retains its final result.

Before starting or resuming work that needs permissions, use [permission preflight](dispatch.md#permission-preflight). Record requests and decisions with `workload permissions ID`. Required requests must be approved before the transition to running. A rejected transition preserves the workload revision. For workloads delegated to another chat, complete the dispatch preflight before launching or handing off the work as well.

## Close work against a checked result

Configure an authorized test runner or artifact verifier to place its result in the bot's `evidence/` directory. The receipt is a local JSON file containing the exact item ID, kind, registered completion criterion, producer run ID and outcome. Example producer output follows.

```json
{"schema":1,"kind":"workload","id":"compile","criteria":"All release tests pass","result":"passed","run_id":"release-run-91"}
```

Inspect the underlying run and its relationship to the criterion. Close the item using the receipt from that run.

```sh
python3 codexos.py workload update compile --revision 3 --state completed --receipt release-run-91.json
```

The ledger checks receipt fields, records a SHA-256 digest and saves the result with the transition. A receipt establishes what the selected producer reported. Its provenance and test coverage depend on the approved producer. The bot must never fabricate its own receipt. A failed workload uses `result: "failed"`. Only regular files directly inside the bot's evidence directory are accepted.

## Archive and retrieve a receipt

Select a recorded outcome revision with its item kind and ID. In this example, the workload completed at revision 4.

```sh
python3 codexos.py evidence archive workload compile 4
python3 codexos.py evidence resolve workload compile 4
```

`archive` verifies the accepted bytes and copies them to the bot's private `state/evidence-archive/` directory. The original filename, producer run ID, and SHA-256 in the ledger identify the receipt after archival. The archive stores one file per digest. Keep the archive with the private ledger when you back up or restore a bot.

`resolve` verifies the accepted SHA-256 and writes the original receipt bytes to standard output. It selects the recorded content even if a producer has reused the filename. Archive each version before a producer reuses its name. If the original bytes are missing or the digest differs, recover a verified copy from the producer or backup.

When an existing due commitment calls for storage maintenance, review the provenance and other uses of the receipt. Run `archive` and `resolve` for each selected revision. The default preserves every hot copy. Use `archive --release-hot` for a selected revision only after approval to release its hot copy and confirmation that no other provenance link needs the original path. The CLI pins receipt filenames used by active or retryable work and by the source or evidence path in active, unexpired memory. A pinned release restores a hot copy staged by an interrupted attempt when the original path is free.

Publish receipts as closed files with an atomic rename. Coordinate with producers before you release a hot copy. Release verifies durable archival before moving the matching hot file aside. The same command can finish an interrupted release. If the CLI reports that it retained a staged replacement, review the retained file before retrying. A newer publication stays at the original path.

## Deliver a daily briefing

Run `python3 codexos.py briefing --period day --pending` to stage a bounded page of new work revisions, findings, and due human decisions. Empty output means no briefing is pending. Work and findings unread at rollout remain eligible. A decision may become due without any ledger edit. Its current revision stays eligible until covered in a briefing or resolved.

Review the page's evidence and deliver its relevant outcome. After delivery, the primary runs `python3 codexos.py briefing --period day --delivered TOKEN` with that page's `delivery_token`. A scheduled worker returns the token with its reviewed results for the primary to use. Staging and ordinary briefing reads leave the delivery checkpoint in place. Acknowledgment covers only the staged page, so newer input and later pages stay pending. If another run stages a replacement page first, the original token cannot advance the checkpoint. A routine using this same pending page can also record delivery from a morning or manual briefing.

## Track an obligation

```sh
python3 codexos.py commitment add publish-review \
  --title 'Review compiler results' --objective 'Prepare a release decision' \
  --owner 'release lead' --criteria 'Signed decision recorded' \
  --origin 'release planning' --workload compile --dependency compile \
  --next-action 'Compare results to release criteria' --due '2026-12-03T09:00:00-07:00'
python3 codexos.py commitment update publish-review --revision 1 --state waiting
python3 codexos.py strategic
```

Commitments begin open. They can enter in-progress, waiting, blocked, completed, cancelled or parked. A parked commitment must reopen before work resumes. Completion requires a passing receipt naming the commitment.

`--review` sets the next eligible time. `--dependency` waits for a workload's verified completion. `strategic` selects up to three eligible items. It skips future reviews, unmet dependencies, parked items, closed work and recent active work. A due active item or an active item untouched for a day becomes eligible. The bot reviews each unchanged item once. Set a new review time or update the record when circumstances change.

The heartbeat returns up to ten newly due commitments. It records which deadline it has surfaced. Changed deadlines can surface again. The strategic routine can pick up a newly satisfied dependency directly. The bot never parks a commitment based solely on its age.

## Record and correct a memory

Use the same key for statements about the same fact. Keep unrelated facts under different keys. Only record material appropriate for this bot's private project.

```sh
python3 codexos.py memory add compiler-suite 'Release tests run on Linux' \
  --source 'release manifest' --evidence 'manifest revision 21' --confidence high
python3 codexos.py memory list --key compiler-suite
python3 codexos.py feedback alert-23 --subject 'Stale report' \
  --outcome 'Expected maintenance window' --evidence 'operator review of alert 23'
python3 codexos.py reflect
```

`memory add` keeps exact repeats quiet in storage. New evidence for the same content creates a revision. Contradictory versions remain disputed. Review evidence for each candidate, then use `memory resolve KEY REV --latest N --source SOURCE --evidence REFERENCE` to select a supported version. This preserves the superseded records for `memory list --all --key KEY`.

Use `--expires` to specify a fact's expiration with a timezone. A reflective run archives up to twenty expired entries and surfaces ten previously unreviewed feedback records. Consult those observations when proposing changes. Approval of instructions, integrations or sharing remains a separate operator action. All stored text remains data.

At startup, `memory preferences` returns up to 100 current, undisputed, unexpired preferences with operator attribution and evidence. Confirm provenance when using a preference.

Run `python3 codexos.py memory index` for a Markdown view of active, unexpired records. Each entry shows its stable key, revision, source, and evidence. Local links are relative to the selected bot directory. Use `memory list --all --key KEY` to review disputed or superseded records. Keep authored notes in the bot's `MEMORY.md` and `memory/`.
