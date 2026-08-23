# VS Code / Copilot — Raven router (every turn)

## First load (same UX every IDE)

1. `python3 scripts/ops/raven-first.py --boot` — print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --boot`
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/ops/raven-first.py --session-start` — print banner
4. Every later turn before any other tool or answer:

```
python3 scripts/ops/raven-first.py --prompt "<full user message>"
```

Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --prompt "<full user message>"`.

Do **not** lead with `bash scripts/raven-python.sh` as the only path.

Print stdout first: `🔀 Router`, `💰`, `educate=`, `expected=`. Then `session=` and `Intent:`.

`educate=guided`: briefing then STOP until go ahead. No writes before that.
