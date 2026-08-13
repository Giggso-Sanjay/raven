#!/usr/bin/env python3
"""push-gate.py — PreToolUse hook for the Educated Push Contract.

Two modes, switched by the /educate skill and stored in .raven/.push-mode:

  advisory (DEFAULT, also when the file is absent)
      The first mutation of each TURN emits a reminder of the briefing loop and
      names the way to enforce. Then it allows. Never denies.

  enforced
      Every mutation is denied until a go-ahead is recorded (1h TTL). The deny
      message names the way back to advisory.

Each mode tells you how to leave it — the piece both previous attempts lacked:
advisory never mentioned enforcement existed, and enforced never mentioned the
exit. The mode persists PER PROJECT (it is deliberately not in reset_markers),
so it survives SessionStart; the approval does not.

History, because this has moved four times and the reasons matter:
  c8c5c2e  hard gate. Reverted one commit later — it denied its own --status
           probes and blocked the very Edit needed to fix it.
  bb40ee0  advisory only ("educated is educational — it should not block").
  BUG-023  opt-in `guided` mode, then removed, then enforced-by-default.
  now      both modes, switched by /educate, advisory the default.

The mode switch used to be prose matched by a regex inside push-approve.py, and
it broke twice — BUG-025 (a natural phrasing matched nothing) and BUG-024 (the
confirmation was swallowed, so the feature worked and looked dead). It is now an
explicit slash command, which has neither failure mode.

SCOPE: only Write / Edit / MultiEdit / NotebookEdit are gated. Bash is out of the
matcher entirely, and bash_is_read_only() is deleted with it. That classifier
split commands on `|` and `>` without respecting quotes, so
`grep -oE "(allow|deny)" f` — a read — was classified as mutating and DENIED.
It blocked real research (observed 2026-08-13). A read cannot be wrongly blocked
by a gate that never inspects reads; deleting the classifier is a stronger
guarantee than fixing it. Known hole: `echo x > f` and `sed -i` are no longer
gated. Accepted — Claude mutates through Edit/Write, and the alternative is
keeping a classifier that has now misfired twice.

Fail-open: any internal error exits 0 without denying. A gate that bricks a
session is worse than one that occasionally lets something through.
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

ADVISORY_NOTICE = (
    "🪶 Educated Push (advisory): for non-trivial changes the loop is — briefing "
    "(WHAT/HOW/files, ≤200 words) → your go-ahead → execute → confirmation "
    "(≤150 words). Not a block; this action is proceeding. "
    "Want it required? Run /educate enforced mode."
)

DENY_REASON = (
    "🎓 Educated Push (enforced) — BLOCKED until approved. Post a briefing first "
    "(≤200 words, bullets): WHAT will be done, HOW it works, WHAT changes (files, "
    "db, config). Then STOP and wait. When the user replies 'go ahead' / "
    "'approved' / 'GO' / 'proceed', this opens for an hour. "
    "To stop requiring approval: /educate advisory mode."
)

APPROVAL_TTL_SECONDS = 3600  # CLAUDE.md: approval expires after 1 hour regardless




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
    # .push-mode is deliberately NOT cleared — the mode is a PER-PROJECT setting
    # chosen via /educate and must survive SessionStart. The approval must not.
    for name in (".push-approved", ".push-notice-shown", ".model-disclosed"):
        try:
            os.remove(os.path.join(root, ".raven", name))
        except OSError:
            pass  # absent is the normal case


def marker_path() -> str:
    """Per-TURN reminder marker. push-approve.py clears it on every prompt."""
    return os.path.join(repo_root(), ".raven", ".push-notice-shown")


def session_mode() -> str:
    """'enforced' only when explicitly set by /educate. Anything else is advisory.

    Absent file, unreadable file, or an unrecognised value all mean advisory — a
    typo must fail toward the less surprising behaviour.
    """
    try:
        with open(flag_path(".push-mode"), encoding="utf-8") as fh:
            return "enforced" if fh.read().strip().lower() == "enforced" else "advisory"
    except OSError:
        return "advisory"


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

    # Bash is no longer in the matcher; this guard keeps the script correct even if
    # someone re-adds it, without resurrecting the quote-blind classifier.
    mutating = tool in ("Write", "Edit", "MultiEdit", "NotebookEdit")
    if not mutating or is_self_exempt(tool, tool_input):
        sys.exit(0)

    if session_mode() == "enforced":
        if not approval_is_fresh():
            _emit("deny", DENY_REASON)
        sys.exit(0)

    # advisory: one reminder per TURN. push-approve.py clears the marker on every
    # prompt, so "per turn" needs no clock and no session id.
    if os.path.exists(marker_path()):
        sys.exit(0)
    try:
        os.makedirs(os.path.dirname(marker_path()), exist_ok=True)
        with open(marker_path(), "w", encoding="utf-8") as fh:
            fh.write("shown\n")
    except OSError:
        pass  # unwritable .raven/ must not turn a reminder into a failure
    _emit("allow", "Educated Push is advisory — reminder shown, action allowed.",
          ADVISORY_NOTICE)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
