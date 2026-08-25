#!/usr/bin/env python3
"""
raven-xray.py — pure-Python code-symbol map for Raven ("Code Map" on the dashboard).

Not a port of any external tool. Parses Python source with the stdlib `ast`
module (no tree-sitter, no native binary, no database) and stores the result
as a plain JSON tree — human-readable, diffable, grep-able, consistent with
every other Raven store (knowledge-graph.json, dashboard-stamp.json, monthly
rollups). Answers caller/callee/impact queries from the CLI. Rebuilt on the
Stop hook, throttled via --if-stale so it doesn't re-scan the tree every turn.

Scope (deliberate, stated up front):
  - Python only. No JS/TS/other languages.
  - Static import resolution only. Dynamic imports (importlib, string-based
    dispatch, decorator-registered handlers) are NOT resolved — a call graph
    built from `ast` alone cannot see those without executing the code.
  - Unqualified-name call matching: first definition found wins on ambiguity.
  - One map per project root; no cross-repo/monorepo support.
"""
import argparse
import ast
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".raven", "dist", "build", ".mypy_cache", ".pytest_cache",
}


def find_project_root() -> Path:
    """Anchor to the repo root via .git, never the invocation cwd.

    Same fix pattern applied to model-router.py/session-start.py for the
    .raven/ and .model.env cwd-relative bugs — literal cwd-relative paths
    break the moment a hook is invoked from a nested directory.
    """
    d = Path.cwd()
    for candidate in (d, *d.parents):
        if (candidate / ".git").is_dir():
            return candidate
    return d


RAVEN_ROOT = find_project_root()
RAVEN_DIR = RAVEN_ROOT / ".raven"
XRAY_PATH = RAVEN_DIR / "xray.json"
STAMP_PATH = RAVEN_DIR / "xray-stamp.json"
SCOPE_NOTE = "python-only, static-import-resolution-only"


def iter_python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _node_id(file: str, name: str, lineno: int) -> str:
    return f"{file}:{name}:{lineno}"


class SymbolVisitor(ast.NodeVisitor):
    """Walks one file's AST, collecting function/class defs and call edges.

    Only resolves calls made via a bare name or `self.method()` — a call
    through an aliased import, a dynamically constructed callable, or a
    decorator-registered handler will not be linked. That's the explicit
    static-analysis boundary for this module (see module docstring).
    """

    def __init__(self, rel_file: str):
        self.rel_file = rel_file
        self.nodes = {}    # id -> {name, type, file, line}
        self.calls = []    # (src_id, callee_name)
        self.imports = []  # imported dotted names
        self._scope_stack = []

    def _current_scope(self):
        return self._scope_stack[-1] if self._scope_stack else None

    def visit_FunctionDef(self, node):
        ntype = "method" if self._current_scope() else "function"
        nid = _node_id(self.rel_file, node.name, node.lineno)
        self.nodes[nid] = {"name": node.name, "type": ntype, "file": self.rel_file, "line": node.lineno}
        self._scope_stack.append(nid)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        nid = _node_id(self.rel_file, node.name, node.lineno)
        self.nodes[nid] = {"name": node.name, "type": "class", "file": self.rel_file, "line": node.lineno}
        self._scope_stack.append(nid)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Call(self, node):
        scope = self._current_scope()
        if scope:
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            if callee_name:
                self.calls.append((scope, callee_name))
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}" if module else alias.name)
        self.generic_visit(node)


def parse_file(root: Path, path: Path):
    rel_file = str(path.relative_to(root))
    try:
        source = path.read_text(errors="replace")
        tree = ast.parse(source, filename=rel_file)
    except (SyntaxError, UnicodeDecodeError, ValueError) as e:
        sys.stderr.write(f"xray: skipping {rel_file} (parse error: {e})\n")
        return None
    visitor = SymbolVisitor(rel_file)
    visitor.visit(tree)
    return visitor


def build_map(root: Path) -> dict:
    nodes = {}
    raw_calls = []
    files = []
    imports_by_file = {}
    for py_file in iter_python_files(root):
        visitor = parse_file(root, py_file)
        if visitor is None:
            continue
        nodes.update(visitor.nodes)
        raw_calls.extend(visitor.calls)
        rel = str(py_file.relative_to(root))
        files.append([rel, py_file.stat().st_mtime])
        if visitor.imports:
            imports_by_file[rel] = visitor.imports

    # Resolve call edges: callee_name -> node id (unqualified match, first
    # definition wins on ambiguity — known static-only limitation, not a bug).
    by_name = {}
    for nid, meta in nodes.items():
        by_name.setdefault(meta["name"], nid)

    edges = []
    seen = set()
    for src, callee_name in raw_calls:
        dst = by_name.get(callee_name)
        if dst and dst != src and (src, dst) not in seen:
            seen.add((src, dst))
            edges.append({"src": src, "dst": dst, "rel": "calls"})

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": SCOPE_NOTE,
        "nodes": nodes,
        "edges": edges,
        "files": files,
        "imports": imports_by_file,
    }


