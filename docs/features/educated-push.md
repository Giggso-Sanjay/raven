# Educated Push

**Status:** shipped · **enforced** — mutations are denied until you approve
**Scripts:** `scripts/push-gate.py` (PreToolUse) · `scripts/push-approve.py` (UserPromptSubmit)
**Written per** `CLAUDE.md` Rule A. Every claim below is verified against the code on disk.

---

## 1. What & why

AI writes code faster than a human can read it. Educated Push inserts a deliberate pause: Claude
explains what it is about to do **before** touching anything, and summarises what it did **after**.
"Push" is pushing changes into your codebase; "educated" is that you are told what is coming, in
plain words, first.

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

### It is enforced

`push-gate.py` returns **`deny`** for any mutating tool call until a go-ahead is recorded. The deny
message carries the briefing instructions, so Claude is told what to do rather than merely stopped.
Approval lasts **1 hour**, or until your next non-approval message.

This has moved three times, and the reasons are worth keeping:

| | |
|---|---|
| `c8c5c2e` | hard gate. Reverted one commit later — it denied its own `--status` probes, counted `2>/dev/null` as a write, and blocked the very Edit needed to fix it |
| `bb40ee0` | advisory only, never denies ("educated is educational — it should not block") |
| BUG-023 | opt-in `guided` mode. Removed at the user's request — never asked for, and it produced two mode-selection bugs of its own |
| **now** | **enforced by default, no modes** (2026-08-13), after advisory mode was observed being ignored on every edit across several sessions |

The advisory era's honest limit was that *nothing made the loop happen*. Enforcement is the only
mechanism that does — a reminder cannot compel, only a deny can.

### It cannot trap you

Every one of `c8c5c2e`'s failure modes is closed, and each has a test that fails if it returns:

| Always allowed | Why |
|---|---|
| `.raven/` paths — relative **or** absolute | the state you would edit to disable the gate |
| `push-gate.py` / `push-approve.py` | the Edit `c8c5c2e` blocked, which is what killed it |
| Bash carrying those names, or `--status` / `--reset` | diagnostics must never be gated |
| all read-only Bash | research for the briefing is always allowed |
| every non-mutating tool | `Read`, `Grep`, `Glob`, … |

`sed -i` is **not** in the read-only allowlist, so it is correctly gated — `c8c5c2e` let that through
while blocking probes, which is precisely backwards.

**Escape hatch:** `Lucky` is an approval keyword, so a single message opens the gate for a turn.
**Fail-open:** unparseable input exits 0 without denying. A mutating tool with no `tool_input` is
still gated — guessing "probably harmless" would be a hole a malformed payload could walk through.

---

## 2. Entry points

| Entry point | Effect |
|---|---|
| Any mutating tool call | `push-gate.py` — **denied** unless a fresh approval exists |
| `go ahead` / `approved` / `GO` / `proceed` / `ship it` / `lgtm` / `do it` / `yes` / `Lucky` | Records the approval in `.raven/.push-approved`, opening the gate for 1 hour |
| Any other message | **Removes** `.raven/.push-approved` (`push-approve.py:83`) — the next change needs a fresh briefing |
| `python3 scripts/push-gate.py --reset` | Clears all session state. Called by `SessionStart`. |

`guided` and `auto` do nothing — the modes were removed (BUG-023).

---

## 3. Hooks

