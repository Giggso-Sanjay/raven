# Educated Push

**Status:** shipped · **two modes** — advisory (default) or enforced, switched by `/educate`
**Scripts:** `scripts/push-gate.py` (PreToolUse) · `scripts/push-approve.py` (UserPromptSubmit) · `scripts/educate.py` (behind the `/educate` skill)
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

### Two modes

| Mode | Set with | Behaviour |
|---|---|---|
| **advisory** (default) | `/educate advisory mode` | First change of each **turn** prints a reminder of the loop, then proceeds. Never blocks. |
| **enforced** | `/educate enforced mode` | Every mutation is **denied** until a go-ahead is recorded. Approval holds 1 hour, or until the next non-approval message. |

**Each mode names the way out of it.** Advisory's reminder ends with *"Want it required? Run /educate
enforced mode."*; the deny ends with *"To stop requiring approval: /educate advisory mode."* Both
earlier attempts lacked this, and it is the main reason the previous opt-in mode went unused —
nobody knew it was there.

The mode lives in `.raven/.push-mode` and is **per project**: it survives SessionStart, deliberately
excluded from `reset_markers()`. The approval is not persistent. Absent, unreadable, or any
unrecognised value means advisory — a typo must fail toward the less surprising behaviour.

### Why a skill, not a magic word

The switch used to be prose matched by a regex inside `push-approve.py`, and it broke twice:

- **BUG-025** — `turn on enforcement: guided` matched nothing. The mode silently stayed put and the
  instruction was read as an unrelated task, sending Claude hunting through `mcp-policy.json`.
- **BUG-024** — `guided` *did* match and wrote the flag, but the confirmation was swallowed by a
  legacy console codepage. The feature worked and looked dead.

`/educate` has neither failure mode: explicit, discoverable by typing `/`, no natural-language
guessing. Same shape as `/router` → `model-router.py`.

### Scope: only edits are gated

`Write`, `Edit`, `MultiEdit`, `NotebookEdit`. **Bash is not in the matcher**, and its read-only
classifier was deleted rather than fixed.

That classifier split commands on `|` and `>` without respecting quotes, so a genuine read was
denied:

```
grep -oE "(allow|deny)" f     ->  classified as MUTATING  ->  DENIED
```

Observed live on 2026-08-13, blocking real research. **A read cannot be wrongly blocked by a gate
that never inspects reads** — deleting the classifier is a stronger guarantee than patching it, and
it removes the whole failure class.

**Known hole, accepted:** `echo x > f` and `sed -i` are no longer gated. Claude mutates through
`Edit`/`Write`; the alternative was keeping a classifier that had already misfired twice.

### It cannot trap you

Always allowed, in either mode, each pinned by a test:

| Always allowed | Why |
|---|---|
| `.raven/` paths — relative **or** absolute | the state you would edit to disable the gate |
| `push-gate.py` / `push-approve.py` | the Edit `c8c5c2e` blocked, which is what killed it |
| everything that is not an edit tool | reads, searches, Bash |

**Escape hatch:** `Lucky` counts as an approval. **Fail-open:** unparseable input or any internal
error allows rather than denies. A mutating tool with no `tool_input` is still gated — treating a
sparse payload as harmless would be a hole.

### History

| | |
|---|---|
| `c8c5c2e` | hard gate. Reverted one commit later — denied its own `--status` probes, counted `2>/dev/null` as a write, and blocked the very Edit needed to fix it |
| `bb40ee0` | advisory only ("educated is educational — it should not block") |
| BUG-023 | opt-in `guided` mode → removed → enforced-by-default → **both modes** |

Four positions in three days. What settled it was separating the *mechanism* (a hook can only allow
or deny) from the *choice* (which the user makes, per project, through a discoverable command).

---

## 2. Entry points

