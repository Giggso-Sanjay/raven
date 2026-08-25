#!/usr/bin/env python3
"""push-gate.py — PreToolUse hook for the Educated Push Contract.

Two modes, chosen per session. ADVISORY IS THE DEFAULT — the 2026-08-07 decision
("educated is educational — it should not block anything") still governs any
session that has not explicitly opted in.

  auto / unset (DEFAULT)  the first mutating action surfaces a one-time reminder
                          of the briefing loop, then the gate stays silent. Never
                          denies anything.
  guided (opt-in)         say "guided" and mutations are denied until you reply
                          "go ahead" / "approved" / "GO" / "proceed". The approval
                          expires after 1 hour. Say "auto" to leave guided mode.

Why guided is opt-in and not the default: the hard-enforced version (c8c5c2e) was
reverted one commit later because it blocked its own diagnostics, counted
`2>/dev/null` as a write, and blocked the very Edit needed to fix itself. Those
were allowlist bugs, not a flaw in the concept — both are fixed here, plus a
self-exemption so the gate can never lock you out of repairing it:

  * `.raven/` paths and push-gate.py / push-approve.py are always allowed
  * Bash commands touching those scripts, or carrying --status/--reset, pass
  * read-only Bash passes (2> / 2>> are not writes — the old regex said they were)

Markers live in .raven/ (.push-notice-shown, .push-mode, .push-approved) and are
cleared by `push-gate.py --reset`, which SessionStart calls. Fail-soft: any
internal error exits 0, so a broken gate can never brick a session.
"""

import json
import os
import re
import sys
import time

NOTICE = (
    "🪶 Educated Push (advisory): for non-trivial changes, Raven's loop is — "
    "briefing (WHAT/HOW/files, ≤200 words) → your go-ahead → execute → "
    "confirmation (≤150 words). This is a reminder, not a block; the action "
    "is proceeding. Shown once per session. Say 'guided' to make it enforced."
)

DENY_REASON = (
    "🎓 Educated Push — GUIDED mode. Before this change, post a briefing "
    "(≤200 words, bullets): WHAT will be done, HOW it works, WHAT changes "
    "(files, db, config). Then STOP and wait. When the user replies "
    "'go ahead' / 'approved' / 'GO' / 'proceed', the gate opens for this "
    "change; afterwards confirm in ≤150 words with the files touched. "
    "Say 'auto' to return to advisory mode."
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


def marker_path() -> str:
    return os.path.join(repo_root(), ".raven", ".push-notice-shown")


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
    for name in (".push-mode", ".push-approved", ".push-notice-shown", ".model-disclosed"):
        try:
            os.remove(os.path.join(root, ".raven", name))
        except OSError:
            pass  # absent is the normal case


def flag_path(name: str) -> str:
    return os.path.join(repo_root(), ".raven", name)


def session_mode() -> str:
    """'guided' only when explicitly chosen. Anything else means advisory."""
    try:
        with open(flag_path(".push-mode"), encoding="utf-8") as fh:
            return fh.read().strip().lower()
    except OSError:
        return ""


def approval_is_fresh() -> bool:
    path = flag_path(".push-approved")
    try:
        return (time.time() - os.path.getmtime(path)) < APPROVAL_TTL_SECONDS
    except OSError:
        return False


def is_self_exempt(tool: str, tool_input: dict) -> bool:
    """Never deny what is needed to inspect, repair, or disable the gate itself.

    c8c5c2e's fatal flaw was denying its own diagnostics and the Edit that would
    have fixed it. A gate that can trap you is worse than no gate.
    """
    path = str(tool_input.get("file_path") or "").replace("\\", "/")
    if path and ("/.raven/" in path or path.endswith(("push-gate.py", "push-approve.py"))):
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

    if session_mode() == "guided" and not approval_is_fresh():
        _emit("deny", DENY_REASON)
        sys.exit(0)

    if os.path.exists(marker_path()):
        sys.exit(0)

    os.makedirs(os.path.dirname(marker_path()), exist_ok=True)
    with open(marker_path(), "w") as fh:
        fh.write("shown\n")
    _emit("allow", "Educated Push is advisory — reminder shown, action allowed.", NOTICE)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
