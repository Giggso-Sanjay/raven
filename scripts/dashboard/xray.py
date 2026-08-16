#!/usr/bin/env python3
"""
xray.py — Raven Code-XRay: deterministic JSON code tree of the repo (no LLM).

The codebase is the skeleton; commit "whys" and session touches are
annotations pinned to the exact node they describe. AST + paths + docstrings
+ git only. Spec: docs/APPLY-PROMPT-code-tree-enterprise.md

Usage:
  python3 code-xray.py --build                      full scan → .raven/code-tree.json
  python3 code-xray.py --delta [--files f1 f2 …] [--session ID] [--commit SHA]
  python3 code-xray.py --digest [--for-prompt "…"]  ≤1500-token context payload
  python3 code-xray.py --html [--open]              self-contained tree view HTML
"""
from __future__ import annotations

import argparse
import ast
import datetime
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(
    os.environ.get("CLAUDE_PROJECT_DIR") or pathlib.Path(__file__).resolve().parent.parent.parent
)
TREE_PATH = REPO / ".raven" / "code-xray.json"
VAULT = pathlib.Path(os.environ.get("RAVEN_VAULT", str(pathlib.Path.home() / "RavenVault")))
TREES_DIR = VAULT / "dashboard" / "trees"
HTML_PATH = TREES_DIR / (REPO.name + ".html")

HISTORY_CAP = 5
SESSIONS_CAP = 10
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".raven", "dist", "build"}
SOURCE_EXT = {".py", ".js", ".ts", ".sh", ".md", ".yaml", ".yml", ".json", ".html", ".css"}
CONV_RX = re.compile(r"^(feat|fix|docs|refactor|test|chore|perf|style|ci|build)\(?([^):]*)\)?:\s*(.+)$")

ROLE_RULES = [
    (re.compile(r"-guard\.py$"), "guard"),
    (re.compile(r"-router\.py$"), "router"),
    (re.compile(r"(^|/)\.claude/skills/.*SKILL\.md$"), "skill"),
    (re.compile(r"(^|/)hooks/"), "hook"),
    (re.compile(r"(^|/)scripts/.*\.py$"), "script"),
    (re.compile(r"(^|/)docs/"), "doc"),
]

ROLE_COLORS = {
    "guard": "#e05252", "router": "#e0a030", "hook": "#4a90d9",
    "skill": "#9b6dd6", "script": "#8a949e", "doc": "#5aa87a",
    "entrypoint": "#38b2ac", "": "#8a949e",
}


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _hook_roles() -> dict[str, str]:
    """Map script path → hook:<Event> from .claude/settings.json."""
    out: dict[str, str] = {}
    try:
        cfg = json.loads((REPO / ".claude" / "settings.json").read_text())
        for event, groups in (cfg.get("hooks") or {}).items():
            for g in groups or []:
                for h in g.get("hooks") or []:
                    for m in re.finditer(r"([\w./-]+\.py)", h.get("command", "")):
                        name = pathlib.Path(m.group(1)).name
                        out.setdefault(name, f"hook:{event}")
    except Exception:
        pass
    return out


def _role(rel: str, hook_roles: dict[str, str]) -> str:
    name = pathlib.Path(rel).name
    if name in hook_roles:
        return hook_roles[name]
    for rx, role in ROLE_RULES:
        if rx.search(rel):
            return role
    return ""


