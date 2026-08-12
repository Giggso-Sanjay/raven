#!/usr/bin/env python3
"""
knowledge-extract.py — fail-soft durable facts from recent session notes.

Creates/updates lightweight concept stubs when high-signal file paths appear.
Does not invent ADRs without clear signal. Safe to run async from Stop hook.

Usage:
  python3 knowledge-extract.py --project raven
  python3 knowledge-extract.py --quiet
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from vault_common import (  # noqa: E402
    CONCEPTS,
    DECISIONS,
    SESSIONS,
    ensure_dirs,
    ensure_project_hub,
    get_project,
)

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

# Path fragments → concept slug hints (high confidence only)
PATH_CONCEPTS = [
    (re.compile(r"vault[_-]?load|obsidian|RavenVault", re.I), "raven-vault"),
    (re.compile(r"knowledge[_-]?graph|knowledge_graph", re.I), "knowledge-graph"),
    (re.compile(r"manifest\.json", re.I), "raven-manifest"),
    (re.compile(r"dashboard\.py", re.I), "raven-dashboard"),
    (re.compile(r"session-start", re.I), "session-start-hooks"),
]


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "concept"


def _latest_session(project: str) -> pathlib.Path | None:
    files = sorted(
        SESSIONS.glob(f"*-{project}.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _files_from_session(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def ensure_concept(slug: str, project: str, evidence: str) -> bool:
    ensure_dirs()
    path = CONCEPTS / f"{slug}.md"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if path.exists():
        # Append evidence line once if not present
        try:
            t = path.read_text()
            if evidence[:80] in t:
                return False
            path.write_text(
                t.rstrip()
                + f"\n- {now}: {evidence[:200]} (from [[{project}]] session)\n"
            )
            return True
        except OSError:
            return False
    # pick a simple icon key from slug keywords (login/db/security/…)
    icon = "concept"
    low = slug.lower()
    for key, words in (
        ("login", ("login", "auth")),
        ("security", ("secur", "guard", "vault", "secret")),
        ("database", ("db", "database", "sql", "postgres", "oracle")),
        ("api", ("api", "endpoint", "router")),
        ("ui", ("ui", "dashboard", "report", "screen")),
        ("money", ("pay", "card", "billing", "money")),
        ("cloud", ("cloud", "deploy", "aws", "oci")),
        ("workflow", ("workflow", "pipeline", "stream")),
        ("code", ("code", "hook", "script")),
        ("data", ("data", "metric", "token")),
    ):
        if any(w in low for w in words):
            icon = key
            break
    path.write_text(
        f"""---
type: concept
name: {slug}
project: {project}
icon: {icon}
updated: {now}
tags: [concept, raven]
---
# {slug.replace('-', ' ').title()}

[[projects/{project}]]

## Notes
- Auto-extracted (high-confidence path signal). Refine in Obsidian.
- {now}: {evidence[:200]}
"""
    )
    # Link from hub concepts section
    hub = ensure_project_hub(project)
    try:
        ht = hub.read_text()
        link = f"[[concepts/{slug}]]"
        if link not in ht:
            if "## Concepts" in ht:
                ht = ht.replace("## Concepts\n", f"## Concepts\n- {link}\n", 1)
            else:
                ht += f"\n## Concepts\n- {link}\n"
            hub.write_text(ht)
    except OSError:
        pass
    return True


def maybe_decision_stub(project: str, text: str) -> bool:
    """Only if session text explicitly mentions ADR/decision."""
    if not re.search(r"\b(ADR|architecture decision|decided to)\b", text, re.I):
        return False
    ensure_dirs()
    date = datetime.date.today().isoformat()
    slug = _slug(f"{project}-{date}-session")
    path = DECISIONS / f"{slug}.md"
    if path.exists():
        return False
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Extract one sentence near 'decid'
    m = re.search(r"([^.!\n]*decid[^.!\n]*[.!])", text, re.I)
    body = (m.group(1).strip() if m else "See linked session for context.")[:300]
    path.write_text(
        f"""---
type: decision
title: {slug}
project: {project}
updated: {now}
tags: [decision, raven]
---
# {slug}

[[projects/{project}]]

## Decision
{body}

## Context
Extracted from session note — refine manually.
"""
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    project = args.project or get_project()
    ensure_project_hub(project)
    session = _latest_session(project)
    if not session:
        if not args.quiet:
            print("knowledge-extract: no session notes yet")
        return
    text = session.read_text(errors="replace")
    files = _files_from_session(text)
    created = 0
    for fp in files:
        for rx, slug in PATH_CONCEPTS:
            if rx.search(fp):
                if ensure_concept(slug, project, f"touched `{fp}`"):
                    created += 1
    if maybe_decision_stub(project, text):
        created += 1
    if not args.quiet:
        print(f"knowledge-extract: {created} note(s) updated for {project}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"knowledge-extract fail-soft: {e}", file=sys.stderr)
        sys.exit(0)