def write_map(cmap: dict) -> None:
    RAVEN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = XRAY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cmap, indent=1))
    tmp.replace(XRAY_PATH)

    stamp = {
        "generated_at": cmap["generated_at"],
        "nodes": len(cmap["nodes"]),
        "edges": len(cmap["edges"]),
        "files": len(cmap["files"]),
        "scope": cmap["scope"],
        "path": str(XRAY_PATH),
    }
    STAMP_PATH.write_text(json.dumps(stamp, indent=2) + "\n")
    print(f"raven-xray: {stamp['nodes']} symbols, {stamp['edges']} call edges, {stamp['files']} files → {XRAY_PATH.name}", file=sys.stderr)


def is_stale(minutes: int) -> bool:
    if not STAMP_PATH.exists() or not XRAY_PATH.exists():
        return True
    try:
        stamp = json.loads(STAMP_PATH.read_text())
        generated_at = datetime.strptime(stamp["generated_at"], "%Y-%m-%d %H:%M:%S")
        age_minutes = (datetime.now() - generated_at).total_seconds() / 60
        return age_minutes >= minutes
    except Exception:
        return True


def load_map() -> dict:
    return json.loads(XRAY_PATH.read_text())


def _indices(cmap: dict):
    """In-memory lookup dicts — at Raven-scale repos (hundreds of symbols)
    this is microseconds; no database needed."""
    callers_of = defaultdict(list)  # dst id -> [src ids]
    callees_of = defaultdict(list)  # src id -> [dst ids]
    for e in cmap["edges"]:
        callers_of[e["dst"]].append(e["src"])
        callees_of[e["src"]].append(e["dst"])
    ids_by_name = defaultdict(list)
    for nid, meta in cmap["nodes"].items():
        ids_by_name[meta["name"]].append(nid)
    return callers_of, callees_of, ids_by_name


def _fmt(cmap: dict, nid: str) -> str:
    meta = cmap["nodes"].get(nid)
    if not meta:
        return nid
    return f"{meta['name']}  ({meta['file']}:{meta['line']})"


def query_callers(cmap: dict, name: str):
    callers_of, _, ids_by_name = _indices(cmap)
    out = []
    for nid in ids_by_name.get(name, []):
        out.extend(callers_of.get(nid, []))
    return sorted(set(out))


def query_callees(cmap: dict, name: str):
    _, callees_of, ids_by_name = _indices(cmap)
    out = []
    for nid in ids_by_name.get(name, []):
        out.extend(callees_of.get(nid, []))
    return sorted(set(out))


def query_impact(cmap: dict, name: str, max_hops: int = 3):
    """BFS over callers — 'what breaks if I change this' (blast radius)."""
    callers_of, _, ids_by_name = _indices(cmap)
    frontier = set(ids_by_name.get(name, []))
    if not frontier:
        return []
    visited = set(frontier)
    result = []
    for _hop in range(max_hops):
        if not frontier:
            break
        next_frontier = set()
        for nid in frontier:
            for src in callers_of.get(nid, []):
                if src not in visited:
                    next_frontier.add(src)
        for nid in sorted(next_frontier):
            result.append(nid)
        visited |= next_frontier
        frontier = next_frontier
    return result


def main():
    parser = argparse.ArgumentParser(description="Raven code-symbol map (Python-only, pure stdlib, JSON storage)")
    parser.add_argument("--build", action="store_true", help="(Re)build the map")
    parser.add_argument("--if-stale", type=int, metavar="MINUTES", help="Skip --build if map is younger than MINUTES")
    parser.add_argument("--callers", metavar="NAME", help="Who calls this function/method?")
    parser.add_argument("--callees", metavar="NAME", help="What does this function/method call?")
    parser.add_argument("--impact", metavar="NAME", help="Blast radius — who's affected if this changes?")
    parser.add_argument("--max-hops", type=int, default=3, help="Impact query depth (default 3)")
    parser.add_argument("--status", action="store_true", help="Show map stats")
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"raven-xray: ignoring unknown args {unknown}", file=sys.stderr)

    if args.build:
        if args.if_stale is not None and not is_stale(args.if_stale):
            return  # fresh enough — silent skip, same pattern as dashboard.py
        write_map(build_map(RAVEN_ROOT))
        return

    if not XRAY_PATH.exists():
        print("raven-xray: no map built yet — run with --build first", file=sys.stderr)
        return

    cmap = load_map()

    if args.callers:
        for nid in query_callers(cmap, args.callers):
            print(_fmt(cmap, nid))
    elif args.callees:
        for nid in query_callees(cmap, args.callees):
            print(_fmt(cmap, nid))
    elif args.impact:
        rows = query_impact(cmap, args.impact, args.max_hops)
        print(f"Impact of changing '{args.impact}' — {len(rows)} symbol(s) within {args.max_hops} hop(s):")
        for nid in rows:
            print(f"  {_fmt(cmap, nid)}")
    elif args.status:
        if STAMP_PATH.exists():
            print(STAMP_PATH.read_text())
        else:
            print("raven-xray: no stamp file — map never built", file=sys.stderr)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
