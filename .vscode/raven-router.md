# VS Code / Copilot — Raven router (every turn)

## First load (same UX every IDE)

1. `python3 scripts/memory/ide-boot.py` — print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/routing/model-router.py --session-start` — print banner
4. Every later turn before any other tool or answer:

```
bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<full user message>"
```

Print stdout first: `🔀 Router`, `💰`, `educate=`, `expected=`. Then `session=` and `Intent:`.

`educate=guided`: briefing then STOP until go ahead. No writes before that.
