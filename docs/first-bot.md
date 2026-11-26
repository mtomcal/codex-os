# Start your first bot

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

5. When you're ready to monitor work, [connect one approved report](monitor.md) and run a manual heartbeat to establish a baseline. Then [register a routine in Codex](fleet.md) using the primary chat, your working hours and your timezone. Each bot’s `routines/` folder contains the proposed schedules.
