#!/usr/bin/env python3
"""
check-version-consistency.py — raven-version-consistency-check (CI + local).

raven-core/VERSION is the single canonical version. Every file that claims a
CURRENT version must match it exactly. Historical entries (changelogs,
version-history sections) are exempt — history is never rewritten (Rule 5
works both ways).

Exit 0 = consistent. Exit 1 = any mismatch, each listed.
"""
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent.parent
CANON = (REPO / "raven-core" / "VERSION").read_text(encoding="utf-8").strip()

# (path, how to extract the claimed current version)
CHECKS = [
    ("CLAUDE.md", r"^# CLAUDE\.md — Raven Discipline Engine v([\d.]+)"),
    ("plugin/CLAUDE.md", r"^# CLAUDE\.md — Raven Discipline Engine v([\d.]+)"),
    ("README.md", r"^# Raven v([\d.]+)"),
    ("plugin/README.md", r"^# Raven Plugin — v([\d.]+)"),
    ("VERSIONLOG.md", r"^## v([\d.]+) — "),  # newest entry on top
    ("plugin/make-plugin.sh", r'^VERSION="([\d.]+)"'),
    ("scripts/dashboard/core.py", r'^PLUGIN_VERSION = "([\d.]+)"'),
]

JSON_CHECKS = [
    ("plugin/plugin.json", "version"),
    ("plugin/.claude-plugin/plugin.json", "version"),
    (".raven/manifest.json", "version"),
]


def main() -> int:
    failures = []
    for rel, pattern in CHECKS:
        p = REPO / rel
        if not p.exists():
            failures.append(f"MISSING file with version claim: {rel}")
            continue
        m = re.search(pattern, p.read_text(encoding="utf-8"), re.MULTILINE)
        if not m:
            failures.append(f"NO current-version claim found in {rel} (pattern: {pattern})")
        elif m.group(1) != CANON:
            failures.append(f"STALE version in {rel}: claims {m.group(1)}, canonical is {CANON}")

    for rel, key in JSON_CHECKS:
        p = REPO / rel
        if not p.exists():
            continue  # manifest.json is per-install; plugin files must exist though
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get(key, "")
        except Exception as e:
            failures.append(f"UNPARSEABLE {rel}: {e}")
            continue
        if v != CANON:
            failures.append(f"STALE version in {rel}[{key}]: {v}, canonical is {CANON}")

    if failures:
        print(f"raven-version-consistency-check: FAIL (canonical: {CANON})")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"raven-version-consistency-check: PASS — all current-version claims = {CANON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
