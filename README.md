# CodexOS

Use CodexOS to give a Codex agent a project it can return to. Its private ledger stores commitments, preferences and evidence across chats. When you ask the agent to implement something, it can hand the work to a temporary worker, answer other requests, and review the result when the worker finishes.

## Start your first bot

You need Python 3.11 or later, macOS or Linux, and a local disk. The framework uses the Python standard library. For a persistent chat and scheduled runs, use a Codex installation with the corresponding features enabled.

1. Clone the repository and initialize your local fleet.

   ```sh
   gh repo clone mtomcal/codex-os
   cd codex-os
   python3 codexos.py init
   ```

   This creates two local project folders in `bots/`. Start with `chief-of-staff`. The optional `eval-monitor` project can stay inactive. You can run `init` again without overwriting your bot’s settings.

2. Check the Chief of Staff from its own directory.

   ```sh
   cd bots/chief-of-staff
   python3 ../../codexos.py status
   python3 ../../codexos.py heartbeat
   ```

   Look for `chief-of-staff`, database integrity `ok`, and zero sources. With no sources or outstanding work, the heartbeat exits quietly.

3. Open this folder as a project in Codex. If the Codex CLI is installed, run `codex app .`. Start one primary chat and select `gpt-6.2-sol`. The project needs approved access to the fleet CLI two directories above it.

4. Ask the new chat: “Read your project instructions. Remember that I prefer a one-sentence verdict at the start of a briefing. Save it as an operator preference with this request as evidence.” Inspect what it saved.

   ```sh
   python3 ../../codexos.py memory preferences
   ```

   To check persistence, open a fresh chat in the same project and ask what briefing format you prefer.

5. When you're ready to monitor work, [connect one approved report](monitor.md) and run a manual heartbeat to establish a baseline. Then [register a routine in Codex](FLEET.md) using the primary chat, your working hours and your timezone. Each bot’s `routines/` folder contains the proposed schedules.

## Test a change

From the repository root, run:

```sh
python3 acceptance/run.py
```

The harness creates disposable bots, exercises the public CLI, and checks that cleanup removes only the test run. The candidate evaluator tries a deliberately broken monitor and must catch both a missed regression and a duplicate alert. The memory and dispatch graders also run against synthetic examples. A failing stage exits nonzero.

For new evidence from the desktop app, follow the [live Memory Lab guide](acceptance/LIVE.md). To grade captured runs as part of the same suite, supply a directory containing `live-evidence.json` and `dispatch-evidence.json` with `--evidence-dir`. To save the test reports, add `--results results/trial-1` with a new output path.

## Where to go next

| To do this | Read |
|---|---|
| Create a specialist, attach a schedule or replace a chat | [Fleet setup](FLEET.md) |
| Track a workload, close a commitment or correct a memory | [Work and memory commands](ledger.md) |
| Delegate implementation and retrieve the verified result | [Worker lifecycle](DISPATCH.md) |
| Compare a proposed monitoring change against reviewed cases | [Candidate evaluation](acceptance/maintainer/README.md) |
| Understand state ownership, permissions and recovery | [Architecture](architecture/overview.md) and [trust and recovery](architecture/threat-model.md) |

Git tracks the framework, templates and synthetic tests. Your bot projects, shared state, local evidence and test results stay in the checkout’s ignored directories. Keep raw conversations and credentials in their tool-owned storage.
