# CodexOS

Use CodexOS to give a Codex agent a project it can return to. Its private ledger stores commitments, preferences and evidence across chats. When you ask the agent to implement something, it can hand the work to a temporary worker, answer other requests, and review the result when the worker finishes.

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
