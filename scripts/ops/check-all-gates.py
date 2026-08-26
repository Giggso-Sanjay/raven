#!/usr/bin/env python3
"""check-all-gates.py — run every discipline gate locally, in one command.

Absent from main (only a stale .pyc survived the 5.5.x restructure). Rebuilt
against the gates that actually exist on this layout — engine-drift,
docs-vs-reality, version-consistency, counts. Older gates from the pre-5.5.4
line (config-canon, distribution-coverage, skill-manifest) have no equivalent
here and are not faked back in.

Usage:
    python3 scripts/ops/check-all-gates.py           # gates only
    python3 scripts/ops/check-all-gates.py --tests   # gates + pytest

Exit codes are read directly from each subprocess, never through a pipe —
`cmd 2>&1 | tail` reports tail's exit code, not the command's. That mistake has
already produced one false "all green" in this repo.
"""
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent.parent

GATES = [
    ("engine-drift", ["scripts/ops/check-engine-drift.py"]),
    ("docs-vs-reality", ["scripts/ops/check-docs-vs-reality.py"]),
    ("version-consistency", ["scripts/ops/check-version-consistency.py"]),
    ("counts", ["scripts/ops/check-counts.py"]),
]


def _run(label, argv):
    proc = subprocess.run([sys.executable, *argv], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    out = proc.stdout.strip() or proc.stderr.strip()
    # last non-empty line — pytest's summary and each gate's PASS/FAIL both land there
    lines = [l for l in out.splitlines() if l.strip()]
    verdict = (next((l for l in reversed(lines)
                     if any(k in l for k in ("passed", "failed", "error", "PASS", "FAIL"))), out)
               if lines else out)
    return ok, verdict, out


def main() -> int:
    ap_tests = "--tests" in sys.argv
    failed = []

    print(f"running {len(GATES)} gates from {REPO}\n")
    for label, argv in GATES:
        ok, verdict, out = _run(label, argv)
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label:24s} {verdict[:100]}")
        if not ok:
            failed.append(label)
            for line in out.splitlines()[:15]:
                print(f"           {line}")

    if ap_tests:
        print()
        ok, verdict, out = _run("tests", ["-m", "pytest", "tests/", "-q"])
        print(f"  [{'PASS' if ok else 'FAIL'}] {'tests':24s} {verdict[:100]}")
        if not ok:
            failed.append("tests")
            for line in out.splitlines()[-25:]:
                print(f"           {line}")

    total = len(GATES) + (1 if ap_tests else 0)
    print()
    if failed:
        print(f"FAIL — {len(failed)} of {total}: {', '.join(failed)}")
        print("Re-run the individual command above for full output.")
        return 1
    print(f"PASS — all {total} checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
