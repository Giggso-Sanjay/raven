#!/usr/bin/env python3
"""push-gate.py — PreToolUse hook for the Educated Push Contract (advisory).

Educational, never blocking: the first mutating action of a session surfaces
a one-time reminder of the briefing loop (what/how/files → go-ahead →
confirm), then the gate stays silent. It NEVER denies a tool call — the
contract is taught, not enforced (user decision 2026-08-07: "educated is
educational — it should not block anything").

The one-time marker lives at .raven/.push-notice-shown and is wiped at every
SessionStart alongside .push-mode, so each session sees the reminder once.
Fail-soft: any internal error exits 0 (never bricks the session).
"""

import json
import os
import re
import sys

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
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


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


def main() -> None:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")

    if tool == "Bash":
        command = (payload.get("tool_input") or {}).get("command", "")
        mutating = not bash_is_read_only(command)
    else:
        mutating = tool in ("Write", "Edit", "MultiEdit", "NotebookEdit")

    if not mutating or os.path.exists(marker_path()):
        sys.exit(0)

    os.makedirs(os.path.dirname(marker_path()), exist_ok=True)
    with open(marker_path(), "w") as fh:
        fh.write("shown\n")
    print(json.dumps({
        "systemMessage": NOTICE,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Educated Push is advisory — reminder shown, action allowed.",
        },
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
