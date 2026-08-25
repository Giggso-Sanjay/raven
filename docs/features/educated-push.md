# Educated Push

**Status:** shipped · advisory by default, enforced on request
**Scripts:** `scripts/push-gate.py` · `scripts/push-approve.py`
**Written per** `CLAUDE.md` Rule A. Every claim below is verified against the code on disk.

---

## 1. What & why

AI writes code faster than a human can read it. Educated Push inserts a deliberate pause: Claude
explains what it is about to do **before** touching anything, and summarises what it did
**after**. "Push" is pushing changes into your codebase; "educated" is that you are told what is
coming, in plain words, first.

The loop it teaches:

```
1. BRIEFING     WHAT will be done, HOW it works, WHAT changes
                (files, db, config).  ≤200 words, bullets.  Then STOP.
   ↓
2. GO-AHEAD     you reply "go ahead" / "approved" / "GO" / "proceed"
   ↓
3. EXECUTE      exactly what the briefing said. No scope creep.
   ↓
4. CONFIRM      what was done + which files changed.  ≤150 words, bullets.
   ↓
5. RESET        any later message that is not an approval clears the flag,
                so the next change needs a fresh briefing.
```

The word limits are the mechanism, not decoration — they force a summary that gets read instead of
a wall of text that gets skipped.

### Two modes

| Mode | How to set | Behaviour |
|---|---|---|
| **auto / unset** (default) | nothing to do | One-time reminder on the first mutating action, then silent. **Never denies.** |
| **guided** (opt-in) | say `guided` | Mutations **denied** until you approve. Approval expires after 1 hour. Say `auto` to leave. |

**Advisory is the default by explicit decision** (2026-08-07): *"educated is educational — it
should not block."* Guided mode exists because in live testing the reminder alone was ignored three
sessions running — an injected instruction is a suggestion, and only a deny can compel a pause.

---

## 2. Entry points

| Entry point | What it does |
|---|---|
| Typing `guided` (or `guided mode`, `enable guided`, `turn on enforcement: guided`, `switch to guided mode`, `activate guided`) | Sets `.raven/.push-mode` = `guided` |
| Typing `auto` (or `auto mode`, `switch to auto`, `Lucky`) | Sets `.raven/.push-mode` = `auto` |
| Typing `go ahead` / `approved` / `GO` / `proceed` / `ship it` / `lgtm` / `do it` / `yes` | Writes `.raven/.push-approved` |
| Any other message | **Removes** `.raven/.push-approved` (`push-approve.py:110`) |
| First mutating tool call of a session | `push-gate.py` emits the reminder (advisory) or denies (guided) |
| `python3 scripts/push-gate.py --reset` | Clears all session markers. Called by `SessionStart`. |

Mode words match: the word alone on any line, `<word> mode`, or a switch verb
(`turn on`/`enable`/`switch to`/`set`/`use`/`activate`/`go`) followed by the word within one clause.
Incidental use does **not** trigger — "write a guided tour page" and "auto-generate the docs" are
both clean.

---

## 3. Hooks

