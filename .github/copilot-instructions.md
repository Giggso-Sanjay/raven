# Raven — GitHub Copilot / VS Code

## First load (same UX every IDE)

1. `python3 scripts/memory/ide-boot.py` — print host/rules/memory/load/educate/route/expected_route/first_load
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/routing/model-router.py --session-start` (version, host, rules, educate, expected SIMPLE/MEDIUM/COMPLEX)
4. Every user prompt: run `bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<message>"` first

Print `🔀 Router`, `💰`, `educate=`, `expected=`, then `session=` and `Intent: plan|debug|direct`.

Educate guided: briefing (WHAT/HOW/files) then wait for go ahead before any write.
