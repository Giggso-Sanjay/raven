#!/usr/bin/env python3
"""
vault-load.py — optional manual vault digest (NOT SessionStart).
TRACKED: docs/DEPRECATIONS.md — keep as CLI; never re-wire to SessionStart.

Agent boot Reads .raven/memory/CARD.md instead. Keep this CLI for humans
who explicitly want a capped vault dump.

Usage:
  python3 vault-load.py
  python3 vault-load.py --project raven
  python3 vault-load.py --hook   # JSON {additionalContext} — unused at boot
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_HERE = __import__('pathlib').Path(__file__).resolve().parent
for _d in (_HERE, _HERE.parent / 'memory', _HERE.parent / 'routing'):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
from vault_common import (  # noqa: E402
    CONCEPTS,
    DECISIONS,
    PROJECTS,
    SESSIONS,
    ensure_dirs,
    ensure_project_hub,
    get_project,
    parse_frontmatter,
    section_bullets,
)

MAX_CHARS = 3500


def _last_session_summaries(project: str, n: int = 2) -> list[str]:
    if not SESSIONS.exists():
        return []
    files = sorted(
        SESSIONS.glob(f"*-{project}.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:n]
    out = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        # Prefer AI Summary section bullets / first 12 non-empty lines after frontmatter
        _, body = parse_frontmatter(text)
        summary_lines = []
        in_sum = False
        for ln in body.splitlines():
            if ln.strip().startswith("### AI Summary"):
                in_sum = True
                continue
            if in_sum:
                if ln.startswith("###") or ln.startswith("## "):
                    break
                if ln.strip():
                    summary_lines.append(ln.strip())
        if not summary_lines:
            for ln in body.splitlines():
                s = ln.strip()
                if s and not s.startswith("#") and not s.startswith("---"):
                    summary_lines.append(s)
                if len(summary_lines) >= 6:
                    break
        blurb = " | ".join(summary_lines[:5])[:400]
        out.append(f"{f.stem}: {blurb or '(no summary)'}")
    return out


def _last_decisions(n: int = 3) -> list[str]:
    if not DECISIONS.exists():
        return []
    files = sorted(DECISIONS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[
        :n
    ]
    out = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        title = meta.get("title") or f.stem
        one = ""
        for ln in body.splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                one = s[:120]
                break
        out.append(f"{title}: {one}" if one else title)
    return out


def build_digest(project: str) -> str:
    ensure_dirs()
    ensure_project_hub(project)
    hub_path = PROJECTS / f"{project}.md"
    hub_text = hub_path.read_text(errors="replace") if hub_path.exists() else ""
    _, hub_body = parse_frontmatter(hub_text)
    open_qs = section_bullets(hub_body, "Open questions", limit=8)
    state = section_bullets(hub_body, "Current state", limit=6)
    sessions = _last_session_summaries(project, 2)
    decisions = _last_decisions(3)
    graph = pathlib.Path.home() / "RavenVault" / "graph" / "knowledge-graph.json"

    lines = [
        "🪶 RavenVault digest (curated — not full vault)",
    ]
    try:
        from vault_common import dashboard_link_lines  # noqa: E402

        lines.extend(dashboard_link_lines(when="session digest — open on every run"))
    except Exception:
        dash = pathlib.Path.home() / "RavenVault" / "dashboard.html"
        lines.extend(
            [
                f"📊 Dashboard (open this): {dash}",
                f"   file://{dash}",
                "   Rebuild: python3 scripts/dashboard.py --html --open",
            ]
        )
    lines.extend(
        [
            f"Project hub: [[projects/{project}]]",
            "",
            "Current state:",
        ]
    )
    lines += [f"  • {s}" for s in state] or ["  • (empty)"]
    lines.append("Open questions:")
    lines += [f"  • {q}" for q in open_qs] or ["  • (none)"]
    lines.append("Last session summaries:")
    lines += [f"  • {s}" for s in sessions] or ["  • (none yet)"]
    lines.append("Recent decisions:")
    lines += [f"  • {d}" for d in decisions] or ["  • (none yet)"]
    if graph.exists():
        lines.append(f"Graph export: {graph}")
    n_concepts = len(list(CONCEPTS.glob("*.md"))) if CONCEPTS.exists() else 0
    n_sessions = len(list(SESSIONS.glob(f"*-{project}.md"))) if SESSIONS.exists() else 0
    n_dec = len(list(DECISIONS.glob("*.md"))) if DECISIONS.exists() else 0
    lines.append("")
    lines.append("Memory sources (RavenVault — load these, not full vault dumps):")
    lines.append(f"  · Hub: ~/RavenVault/projects/{project}.md")
    lines.append(f"  · Sessions: {n_sessions} note(s) in ~/RavenVault/sessions/*-{project}.md")
    lines.append(f"  · Concepts: {n_concepts} · Decisions: {n_dec}")
    lines.append("  · Dashboard: ~/RavenVault/dashboard.html (human view of same memory)")
    lines.append("  · Prefer open questions + last decisions before inventing architecture.")
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 20] + "\n… (truncated)"
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="RavenVault session digest")
    ap.add_argument("--project", type=str, default=None)
    ap.add_argument("--hook", action="store_true", help="Emit Claude additionalContext JSON")
    ap.add_argument("--json", action="store_true", help="Emit {digest, project} JSON")
    args = ap.parse_args()
    project = args.project or get_project()
    digest = build_digest(project)
    if args.hook:
        print(json.dumps({"additionalContext": digest}))
    elif args.json:
        print(json.dumps({"project": project, "digest": digest}))
    else:
        print(digest)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block SessionStart
        if "--hook" in sys.argv:
            print(json.dumps({"additionalContext": f"RavenVault digest unavailable: {e}"}))
        else:
            print(f"vault-load fail-soft: {e}", file=sys.stderr)
        sys.exit(0)
