---
name: create-bot
description: Guide the operator through confirming a new persistent specialist's job, preferences, and permissions, then provision its Codex project.
---

# Create a specialist

Use the guided setup in [the fleet guide](../../../../../docs/fleet.md). Run the steps in order and skip questions the operator already answered. Wait for approval of the complete summary before creating the project. When the operator confirms they added the exact project folder, resume the desktop check with the saved bot ID. Follow the returned pending action. Report full onboarding only when the check returns `ready`.

Confirm whether the bot needs a heartbeat. If it does, offer every 15 minutes and confirm the cadence, operating window, and time zone. Record the required routine plan or an explicit empty plan. For a manual-only bot, skip the scheduling questions. Include the choice in the approval summary and use the approved setup file on retries. Schedule activation requires separate authorization.
