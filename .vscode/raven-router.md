# VS Code / Copilot — Raven router (every turn)

Before any other tool or answer:

```
bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<full user message>"
```

Print stdout first: `🔀 Router`, `💰`, `educate=`, `expected=`. Then `session=` and `Intent:`.

First load: `python3 scripts/memory/ide-boot.py` and `python3 scripts/routing/model-router.py --session-start`.

`educate=guided`: briefing then STOP until go ahead. No writes before that.
