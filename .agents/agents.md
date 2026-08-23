# AntiGravity — same contract as Codex/Grok (`AGENTS.md`). Not optional.

**FORCE — every user turn, before any other tool or prose.**

1. Run (this wrapper, **not** bare `python3` — Anaconda on this machine crashes `encodings`):
   ```
   bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "<full user message>"
   ```
2. Print the script stdout **first**, unedited:
   - Line 1 `🔀 Router · host=antigravity · …`
   - Line 2 `💰 total-cost= last_turn= est=`
   - Line 3 `educate=` and `expected=`
3. Then `session=<the model writing this>` (e.g. Gemini 3.1 Pro). Never print `anthropic/claude-*` as session.
4. Then `Intent: plan|debug|direct — {why}`
   First load: also `bash scripts/raven-python.sh scripts/routing/model-router.py --session-start` and print that banner.
5. Then work. Empty dashboard Logs = you skipped. No exemptions (git status, “quick X”, “hooks.json”).

Do **not** invent architecture (injectSteps vs Claude hooks) to cover a failed shell. If the command fails, switch interpreter or say the stderr. `/usr/bin/python3` is the fallback if the wrapper is missing.

Recommend tiers come from `.raven/boot.json` host `antigravity` (`gemini-flash` / `gemini-pro`). Never apply Claude model ids on this host.

`applied=true` only if this session model already matches `recommend`, or you actually switched/spawned to it.

First load: `bash scripts/raven-python.sh scripts/memory/ide-boot.py`  
Dashboard: `bash scripts/raven-python.sh scripts/memory/ide-boot.py --open`  
Turn end: `bash scripts/raven-python.sh scripts/session/cost_calc.py --end`

Educate guided until `go ahead`. Briefing then STOP — no mutating tools before approval. Lucky / `educate off` persist in `.raven/educate.json`.
