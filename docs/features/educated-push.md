# Educated Push

**Status:** shipped · advisory — it reminds, it never blocks
**Scripts:** `scripts/push-gate.py` (PreToolUse) · `scripts/push-approve.py` (UserPromptSubmit)
**Written per** `CLAUDE.md` Rule A. Every claim below is verified against the code on disk.

---

## 1. What & why

AI writes code faster than a human can read it. Educated Push inserts a deliberate pause: Claude
explains what it is about to do **before** touching anything, and summarises what it did
**after**. "Push" is pushing changes into your codebase; "educated" is that you are told what is
coming, in plain words, first.

The loop:

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
5. RESET        any later message that is not an approval clears the flag.
```

### It is taught, not enforced

`push-gate.py` shows **one reminder** on the first mutating action of a session, then stays silent.
It always returns `allow`. Whether the briefing actually appears depends on Claude choosing to write
it — **no hook can compel that.** Observed in live sessions: often it doesn't.

That is the design, by decision (2026-08-07): *"educated is educational — it should not block."*

An opt-in `guided` mode that denied until approval was added and then **removed at the user's
request** (2026-08-13). It was never asked for, it reversed a decision made deliberately after
`c8c5c2e`'s hard gate blocked its own diagnostics, and it produced two bugs of its own that existed
only because a second mode existed. See `bug-fix-log.md` BUG-023.

**If you want the loop enforced, this feature will not do it** — that needs a deny path, which was
tried (`c8c5c2e`), reverted (`bb40ee0`), re-added as opt-in (BUG-023), and removed again.

---

## 2. Entry points

| Entry point | Effect |
|---|---|
| First mutating tool call of a session | `push-gate.py` emits the reminder, allows |
| `go ahead` / `approved` / `GO` / `proceed` / `ship it` / `lgtm` / `do it` / `yes` / `Lucky` | Records the approval in `.raven/.push-approved` |
| Any other message | **Removes** `.raven/.push-approved` (`push-approve.py:83`) |
| `python3 scripts/push-gate.py --reset` | Clears all session markers. Called by `SessionStart`. |

`guided` and `auto` no longer do anything — a test asserts they no longer write `.push-mode`.

---

## 3. Hooks

| Event | Matcher | Script | Sync | Timeout | Exit code |
|---|---|---|---|---|---|
| `PreToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | `push-gate.py` | sync | 5s | **always 0** |
| `UserPromptSubmit` | `*` | `push-approve.py` | sync | 5s | **always 0** |
| `SessionStart` | `*` | `push-gate.py --reset` | sync | 5s | **always 0** |

Both scripts exit 0 unconditionally and carry their decision in
`hookSpecificOutput.permissionDecision` — a non-zero exit on `UserPromptSubmit` can lock you out of
your own tool (`e70c971`), so both wrap `main()` in a bare `except` that still exits 0.

All hook commands are prefixed `PYTHONUTF8=1` (BUG-017), and both scripts also carry an in-script
`reconfigure()` guard for when they are run by hand (BUG-029).

---

## 4. Trigger conditions

An action counts as **mutating** when:

- `tool_name` is `Write`, `Edit`, `MultiEdit`, or `NotebookEdit`; or
- `tool_name` is `Bash` and `bash_is_read_only()` returns False.

`bash_is_read_only()` requires **every** segment of a compound command (split on `&&`, `||`, `;`,
`|`) to be read-only:

- head in `READ_ONLY_HEADS` — `ls cat head tail grep rg find wc pwd which file stat tree du echo env
  uname date diff sort uniq cut column basename dirname`
- for `git`, subcommand in `READ_ONLY_GIT_SUBCOMMANDS` — `status log diff show branch remote
  rev-parse ls-files blame shortlog describe tag`
- any remaining `<` or `>` after stripping `2>` / `2>>` means a write

**`2>` and `2>>` are NOT writes.** Silencing stderr is not mutation; `c8c5c2e`'s `[><]` regex counted
`ls foo 2>/dev/null` as a write and made its allowlist useless.