def _purpose(path: pathlib.Path) -> tuple[str, list[str], list[str]]:
    """Return (purpose, functions, imports) for a file — AST for .py, first line otherwise."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return "", [], []
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
            doc = (ast.get_docstring(tree) or "").strip().splitlines()
            purpose = doc[0][:120] if doc else ""
            if purpose and len(doc) > 1 and len(purpose) < 30:
                purpose = " ".join(doc[:2])[:120]
            funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            imports: list[str] = []
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imports += [a.name.split(".")[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    imports.append(n.module.split(".")[0])
            local = {p.stem for p in path.parent.glob("*.py")}
            imports = sorted({i for i in imports if i in local and i != path.stem})
            return purpose, funcs[:20], imports
        except SyntaxError:
            return "", [], []
    for line in text.splitlines()[:10]:
        s = line.strip().lstrip("#/<!-* \t").rstrip("->")
        if s and not s.startswith(("---", "!", "{", "import", "from")):
            return s[:120], [], []
    return "", [], []


def _git_history(rel: str, limit: int = HISTORY_CAP) -> list[dict]:
    raw = _run(["git", "log", f"-{limit}", "--follow", "--format=%h|%as|%s", "--", rel])
    out = []
    for line in raw.splitlines():
        try:
            sha, date, subj = line.split("|", 2)
        except ValueError:
            continue
        m = CONV_RX.match(subj)
        if m:
            out.append({"commit": sha, "kind": m.group(1), "scope": m.group(2), "why": m.group(3)[:150], "date": date})
        else:
            out.append({"commit": sha, "kind": "other", "scope": "", "why": subj[:150], "date": date})
    return out


def _churn_30d() -> dict[str, int]:
    since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    raw = _run(["git", "log", f"--since={since}", "--name-only", "--format="])
    counts: dict[str, int] = {}
    for line in raw.splitlines():
        if line.strip():
            counts[line.strip()] = counts.get(line.strip(), 0) + 1
    return counts


def _tracked_files() -> list[str]:
    raw = _run(["git", "ls-files"])
    files = []
    for f in raw.splitlines():
        p = pathlib.Path(f)
        if p.suffix not in SOURCE_EXT:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(f)
    return files


def _file_node(rel: str, hook_roles: dict, churn: dict) -> dict:
    purpose, funcs, imports = _purpose(REPO / rel)
    return {
        "id": rel, "type": "program", "role": _role(rel, hook_roles),
        "purpose": purpose, "functions": funcs, "imports": imports,
        "history": _git_history(rel), "churn_30d": churn.get(rel, 0), "sessions": [],
    }


def _to_tree(file_nodes: dict[str, dict]) -> dict:
    root = {"id": REPO.name, "type": "project", "children": []}
    dirs: dict[str, dict] = {"": root}

    def ensure_dir(d: str) -> dict:
        if d in dirs:
            return dirs[d]
        parent = ensure_dir(str(pathlib.PurePosixPath(d).parent) if "/" in d else "")
        node = {"id": d, "type": "module", "children": []}
        parent["children"].append(node)
        dirs[d] = node
        return node

    for rel in sorted(file_nodes):
        d = str(pathlib.PurePosixPath(rel).parent)
        parent = ensure_dir("" if d == "." else d)
        parent["children"].append(file_nodes[rel])
    return root


def _flatten(node: dict, out: dict[str, dict]) -> None:
    if node.get("type") == "program":
        out[node["id"]] = node
    for c in node.get("children", []):
        _flatten(c, out)


def _atomic_write(payload: dict) -> None:
    TREE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(TREE_PATH.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, TREE_PATH)


def _load() -> dict | None:
    try:
        return json.loads(TREE_PATH.read_text())
    except Exception:
        return None


def build() -> dict:
    hook_roles = _hook_roles()
    churn = _churn_30d()
    file_nodes = {rel: _file_node(rel, hook_roles, churn) for rel in _tracked_files()}
    payload = {
        "version": 1,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "repo": REPO.name,
        "root": _to_tree(file_nodes),
    }
    _atomic_write(payload)
    return payload


def delta(files: list[str], session: str | None, commit: str | None) -> int:
    tree = _load()
    if tree is None:
        build()
        return -1
    if not files:
        changed = _run(["git", "diff", "--name-only", "HEAD~1"]).splitlines()
        changed += [l[3:] for l in _run(["git", "status", "--short"]).splitlines() if len(l) > 3]
        files = [f.strip() for f in changed if f.strip()]
    flat: dict[str, dict] = {}
    _flatten(tree["root"], flat)
    hook_roles = _hook_roles()
    churn = _churn_30d()
    touched = 0
    rebuilt_nodes = dict(flat)
    for rel in files:
        p = REPO / rel
        if pathlib.Path(rel).suffix not in SOURCE_EXT or any(part in SKIP_DIRS for part in pathlib.Path(rel).parts):
            continue
        if not p.exists():
            if rel in rebuilt_nodes:
                rebuilt_nodes[rel]["deleted"] = True
                touched += 1
            continue
        node = _file_node(rel, hook_roles, churn)
        old = rebuilt_nodes.get(rel, {})
        node["sessions"] = old.get("sessions", [])
        if session and session not in node["sessions"]:
            node["sessions"] = (node["sessions"] + [session])[-SESSIONS_CAP:]
        rebuilt_nodes[rel] = node
        touched += 1
    tree["root"] = _to_tree({k: v for k, v in rebuilt_nodes.items() if not v.get("deleted")})
    tree["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _atomic_write(tree)
    return touched


def digest(for_prompt: str | None = None) -> str:
    tree = _load() or build()
    flat: dict[str, dict] = {}
    _flatten(tree["root"], flat)
    lines = ["🩻 Raven Code-XRay (.raven/code-xray.json)"]
    mods: dict[str, int] = {}
    for rel in flat:
        top = rel.split("/")[0] if "/" in rel else "(root)"
        mods[top] = mods.get(top, 0) + 1
    lines.append("Shape: " + " · ".join(f"{m}({n})" for m, n in sorted(mods.items(), key=lambda x: -x[1])[:8]))
    hot = sorted(flat.values(), key=lambda n: -n.get("churn_30d", 0))[:10]
    lines.append("Hot nodes (30d churn · latest why):")
    for n in hot:
        if n.get("churn_30d", 0) == 0:
            break
        why = n["history"][0]["why"] if n.get("history") else "(no commits)"
        lines.append(f"  • {n['id']} ×{n['churn_30d']} — {why}")
    missing = [n["id"] for n in flat.values() if not n.get("purpose") and n["id"].endswith(".py")]
    if missing:
        lines.append(f"⚠ No purpose statement: {', '.join(missing[:6])}" + (" …" if len(missing) > 6 else ""))
    if for_prompt:
        low = for_prompt.lower()
        matched = [n for rel, n in flat.items()
                   if pathlib.Path(rel).name.lower() in low or rel.lower() in low][:3]
        for n in matched:
            lines.append(f"\nNode {n['id']}:")
            lines.append(json.dumps({k: n[k] for k in ("role", "purpose", "history", "sessions", "imports")}, indent=1))
    lines.append("Read the relevant subtree of .raven/code-xray.json before editing a file.")
    text = "\n".join(lines)
    return text[:6000]  # ~1500 tokens hard cap


def render_html(open_after: bool = False) -> pathlib.Path:
    tree = _load() or build()

    def node_html(n: dict, depth: int = 0) -> str:
        if n.get("type") in ("project", "module"):
            kids = "".join(node_html(c, depth + 1) for c in sorted(
                n.get("children", []), key=lambda c: (c.get("type") == "program", c["id"])))
            label = html.escape(n["id"].split("/")[-1] or n["id"])
            return (f"<details {'open' if depth < 2 else ''}><summary class='mod'>📁 {label}</summary>"
                    f"<div class='kids'>{kids}</div></details>")
        role = n.get("role", "")
        color = ROLE_COLORS.get(role.split(":")[0], ROLE_COLORS[""])
        churn = n.get("churn_30d", 0)
        badge = f"<span class='churn'>×{churn}</span>" if churn else ""
        warn = "" if n.get("purpose") or not n["id"].endswith(".py") else "<span class='warn'>⚠ no purpose</span>"
        why = html.escape(n["history"][0]["why"]) if n.get("history") else ""
        kind = n["history"][0]["kind"] if n.get("history") else ""
        hist = "".join(
            f"<li><code>{h['commit']}</code> <b>{html.escape(h['kind'])}</b>"
            f"{('(' + html.escape(h['scope']) + ')') if h['scope'] else ''}: "
            f"{html.escape(h['why'])} <span class='dim'>{h['date']}</span></li>"
            for h in n.get("history", []))
        sess = ", ".join(html.escape(s) for s in n.get("sessions", [])) or "—"
        imps = ", ".join(html.escape(i) for i in n.get("imports", [])) or "—"
        ses_attr = " ".join(html.escape(s) for s in n.get("sessions", []))
        vs = f"vscode://file{html.escape(str(REPO / n['id']))}"
        return (
            f"<details class='prog' id='f-{html.escape(n['id']).replace('/', '--').replace('.', '_')}' data-sessions='{ses_attr}'>"
            f"<summary><span class='chip' style='background:{color}'>{html.escape(role or 'file')}</span> "
            f"<b>{html.escape(pathlib.Path(n['id']).name)}</b> {badge}{warn}"
            f"<span class='purpose'>{html.escape(n.get('purpose') or '')}</span>"
            f"{('<span class=why>' + html.escape(kind) + ': ' + why + '</span>') if why else ''}"
            f"</summary><div class='panel'>"
            f"<p><b>Path:</b> <code>{html.escape(n['id'])}</code> · "
            f"<a href='{vs}' style='color:#4a90d9'>Open in VS Code ↗</a></p>"
            f"<p><b>Imports:</b> {imps}</p><p><b>Sessions:</b> {sess}</p>"
            f"<b>History:</b><ul>{hist or '<li>—</li>'}</ul></div></details>")

    def slim(n: dict) -> dict:
        out = {"id": n["id"].split("/")[-1] or n["id"], "path": n["id"],
               "role": (n.get("role") or "").split(":")[0], "churn": n.get("churn_30d", 0),
               "purpose": n.get("purpose", ""),
               "why": (n["history"][0]["kind"] + ": " + n["history"][0]["why"]) if n.get("history") else ""}
        kids = n.get("children")
        if kids:
            out["children"] = [slim(c) for c in sorted(kids, key=lambda c: (c.get("type") == "program", c["id"]))]
        return out

    graph_json = json.dumps(slim(tree["root"]))
    all_sessions = sorted({s for _, n in _flat_items(tree) for s in n.get("sessions", [])}, reverse=True)
    opts = "".join(f"<option value='{html.escape(s)}'>{html.escape(s)}</option>" for s in all_sessions)
    body = node_html(tree["root"])
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Raven Code-XRay — {html.escape(tree['repo'])}</title><style>
:root{{color-scheme:dark}}body{{background:#12161c;color:#e2e8f0;font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:2rem auto;max-width:960px;padding:0 1rem}}
h1{{font-size:1.3rem}}summary{{cursor:pointer;padding:.2rem 0}}
.mod{{font-weight:600;color:#a8b3c0}}.kids{{margin-left:1.2rem;border-left:1px solid #2a3340;padding-left:.8rem}}
.chip{{color:#0e1116;border-radius:4px;padding:0 .45em;font-size:.72em;font-weight:700}}
.purpose{{color:#8fa0b3;margin-left:.6em;font-style:italic}}
.why{{display:block;color:#6b7a8c;margin-left:2.2em;font-size:.85em}}
.churn{{background:#e0a030;color:#0e1116;border-radius:8px;padding:0 .5em;font-size:.72em;margin-left:.4em;font-weight:700}}
.warn{{color:#e0a030;font-size:.8em;margin-left:.4em}}
.panel{{background:#1a212b;border-radius:6px;margin:.4rem 0 .6rem 1.6rem;padding:.6rem .9rem}}
.dim{{color:#5a6878}}code{{background:#232c38;padding:0 .3em;border-radius:3px}}
.hl>summary{{background:#243447;border-radius:4px}}
.flash>summary{{background:#2c4a6e;border-radius:4px;transition:background 1.5s}}
.toolbar{{margin:1rem 0}}select{{background:#1a212b;color:#e2e8f0;border:1px solid #2a3340;padding:.3em;border-radius:4px}}
.zb{{background:#1a212b;color:#e2e8f0;border:1px solid #3a4656;border-radius:4px;width:34px;height:28px;cursor:pointer;font-size:14px}}
.zb:hover{{background:#243447}}.zb:last-child{{width:auto;padding:0 .5em}}
</style></head><body>
<h1>🩻 Raven Code-XRay — {html.escape(tree['repo'])}</h1>
<p class='dim'>Generated {html.escape(tree['generated_at'])} · source: .raven/code-tree.json · deterministic (AST + git, no LLM)
· <a style='color:#4a90d9' href='../index.html'>← dashboard</a></p>
<div class='toolbar'>Session overlay: <select id='sess' onchange='hl(this.value)'>
<option value=''>— none —</option>{opts}</select></div>
<h2 style='font-size:1.05rem'>Graph view <span class='dim' style='font-weight:400'>(scroll = zoom at cursor · drag = pan · click folder = expand/collapse · hover = purpose + why)</span></h2>
<p style='font-size:.8rem;margin:.2rem 0 .5rem'>
<span style='color:#38b2ac'>●</span> folder&nbsp;
<span style='color:#e05252'>●</span> guard&nbsp;
<span style='color:#e0a030'>●</span> router&nbsp;
<span style='color:#4a90d9'>●</span> hook&nbsp;
<span style='color:#9b6dd6'>●</span> skill&nbsp;
<span style='color:#8a949e'>●</span> script&nbsp;
<span style='color:#5aa87a'>●</span> doc&nbsp;
<span style='color:#e0a030'>◯</span> = changed in last 30d (bigger dot = more changes)</p>
<div id='gwrap' style='overflow:hidden;background:#0e1218;border:1px solid #2a3340;border-radius:8px;margin-bottom:1.5rem;position:relative;height:72vh'>
<div style='position:absolute;top:8px;right:8px;z-index:2;display:flex;gap:4px'>
<button class='zb' onclick='zoomBy(1.4)'>＋</button><button class='zb' onclick='zoomBy(1/1.4)'>－</button><button class='zb' onclick='zoomFit()'>⤢ fit</button></div>
<svg id='g' xmlns='http://www.w3.org/2000/svg' style='width:100%;height:100%;cursor:grab'><g id='vp'></g></svg></div>
<div id='tip' style='display:none;position:fixed;background:#1a212b;border:1px solid #3a4656;border-radius:6px;padding:.5rem .7rem;font-size:.8rem;max-width:380px;pointer-events:none;z-index:9'></div>
<h2 style='font-size:1.05rem'>Explorer view</h2>
{body}
<script>
const DATA={graph_json};
const COLORS={{guard:'#e05252',router:'#e0a030',hook:'#4a90d9',skill:'#9b6dd6',script:'#8a949e',doc:'#5aa87a','':'#5f6b78'}};
(function(){{
 DATA.open=true; if(DATA.children) DATA.children.forEach(c=>c.open=true);
 const svg=document.getElementById('g'), vp=document.getElementById('vp'), tip=document.getElementById('tip');
 const ROW=20, COL=190, PAD=30;
 let tx=0, ty=0, sc=1, extent={{w:900,h:400}};
 function apply(){{ vp.setAttribute('transform',`translate(${{tx}},${{ty}}) scale(${{sc}})`); }}
 window.zoomBy=function(f,cx,cy){{
  const r=svg.getBoundingClientRect();
  cx=(cx===undefined)?r.width/2:cx; cy=(cy===undefined)?r.height/2:cy;
  const ns=Math.min(6,Math.max(0.08,sc*f));
  tx=cx-(cx-tx)*(ns/sc); ty=cy-(cy-ty)*(ns/sc); sc=ns; apply();
 }};
 window.zoomFit=function(){{
  const r=svg.getBoundingClientRect();
  sc=Math.min(6,Math.max(0.08,Math.min(r.width/extent.w,r.height/extent.h)));
  tx=(r.width-extent.w*sc)/2; ty=(r.height-extent.h*sc)/2; apply();
 }};
 svg.addEventListener('wheel',e=>{{ e.preventDefault();
  const r=svg.getBoundingClientRect();
  zoomBy(e.deltaY<0?1.15:1/1.15, e.clientX-r.left, e.clientY-r.top);
 }},{{passive:false}});
 let drag=null;
 svg.addEventListener('mousedown',e=>{{ drag={{x:e.clientX-tx,y:e.clientY-ty}}; svg.style.cursor='grabbing'; }});
 window.addEventListener('mousemove',e=>{{ if(drag){{ tx=e.clientX-drag.x; ty=e.clientY-drag.y; apply(); }} }});
 window.addEventListener('mouseup',()=>{{ drag=null; svg.style.cursor='grab'; }});
 function layout(){{
  let y=0; const nodes=[], links=[];
  (function walk(n,depth,parent){{
   const me={{n:n,x:PAD+depth*COL,y:0,depth:depth}};
   nodes.push(me);
   if(n.children&&n.open){{
    const kids=n.children.map(c=>walk(c,depth+1,me));
    me.y=(kids[0].y+kids[kids.length-1].y)/2;
   }} else {{ me.y=PAD+y*ROW; y++; }}
   if(parent) links.push([parent,me]);
   return me;
  }})(DATA,0,null);
  return {{nodes:nodes,links:links,h:PAD*2+y*ROW,w:PAD*2+(Math.max(...nodes.map(m=>m.depth))+1)*COL}};
 }}
 function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}}
 function render(keepView){{
  const L=layout();
  extent={{w:Math.max(L.w,900),h:Math.max(L.h,120)}};
  let out='';
  for(const [a,b] of L.links)
   out+=`<path d='M${{a.x+6}} ${{a.y}} C ${{(a.x+b.x)/2}} ${{a.y}}, ${{(a.x+b.x)/2}} ${{b.y}}, ${{b.x-6}} ${{b.y}}' fill='none' stroke='#2e3a49' stroke-width='1.2'/>`;
  L.nodes.forEach((m,i)=>{{
   const n=m.n, isDir=!!n.children, r=isDir?6:Math.min(4+n.churn,9);
   const fill=isDir?'#38b2ac':(COLORS[n.role]||COLORS['']);
   out+=`<g class='nd' data-i='${{i}}' transform='translate(${{m.x}},${{m.y}})' style='cursor:pointer'>`+
    `<circle r='${{r}}' fill='${{fill}}' stroke='#0e1218' stroke-width='1.5' opacity='${{isDir&&!n.open?0.55:1}}'/>`+
    (n.churn?`<circle r='${{r+3}}' fill='none' stroke='#e0a030' stroke-width='1'/>`:'')+
    `<text x='${{r+5}}' y='4' fill='${{isDir?'#a8e0dc':'#c4cfdb'}}' font-size='11'>${{esc(n.id)}}${{isDir?(n.open?'':' ▸ ('+n.children.length+')'):''}}</text></g>`;
  }});
  vp.innerHTML=out;
  if(!keepView) zoomFit();
  vp.querySelectorAll('.nd').forEach(g=>{{
   const m=L.nodes[+g.dataset.i], n=m.n;
   g.onclick=()=>{{
    if(n.children){{ n.open=!n.open; render(true); return; }}
    const el=document.getElementById('f-'+n.path.replace(/\\//g,'--').replace(/\\./g,'_'));
    if(el){{ el.open=true; let p=el.parentElement;
     while(p){{ if(p.tagName==='DETAILS')p.open=true; p=p.parentElement; }}
     el.scrollIntoView({{behavior:'smooth',block:'center'}});
     el.classList.add('flash'); setTimeout(()=>el.classList.remove('flash'),1600); }}
   }};
   g.onmousemove=e=>{{ tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+10)+'px';
    tip.innerHTML=`<b>${{esc(n.path)}}</b>`+(n.role?` <span style='color:#8fa0b3'>[${{esc(n.role)}}]</span>`:'')+
     (n.purpose?`<br>${{esc(n.purpose)}}`:'')+(n.why?`<br><span style='color:#e0a030'>${{esc(n.why)}}</span>`:'')+
     (n.churn?`<br><span style='color:#8fa0b3'>churn 30d: ×${{n.churn}}</span>`:''); }};
   g.onmouseleave=()=>tip.style.display='none';
  }});
 }}
 render();
}})();
</script>
<script>
function hl(s){{document.querySelectorAll('.prog').forEach(d=>{{
 const on=s&&(d.dataset.sessions||'').split(' ').includes(s);
 d.classList.toggle('hl',on); if(on){{let p=d.parentElement;while(p){{if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}}}}
}});}}
</script></body></html>"""
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(page)
    # Uniform per-repo name so the dashboard switcher can address every tree
    named = TREES_DIR / f"{tree['repo']}.html"
    if named != HTML_PATH:
        named.write_text(page)
    if open_after:
        subprocess.Popen(["open", str(HTML_PATH)])
    return HTML_PATH