| Entry point | Effect |
|---|---|
| `/educate` or `/educate status` | Shows the current mode |
| `/educate advisory mode` | Sets advisory (also `advisory`, `advise`, `off`) |
| `/educate enforced mode` | Sets enforced (also `enforced`, `enforce`, `on`) |
| Any edit tool call | `push-gate.py` — reminder (advisory) or deny-unless-approved (enforced) |
| `go ahead` / `approved` / `GO` / `proceed` / `ship it` / `lgtm` / `do it` / `yes` / `Lucky` | Records the approval in `.raven/.push-approved` |
| Any other message | **Removes** `.raven/.push-approved`, and re-arms the per-turn reminder |
| `python3 scripts/push-gate.py --reset` | Clears approval + turn marker. Called by `SessionStart`. **Does not clear the mode.** |

---

## 3. Hooks

| Event | Matcher | Script | Sync | Timeout | Exit code |
|---|---|---|---|---|---|
| `PreToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit` | `push-gate.py` | sync | 5s | **always 0** |
| `UserPromptSubmit` | `*` | `push-approve.py` | sync | 5s | **always 0** |
| `SessionStart` | `*` | `push-gate.py --reset` | sync | 5s | **always 0** |

**Deny is not signalled by the exit code.** Both scripts exit 0 unconditionally and carry the
decision in `hookSpecificOutput.permissionDecision` — a non-zero exit on `UserPromptSubmit` can lock
you out of your own tool (`e70c971`), so both wrap `main()` in a bare `except` that still exits 0.

`/educate` is a **skill**, not a hook — it cannot intercept anything. Enforcement must live in a
hook, because only a hook can deny a tool call.

All hook commands are prefixed `PYTHONUTF8=1` (BUG-017); all three scripts also carry an in-script
`reconfigure()` guard for when they run by hand or from a skill (BUG-029).

---

## 4. Trigger conditions

The gate acts when `tool_name` is `Write`, `Edit`, `MultiEdit`, or `NotebookEdit`.

Nothing else reaches it — the matcher excludes Bash, and `main()` re-checks the tool name anyway so
the script stays correct if someone re-adds Bash to the matcher without resurrecting the quote-blind
classifier.

Within that scope, nothing is denied when the path is self-exempt (§1), the mode is advisory, or a
fresh approval exists.

**Per-turn mechanics:** `push-approve.py` runs on every prompt and deletes `.push-notice-shown`, so
the next mutation in that turn shows the reminder exactly once — however many files it touches. A
multi-file refactor gets one line, not twelve. No clock and no session id involved.

---

## 5. Flow

1. `main()` — `--reset` short-circuits before stdin is read
2. Payload parsed; `mutating` = tool is an edit tool
3. Not mutating **or** `is_self_exempt()` → `sys.exit(0)`, silent
4. `session_mode() == "enforced"` → deny unless `approval_is_fresh()`; then exit
5. Advisory: `.push-notice-shown` exists → silent; otherwise write it and emit the reminder + allow

---

## 6. Files touched

| Path | Written by | Cleared at SessionStart |
|---|---|---|
| `.raven/.push-mode` | `educate.py` | **No** — per project, by decision |
| `.raven/.push-approved` | `push-approve.py` | Yes |
| `.raven/.push-notice-shown` | `push-gate.py` (cleared each turn by `push-approve.py`) | Yes |
| `.raven/.model-disclosed` | `model-router.py` (reset here for one entry point) | Yes |

All are gitignored.

---

## 7. Config & state

| Item | Value |
|---|---|
| `APPROVAL_TTL_SECONDS` | `3600` — approval expires after 1 hour regardless of activity |
| Approval lifetime | The TTL, **or** the next non-approval message, whichever comes first |
| Mode default | `advisory` — including when the file is absent, unreadable, or holds an unrecognised value |
| Root resolution | `CLAUDE_PROJECT_DIR`, else walk up to `.git` — never bare `cwd` |
| Reset owner | `push-gate.py --reset`, called by `SessionStart` |

### ⚠️ Root anchoring is security-relevant

