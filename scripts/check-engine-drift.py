#!/usr/bin/env python3
"""
check-engine-drift.py — raven-engine-drift-check (CI + local).

The engine lives canonically in scripts/. raven-core/ and .claude/scripts/
carry same-named entries (relative symlinks in-repo). This check fails if any
same-named entry's CONTENT (symlinks followed) differs from its canonical
scripts/ source, or if any symlink is broken/absolute.

On a checkout with core.symlinks=false (the Windows default), git materializes
symlinks as regular files containing their target path. Comparing contents there
would report every mirror as drifted, so those entries are verified against the
git index instead: the recorded mode must be 120000 and the stored target must
resolve to the canonical file. That checks the same invariant without pretending
a path string is Python.

Exit 0 = no drift. Exit 1 = drift (each divergence listed).
"""
import subprocess
import sys
from pathlib import Path

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "scripts"
# plugin/scripts was NOT in this list, so 7 symlinks there pointed at absolute paths
# under /Users/giggso/AntiGravity_Projects/... — resolvable on one machine only, and
# shipped in the package (BUG-026). 4129672 converted 17 absolute symlinks to relative
# and added this gate specifically to fail on "a symlink is absolute", but scoped it to
# the two trees the author happened to be looking at. The check was right; its coverage
# was narrower than the invariant the repo needs.
MIRRORS = [
    REPO / "raven-core",
    REPO / ".claude" / "scripts",
    REPO / "plugin" / "scripts",
]

SYMLINK_MODE = "120000"


def _index_modes() -> dict:
    """Repo-relative posix path -> git index mode. Empty dict if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s"], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout:
        return {}
    modes = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")  # "<mode> <sha> <stage>\t<path>"
        if path:
            modes[path] = meta.split()[0]
    return modes


def _check_unmaterialized(entry: Path, canon: Path) -> str | None:
    """Verify a symlink that git checked out as a plain text file. None = OK."""
    try:
        target = entry.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as e:
        return f"UNREADABLE: {entry} ({e})"
    if not target or "\n" in target or len(target) > 512:
        return f"NOT A SYMLINK PAYLOAD: {entry} (index says {SYMLINK_MODE}, content is not a path)"
    if target.startswith(("/", "\\")) or (len(target) > 1 and target[1] == ":"):
        return f"ABSOLUTE SYMLINK (breaks other clones): {entry} -> {target}"
    resolved = (entry.parent / target).resolve()
    if not resolved.exists():
        return f"BROKEN SYMLINK: {entry} -> {target}"
    if resolved != canon.resolve():
        return f"SYMLINK TARGET MISMATCH: {entry} -> {target} (expected {canon})"
    return None


def main() -> int:
    failures = []
    index = _index_modes()
    verified_via_index = 0

    for mirror in MIRRORS:
        if not mirror.is_dir():
            continue
        for entry in sorted(mirror.glob("*.py")):
            canon = CANONICAL / entry.name
            if not canon.is_file():
                continue  # mirror-unique file — allowed, not drift
            if entry.is_symlink():
                target = entry.readlink()
                if target.is_absolute():
                    failures.append(f"ABSOLUTE SYMLINK (breaks other clones): {entry} -> {target}")
                    continue
                if not entry.resolve().exists():
                    failures.append(f"BROKEN SYMLINK: {entry} -> {target}")
                    continue
            elif index.get(entry.relative_to(REPO).as_posix()) == SYMLINK_MODE:
                # Declared a symlink in git but checked out as a plain file.
                problem = _check_unmaterialized(entry, canon)
                if problem:
                    failures.append(problem)
                else:
                    verified_via_index += 1
                continue  # never content-compare a path string against Python
            try:
                if entry.read_bytes() != canon.read_bytes():
                    failures.append(f"CONTENT DRIFT: {entry} != {canon}")
            except OSError as e:
                failures.append(f"UNREADABLE: {entry} ({e})")

    if verified_via_index:
        print(
            f"note: {verified_via_index} mirror entries are symlinks that this checkout did not "
            f"materialize (core.symlinks=false) — verified via the git index instead"
        )

    if failures:
        print("raven-engine-drift-check: FAIL")
        for f in failures:
            print(f"  {f}")
        return 1
    print("raven-engine-drift-check: PASS — all mirror entries match scripts/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
