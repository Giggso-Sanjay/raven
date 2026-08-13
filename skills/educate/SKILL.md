---
name: educate
description: Switch the Educated Push mode for this project. /educate advisory mode reminds but never blocks (the default). /educate enforced mode denies edits until you give a go-ahead. /educate status shows the current mode. The setting persists per project until changed.
---

# Educated Push — Mode Switch

Run the matching command and relay its printed output to the user verbatim:

- `/educate` or `/educate status` → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/educate.py" --status`
- `/educate advisory mode` (or `advisory`, `advise`, `off`) → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/educate.py" --advisory`
- `/educate enforced mode` (or `enforced`, `enforce`, `on`) → `python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/educate.py" --enforced`

If the argument does not clearly match one of those, run `--status` and show the
user the two options rather than guessing.

## What to tell the user (keep it honest)

- **advisory** (the default, and what you get when no mode has ever been set): the
  first change of each turn prints a reminder of the briefing loop, then the edit
  proceeds. Nothing is ever blocked. Whether Claude actually writes the briefing is
  Claude's discipline — a reminder cannot compel it.
- **enforced**: every `Write` / `Edit` / `MultiEdit` / `NotebookEdit` is **denied**
  until the user replies `go ahead` / `approved` / `GO` / `proceed`. The approval
  then holds for 1 hour, or until the user's next non-approval message.
- The mode is **per project** and persists across sessions — it is not reset at
  SessionStart. The approval is not: that clears every session.
- Only edit tools are gated. Reads, searches and Bash are never blocked, in either
  mode. Say so if the user worries about being locked out of research.
- Escape hatch: `Lucky` counts as an approval, so one message opens the gate for a
  turn even in enforced mode.
- Never claim the mode blocks reads, or that advisory guarantees a briefing.

## State

`.raven/.push-mode` — the literal string `advisory` or `enforced`. Absent,
unreadable, or any unrecognised value means advisory, so a typo fails toward the
less surprising behaviour.
