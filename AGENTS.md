# Acceptance criteria

1. For every CodexOS change, add or update acceptance harness coverage that exercises the changed behavior through its normal entry point.
2. Run the full harness from the repository root with `python3 acceptance/run.py`. A passing full run is required to claim acceptance. Unit tests can supplement the full run.
3. If the full harness fails or cannot run, report acceptance as failed or blocked. Include the command, the failing check and observed error or the specific blocker, and the behavior still unverified.
4. When an edit changes a native tool boundary, anchor a replay fixture in a sanitized, representative read-only response. Add a negative case for a meaningful shape mismatch. Record what you observed live and what you replayed.
