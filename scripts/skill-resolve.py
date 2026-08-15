#!/usr/bin/env python3
"""Single funnel point for resolving a requested skill keyword to a skill dir.

Fixes: scattered routing (no one resolve function), silent skill-miss
fallthrough, and missing miss/hit logging. Does NOT fetch, sandbox, or
install anything — miss handling here is log-and-report only.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "skills" / "MANIFEST.json"
MISS_LOG_PATH = REPO_ROOT / ".raven" / "audit" / "skill-misses.jsonl"


def load_manifest():
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH) as f:
        return json.load(f).get("skills", {})


def resolve(keyword, caller="unknown"):
    """Return (skill_name, skill_path) on match, or (None, None) on miss.

    Match order: exact name -> substring match against name or purpose.
    A miss is logged; a hit is not (hits are the expected path, only
    misses need a trail per the audit).
    """
    skills = load_manifest()
    kw = keyword.strip().lower()

    if kw in skills:
        entry = skills[kw]
        return entry["name"], entry["paths"][0]

    for name, entry in skills.items():
        purpose = entry.get("purpose", "").lower()
        if kw in name.lower() or kw in purpose:
            return entry["name"], entry["paths"][0]

    _log_miss(keyword, caller)
    return None, None


def _log_miss(keyword, caller):
    MISS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "skill_miss",
        "keyword": keyword,
        "caller": caller,
    }
    with open(MISS_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Resolve a skill keyword against skills/MANIFEST.json")
    parser.add_argument("keyword", help="Skill name or platform keyword to resolve, e.g. 'falkordb'")
    parser.add_argument("--caller", default="cli", help="Who is asking (db-router, dynamic-specialist, cli, ...)")
    args = parser.parse_args()

    name, path = resolve(args.keyword, caller=args.caller)
    if name:
        print(json.dumps({"status": "hit", "name": name, "path": path}))
        sys.exit(0)
    else:
        print(json.dumps({"status": "miss", "keyword": args.keyword, "logged_to": str(MISS_LOG_PATH)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
