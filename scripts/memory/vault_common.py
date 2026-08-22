#!/usr/bin/env python3
"""Shared RavenVault helpers — hub ensure, project name, index hygiene."""
from __future__ import annotations

import datetime
import json
import os
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


def project_dashboard_uri(project: str) -> str:
    """file:// URI for THE dashboard (one file, no per-project builds),
    hash-scoped to one project.

    Every project gets the SAME dashboard/index.html with a #{project}
    filter — never a separate per-project file (2026-08-21 consolidation,
    see ~/RavenVault/decisions/dashboard-consolidation.md). dashboard.html
    is a meta-refresh redirect stub and does not carry the #hash fragment
    through the redirect, so this points directly at dashboard/index.html,
    which reads location.hash on load and switches to that project's
    Code-XRay tree via openCodeTree().
    """
    real = DASHBOARD_HTML.parent / "dashboard" / "index.html"
    try:
        base = real.resolve().as_uri() if real.exists() else real.expanduser().absolute().as_uri()
    except Exception:
        base = f"file://{real}"
    return f"{base}#{project}"


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
    scoped_uri = project_dashboard_uri(project)
    link_path.write_text(
        f"""# Raven Dashboard — {project}

Generated: {now}

Shared vault dashboard: `{dashboard_path()}`
Open (this project): {scoped_uri}

The dashboard is one shared file — the `#{project}` hash pre-selects this
project's slice on load, so no per-project rebuild is needed for viewing.

To regenerate the dashboard itself (data refresh, not per-project):

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


# ── Per-repo agent memory card (session start; not the vault digest) ──────────
CARD_SCHEMA = 1
CARD_STALE_AFTER_HOURS = 24
CARD_RELPATH = pathlib.Path(".raven") / "memory" / "CARD.md"
_NONE_MARKERS = ("(none yet)", "(none)", "n/a")


def manifest_project_name(cwd: Optional[pathlib.Path] = None) -> str:
    """Project stamp for the card: .raven/manifest.json then git remote."""
    root = cwd or pathlib.Path.cwd()
    man = root / ".raven" / "manifest.json"
    try:
        name = json.loads(man.read_text()).get("project")
        if name:
            return str(name)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return get_project(root)


def _usable_bullets(items: list[str], limit: int, *, decisions: bool = False) -> list[str]:
    out: list[str] = []
    for raw in items:
        s = raw.strip()
        low = s.lower()
        if not s or any(m in low for m in _NONE_MARKERS):
            continue
        if decisions and ("superseded" in low or s.startswith("~~")):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def memory_card_path(project_root: pathlib.Path) -> pathlib.Path:
    return project_root / CARD_RELPATH


def write_memory_card(
    project_root: pathlib.Path,
    *,
    session_id: str = "",
    project: Optional[str] = None,
) -> pathlib.Path:
    """Atomically write .raven/memory/CARD.md from this repo's hub projection.

    Does not read or embed knowledge-graph.json. Rotation of vault sessions
    is maybe_rotate_sessions() — never call that inside this function.
    """
    root = pathlib.Path(project_root)
    name = project or manifest_project_name(root)
    hub = PROJECTS / f"{name}.md"
    hub_text = ""
    try:
        hub_text = hub.read_text(errors="replace")
    except OSError:
        pass
    questions = _usable_bullets(section_bullets(hub_text, "Open questions", 8), 3)
    decisions = _usable_bullets(
        section_bullets(hub_text, "Key decisions", 8), 3, decisions=True
    )
    if not decisions:
        decisions = _usable_bullets(
            section_bullets(hub_text, "Decisions", 8), 3, decisions=True
        )
    now = datetime.datetime.now(datetime.timezone.utc)
    written = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "FRESH" if questions or decisions or hub_text else "NONE"
    dash = str(dashboard_path())
    q_lines = "\n".join(f"- {q}" for q in questions) or "- (none)"
    d_lines = "\n".join(f"- {d}" for d in decisions) or "- (none)"
    body = (
        f"schema: {CARD_SCHEMA}\n"
        f"status: {status}\n"
        f"written_at: {written}\n"
        f"stale_after_hours: {CARD_STALE_AFTER_HOURS}\n"
        f"project: {name}\n"
        f"session_id: {session_id or '(none)'}\n"
        f"dashboard: {dash}\n"
        f"\n"
        f"## Open questions\n{q_lines}\n"
        f"\n"
        f"## Open decisions\n{d_lines}\n"
        f"\n"
        f"## Agent rules\n"
        f"- If schema is not {CARD_SCHEMA}: MEMORY: INVALID — do not invent.\n"
        f"- If written_at older than stale_after_hours: STALE — do not treat as current.\n"
        f"- Do not read ~/RavenVault or knowledge-graph.json unless asked.\n"
    )
    dest = memory_card_path(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name("CARD.md.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def maybe_rotate_sessions() -> None:
    """Vault session archival. Separate from write_memory_card. No-op for now."""
    return None
