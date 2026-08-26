#!/usr/bin/env python3
"""check-engine-drift.py — gate 1: mirrors must not diverge from canonical scripts/.

Root scripts/ is canonical. raven-core/, .claude/scripts/ and plugin/scripts/ are
mirrors of it. A mirror entry is legitimate only if it is a relative symlink to the
canonical file, or a byte-identical copy.

Three defects this rewrite fixes, all found 2026-08-13 by asking why a shipped
Rule 8 violation was passing a green gate:

  1. plugin/scripts/ was not in MIRRORS at all. plugin/scripts/session-start.py was a
     651-line stale copy of the 750-line canonical, and it still tiered
     claude-opus-4-5 as "high" (line 268) which complex_pick then selected (line 348).
     So every INSTALL auto-picked Opus on COMPLEX prompts — a Rule 8 violation
     shipping to users — while the repo's own canonical file was clean and the gate
     said PASS. A gate's coverage is part of its correctness.

  2. Canonical lookup was flat: `CANONICAL / entry.name`. After scripts/ was
     reorganised into routing/ guards/ memory/ session/ ops/ dashboard/, only four
     .py files remained directly under scripts/, so nearly every mirror entry hit
     `if not canon.is_file(): continue` and was waved through as "mirror-unique".
     Measured before the fix: 4 of 68 mirror entries were actually compared. The gate
     passed because it checked almost nothing.

  3. The symlink validity check sat AFTER the canonical-exists check, so a broken or
     absolute symlink with no canonical counterpart was never flagged. Seven entries
     in plugin/scripts/ were absolute symlinks into
     /Users/giggso/AntiGravity_Projects/... — broken in every clone but the author's,
     and invisible to this gate.

A symlink is validated for its own sake now: broken is broken whether or not a
canonical twin exists.
"""
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent.parent
CANONICAL = REPO / "scripts"
MIRRORS = [
    REPO / "raven-core",
    REPO / ".claude" / "scripts",
    REPO / "plugin" / "scripts",
]


def index_modes() -> dict:
    """repo-relative posix path -> git index mode.

    On Windows with core.symlinks=false git materialises a symlink as a REGULAR FILE
    whose contents are the target path, so Path.is_symlink() is False and a naive
    content compare reports every symlink as drift (observed: 31 bytes vs 33113).
    The git index is the only reliable source of truth for what is a symlink here.
    """
    out = subprocess.run(["git", "ls-files", "-s"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    modes = {}
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        meta, _, path = line.partition("	")
        parts = meta.split()
        if parts:
            modes[path.strip()] = parts[0]
    return modes


SYMLINK_MODE = "120000"


def canonical_index() -> dict:
    """basename -> [paths under scripts/], recursively.

    Recursive because scripts/ has subdirectories now. A basename appearing twice is
    reported rather than silently resolved to whichever sorted first.
    """
    idx = defaultdict(list)
    for p in sorted(CANONICAL.rglob("*.py")):
        idx[p.name].append(p)
    return idx


def main() -> int:
    failures = []
    index = canonical_index()

    for name, paths in sorted(index.items()):
        if len(paths) > 1:
            rels = ", ".join(str(p.relative_to(REPO)) for p in paths)
            failures.append(f"AMBIGUOUS CANONICAL: {name} exists at {rels}")

    modes = index_modes()
    compared = skipped = linked = 0
    for mirror in MIRRORS:
        if not mirror.is_dir():
            continue
        for entry in sorted(mirror.rglob("*.py")):
            rel = entry.relative_to(REPO)

            # Symlink sanity FIRST — a broken link is broken regardless of whether a
            # canonical twin exists. This ordering is the point (defect 3).
            posix = rel.as_posix()
            is_link = modes.get(posix) == SYMLINK_MODE or entry.is_symlink()
            if is_link:
                raw = (entry.read_text(encoding="utf-8", errors="replace").strip()
                       if not entry.is_symlink() else str(entry.readlink()))
                target = Path(raw)
                if target.is_absolute() or raw.startswith("/"):
                    failures.append(f"ABSOLUTE SYMLINK (breaks other clones): {posix} -> {raw}")
                    continue
                if not (entry.parent / target).resolve().exists():
                    failures.append(f"BROKEN SYMLINK: {posix} -> {raw}")
                    continue
                linked += 1
                continue  # a valid relative symlink cannot drift

            matches = index.get(entry.name)
            if not matches:
                skipped += 1
                continue  # genuinely mirror-unique
            canon = matches[0]
            compared += 1
            try:
                if entry.read_bytes() != canon.read_bytes():
                    failures.append(
                        f"CONTENT DRIFT: {rel} != {canon.relative_to(REPO)} "
                        f"({len(entry.read_bytes())} vs {len(canon.read_bytes())} bytes)")
            except OSError as e:
                failures.append(f"UNREADABLE: {rel} ({e})")

    if failures:
        print("raven-engine-drift-check: FAIL")
        for f in failures:
            print(f"  {f}")
        print(f"  ({compared} compared, {linked} symlinked, {skipped} mirror-unique)")
        return 1
    print(f"raven-engine-drift-check: PASS — {compared} copies match, {linked} valid "
          f"symlinks, {skipped} mirror-unique, across {len(MIRRORS)} mirrors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