| Event | Matcher | Script | Args | Sync | Timeout | Exit code |
|---|---|---|---|---|---|---|
| `PreToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | `push-gate.py` | — | sync | 5s | **always 0** |
| `UserPromptSubmit` | `*` | `push-approve.py` | — | sync | 5s | **always 0** |
| `SessionStart` | `*` | `push-gate.py` | `--reset` | sync | 5s | **always 0** |

**Deny is not signalled by the exit code.** Both scripts exit 0 unconditionally; the decision is
carried in the JSON payload as `hookSpecificOutput.permissionDecision` (`allow` or `deny`). This is
deliberate — a non-zero exit on `UserPromptSubmit` can lock you out of your own tool (`e70c971`),
so both scripts wrap `main()` in a bare `except` that still exits 0.

---

## 4. Trigger conditions

`push-gate.py` treats an action as **mutating** when:

- `tool_name` is one of `Write`, `Edit`, `MultiEdit`, `NotebookEdit`; or
- `tool_name` is `Bash` and `bash_is_read_only()` (`:93`) returns False.

`bash_is_read_only()` requires **every** segment of a compound command (split on `&&`, `||`, `;`,
`|`) to be read-only:

- head must be in `READ_ONLY_HEADS` — `ls cat head tail grep rg find wc pwd which file stat tree du
  echo env uname date diff sort uniq cut column basename dirname`
- for `git`, the subcommand must be in `READ_ONLY_GIT_SUBCOMMANDS` — `status log diff show branch
  remote rev-parse ls-files blame shortlog describe tag`
- any remaining `<` or `>` after stripping `2>` / `2>>` means a write

**`2>` and `2>>` are NOT writes.** Silencing stderr is not mutation; the original `[><]` regex
counted `ls foo 2>/dev/null` as a write and made the allowlist useless.

### It does not trigger when

| Condition | Why |
|---|---|
| Read-only Bash | research must never be gated |
| Reads (`Read`, `Grep`, `Glob`, …) | not in the mutating set |
| The reminder already fired this session | `.push-notice-shown` exists |
| **Self-exemption** (`is_self_exempt()`, `:155`) | see below |

### Self-exemption — the gate can never trap you

Always allowed, even in guided mode:

- `file_path` containing `/.raven/`, or ending in `push-gate.py` / `push-approve.py`
- Bash commands mentioning `push-gate.py`, `push-approve.py`, `--status`, or `--reset`

This is the guard the hard-enforced version (`c8c5c2e`) lacked: it denied its own `--status` probes
and blocked the very Edit needed to fix it. **A gate that can trap you is worse than no gate.**

---

## 5. Flow

### Advisory (default)

1. `push-gate.py:185` `main()` — `--reset` short-circuits before stdin is read
2. Payload parsed; mutation determined (`:196-199`)
3. Not mutating, or self-exempt → `sys.exit(0)`, silent (`:201`)
4. `session_mode()` (`:138`) reads `.push-mode` → not `guided`, so no deny
5. `.push-notice-shown` exists → `sys.exit(0)`, silent
6. Otherwise: marker written, then `_emit("allow", …, NOTICE)` — reminder shown, action proceeds

### Guided

1. You type `guided` → `push-approve.py:92` writes `.push-mode`, prints the 🎓 confirmation
2. You request work; Claude attempts a mutating tool call
3. `push-gate.py:203` — `session_mode() == "guided"` and `approval_is_fresh()` False → `_emit("deny", DENY_REASON)`
4. Claude posts the ≤200-word briefing and stops
5. You type `go ahead` → `push-approve.py:104` writes `.push-approved`
6. Claude retries → `approval_is_fresh()` (`:147`) True → falls through to allow
7. Claude executes, then confirms in ≤150 words
8. Your next non-approval message → `push-approve.py:110` removes `.push-approved` → gate closes again

---

## 6. Files touched

| Path | Written by | Gitignored |
|---|---|---|
| `.raven/.push-mode` | `push-approve.py:93,98` | yes (`.raven/` state) |
| `.raven/.push-approved` | `push-approve.py:104` | yes |
| `.raven/.push-notice-shown` | `push-gate.py` `main()` | yes |
| `.raven/.model-disclosed` | `model-router.py` (reset here for one entry point) | yes |

All four are cleared by `reset_markers()` (`push-gate.py:115`).

---

## 7. Config & state

| Item | Value | Notes |
|---|---|---|
| `APPROVAL_TTL_SECONDS` | `3600` (`push-gate.py:52`) | Approval expires after 1 hour regardless of activity |
| Mode source | `.raven/.push-mode` | **Only the literal `guided` enables denial.** Unset, `auto`, or any unrecognised value ⇒ advisory |
| Root resolution | `CLAUDE_PROJECT_DIR`, else walk up to `.git` (`push-gate.py:66`, `push-approve.py:58`) | Never bare `cwd` — that put markers in the wrong project (BUG-022) |
| Reset owner | `push-gate.py --reset`, called by `SessionStart` | One resolver for both write and wipe |

### ⚠️ Cleanup lives ONLY in `push-approve.py`

Never add a `Stop`-hook `rm` for `.push-approved`. `Stop` hooks execute at **next-prompt
submission**, so such an `rm` races the approval write and deletes fresh approvals — verified
2026-08-07, it deadlocked the session.

---

## 8. Failure modes

| Condition | Behaviour |
|---|---|
| Any internal exception | Both scripts exit 0 — fail soft, never brick a session |
| `.raven/` not writable | Reminder may repeat; the action still proceeds |
| Script missing from `scripts/` | `\|\| true` in the hook swallows it and the gate silently no-ops — this shipped for months (BUG-019). Gate 6 now asserts existence |
| Non-ASCII output on a legacy Windows console | Confirmations were silently swallowed while the flag was still written, so the feature worked but looked dead (BUG-024). Both scripts now `reconfigure(encoding="utf-8", errors="replace")` |
| Guided mode set but gate not enforcing | Check `.push-mode` contains exactly `guided`; anything else is advisory |
| Setting `guided` while an approval is live | An existing `.push-approved` is **not** cleared (the mode branch returns early at `:96`). The stale approval remains valid until its TTL or your next non-approval message |

---

## 9. How to verify

```bash
# --- advisory default ---
rm -f .raven/.push-mode
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: permissionDecision "allow" + the reminder, once

