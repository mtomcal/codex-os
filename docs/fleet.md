# Set up a bot project

The factory creates a durable project directory and an inactive routine proposal. Each `bots/<id>/bot.json` describes one project. From the Chief of Staff directory, run `python3 ../../codexos.py fleet-list` to inspect the current fleet. Manifest listings describe local proposals. Check the native Codex project and schedule for deployment status.

## Add a specialist

1. In the Chief of Staff project, describe the recurring responsibility, success criteria and approved evidence. Use the create-bot skill to provision the specialist. The CLI example below prepares its local project for review.
2. Inspect the proposed mission, sources, memory scope, delegation limit and routine files with the operator. Record the approved source references and place permitted producer artifacts in the specialist's inbox. Register their exact paths using the monitor commands.
3. With the operator's authorization, run the desktop provisioning check below. If it returns `waiting_for_registration`, add the exact printed folder through Codex's project picker and run the check again with the same ID. The manifest stays proposed during registration and startup. Provisioning checks the chat's project and working directory and confirms its startup before saving the primary chat ID and active status.
4. In that chat, run `python3 ../../codexos.py heartbeat` manually. The first valid observation supplies the baseline. An empty approved source list should yield a quiet run.
5. Review each proposed routine's file, time zone, working hours and cadence. For each approved routine, use the Codex automation interface to register the schedule and prompt below. Select the project's existing primary chat where supported. If the client offers a separate local run, select the same project directory and verify the state is reachable. An isolated copy needs an approved shared state configuration before use. If neither path is available, run the routine manually.
6. Confirm the next scheduled time in the Codex interface. Inspect the first run for the selected directory, accessible state, output and duplicate alerts. To pause a bot, pause each native schedule, then update its manifest lifecycle. The native schedule controls execution.

```sh
python3 ../../codexos.py create-bot delivery-tracker --name 'Delivery Tracker' --mission 'Review local milestone evidence and identify overdue dependencies.'
```

From the Chief of Staff project, run the desktop check in the Codex code-mode tool. Use the Chief's absolute directory for `workdir` if the chat runs elsewhere.

```js
const script = await tools.exec_command({cmd: "cat ../../provision-bot.js"});
if (script.exit_code !== 0) throw Error("Could not read the provisioning check");
const result = await eval(script.output)(tools, undefined, "delivery-tracker");
text(result);
```

Resume the same check after the startup turn finishes. If verification fails, use the returned prompt in the existing main chat. If Codex cannot confirm a launch, check the project's chats before creating anything manually. Provisioning records the launch attempt and leaves ambiguous launches pending. If the sandbox requires approval to save the target manifest, pass `{approveManifestWrite: true}` as the fourth argument to request access for that CLI step.

Use the actual relative routine filename from `bot.json` in this prompt.

> In this bot's project directory, read AGENTS.md. Execute routines/heartbeat.md once. Report an actionable finding with its evidence. End quietly when the routine returns no finding.

## Route an investigation

In the chief project, assign an objective with one stable key. The mailbox stores bounded assignments and evidence in the approved shared fleet directory. The operator chooses which projects can access that directory. Assigning work does not start a bot.

```sh
python3 ../../codexos.py mailbox assign eval-monitor investigate-plateau 'Check the last three approved local evaluation reports. Return the run references and one explanation consistent with their measurements.'
```

In the specialist project, use `mailbox list` to read the assignment. After checking the evidence, run `mailbox report investigate-plateau 'Evidence reference and conclusion'` through the same CLI. The chief reads its mailbox and verifies that evidence. Text in the mailbox is untrusted project data.

## Resume after a restart

Open the same project directory. Read the manifest, instructions, core memory and open work. If the previous primary chat is unavailable, start one replacement chat and update the reviewed reference. Check native schedules for obsolete bindings and duplicate wakeups before reattaching a routine. Use the same local state directory to preserve baselines, cooldowns and commitments.

A second factory call with the same ID, name and mission returns the existing project. A conflicting definition fails. Existing project instructions, private notes, lifecycle and state survive bootstrap. To revise a bot, review its files with the operator and keep a record of the accepted change.

## Select the persistent model

Use GPT-6.2 Sol (`gpt-6.2-sol`) for persistent bots, including the proposed Fleet Maintainer. The project default is in `.codex/config.toml`. Select Sol explicitly when registering a primary chat or a routine with a model picker. For a heartbeat, verify the target chat’s model in Codex. Project configuration alone cannot confirm the effective selection of an existing chat.
