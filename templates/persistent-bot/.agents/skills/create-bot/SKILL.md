---
name: create-bot
description: Use when the operator asks the Chief of Staff to create or resume provisioning a persistent specialist.
---

# Create bot

Choose a stable lowercase ID, a display name and a one-sentence mission. From the Chief of Staff project run `python3 ../../codexos.py create-bot ID --name NAME --mission MISSION`, passing each value as one shell argument. Reuse an existing proposal by ID. Review the proposed manifest with the operator.

With the operator's authorization to provision the bot, run the desktop check in `../../docs/fleet.md`. If the check returns `waiting_for_registration`, give the operator the exact folder and ask them to add it using the Codex project picker. End the turn with the bot pending. Resume with the same ID when the operator confirms registration. Follow the returned action for a pending or failed startup. Report completion and share the main chat link only after the check returns `active`.

Get separate authorization for new sources or schedule activation.
