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

REPO = Path(__file__).resolve().parent.parent
CANON = (REPO / "raven-core" / "VERSION").read_text(encoding="utf-8").strip()

# (path, how to extract the claimed current version)
CHECKS = [
    ("CLAUDE.md", r"^# CLAUDE\.md — Raven Discipline Engine v([\d.]+)"),
    ("plugin/CLAUDE.md", r"^# CLAUDE\.md — Raven Discipline Engine v([\d.]+)"),
    ("README.md", r"^# Raven v([\d.]+)"),
    ("plugin/README.md", r"^# Raven Plugin — v([\d.]+)"),
    ("VERSIONLOG.md", r"^## v([\d.]+) — "),  # newest entry on top
    ("plugin/make-plugin.sh", r'^VERSION="([\d.]+)"'),
    ("scripts/dashboard.py", r'^PLUGIN_VERSION = "([\d.]+)"'),
]

JSON_CHECKS = [
    ("plugin/plugin.json", "version"),
    ("plugin/.claude-plugin/plugin.json", "version"),
    (".raven/manifest.json", "version"),
    # marketplace.json determines the version label users see at install time — it was
    # the one place the v5.0.0 sweep missed, precisely because nothing checked it.
    (".claude-plugin/marketplace.json", "version"),
    (".claude-plugin/marketplace.json", "metadata.version"),
    (".claude-plugin/marketplace.json", "plugins.0.version"),
]


def _dig(obj, dotted: str):
    """Resolve a dotted path; integer segments index into lists."""
    for seg in dotted.split("."):
        obj = obj[int(seg)] if seg.isdigit() else obj.get(seg, "")
        if obj == "":
            return ""
    return obj


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
            v = _dig(json.loads(p.read_text(encoding="utf-8")), key)
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