| Event | Matcher | Script | Sync | Timeout | Exit code |
|---|---|---|---|---|---|
| `PreToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | `push-gate.py` | sync | 5s | **always 0** |
| `UserPromptSubmit` | `*` | `push-approve.py` | sync | 5s | **always 0** |
| `SessionStart` | `*` | `push-gate.py --reset` | sync | 5s | **always 0** |

**Deny is not signalled by the exit code.** Both scripts exit 0 unconditionally and carry the
decision in `hookSpecificOutput.permissionDecision` — a non-zero exit on `UserPromptSubmit` can lock
you out of your own tool (`e70c971`), so both wrap `main()` in a bare `except` that still exits 0.

All hook commands are prefixed `PYTHONUTF8=1` (BUG-017); both scripts also carry an in-script
`reconfigure()` guard for when they run by hand or from a skill (BUG-029).

---

## 4. Trigger conditions

An action is **mutating** when:

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

Nothing is denied when the action is read-only, is a non-mutating tool, is self-exempt (§1), or a
fresh approval exists.

---

## 5. Flow

1. `main()` — `--reset` short-circuits before stdin is read
2. Payload parsed; `mutating` determined
3. Not mutating **or** `is_self_exempt()` → `sys.exit(0)`, silent
4. `approval_is_fresh()` False → `_emit("deny", DENY_REASON)` — Claude is told to brief and wait
5. Otherwise → `sys.exit(0)`, silent: approved and inside the TTL

`tests/test_push_gate_enforced.py` pins each branch, including the two that killed `c8c5c2e`
(`test_diagnostic_probes_are_never_denied`, `test_the_gate_can_always_be_repaired`).

---

## 6. Files touched

| Path | Written by | Gitignored |
|---|---|---|
| `.raven/.push-approved` | `push-approve.py` — **this one decides allow vs deny** | yes |
| `.raven/.model-disclosed` | `model-router.py` (reset here for one entry point) | yes |
| `.raven/.push-mode`, `.raven/.push-notice-shown` | nothing — vestigial, still cleared so stale files never linger | yes |

---

## 7. Config & state

| Item | Value |
|---|---|
| `APPROVAL_TTL_SECONDS` | `3600` — approval expires after 1 hour regardless of activity |
| Approval lifetime | The TTL, **or** your next non-approval message, whichever comes first |
| Root resolution | `CLAUDE_PROJECT_DIR`, else walk up to `.git` — never bare `cwd` |
| Reset owner | `push-gate.py --reset`, called by `SessionStart` |

### ⚠️ Root anchoring is now security-relevant

`.push-approved` decides whether mutations are allowed, so if it lands in the wrong directory an
approval given in project A can open the gate in project B — or a real approval becomes invisible and
every mutation stays denied. BUG-022 was exactly that bug (a bare `cwd` fallback), and
`tests/test_push_gate_root.py` pins both directions.

### ⚠️ Cleanup lives ONLY in `push-approve.py`

Never add a `Stop`-hook `rm` for `.push-approved`. `Stop` hooks execute at **next-prompt
submission**, so such an `rm` races the approval write and deletes fresh approvals — verified
2026-08-07, it deadlocked the session.

---

## 8. Failure modes

| Condition | Behaviour |
|---|---|
| Unparseable hook input | Exits 0 **without denying** — fails open |
| Any internal exception | Exits 0 without denying. A broken gate must never brick a session |
| Mutating tool with no `tool_input` | **Still gated.** Guessing "probably harmless" would be a hole a malformed payload could walk through |
| `.raven/` not writable | Approval cannot be recorded, so mutations stay denied. Use `Lucky`, or fix permissions — editing `.raven/` is self-exempt |
| Script missing from `scripts/` | `\|\| true` swallows it and the gate silently no-ops, i.e. **fails open** (BUG-019 shipped that way for months). Gate 6 now asserts existence |
| Non-ASCII output on a legacy Windows console | Confirmations were silently swallowed while the flag was still written (BUG-024). Fixed twice over: hook prefix + in-script guard |

---

## 9. How to verify

```bash
# denied without approval
rm -f .raven/.push-approved
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: permissionDecision "deny" + briefing instructions

# approval opens it
echo '{"prompt":"go ahead","session_id":"s1"}' | python3 scripts/push-approve.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: nothing (allowed)

# a non-approval message closes it again
echo '{"prompt":"now add tests","session_id":"s1"}' | python3 scripts/push-approve.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: "deny"

# never denied — the c8c5c2e failure modes
echo '{"tool_name":"Bash","tool_input":{"command":"cat app.py 2>/dev/null"}}' | python3 scripts/push-gate.py
echo '{"tool_name":"Bash","tool_input":{"command":"python3 scripts/notify.py --status"}}' | python3 scripts/push-gate.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"scripts/push-gate.py"}}' | python3 scripts/push-gate.py
# expect: nothing for all three
```

### The break-it step (Rule C)

```
python3 -m pytest tests/test_push_gate_enforced.py -q     -> 15 passed
edit is_self_exempt out of main(), re-run:
  FAILED test_diagnostic_probes_are_never_denied
  FAILED test_the_gate_can_always_be_repaired
restore -> 15 passed
```

Automated: `tests/test_push_gate_enforced.py` (15) · `tests/test_push_gate_root.py` (5).

---

## 10. Known limits

- **The word budgets are unenforceable.** ≤200 / ≤150 are Claude's discipline; a deny can compel a
  *stop*, not a word count.
- **The approval is not scoped to a briefing.** `.push-approved` records that you said yes, not
  *what* you said yes to — a go-ahead for one change opens the gate for whatever comes next in the
  hour.
- **It gates tool calls, not intent.** Claude can still restructure a plan between briefing and
  execution; the gate only knows a mutation was attempted.
- **Bash detection is allowlist-based on the command head**, not its arguments — so `find … -delete`
  passes. Conservative about heads, not about flags.
- **1 hour is a long time.** Within the TTL, later mutations are allowed with no further prompting
  unless you send a non-approval message.
- **Fails open by design.** A crash, a missing script, or unparseable input allows rather than
  blocks. That is deliberate — a gate that bricks sessions is worse than one that occasionally lets
  something through.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
