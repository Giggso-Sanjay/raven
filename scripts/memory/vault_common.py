#!/usr/bin/env python3
"""Shared RavenVault helpers — hub ensure, project name, index hygiene."""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess
from typing import Optional

VAULT = pathlib.Path.home() / "RavenVault"
SESSIONS = VAULT / "sessions"
PROJECTS = VAULT / "projects"
CONCEPTS = VAULT / "concepts"
DECISIONS = VAULT / "decisions"
GRAPH_DIR = VAULT / "graph"
INDEX = VAULT / "index" / "README.md"
RAW_SESSIONS = VAULT / "sessions" / "raw"
DASHBOARD_HTML = VAULT / "dashboard.html"


def dashboard_path() -> pathlib.Path:
    """Canonical human dashboard (tokenomics + knowledge graph)."""
    return DASHBOARD_HTML


def dashboard_uri() -> str:
    """file:// URI for opening in a browser."""
    p = dashboard_path()
    try:
        if p.exists():
            return p.resolve().as_uri()
        return p.expanduser().absolute().as_uri()
    except Exception:
        return f"file://{p}"


def dashboard_link_lines(prefix: str = "📊", when: str = "") -> list[str]:
    """Short lines every Raven surface should show (session start / end / PR).

    Always points at ~/RavenVault/dashboard.html — rebuild with:
      python3 scripts/dashboard.py --html --open
    """
    path = dashboard_path()
    uri = dashboard_uri()
    when_bit = f" ({when})" if when else ""
    exists = path.exists()
    lines = [
        f"{prefix} Raven dashboard{when_bit}:",
        f"   {path}",
        f"   Open: {uri}",
    ]
    if not exists:
        lines.append(
            "   (not built yet — run: python3 scripts/dashboard.py --html --open)"
        )
    else:
        lines.append(
            "   Rebuild anytime: python3 scripts/dashboard.py --html --open"
        )
    return lines


def dashboard_link_oneline(when: str = "") -> str:
    """Single-line toaster-friendly dashboard pointer."""
    when_bit = f" · {when}" if when else ""
    return f"📊 Dashboard{when_bit}: {dashboard_path()}  ·  open {dashboard_uri()}"


def write_project_dashboard_link(project_root: pathlib.Path, project: str) -> pathlib.Path:
    """Write .raven/dashboard-link.md in the project's own repo — a pointer
    to the shared vault dashboard, scoped to this project via --current-project.

    The dashboard itself is one shared file (rebuilt on demand, not per-project
    output) — this just gives each repo a fixed place to find "its" view.
    """
    raven_dir = project_root / ".raven"
    raven_dir.mkdir(parents=True, exist_ok=True)
    link_path = raven_dir / "dashboard-link.md"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    link_path.write_text(
        f"""# Raven Dashboard — {project}

Generated: {now}

Shared vault dashboard: `{dashboard_path()}`
Open: {dashboard_uri()}

To view this repo's slice, regenerate scoped to it:

    python3 scripts/dashboard.py --current-project --html --open

(Run from this repo. `--current-project` resolves the project from
`.raven/manifest.json` or the git remote — no need to pass `--project` by hand.)
"""
    )
    return link_path


def run(cmd: list, **kw) -> str:
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, text=True, **kw
        ).strip()
    except Exception:
        return ""


def get_project(cwd: Optional[pathlib.Path] = None) -> str:
    remote = run(["git", "remote", "get-url", "origin"])
    if remote:
        return remote.rstrip("/").split("/")[-1].replace(".git", "")
    return (cwd or pathlib.Path.cwd()).name


def ensure_dirs() -> None:
    for d in (SESSIONS, PROJECTS, CONCEPTS, DECISIONS, GRAPH_DIR, INDEX.parent, RAW_SESSIONS):
        d.mkdir(parents=True, exist_ok=True)


