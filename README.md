# CodexOS

CodexOS turns a Codex project into an always-on assistant that helps you manage your day. You give it tasks in one main chat and choose when it checks in. Once you set up a schedule, it can start your morning with what’s due, flag a new blocker in a project report you’ve connected, and carry unfinished work into tomorrow. You can also hand it a longer job and keep using the main chat while a worker takes care of it.

The assistant learns from the work you track together and the feedback you give it. For example, tell it, “Put decisions I need to make at the top of my morning briefing.” It can save that preference in the project and use it in future briefings, even after you start a fresh chat. You can inspect what it remembers and correct it when your priorities change.

[Set up your first bot](docs/first-bot.md).

## Run the acceptance tests

From the repository root, run `python3 acceptance/run.py`. See [testing](docs/testing.md) to save results or grade captured runs.

## Guides

| To do this | Read |
|---|---|
| Create a specialist, attach a schedule or replace a chat | [Fleet setup](docs/fleet.md) |
| Track a workload, close a commitment or correct a memory | [Work and memory commands](docs/ledger.md) |
| Delegate implementation and retrieve the verified result | [Worker lifecycle](docs/dispatch.md) |
| Compare a proposed monitoring change against reviewed cases | [Candidate evaluation](docs/candidate-evaluation.md) |
| Understand state ownership, permissions and recovery | [Architecture](docs/architecture.md) and [trust and recovery](docs/threat-model.md) |

Git tracks the framework, templates and synthetic tests. Your bot projects, shared state, local evidence and test results stay in the checkout’s ignored directories. Keep raw conversations and credentials in their tool-owned storage.
