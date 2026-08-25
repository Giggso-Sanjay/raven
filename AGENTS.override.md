# RAVEN — first tools every turn. Not optional. Not “greeting later.”

A reply without `🔀 Router` as the first line is a defect. Do not substitute
`Raven: routed ->` or a “what can you do” banner.

## First load (same UX every IDE)

```
python3 scripts/ops/raven-first.py --boot
```

Fallback if that path is missing (plugin installed, app repo empty):

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --boot
```

Print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`.
If `load=1`, Read **only** the `memory=` card. That is the vault card. Then:

```
python3 scripts/ops/raven-first.py --session-start
```

Print that banner (version, host, rules, educate, expected tiers). Then load `rules=` (this file / `AGENTS.md` / `CLAUDE.md`).

## Every user message, before any other tool

```
python3 scripts/ops/raven-first.py --prompt "<full user text>"
```

Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --prompt "<full user text>"`.

Do **not** lead with `bash scripts/raven-python.sh` as the only path — public
app repos often lack that wrapper until raven-first copies the engine in.

Print that stdout first (`🔀` `💰` `educate=` `expected=`). Then `session=` and `Intent:`.

## Educate

If `educate=guided`: briefing (WHAT/HOW/files) then STOP. No writes until go ahead.

## Turn end

```
python3 scripts/ops/raven-first.py --end
```

Empty dashboard Logs = you skipped the router. There is no “direct path.”
