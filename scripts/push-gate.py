#!/usr/bin/env python3
"""push-gate.py — PreToolUse hook for the Educated Push Contract (advisory).

Educational, never blocking: the first mutating action of a session surfaces a
one-time reminder of the briefing loop (what/how/files -> go-ahead -> confirm),
then the gate stays silent. It NEVER denies a tool call — the contract is taught,
not enforced (user decision 2026-08-07: "educated is educational — it should not
block anything").

An opt-in `guided` mode that denied until approval was added and then removed at
the user's request (2026-08-13). Reasons recorded in bug-fix-log.md BUG-023: it
was never asked for, it reversed a decision made deliberately after c8c5c2e's
hard gate blocked its own diagnostics, and it produced two bugs of its own
(BUG-024, BUG-025) that existed only because a second mode existed. Removing the
deny path removes those failure modes with it.

Markers live in .raven/ (.push-notice-shown, and .model-disclosed for the model
router) and are cleared by `push-gate.py --reset`, which SessionStart calls.
Fail-soft: any internal error exits 0, so a broken gate can never brick a session.
"""

import json
import os
import re
import sys

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

NOTICE = (
    "🪶 Educated Push (advisory): for non-trivial changes, Raven's loop is — "
    "briefing (WHAT/HOW/files, ≤200 words) → your go-ahead → execute → "
    "confirmation (≤150 words). This is a reminder, not a block; the action "
    "is proceeding. Shown once per session."
)


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

    if not mutating or os.path.exists(marker_path()):
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
