#!/usr/bin/env python3
"""educate.py — set or show the Educated Push mode for this project.

Backs the /educate skill. Writes .raven/.push-mode, which push-gate.py reads on
every mutating tool call.

Why a script behind a skill rather than prose matched inside a hook: the mode
switch used to be a regex in push-approve.py and it broke twice — BUG-025 (a
natural phrasing matched nothing, so the mode silently stayed put and the
instruction was read as an unrelated task) and BUG-024 (the confirmation was
swallowed by a legacy console codepage, so the feature worked and looked dead).
An explicit command has neither failure mode. Same shape as /router → model-router.

The mode is PER PROJECT and survives SessionStart — push-gate.py's reset
deliberately does not clear it. The approval flag is not persistent and is cleared.
"""
import argparse
import os
import pathlib
import sys

# Raven output is emoji-forward and a console defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError there and the confirmation vanishes — the exact
# way BUG-024 made a working feature look dead. Guard before anything prints.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

MODES = ("advisory", "enforced")


def repo_root() -> pathlib.Path:
    """CLAUDE_PROJECT_DIR, else walk up to the nearest .git, else cwd.

    Never a bare cwd fallback: BUG-022 wrote Educated Push state into a different
    project because of exactly that, and the mode decides whether edits are blocked.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root and pathlib.Path(env_root).is_dir():
        return pathlib.Path(env_root)
    d = pathlib.Path.cwd()
    for candidate in [d, *d.parents]:
        if (candidate / ".git").is_dir():
            return candidate
    return d


def mode_file() -> pathlib.Path:
    return repo_root() / ".raven" / ".push-mode"


def read_mode() -> str:
    """Anything other than the literal 'enforced' is advisory — typos fail safe."""
    try:
        value = mode_file().read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "advisory"
    return "enforced" if value == "enforced" else "advisory"


def write_mode(mode: str) -> bool:
    try:
        path = mode_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(mode + "\n", encoding="utf-8")
        return True
    except OSError as e:
        print(f"⚠️  Could not write {mode_file()}: {e}", file=sys.stderr)
        return False


ADVISORY_MSG = (
    "🪶 EDUCATED PUSH: ADVISORY (default). The first change of each turn prints a "
    "reminder of the briefing loop, then proceeds — nothing is blocked. "
    "Run /educate enforced mode to require approval before edits."
)
ENFORCED_MSG = (
    "🎓 EDUCATED PUSH: ENFORCED. Every Write/Edit/MultiEdit/NotebookEdit is denied "
    "until you reply 'go ahead' / 'approved' / 'GO' / 'proceed'; the approval then "
    "holds for 1 hour or until your next non-approval message. Reads, searches and "
    "Bash are never blocked. Run /educate advisory mode to stop requiring approval."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--advisory", action="store_true", help="remind, never block (default)")
    g.add_argument("--enforced", action="store_true", help="deny edits until approved")
    g.add_argument("--status", action="store_true", help="show the current mode")
    args, unknown = ap.parse_known_args()
    if unknown:
        print(f"educate: ignoring unknown args {unknown}", file=sys.stderr)

    if args.enforced:
        if not write_mode("enforced"):
            return 1
        print(ENFORCED_MSG)
    elif args.advisory:
        if not write_mode("advisory"):
            return 1
        print(ADVISORY_MSG)
    else:
        current = read_mode()
        where = "set in" if mode_file().exists() else "defaulting (no mode file at"
        suffix = "" if mode_file().exists() else ")"
        print(ENFORCED_MSG if current == "enforced" else ADVISORY_MSG)
        print(f"   mode: {current} — {where} {mode_file()}{suffix}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never let a toggle crash a session
        print(f"educate fail-soft: {e}", file=sys.stderr)
        sys.exit(0)
