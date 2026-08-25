#!/usr/bin/env python3
"""check-counts.py — gate 7: every count claim in the repo matches the code.

CONTRIBUTING's Truth Rule says counts must be verified, never hardcoded from
memory. That instruction was unenforceable and duly ignored: on 2026-08-13 the
repo claimed "61 skills" in 19 places across 13 files while skills/ held 63, and
VERSIONLOG.md said 62 — three numbers, none correct. The audit that found the
v3.4 miscount ("wrong in four different directions") had already happened; the
lesson was written into prose and prose does not fail a build.

Root cause of the drift: the only sanctioned way to get the number was
`bash plugin/make-plugin.sh`, which needs `zip`. On a default Windows install
that exits 127 before printing any count, so the mandated check could not run
and nobody could notice. This gate recounts from disk with nothing but the
stdlib, so it runs everywhere the tests do.

Exit 0 = every claim matches. Exit 1 = at least one disagrees.
"""
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent

# Historical records: a dated entry describing a past release must keep the number
# that release shipped, right or wrong. Rewriting history to satisfy a gate would
# be the same dishonesty from the other direction.
EXEMPT_FILES = {
    "CHANGELOG.md",
    "VERSIONLOG.md",
    "docs/CHANGELOG-4.2.0-vault-graph.md",
    "CONTRIBUTING.md",       # documents the failure itself, quotes the wrong numbers
    "scripts/check-counts.py",
    # Append-only observation log: entries are dated findings, not live claims.
    "docs/observations/security_log.md",
}

# Legacy subtree with its own inventory, not the root skills/agents set.
EXEMPT_PREFIXES = ("guard/",)

# A line may opt out where a number is genuinely unrelated to these inventories.
OPT_OUT = "[counts:ignore]"


def authoritative() -> dict:
    """Recount from disk. Same formulas plugin/make-plugin.sh uses, minus the zip."""
    return {
        "skills": len(list((REPO / "skills").rglob("SKILL.md"))),
        "agents": len(list((REPO / "agents").glob("*.md"))),
        "commands": len(list((REPO / "core" / "commands").glob("*.md"))),
    }


# (regex, which inventory it asserts). Kept narrow on purpose — a broad
# r"(\d+) skills" would match prose about someone else's plugin.
PATTERNS = [
    (re.compile(r"(\d+)\s+skills\b", re.I), "skills"),
    (re.compile(r"(\d+)\s+domain\s+skills\b", re.I), "skills"),
    # (?<!Tier ) — "4 Tier 1 specialists" names four skills by hand; without
    # the lookbehind the regex captured that "1" and reported a count of 1.
    (re.compile(r"(?<!Tier )(\d+)\s+specialists\b", re.I), "skills"),
    (re.compile(r"(?<!Tier )(\d+)\s+domain\s+specialists\b", re.I), "skills"),
    (re.compile(r"(\d+)\s+guard\s+agents\b", re.I), "agents"),
    (re.compile(r"(\d+)\s+slash\s+commands\b", re.I), "commands"),
]


def tracked_files() -> list:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return [l for l in out.stdout.splitlines() if l.strip()]


def main() -> int:
    truth = authoritative()
    if not all(truth.values()):
        print(f"raven-counts-check: FAIL — could not count from disk: {truth}")
        return 1

    bad = []
    for rel in tracked_files():
        if rel in EXEMPT_FILES or rel.startswith(EXEMPT_PREFIXES):
            continue
        p = REPO / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable — nothing to claim
        for lineno, line in enumerate(text.splitlines(), 1):
            if OPT_OUT in line:
                continue
            for rx, kind in PATTERNS:
                for m in rx.finditer(line):
                    claimed = int(m.group(1))
                    if claimed != truth[kind]:
                        bad.append((rel, lineno, m.group(0).strip(),
                                    kind, claimed, truth[kind]))

    if bad:
        print(f"raven-counts-check: FAIL — {len(bad)} stale count claim(s)")
        print(f"  authoritative: {truth}")
        for rel, ln, frag, kind, claimed, real in bad[:40]:
            print(f"  {rel}:{ln}  \"{frag}\" — claims {claimed} {kind}, actual {real}")
        if len(bad) > 40:
            print(f"  … and {len(bad) - 40} more")
        print(f"  Fix the claims, or add {OPT_OUT} to a line whose number is unrelated.")
        return 1

    print(f"raven-counts-check: PASS — all count claims match "
          f"({truth['skills']} skills, {truth['agents']} agents, "
          f"{truth['commands']} commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
