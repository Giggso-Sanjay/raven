#!/usr/bin/env python3
"""push-approve.py — UserPromptSubmit hook for the Educated Push Contract.

Watches the user's message for:
  'guided' / 'auto'  → sets session mode in .raven/.push-mode
  go-ahead words     → creates .raven/.push-approved (opens push-gate for a turn)
  'Lucky'            → existing opt-out keyword, also opens the gate

Any other message clears a leftover approval flag so each change cycle starts
clean. This script is the ONLY flag cleaner — a Stop-hook rm was removed after
it raced prompt submission and deleted fresh approvals. Mode persists until
SessionStart resets it. Fail-soft: any internal error exits 0.
"""

import json
import os
import re
import sys

# Every confirmation this script prints starts with an emoji (🎓 / ⚡ / 🪶). On a legacy
# Windows console codepage that raises UnicodeEncodeError, the fail-soft wrapper
# swallows it, and the user gets NO feedback that guided mode or their go-ahead
# registered — the flag file is written, so the feature works while appearing dead.
# Verified live: `guided` set .push-mode and printed nothing (BUG-024).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

APPROVAL_PATTERN = re.compile(
    r"(?:\bgo[- ]?ahead\b|\bapproved?\b|\bproceed\b|\bship it\b|\blgtm\b"
    r"|\bdo it\b|\bbuild it\b|^\s*go\s*$|^\s*yes\s*$|\bLucky\b)",
    re.IGNORECASE,
)
# Mode switches. The old patterns anchored `guided` to the very start of the whole
# message (no re.MULTILINE), so a natural instruction like
#   "turn on enforcement:\n  guided"
# matched nothing, the mode was never set, and the request read as an unrelated task
# — observed live (BUG-025). Accept: the word alone on any line, "guided mode", or a
# switch verb followed by the word within one clause.
_MODE_VERB = r"(?:turn\s+on|turn\s+it\s+on|enable|switch(?:\s+to)?|set|use|activate|go)"

GUIDED_PATTERN = re.compile(
    r"^\s*guided\s*$"                        # a line that is just: guided
    r"|\bguided\s+mode\b"                    # "guided mode"
    rf"|\b{_MODE_VERB}\b[^.\n]{{0,40}}?\bguided\b",   # "turn on enforcement: guided"
    re.IGNORECASE | re.MULTILINE,
)
AUTO_PATTERN = re.compile(
    r"^\s*auto\s*$"                          # a line that is just: auto
    r"|\bauto\s+mode\b"
    rf"|\b{_MODE_VERB}\b[^.\n]{{0,40}}?\bauto\b",
    re.IGNORECASE | re.MULTILINE,
)


def repo_root() -> str:
    """CLAUDE_PROJECT_DIR, else walk up to the nearest .git (BUG-022).

    Same cwd bug class as push-gate.py had: a bare os.getcwd() fallback writes the
    approval flag into whatever directory the hook happened to run from, so an approval
    given in one project can land in another's .raven/.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return env_root
    d = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def raven_path(*parts: str) -> str:
    return os.path.join(repo_root(), ".raven", *parts)


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


def main() -> None:
    payload = json.load(sys.stdin)
    prompt = payload.get("prompt", "") or ""

    if GUIDED_PATTERN.search(prompt):
        write_file(raven_path(".push-mode"), "guided")
        print("🎓 EDUCATED PUSH: GUIDED mode set for this session — every change "
              "needs a 200-word briefing and the user's go-ahead first.")
        return
    if AUTO_PATTERN.search(prompt):
        write_file(raven_path(".push-mode"), "auto")
        print("⚡ EDUCATED PUSH: AUTO mode set for this session — write gate open, "
              "no briefings required. User owns risk.")
        return

    if APPROVAL_PATTERN.search(prompt):
        write_file(raven_path(".push-approved"), prompt[:200])
        print("✅ EDUCATED PUSH: approval detected — write gate OPEN for this turn. "
              "Execute the approved briefing, then confirm in max 150 words "
              "(bullets + changed files).")
    else:
        try:
            os.remove(raven_path(".push-approved"))
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
