# Windsurf — Raven first-load + every-turn router

## First load (same UX every IDE)

1. `python3 scripts/ops/raven-first.py --boot` — print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --boot`
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/ops/raven-first.py --session-start` — print banner (rules + educate + expected tiers)
4. Every later turn before any reply: `python3 scripts/ops/raven-first.py --prompt "<message>"`
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --prompt "<message>"`

Do **not** lead with `bash scripts/raven-python.sh` as the only path.

Print 🔀, 💰, educate=, expected=, session=, Intent:. **raven dashboard** → `ide-boot.py --open`. Educate guided: briefing then STOP until go-ahead.
