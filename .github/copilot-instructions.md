# Raven — GitHub Copilot / VS Code

Every user prompt: run `bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<message>"` first. Print `🔀 Router`, `💰`, `educate=`, `expected=`, then `session=` and `Intent: plan|debug|direct`.

Session start: `python3 scripts/routing/model-router.py --session-start` (version, host, expected SIMPLE/MEDIUM/COMPLEX).

Educate guided: briefing (WHAT/HOW/files) then wait for go ahead before any write.
