#!/usr/bin/env python3
"""push-approve.py — UserPromptSubmit hook for the Educated Push Contract.

Watches the user's message for go-ahead words ('go ahead', 'approved', 'GO',
'proceed', 'Lucky', ...) and RECORDS the approval in .raven/.push-approved.
Any other message clears a leftover flag so each change cycle starts clean.

Nothing gates on that flag. Educated Push is advisory (bb40ee0) — push-gate.py
always allows — so the flag is a record of consent, not a key. CLAUDE.md used to
claim the go-ahead "opens the write gate"; there is no write gate, and that
wording was corrected rather than reinstated when the opt-in guided mode was
removed (2026-08-13, see bug-fix-log.md BUG-023).

This script is the ONLY flag cleaner — a Stop-hook rm was removed after it raced
prompt submission and deleted fresh approvals. Fail-soft: any internal error
exits 0.
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

    if APPROVAL_PATTERN.search(prompt):
        write_file(raven_path(".push-approved"), prompt[:200])
        print("✅ EDUCATED PUSH: go-ahead recorded. Execute the briefing as stated, "
              "then confirm in max 150 words (bullets + changed files). "
              "Advisory — nothing was blocked.")
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
