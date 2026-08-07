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

- Router ON means: prompts Raven classifies as SIMPLE arrive with an advisory note asking Claude to consider delegating to a Haiku subagent via the Agent tool — only when the question is fully self-contained (no conversation context, no file reads, no tool calls needed).
- The primary session model NEVER changes. Claude Code has no per-turn model swap; the session model is set only via `/model`. Never claim the router reroutes the main conversation.
- Router OFF (the default) means: no delegation nudges, everything runs on the session's default model. The secrets guard (LOCAL_ONLY warning) stays active either way.
- The mode persists in `.raven/.router-state.json` until toggled again.