def _flat_items(tree: dict):
    flat: dict[str, dict] = {}
    _flatten(tree["root"], flat)
    return flat.items()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--commit", default=None)
    ap.add_argument("--for-prompt", default=None)
    ap.add_argument("--repo", default=None, help="build for another repo root (writes code-tree-<name>.html)")
    args = ap.parse_args()

    if args.repo:
        global REPO, TREE_PATH, HTML_PATH
        REPO = pathlib.Path(args.repo).resolve()
        if not (REPO / ".git").exists():
            print(f"code-tree: {REPO} is not a git repo", file=sys.stderr)
            return
        TREE_PATH = REPO / ".raven" / "code-xray.json"
        HTML_PATH = TREES_DIR / f"{REPO.name}.html"

    if args.build:
        t = build()
        flat = dict(_flat_items(t))
        print(f"code-tree: built {len(flat)} nodes → {TREE_PATH}")
    if args.delta:
        n = delta(args.files or [], args.session, args.commit)
        print(f"code-tree: {'full rebuild (no tree existed)' if n < 0 else f'{n} node(s) patched'}")
    if args.digest:
        print(digest(args.for_prompt))
    if args.html:
        p = render_html(args.open)
        print(f"code-tree: HTML → {p}")
    if not any([args.build, args.delta, args.digest, args.html]):
        ap.print_help()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"code-tree fail-soft: {e}", file=sys.stderr)
        sys.exit(0)
