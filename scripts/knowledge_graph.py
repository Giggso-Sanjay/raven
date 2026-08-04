#!/usr/bin/env python3
"""
knowledge_graph.py — scan RavenVault markdown → knowledge-graph.json

Usage:
  python3 knowledge_graph.py
  python3 knowledge_graph.py --project fin-processor
  python3 knowledge_graph.py --days 30
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from vault_common import (  # noqa: E402
    CONCEPTS,
    DECISIONS,
    GRAPH_DIR,
    PROJECTS,
    SESSIONS,
    VAULT,
    ensure_dirs,
    extract_wikilinks,
    parse_frontmatter,
)

TYPE_DIRS = {
    "project": PROJECTS,
    "concept": CONCEPTS,
    "decision": DECISIONS,
    "session": SESSIONS,
}


def _node_id(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("./")
    if rel.endswith(".md"):
        rel = rel[:-3]
    # normalize wikilink targets
    return rel.split("|")[0].strip()


def _session_too_old(path: pathlib.Path, days: int | None) -> bool:
    if days is None:
        return False
    try:
        mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
        return mtime < datetime.datetime.now() - datetime.timedelta(days=days)
    except OSError:
        return False


def build_graph(project_filter: str | None = None, session_days: int | None = 30) -> dict:
    ensure_dirs()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid: str, ntype: str, path: str, label: str | None = None, tags=None):
        if nid in nodes:
            return
        nodes[nid] = {
            "id": nid,
            "label": label or nid.split("/")[-1],
            "type": ntype,
            "path": path,
            "tags": tags or [ntype],
        }

    for ntype, folder in TYPE_DIRS.items():
        if not folder.exists():
            continue
        for path in folder.glob("*.md"):
            if ntype == "session" and _session_too_old(path, session_days):
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            rel_id = f"{folder.name}/{path.stem}"
            proj = meta.get("project") or ""
            if project_filter:
                if ntype == "project" and path.stem != project_filter:
                    # still include if linked later — skip primary filter for non-matching project hubs
                    continue
                if ntype != "project":
                    if proj and proj != project_filter and project_filter not in path.stem:
                        continue
                    if not proj and project_filter not in path.stem and project_filter not in text[:500]:
                        continue
            ntype_final = meta.get("type") or ntype
            tags = []
            if "tags" in meta:
                raw = meta["tags"].strip("[]")
                tags = [t.strip() for t in raw.split(",") if t.strip()]
            add_node(
                rel_id,
                ntype_final,
                (str(path.relative_to(VAULT)) if str(path).startswith(str(VAULT)) else str(path)),
                label=meta.get("name") or meta.get("title") or path.stem,
                tags=tags or [ntype_final],
            )
            for link in extract_wikilinks(text):
                target = _node_id(link)
                if not target:
                    continue
                # skip anchors only
                if target.startswith("#"):
                    continue
                # ensure target node stub
                if target not in nodes:
                    ttype = "unknown"
                    if target.startswith("projects/"):
                        ttype = "project"
                    elif target.startswith("concepts/"):
                        ttype = "concept"
                    elif target.startswith("decisions/"):
                        ttype = "decision"
                    elif target.startswith("sessions/"):
                        ttype = "session"
                    add_node(target, ttype, f"{target}.md", label=target.split("/")[-1])
                edges.append(
                    {"source": rel_id, "target": target, "rel": "wikilink"}
                )
            # frontmatter related:
            if meta.get("related"):
                for part in re.split(r"[, ]+", meta["related"]):
                    t = _node_id(part)
                    if t:
                        edges.append(
                            {"source": rel_id, "target": t, "rel": "related"}
                        )

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_filter": project_filter,
        "session_days": session_days,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def write_graph(graph: dict, out: pathlib.Path | None = None) -> pathlib.Path:
    ensure_dirs()
    out = out or (GRAPH_DIR / "knowledge-graph.json")
    out.write_text(json.dumps(graph, indent=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build RavenVault knowledge-graph.json")
    ap.add_argument("--project", default=None)
    ap.add_argument("--days", type=int, default=30, help="Session node window (default 30)")
    ap.add_argument("--all-sessions", action="store_true", help="Include all sessions")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    days = None if args.all_sessions else args.days
    g = build_graph(project_filter=args.project, session_days=days)
    if args.stdout:
        print(json.dumps(g, indent=2))
    else:
        path = write_graph(g)
        print(f"Wrote {path} ({len(g['nodes'])} nodes, {len(g['edges'])} edges)")


if __name__ == "__main__":
    main()
