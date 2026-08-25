# AntiGravity — same contract as Codex/Grok (`AGENTS.md`). Not optional.
# Also honor AGENTS.override.md. First tools: raven-first --boot then --session-start then every-turn --prompt. No skip.

## First load (same UX every IDE)

1. `python3 scripts/ops/raven-first.py --boot` — print `host=` `rules=` `memory=` `load=` `educate=` `route=` `expected_route=` `first_load=`
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --boot`
2. If `load=1`, Read **only** the `memory=` card
3. `python3 scripts/ops/raven-first.py --session-start` — print banner
4. Dashboard later: `python3 scripts/ops/raven-first.py --boot` with open, or `ide-boot.py --open`

**FORCE — every user turn, before any other tool or prose.**

1. Run (raven-first copies the engine into this app repo if missing — do **not** lead with `bash scripts/raven-python.sh` alone):
   ```
   python3 scripts/ops/raven-first.py --prompt "<full user message>"
   ```
   Fallback: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ops/raven-first.py" --prompt "<full user message>"`
2. Print the script stdout **first**, unedited:
   - Line 1 `🔀 Router · host=antigravity · …`
   - Line 2 `💰 total-cost= last_turn= est=`
   - Line 3 `educate=` and `expected=`
3. Then `session=<the model writing this>` (e.g. Gemini 3.1 Pro). Never print `anthropic/claude-*` as session.
4. Then `Intent: plan|debug|direct — {why}`
5. Then work. Empty dashboard Logs = you skipped. No exemptions (git status, “quick X”, “hooks.json”).

Do **not** invent architecture (injectSteps vs Claude hooks) to cover a failed shell. If the command fails, switch interpreter or say the stderr. `/usr/bin/python3` is the fallback if the wrapper is missing.

Recommend tiers come from `.raven/boot.json` host `antigravity` (`gemini-flash` / `gemini-pro`). Never apply Claude model ids on this host.

`applied=true` only if this session model already matches `recommend`, or you actually switched/spawned to it.