Both `.push-mode` and `.push-approved` decide whether edits are blocked, so state in the wrong
directory means enforcement applies to the wrong project — or an approval becomes invisible and every
edit stays denied. BUG-022 was exactly that (a bare `cwd` fallback);
`tests/test_push_gate_root.py` pins both directions, and
`test_mode_does_not_leak_between_projects` covers the mode.

### ⚠️ Approval cleanup lives ONLY in `push-approve.py`

Never add a `Stop`-hook `rm` for `.push-approved`. `Stop` hooks execute at **next-prompt
submission**, so such an `rm` races the approval write and deletes fresh approvals — verified
2026-08-07, it deadlocked the session.

---

## 8. Failure modes

| Condition | Behaviour |
|---|---|
| Unparseable hook input | Exits 0 **without denying** — fails open |
| Any internal exception | Exits 0 without denying |
| Mutating tool with no `tool_input` | **Still gated** in enforced mode |
| Unrecognised value in `.push-mode` | Treated as advisory |
| `.raven/` unwritable, advisory mode | Reminder may repeat each edit; nothing is blocked |
| `.raven/` unwritable, enforced mode | Approval cannot be recorded, so edits stay denied. Use `Lucky`, or fix permissions — editing `.raven/` is self-exempt |
| Script missing from `scripts/` | `\|\| true` swallows it and the gate no-ops, i.e. **fails open** (BUG-019 shipped that way for months). Gate 6 now asserts existence |
| Non-ASCII output on a legacy Windows console | Confirmations were silently swallowed while state was still written (BUG-024/029). Fixed twice over: hook prefix + in-script guard |

---

## 9. How to verify

```bash
# default is advisory, one reminder per turn
python3 scripts/educate.py --status
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: allow + reminder naming /educate enforced mode
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: nothing (same turn)
echo '{"prompt":"anything","session_id":"s1"}' | python3 scripts/push-approve.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: allow + reminder again (new turn)

# enforced
python3 scripts/educate.py --enforced
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: deny, naming /educate advisory mode
echo '{"prompt":"go ahead","session_id":"s1"}' | python3 scripts/push-approve.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
# expect: nothing (allowed)

# never gated, either mode
echo '{"tool_name":"Bash","tool_input":{"command":"grep -oE \"(allow|deny)\" f"}}' | python3 scripts/push-gate.py
echo '{"tool_name":"Read","tool_input":{"file_path":"app.py"}}' | python3 scripts/push-gate.py
echo '{"tool_name":"Edit","tool_input":{"file_path":"scripts/push-gate.py"}}' | python3 scripts/push-gate.py
# expect: nothing for all three

python3 scripts/educate.py --advisory      # back to the default
```

### The break-it step (Rule C)

```
python3 -m pytest tests/test_push_gate_modes.py -q        -> 17 passed
remove is_self_exempt from main(), re-run:
  FAILED test_the_gate_can_always_be_repaired_in_enforced
restore -> 17 passed
```

Automated: `tests/test_push_gate_modes.py` (17) · `tests/test_push_gate_root.py` (5).

---

## 10. Known limits

- **Advisory cannot make the loop happen.** It prints a reminder and allows. Across several sessions
  Claude received it and skipped the briefing anyway. If you want the pause, use enforced mode —
  that is the whole reason both exist.
- **The word budgets are unenforceable.** ≤200 / ≤150 are Claude's discipline; a deny compels a
  *stop*, not a word count.
- **The approval is not scoped to a briefing.** `.push-approved` records that you said yes, not
  *what* you said yes to — within the hour it covers whatever comes next.
- **Bash mutations are not gated.** `echo x > f`, `sed -i`, `mv`, `rm` all pass. Deliberate: see §1.
- **1 hour is a long time.** Within the TTL, later edits are allowed with no further prompting unless
  you send a non-approval message.
- **The mode is sticky.** Set enforced in a project and it stays until changed — including weeks
  later, in a session where you have forgotten. `/educate status` tells you.
- **Fails open by design.** A crash, a missing script, or unparseable input allows rather than
  blocks.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
