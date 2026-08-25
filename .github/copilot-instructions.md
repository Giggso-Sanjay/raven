# Raven — GitHub Copilot / VS Code

## First load (same UX every IDE)

1. `python3 scripts/ops/raven-first.py --boot` — print host/rules/memory/load/educate/route/expected_route/first_load
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --boot`
2. If `load=1`, Read only the `memory=` card
3. `python3 scripts/ops/raven-first.py --session-start` (version, host, rules, educate, expected SIMPLE/MEDIUM/COMPLEX)
4. Every user prompt: run `python3 scripts/ops/raven-first.py --prompt "<message>"` first
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --prompt "<message>"`

Do **not** lead with `bash scripts/raven-python.sh` as the only path.

Print `🔀 Router`, `💰`, `educate=`, `expected=`, then `session=` and `Intent: plan|debug|direct`.

Educate guided: briefing (WHAT/HOW/files) then wait for go ahead before any write.
