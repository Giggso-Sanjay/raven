---
name: router
description: Toggle the Raven model router. /router enables advisory Haiku-subagent delegation for simple prompts, /router off disables it, /router status shows the current mode. The primary session model is never changed — that is set only via /model.
---

# Raven Model Router Toggle

Run the matching command and relay its printed output to the user verbatim:

- `/router` or `/router on` → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/model-router.py" --enable`
- `/router off` → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/model-router.py" --disable`
- `/router status` → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/model-router.py" --status`

## What to tell the user (keep it honest)

- **Default ON.** SessionStart runs `model-router.py --session-start` and arms base routing every session.
- SIMPLE + self-contained → Claude **must** spawn a Haiku Agent and return that answer. Context-bound SIMPLE stays on the session model (one-line why).
- The primary session model NEVER changes. Claude Code has no per-turn model swap (`/model` only). LiteLLM is not wired yet — do not claim it is.
- `/router off` opts out until the **next** SessionStart, which turns it ON again.
- LOCAL_ONLY (secrets) still blocks cloud subagents either way.
- State: `.raven/.router-state.json`.