# --- guided ---
echo '{"prompt":"guided","session_id":"s1"}' | python3 scripts/push-approve.py
# expect: 🎓 EDUCATED PUSH: GUIDED mode set …
cat .raven/.push-mode                                    # expect: guided

echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: permissionDecision "deny"

echo '{"prompt":"go ahead","session_id":"s1"}' | python3 scripts/push-approve.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: not "deny"

# --- self-exemption must never deny ---
echo '{"tool_name":"Edit","tool_input":{"file_path":"scripts/push-gate.py"}}' | python3 scripts/push-gate.py
echo '{"tool_name":"Bash","tool_input":{"command":"cat app.py 2>/dev/null"}}' | python3 scripts/push-gate.py
# expect: silent (allow) for both

# --- reset ---
python3 scripts/push-gate.py --reset
ls -a .raven/ | grep -E 'push-|model-disclosed'          # expect: nothing
```

### The break-it step (Rule C)

```bash
mv scripts/push-gate.py /tmp/ && python3 scripts/check-distribution-coverage.py
# expect FAIL: "push-gate.py is wired but scripts/push-gate.py does not exist"
mv /tmp/push-gate.py scripts/ && python3 scripts/check-distribution-coverage.py   # expect PASS
```

Automated: `tests/test_push_gate_guided.py` (13) · `tests/test_push_gate_root.py` (6).

---

## 10. Known limits

- **Advisory mode cannot compel anything.** It prints a reminder and allows. Observed live: Claude
  received the reminder and skipped the briefing loop in three consecutive sessions. If you want
  the loop followed, use `guided`.
- **A deny forces the pause, not the word count.** The ≤200/≤150 budgets remain Claude's
  discipline; no hook can measure them.
- **Guided mode is per session.** `SessionStart` clears `.push-mode`, so it must be re-enabled each
  session — there is no persistent project-level default.
- **Approval is per turn, not per change.** Any non-approval message closes the gate, and a fresh
  approval covers whatever comes next — it is not scoped to the briefing you approved.
- **Bash detection is allowlist-based.** A mutating command whose head happens to be in
  `READ_ONLY_HEADS` (e.g. a `find … -delete`) passes. The allowlist is deliberately conservative
  about *heads*, not about arguments.
- **`Lucky` maps to `auto`**, retaining the historical opt-out keyword — user owns risk.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
