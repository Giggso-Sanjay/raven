# RAVEN — first tools every turn. Not optional. Not “greeting later.”

A reply without `🔀 Router` as the first line is a defect. Do not substitute
`Raven: routed ->` or a “what can you do” banner.

## Every user message, before any other tool

```
bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<full user text>"
```

Print that stdout first (`🔀` `💰` `educate=` `expected=`). Then `session=` and `Intent:`.

## First load this session

```
bash scripts/raven-python.sh scripts/memory/ide-boot.py
bash scripts/raven-python.sh scripts/routing/model-router.py --session-start
```

If `load=1`, Read **only** the `memory=` card. That is the vault card. Then load `rules=` (this file / `AGENTS.md` / `CLAUDE.md`).

## Educate

If `educate=guided`: briefing (WHAT/HOW/files) then STOP. No writes until go ahead.

## Turn end

```
bash scripts/raven-python.sh scripts/session/cost_calc.py --end
```

Empty dashboard Logs = you skipped the router. There is no “direct path.”
