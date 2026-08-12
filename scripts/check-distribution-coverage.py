#!/usr/bin/env python3
"""
check-distribution-coverage.py — raven-distribution-coverage-check (CI + local).

Gate 6. Independent of the exporter, deliberately.

Gate 3 (export-hook-configs.py --check) asks "do the distribution copies match what
the exporter would generate?" That catches hand-edits, but it cannot catch a bug in
the exporter itself — generator and checker agree by construction. BUG-013 was exactly
that: a {**a, **b} merge silently dropped canonical's PreToolUse from
plugin/settings.json, and gate 3 reported PASS.

This gate asserts the SEMANTIC invariant instead, by reading the JSON directly and
sharing no code with export-hook-configs.py: every hook event canonical declares must
exist in every distribution copy, and every script canonical runs for that event must
be present there too. Extra entries are allowed — distribution copies may add
plugin-only hooks (declared exception: plugin/settings.json ships raven-skill-gate).

Two independent paths beat one careful path. If this gate and gate 3 ever disagree,
believe this one: it does not import the code it is checking.

Exit 0 = every distribution copy covers canonical. Exit 1 = something is missing.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / ".claude" / "settings.json"
DISTRIBUTION = [
    Path("hooks") / "hooks.json",
    Path("plugin") / "settings.json",
    Path("core") / "hooks" / "settings.json",
]

SCRIPT_RE = re.compile(r"([a-z0-9_-]+\.py)")


def scripts_by_event(path: Path) -> dict:
    """event -> set of *.py script names, read straight from the JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    out = {}
    for event, groups in hooks.items():
        found = set()
        for group in groups:
            for hook in group.get("hooks", []):
                found |= set(SCRIPT_RE.findall(hook.get("command", "")))
        out[event] = found
    return out


def main() -> int:
    if not CANONICAL.is_file():
        print(f"raven-distribution-coverage-check: FAIL — canonical missing: {CANONICAL}")
        return 1

    canon = scripts_by_event(CANONICAL)
    failures = []

    for rel in DISTRIBUTION:
        path = REPO / rel
        if not path.is_file():
            failures.append(f"MISSING distribution config: {rel}")
            continue
        try:
            dist = scripts_by_event(path)
        except (json.JSONDecodeError, OSError) as e:
            failures.append(f"UNPARSEABLE {rel}: {e}")
            continue

        for event, expected in canon.items():
            if event not in dist:
                failures.append(
                    f"{rel}: canonical event {event} absent entirely "
                    f"(canonical runs {sorted(expected)})"
                )
                continue
            missing = expected - dist[event]
            if missing:
                failures.append(
                    f"{rel}: event {event} is missing canonical scripts {sorted(missing)} "
                    f"(has {sorted(dist[event])})"
                )

    if failures:
        print("raven-distribution-coverage-check: FAIL (distribution lost canonical hooks)")
        for f in failures:
            print(f"  {f}")
        return 1

    events = len(canon)
    total = sum(len(v) for v in canon.values())
    print(
        f"raven-distribution-coverage-check: PASS — all {len(DISTRIBUTION)} distribution "
        f"configs cover canonical ({events} events, {total} script wirings)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