The reminder does not fire when: the action is read-only, it is not a mutating tool, or
`.push-notice-shown` already exists.

---

## 5. Flow

1. `main()` — `--reset` short-circuits before stdin is read
2. Payload parsed; mutation determined
3. Not mutating, or the marker already exists → `sys.exit(0)`, silent
4. Otherwise: marker written, then `_emit("allow", …, NOTICE)` — reminder shown, action proceeds

There is no branch that denies. `tests/test_push_gate_advisory.py::test_never_denies` fails if one
reappears.

---

## 6. Files touched

| Path | Written by | Gitignored |
|---|---|---|
| `.raven/.push-notice-shown` | `push-gate.py` | yes |
| `.raven/.push-approved` | `push-approve.py` | yes |
| `.raven/.model-disclosed` | `model-router.py` (reset here for one entry point) | yes |

`reset_markers()` also clears `.push-mode`, so a leftover `guided` flag from the removed feature
cannot linger.

---

## 7. Config & state

| Item | Value |
|---|---|
| Root resolution | `CLAUDE_PROJECT_DIR`, else walk up to `.git` — never bare `cwd` (BUG-022 put markers in the wrong project) |
| Reset owner | `push-gate.py --reset`, called by `SessionStart` — one resolver for both write and wipe |
| Approval lifetime | Until the next non-approval message. **No TTL** — nothing reads the flag, so nothing expires it |

### ⚠️ `.push-approved` has no readers

The gate always allows, so the flag is a **record of consent, not a key**. `CLAUDE.md` claimed the
go-ahead "opens the write gate" — there has been no write gate since `bb40ee0`; the wording was
corrected rather than reinstated.

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
| Script missing from `scripts/` | `\|\| true` swallows it and the gate silently no-ops — this shipped for months (BUG-019). Gate 6 now asserts existence |
| Non-ASCII output on a legacy Windows console | Confirmations were silently swallowed while the flag was still written (BUG-024). Fixed twice over: hook prefix + in-script guard |
| Stale `.push-mode` from the removed guided mode | Ignored, and cleared at the next reset |

---

## 9. How to verify

```bash
# advisory: reminder once, then silent, never denied
rm -f .raven/.push-notice-shown
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: permissionDecision "allow" + the reminder
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: nothing

# read-only Bash never triggers it
echo '{"tool_name":"Bash","tool_input":{"command":"cat app.py 2>/dev/null"}}' | python3 scripts/push-gate.py
# expect: nothing

# approval is recorded, then cleared
echo '{"prompt":"go ahead","session_id":"s1"}' | python3 scripts/push-approve.py
ls -a .raven/ | grep push-approved
echo '{"prompt":"now add tests","session_id":"s1"}' | python3 scripts/push-approve.py
ls -a .raven/ | grep push-approved      # expect: gone

python3 scripts/push-gate.py --reset
ls -a .raven/ | grep -E 'push-|model-disclosed'   # expect: nothing
```

### The break-it step (Rule C)

```bash
mv scripts/push-gate.py /tmp/ && python3 scripts/check-distribution-coverage.py
# expect FAIL: "push-gate.py is wired but scripts/push-gate.py does not exist"
mv /tmp/push-gate.py scripts/ && python3 scripts/check-distribution-coverage.py   # PASS
```

Automated: `tests/test_push_gate_advisory.py` (8) · `tests/test_push_gate_root.py` (6).

---

## 10. Known limits

- **It cannot make the loop happen.** It prints a reminder and allows. Across three live sessions
  Claude received the reminder and skipped the briefing anyway. If that matters to you, this is not
  the mechanism — and the two attempts at a deny path were both withdrawn.
- **The word budgets are unenforceable.** ≤200 / ≤150 are Claude's discipline; no hook can measure
  them.
- **The approval is not scoped.** `.push-approved` records that you said yes, not *what* you said yes
  to, and nothing consumes it.
- **Bash detection is allowlist-based on the command head**, not its arguments — so `find … -delete`
  passes.
- **One reminder per session, per project root.** A session spanning two repos gets one per root.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
