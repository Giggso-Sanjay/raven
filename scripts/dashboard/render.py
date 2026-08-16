#!/usr/bin/env python3
"""render.py — the Raven dashboard shell: sidebar + five views.

Design source: docs/dashboard-mockup.html (approved 2026-08-15).
Consumes the metrics/metadata dicts produced by core.aggregate() /
core.collect_metadata(); performs only light presentation-side reads
(vault session notes for the activity feed, code-tree.json for the hot file).
Deep tables with citations stay on legacy.html (rendered by core).
"""
from __future__ import annotations

import html as html_mod
import json
import os
import pathlib
import re
import sys

_PKG_DIR = pathlib.Path(__file__).resolve().parent
_SCRIPT_DIR = _PKG_DIR.parent
for _d in (str(_PKG_DIR), str(_SCRIPT_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

_HERE = __import__('pathlib').Path(__file__).resolve().parent
for _d in (_HERE, _HERE.parent / 'memory', _HERE.parent / 'routing'):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
from vault_common import VAULT  # noqa: E402

OUT_DIR = VAULT / "dashboard"
TREES_DIR = OUT_DIR / "trees"


def _esc(s) -> str:
    return html_mod.escape(str(s or ""))


def _fmt_usd(v: float) -> str:
    if v == 0:
        return "$0"
    return f"${v:.4f}" if v >= 0.01 else f"${v:.6f}".rstrip("0")


def _hot_file() -> tuple[str, str]:
    try:
        root = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
        ct = json.loads((root / ".raven" / "code-xray.json").read_text())
        flat: list[dict] = []

        def walk(n):
            if n.get("type") == "program":
                flat.append(n)
            for c in n.get("children", []):
                walk(c)

        walk(ct.get("root") or {})
        flat.sort(key=lambda n: -n.get("churn_30d", 0))
        if flat and flat[0].get("churn_30d", 0):
            why = (flat[0].get("history") or [{}])[0].get("why", "")
            return flat[0]["id"].split("/")[-1], why[:80]
    except Exception:
        pass
    return "—", ""


def _activity_feed(limit: int = 8) -> list[dict]:
    """Latest session notes across all repos → (when, project, first summary bullet)."""
    items = []
    try:
        notes = sorted(
            (VAULT / "sessions").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:limit]
        for p in notes:
            m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", p.stem)
            when, proj = (m.group(1), m.group(2)) if m else ("", p.stem)
            first = ""
            try:
                txt = p.read_text(errors="replace")
                bullets = re.findall(r"^\s*[•-]\s*(.+)$", txt, re.M)
                first = bullets[-1] if bullets else ""
                for b in reversed(bullets):
                    if len(b) > 20:
                        first = b
                        break
            except OSError:
                pass
            items.append({"when": when, "project": proj, "what": first[:110]})
    except OSError:
        pass
    return items


def _repo_rows(metrics: dict) -> list[dict]:
    from datetime import datetime, timedelta

    bp = metrics.get("by_project") or {}

    def last_touch(pname):
        best = 0.0
        for cand in [VAULT / "projects" / f"{pname}.md"] + sorted(
            (VAULT / "sessions").glob(f"*-{pname}.md")
        ):
            try:
                best = max(best, cand.stat().st_mtime)
            except OSError:
                pass
        return best

    names = {p.stem for p in (VAULT / "projects").glob("*.md")} | set(bp.keys())
    cutoff = (datetime.now() - timedelta(days=30)).timestamp()
    rows = []
    for n in names:
        t = last_touch(n)
        st = bp.get(n) or {}
        rows.append({
            "name": n,
            "touch": datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—",
            "mtime": t,
            "sessions": int(st.get("sessions") or 0),
            "tokens": int(st.get("tokens") or 0),
            "cost": float(st.get("cost_usd") or 0),
            "active": bool(st) or t >= cutoff,
        })
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def _tree_pages() -> list[str]:
    return sorted(p.name for p in TREES_DIR.glob("*.html")) if TREES_DIR.exists() else []


def render(metrics: dict, metadata: dict) -> str:
    proj = metadata.get("project") or "repo"
    all_cost = float(metrics.get("total_cost_usd") or 0)
    all_sess = int(metrics.get("sessions_count") or 0)
    all_tok = int(metrics.get("total_tokens") or 0)
    guards = metrics.get("guard_events") or {}
    n_guards = sum(guards.values())
    ok = bool(metadata.get("manifest_present", True))
    hot, hot_why = _hot_file()
    rows = _repo_rows(metrics)
    trees = _tree_pages()
    cur = (metrics.get("by_project") or {}).get(proj) or {}
    cur_cost = float(cur.get("cost_usd") or 0)

    def tree_for(name: str) -> str:
        for t in trees:
            if t.lower() == f"{name.lower()}.html":
                return t
        return ""

    default_tree = tree_for(proj) or (trees[0] if trees else "")
    tree_opts = "".join(
        f"<option value='trees/{t}' {'selected' if t == default_tree else ''}>{_esc(t[:-5])}</option>"
        for t in trees
    ) or "<option value=''>no trees built yet</option>"

    feed = ""
    for it in _activity_feed():
        feed += (
            f"<li><span class='when'>{_esc(it['when'])}</span>"
            f"<span><b>{_esc(it['project'])}</b> — {_esc(it['what']) or '<span class=dim>session logged</span>'}</span></li>\n"
        )

    repo_rows_html = ""
    for r in rows:
        tr = tree_for(r["name"])
        on = f"goTree('trees/{tr}')" if tr else ""
        pill = "<span class='pill act'>active</span>" if r["active"] else "<span class='pill'>idle</span>"
        d = "" if r["active"] else " style='opacity:.55'"
        repo_rows_html += (
            f"<tr class='rowlink' data-a='{1 if r['active'] else 0}'{d} onclick=\"{on}\">"
            f"<td><b>{_esc(r['name'])}</b> {pill}</td><td class='dim'>{_esc(r['touch'])}</td>"
            f"<td class='num'>{r['sessions']}</td><td class='num'>{r['tokens']:,}</td>"
            f"<td class='num'>{_fmt_usd(r['cost'])}</td>"
            f"<td>{'🌳' if tr else '<span class=dim>no tree</span>'}</td></tr>\n"
        )

    cbd = metrics.get("cost_by_day") or {}
    days = sorted(cbd)[-14:]
    peak = max((cbd[d] for d in days), default=0) or 1
    bars = "".join(
        f"<div title='{d} — {_fmt_usd(cbd[d])}' style='flex:1;background:var(--accent);"
        f"border-radius:4px 4px 0 0;height:{max(4, int(cbd[d] / peak * 100))}%'></div>"
        for d in days
    ) or "<p class='dim'>no daily data in window</p>"
    bar_labels = "".join(
        f"<div style='flex:1;text-align:center'>{d[8:]}</div>" for d in days
    )

    guard_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td class='num'>{v}</td></tr>\n"
        for k, v in sorted(guards.items(), key=lambda x: -x[1])[:15]
    ) or "<tr><td colspan='2' class='dim'>no events in window — no fire, not no coverage</td></tr>"

    verdict = "✅ All clear" if ok else "⚠️ Attention"
    verdict_line = (
        "Everything is fine." if ok else "Manifest missing — run /raven-init."
    )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raven — {_esc(proj)}</title>
<style>
:root{{--bg:#0e1116;--panel:#161b23;--panel2:#1c2330;--line:#232c3a;--ink:#e6ebf2;--ink2:#9aa7b8;
--ink3:#5f6d80;--accent:#5aa2e0;--good:#3fb07f;--warn:#e0a030;--r:10px}}
*{{box-sizing:border-box;margin:0}}
body{{background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",sans-serif;display:flex;min-height:100vh}}
aside{{width:210px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--line);padding:18px 12px;
position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:2px}}
aside h1{{font-size:16px;padding:0 10px 14px}}aside h1 span{{color:var(--ink3);font-weight:400;font-size:12px;display:block}}
.nav{{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:8px;color:var(--ink2);cursor:pointer;
font-size:14px;border:0;background:none;width:100%;text-align:left}}
.nav:hover{{background:var(--panel2);color:var(--ink)}}.nav.on{{background:var(--panel2);color:var(--ink);font-weight:600}}
.nav .ic{{width:20px;text-align:center}}aside .foot{{margin-top:auto;color:var(--ink3);font-size:11px;padding:10px}}
main{{flex:1;min-width:0;padding:22px 26px}}
.view{{display:none}}.view.on{{display:block}}
h2{{font-size:18px;margin-bottom:4px}}.sub{{color:var(--ink2);font-size:13px;margin-bottom:18px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}}
.tile{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px}}
.tile .k{{color:var(--ink2);font-size:12px;margin-bottom:6px}}.tile .v{{font-size:22px;font-weight:650}}
.tile .s{{color:var(--ink3);font-size:12px;margin-top:4px}}.tile.hero{{border-left:3px solid var(--good)}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px;margin-bottom:16px}}
.card h3{{font-size:14px;color:var(--ink2);font-weight:600;margin-bottom:10px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{color:var(--ink3);text-align:left;font-weight:500;padding:6px 10px;border-bottom:1px solid var(--line)}}
td{{padding:8px 10px;border-bottom:1px solid var(--line)}}tr:last-child td{{border-bottom:0}}
tr.rowlink{{cursor:pointer}}tr.rowlink:hover td{{background:var(--panel2)}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.dim{{color:var(--ink3)}}
.pill{{font-size:11px;padding:1px 8px;border-radius:99px;background:var(--panel2);color:var(--ink2)}}.pill.act{{color:var(--good)}}
.act li{{list-style:none;padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:10px}}
.act li:last-child{{border:0}}.act .when{{color:var(--ink3);font-size:12px;white-space:nowrap;width:88px}}
iframe{{width:100%;height:calc(100vh - 170px);border:1px solid var(--line);border-radius:var(--r);background:#12161c}}
select{{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:13px}}
a{{color:var(--accent);text-decoration:none}}
.toolrow{{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}}
label.chk{{color:var(--ink2);font-size:13px;cursor:pointer}}
</style></head><body>

<aside>
  <h1>🪶 Raven <span>{_esc(proj)} · {_esc(metadata.get('git_branch') or '')}</span></h1>
  <button class="nav on" data-v="home"><span class="ic">⬛</span>Overview</button>
  <button class="nav" data-v="tree"><span class="ic">🩻</span>Code-XRay</button>
  <button class="nav" data-v="repos"><span class="ic">📦</span>Repos</button>
  <button class="nav" data-v="costs"><span class="ic">💰</span>Costs</button>
  <button class="nav" data-v="guards"><span class="ic">🛡</span>Guards</button>
  <div class="foot">Generated {_esc(metadata.get('report_generated_at_local') or '')}<br>
  window {_esc(metrics.get('window_start') or '')} → {_esc(metrics.get('window_end') or '')}<br>
  <a href="legacy.html">detailed view (citations) ↗</a></div>
</aside>

<main>
<section class="view on" id="v-home">
  <h2>{verdict_line}</h2>
  <p class="sub">{n_guards} guard event(s) logged · guards announce themselves when they fire</p>
  <div class="tiles">
    <div class="tile hero"><div class="k">Status</div><div class="v" style="color:var(--{'good' if ok else 'warn'})">{verdict}</div><div class="s">secret + CVE gates at every commit</div></div>
    <div class="tile"><div class="k">Spend — {_esc(metrics.get('window_days') or 30)}d</div><div class="v">{_fmt_usd(all_cost)}</div><div class="s">this repo: {_fmt_usd(cur_cost)}</div></div>
    <div class="tile"><div class="k">Sessions</div><div class="v">{all_sess:,}</div><div class="s">{all_tok:,} tokens</div></div>
    <div class="tile"><div class="k">Hottest file</div><div class="v" style="font-size:15px">{_esc(hot)}</div><div class="s">{_esc(hot_why) or 'no recent churn'}</div></div>
  </div>
  <div class="card"><h3>Recent activity — latest sessions</h3><ul class="act">{feed or "<li class='dim'>no session notes yet</li>"}</ul></div>
</section>

<section class="view" id="v-tree">
  <h2>Code-XRay</h2>
  <p class="sub">What the codebase looks like, and why each file changed — zoom with scroll, drag to pan.</p>
  <div class="toolrow"><span class="dim">Repo:</span>
    <select id="treeSel" onchange="setTree(this.value)">{tree_opts}</select>
    <a id="treeOpen" href="trees/{_esc(default_tree)}" target="_blank">open full page ↗</a>
  </div>
  <iframe id="treeIF" src="trees/{_esc(default_tree)}"></iframe>
</section>

<section class="view" id="v-repos">
  <h2>Repos</h2>
  <p class="sub">Every repo Raven remembers — latest first. Click a row to open its code tree.</p>
  <div class="toolrow"><label class="chk"><input type="checkbox" id="f30" checked onchange="filt()"> active in last 30 days</label></div>
  <div class="card" style="padding:4px 8px"><table id="repoTbl">
    <thead><tr><th>Repo</th><th>Last activity</th><th class="num">Sessions</th><th class="num">Tokens</th><th class="num">Cost</th><th>Tree</th></tr></thead>
    <tbody>{repo_rows_html}</tbody></table></div>
  <p class="dim" style="font-size:12px">Knowledge-graph briefings and citations live in the <a href="legacy.html">detailed view</a>.</p>
</section>

<section class="view" id="v-costs">
  <h2>Costs</h2>
  <p class="sub">Raven-metered (token × rate card), not invoices. Full tables with citations in the <a href="legacy.html">detailed view</a>.</p>
  <div class="tiles">
    <div class="tile"><div class="k">All repos — {_esc(metrics.get('window_days') or 30)}d</div><div class="v">{_fmt_usd(all_cost)}</div><div class="s">{all_sess:,} sessions · {all_tok:,} tokens</div></div>
    <div class="tile"><div class="k">This repo</div><div class="v">{_fmt_usd(cur_cost)}</div><div class="s">{_esc(proj)}</div></div>
    <div class="tile"><div class="k">Avg / session</div><div class="v">{_fmt_usd(metrics.get('avg_cost_per_session') or 0)}</div><div class="s">portfolio</div></div>
  </div>
  <div class="card"><h3>Daily spend — last {len(days)} day(s)</h3>
    <div style="display:flex;align-items:flex-end;gap:6px;height:120px;padding-top:8px">{bars}</div>
    <div style="display:flex;gap:6px;color:var(--ink3);font-size:11px;margin-top:6px">{bar_labels}</div></div>
  <div class="card"><h3>Advanced</h3><p class="dim" style="font-size:13px">
    <a href="legacy.html">Detailed view</a> — citations, cost method, invoice compare, tier mix, provider attribution, downloads.</p></div>
</section>

<section class="view" id="v-guards">
  <h2>Guards</h2>
  <p class="sub">{n_guards} event(s) in window · quiet means no fire, not no coverage.</p>
  <div class="card"><table>
    <thead><tr><th>Event</th><th class="num">Count</th></tr></thead>
    <tbody>{guard_rows}</tbody></table></div>
</section>
</main>

<script>
const views=document.querySelectorAll('.view'),navs=document.querySelectorAll('.nav');
navs.forEach(n=>n.onclick=()=>{{
  navs.forEach(x=>x.classList.remove('on'));n.classList.add('on');
  views.forEach(v=>v.classList.remove('on'));
  document.getElementById('v-'+n.dataset.v).classList.add('on');
}});
function setTree(p){{if(!p)return;document.getElementById('treeIF').src=p;document.getElementById('treeOpen').href=p;}}
function goTree(p){{if(!p)return;setTree(p);
  const sel=document.getElementById('treeSel');[...sel.options].forEach(o=>{{if(o.value===p)sel.value=p;}});
  navs.forEach(x=>x.classList.remove('on'));document.querySelector('[data-v=tree]').classList.add('on');
  views.forEach(v=>v.classList.remove('on'));document.getElementById('v-tree').classList.add('on');}}
function filt(){{const on=document.getElementById('f30').checked;
  document.querySelectorAll('#repoTbl tbody tr').forEach(r=>r.style.display=(on&&r.dataset.a==='0')?'none':'');}}
filt();
</script>
</body></html>"""


def write_index(metrics: dict, metadata: dict) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TREES_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "index.html"
    out.write_text(render(metrics, metadata))
    # Redirect stub at the historical path so banners/bookmarks keep working
    stub = VAULT / "dashboard.html"
    stub.write_text(
        "<!doctype html><meta http-equiv='refresh' content='0;url=dashboard/index.html'>"
        "<a href='dashboard/index.html'>Raven dashboard moved → dashboard/index.html</a>"
    )
    return out
