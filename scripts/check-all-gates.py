#!/usr/bin/env python3
"""
check-all-gates.py — run every discipline gate locally, in one command.

The gates lived in CI only, so feedback arrived after the commit had landed. For a
repo whose thesis is "every claim is machine-checked", after-the-fact is the wrong
side of the commit — two Rule-5-class defects (BUG-003, BUG-004) reached main even
though gates 2 and 3 both detect them.

Run this before committing:

    python3 scripts/check-all-gates.py           # gates only
    python3 scripts/check-all-gates.py --tests   # gates + pytest

Every gate is spawned as a subprocess so one crashing cannot hide the others, and
each gate's own exit code is captured directly (never through a pipe — `cmd | tail`
reports tail's status, which already produced one false "all green" in this repo).

Exit 0 = everything passed. Exit 1 = at least one gate failed; each is listed.
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Gate verdicts contain non-ASCII (— in "PASS — all gates green"). Relaying them to a
# legacy Windows console codepage raises UnicodeEncodeError and kills the runner —
# BUG-014's bug class, hit by this very script on its first run. See CLAUDE.md Rule C.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

REPO = Path(__file__).resolve().parent.parent

GATES = [
    ("engine-drift", ["scripts/check-engine-drift.py"]),
    ("docs-vs-reality", ["scripts/check-docs-vs-reality.py"]),
    ("config-canon", ["scripts/export-hook-configs.py", "--check"]),
    ("distribution-coverage", ["scripts/check-distribution-coverage.py"]),
    ("skill-manifest", ["scripts/build-skill-manifest.py", "--check"]),
    ("version-consistency", ["scripts/check-version-consistency.py"]),
]


def _run(label: str, argv: list) -> tuple:
    """Return (ok, first_line). Never raises — a crashing gate is a failing gate."""
    try:
        proc = subprocess.run(
            [sys.executable, *argv], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT after 300s"
    except OSError as e:
        return False, f"COULD NOT RUN: {e}"
    output = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in output.splitlines() if ln.strip()]
    # Gates print their verdict as a PASS/FAIL line (sometimes after a "note:" line).
    # pytest has no such line, so fall back to its summary ("22 passed, 1 skipped").
    verdict = next((ln for ln in lines if "PASS" in ln or "FAIL" in ln), "")
    if not verdict:
        verdict = next(
            (ln for ln in reversed(lines) if any(k in ln for k in ("passed", "failed", "error"))),
            lines[-1] if lines else "",
        )
    return proc.returncode == 0, verdict.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tests", action="store_true", help="also run pytest tests/")
    args = ap.parse_args()

    failed = []
    print(f"running {len(GATES)} gates from {REPO}\n")
    for label, argv in GATES:
        ok, verdict = _run(label, argv)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:24} {verdict}")
        if not ok:
            failed.append(label)

    if args.tests:
        print()
        ok, verdict = _run("pytest", ["-m", "pytest", "tests/", "-q"])
        print(f"  [{'PASS' if ok else 'FAIL'}] {'tests':24} {verdict}")
        if not ok:
            failed.append("tests")

    print()
    if failed:
        print(f"FAIL — {len(failed)} of {len(GATES) + (1 if args.tests else 0)}: {', '.join(failed)}")
        print("Re-run the individual command above for full output.")
        return 1
    print(f"PASS — all {len(GATES) + (1 if args.tests else 0)} checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
