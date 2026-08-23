# Gemini CLI / Code Assist — Raven first-load + every-turn router

## First load (same UX every IDE)

1. `python3 scripts/memory/ide-boot.py` — print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/routing/model-router.py --session-start` — print banner
4. Every later turn before any reply: `python3 scripts/routing/model-router.py --prompt "<message>"`

Print 🔀, 💰, educate=, expected=, session=, Intent:. **raven dashboard** → `ide-boot.py --open`. Educate guided: briefing then STOP until go-ahead.
