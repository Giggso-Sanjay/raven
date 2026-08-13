#!/usr/bin/env python3
"""push-gate.py — PreToolUse hook for the Educated Push Contract (ENFORCED).

Mutating tool calls are DENIED until the user gives a go-ahead. The briefing loop
is the contract: briefing (WHAT/HOW/files, <=200 words) -> user go-ahead ->
execute -> confirmation (<=150 words).

History, because this has moved three times and the reasons matter:
  c8c5c2e  hard gate. Reverted one commit later — it denied its own --status
           probes, counted `2>/dev/null` as a write, and blocked the very Edit
           needed to fix it.
  bb40ee0  advisory only, never denies (user: "educated is educational").
  BUG-023  opt-in `guided` mode. Removed at the user's request: never asked for,
           and it produced two mode-selection bugs of its own.
  now      enforced BY DEFAULT, no modes (user request 2026-08-13, after watching
           advisory mode be ignored on every edit).

c8c5c2e's four failure modes are each closed, and the tests pin them:
  * is_self_exempt() — .raven/ paths, push-gate.py / push-approve.py, and Bash
    carrying those names or --status/--reset ALWAYS pass. A gate that can block
    its own repair is worse than no gate.
  * bash_is_read_only() — `2>` / `2>>` are stderr silencing, not writes.
  * read-only Bash always passes, so research is never gated.
  * `sed -i` and friends are NOT in READ_ONLY_HEADS, so they are correctly
    treated as mutating.

Escape hatch: the word `Lucky` is an approval keyword (historical opt-out), so a
single message opens the gate for a turn if the loop is in the way.

Markers live in .raven/ (.push-approved, .push-notice-shown, .model-disclosed)
and are cleared by `push-gate.py --reset`, which SessionStart calls. Fail-soft:
any internal error exits 0 — a broken gate must never brick a session, and
failing open is the right direction for that.
"""

import json
import os
import re
import sys
import time

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

DENY_REASON = (
    "🎓 Educated Push — BLOCKED until you approve. Post a briefing first "
    "(≤200 words, bullets): WHAT will be done, HOW it works, WHAT changes "
    "(files, db, config). Then STOP and wait. When the user replies "
    "'go ahead' / 'approved' / 'GO' / 'proceed', this gate opens for an hour; "
    "afterwards confirm in ≤150 words with the files touched. Read-only "
    "commands are never blocked."
)

APPROVAL_TTL_SECONDS = 3600  # CLAUDE.md: approval expires after 1 hour regardless


# Bash command heads that are always read-only research — no reminder needed.
READ_ONLY_HEADS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "pwd", "which",
    "file", "stat", "tree", "du", "echo", "env", "uname", "date", "diff",
    "sort", "uniq", "cut", "column", "basename", "dirname",
}
READ_ONLY_GIT_SUBCOMMANDS = {
    "status", "log", "diff", "show", "branch", "remote", "rev-parse",
    "ls-files", "blame", "shortlog", "describe", "tag",
}


def repo_root() -> str:
    """Resolve the project root: CLAUDE_PROJECT_DIR, else walk up to the nearest .git.

    The old `or os.getcwd()` fallback is the cwd bug class JOURNEY §8 lesson 1 was
    written about (9de4131 — the phantom guard/guard/.raven/ folder). Verified live:
    a session working in mock-endpoint wrote .push-notice-shown into a DIFFERENT
    project's .raven/, so "once per session" silently tracked the wrong directory and
    os.makedirs created a stray .raven/ tree there. Every other script in this engine
    walks to .git; this one did not.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return env_root
    d = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:  # filesystem root — no repo found
            return os.getcwd()
        d = parent


def bash_is_read_only(command: str) -> bool:
    """True only if every segment of a compound command is read-only.

    `2>` / `2>>` (stderr silencing) is NOT a write — the old pattern flagged
    `ls foo 2>/dev/null` as mutating, which made the allowlist useless.
    """
    stripped = re.sub(r"2>>?\S*", "", command)
    if re.search(r"[><]", stripped):
        return False
    for seg in re.split(r"&&|\|\||;|\|", command):
        tokens = seg.strip().split()
        if not tokens:
            continue
        head = tokens[0]
        if head == "git":
            if len(tokens) < 2 or tokens[1] not in READ_ONLY_GIT_SUBCOMMANDS:
                return False
        elif head not in READ_ONLY_HEADS:
            return False
    return True


def reset_markers() -> None:
    """Clear the per-session flags using THIS script's root resolution.

    SessionStart used a raw `rm -f "${CLAUDE_PROJECT_DIR:-.}/.raven/..."`, whose `.`
    fallback is cwd with no .git walk — a different answer from repo_root(). Write and
    wipe could therefore target different directories, leaving a stale marker that
    suppressed the reminder forever in one project while another got a stray .raven/.
    One resolver, one truth.
    """
    root = repo_root()
    # .model-disclosed belongs to model-router.py but is reset here so SessionStart
    # has a single reset entry point using one root resolver (BUG-021, BUG-022).
    # .push-mode and .push-notice-shown are vestigial (the removed guided mode and
    # the advisory-era reminder); still cleared so stale files never linger.
    for name in (".push-mode", ".push-approved", ".push-notice-shown", ".model-disclosed"):
        try:
            os.remove(os.path.join(root, ".raven", name))
        except OSError:
            pass  # absent is the normal case


def flag_path(name: str) -> str:
    return os.path.join(repo_root(), ".raven", name)


def approval_is_fresh() -> bool:
    """True while a go-ahead recorded by push-approve.py is inside its TTL."""
    try:
        return (time.time() - os.path.getmtime(flag_path(".push-approved"))) < APPROVAL_TTL_SECONDS
    except OSError:
        return False


def is_self_exempt(tool: str, tool_input: dict) -> bool:
    """Never deny what is needed to inspect, repair, or disable the gate itself.

    c8c5c2e's fatal flaw: it denied its own diagnostics and the Edit that would
    have fixed it. A gate that can trap you is worse than no gate.
    """
    path = str(tool_input.get("file_path") or "").replace("\\", "/")
    # Match .raven/ both absolute ("…/proj/.raven/x") and relative (".raven/x") —
    # checking only "/.raven/" denied a relative write to .raven/, which is exactly
    # the state a user would edit to disable the gate.
    in_raven = path.startswith(".raven/") or "/.raven/" in path
    if path and (in_raven or path.endswith(("push-gate.py", "push-approve.py"))):
        return True
    if tool == "Bash":
        command = tool_input.get("command", "")
        if any(tok in command for tok in ("push-gate.py", "push-approve.py",
                                         "--status", "--reset")):
            return True
    return False


def _emit(decision: str, reason: str, message: str = "") -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    if message:
        out["systemMessage"] = message
    print(json.dumps(out))


def main() -> None:
    if "--reset" in sys.argv:
        reset_markers()
        sys.exit(0)

    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool == "Bash":
        mutating = not bash_is_read_only(tool_input.get("command", ""))
    else:
        mutating = tool in ("Write", "Edit", "MultiEdit", "NotebookEdit")

    if not mutating or is_self_exempt(tool, tool_input):
        sys.exit(0)

    if not approval_is_fresh():
        _emit("deny", DENY_REASON)
        sys.exit(0)

    sys.exit(0)  # approved and inside the TTL — allow silently


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