def _read_manifest_stack() -> str:
    man = pathlib.Path(".raven") / "manifest.json"
    if not man.exists():
        man = pathlib.Path.cwd() / ".raven" / "manifest.json"
    if not man.exists():
        return "unknown"
    try:
        m = json.loads(man.read_text())
        stack = m.get("stack") or {}
        langs = stack.get("language") or []
        if isinstance(langs, list):
            return ", ".join(str(x) for x in langs) or "unknown"
        return str(langs)
    except Exception:
        return "unknown"


def ensure_project_hub(project: str) -> pathlib.Path:
    """Create projects/{name}.md if missing. Returns path."""
    ensure_dirs()
    path = PROJECTS / f"{project}.md"
    if path.exists():
        return path
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stack = _read_manifest_stack()
    path.write_text(
        f"""---
type: project
name: {project}
stack: {stack}
updated: {now}
tags: [project, raven]
---
# {project}

## Stack
- {stack}

## Current state
- Initialized by Raven vault writer.

## Open questions
- [ ] (none yet)

## Key decisions
- (none yet)

## Concepts
- (none yet)

## Recent sessions
- (none yet)
"""
    )
    return path


def update_hub_recent_session(project: str, session_link: str, summary_line: str = "") -> None:
    hub = ensure_project_hub(project)
    try:
        text = hub.read_text()
    except OSError:
        return
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = re.sub(r"^updated:.*$", f"updated: {now}", text, count=1, flags=re.M)
    line = f"- [[{session_link}]]" + (f" — {summary_line}" if summary_line else "")
    marker = "## Recent sessions"
    if marker in text:
        before, after = text.split(marker, 1)
        rest = after.split("\n", 1)[1] if "\n" in after else ""
        # Keep last ~15 session lines
        lines = [ln for ln in rest.splitlines() if ln.strip().startswith("- [[sessions/")]
        lines = [line] + lines[:14]
        # preserve trailing sections after blank line following list
        tail = ""
        if "\n## " in rest:
            # drop old list; keep nothing after for simplicity under Recent sessions
            pass
        new_rest = "\n".join(lines) + "\n"
        text = f"{before}{marker}\n{new_rest}"
    else:
        text = text.rstrip() + f"\n\n{marker}\n{line}\n"
    hub.write_text(text)


def rebuild_index(last_session: Optional[str] = None, timestamp: Optional[str] = None) -> None:
    """Rewrite index/README.md from projects/*.md — strips corruption."""
    ensure_dirs()
    hubs = sorted(PROJECTS.glob("*.md"))
    active = []
    for h in hubs:
        name = h.stem
        active.append(f"- [[projects/{name}]]")
    last = last_session or "_(none)_"
    if timestamp and last_session:
        last = f"[[sessions/{last_session}]] — {timestamp}"
    elif last_session and not last_session.startswith("_"):
        last = f"[[sessions/{last_session}]]"
    body = f"""# RavenVault — Index

Central knowledge base for all Raven-assisted projects.
Canonical vault: `~/RavenVault`. Written by obsidian-log / knowledge-extract / mem.

## Structure

| Folder | Purpose |
|---|---|
| `sessions/` | Short session summaries + wikilinks (not full git dumps) |
| `projects/` | One hub note per repo |
| `concepts/` | Durable product facts |
| `decisions/` | ADRs |
| `graph/` | `knowledge-graph.json` export for dashboard |
| `index/` | This file |

## Active Projects

{chr(10).join(active) if active else "- _(none yet)_"}

## Last Session
{last}

<!-- Updated by Raven vault writers -->
"""
    INDEX.write_text(body)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip("\"'")
    return meta, parts[2]


def extract_wikilinks(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def section_bullets(text: str, heading: str, limit: int = 10) -> list[str]:
    """Pull checklist/bullets under ## heading."""
    pat = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$", re.M | re.I
    )
    m = pat.search(text)
    if not m:
        return []
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.M)
    block = rest[: nxt.start()] if nxt else rest
    out = []
    for ln in block.splitlines():
        ln = ln.strip()
        if ln.startswith("- "):
            out.append(ln[2:].strip())
        if len(out) >= limit:
            break
    return out
