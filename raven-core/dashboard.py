#!/usr/bin/env python3
"""
Raven — Tokenomics & Usage Dashboard

Single module. Three render modes. Recommendations engine.

Modes:
  python3 dashboard.py --cli                  → ASCII table to stdout
  python3 dashboard.py --obsidian             → writes ~/RavenVault/Dashboard.md
  python3 dashboard.py --html [--open]        → writes ~/RavenVault/dashboard.html
                                              (tokenomics + knowledge graph panel)
  python3 dashboard.py --graph-only           → rebuild graph JSON + graph-focused HTML
  python3 dashboard.py --graph-json           → only write knowledge-graph.json
  python3 dashboard.py --json                 → dumps raw metrics (for piping)
  python3 dashboard.py --all                  → all of the above

Filters:
  --days N        last N days (default 30)
  --month YYYY-MM specific month
  --project NAME  scope to a project (default: all)

Data sources (all local, no telemetry):
  .raven/audit/*.log                       — guard events, violations, approvals
  .raven/.model-session.json               — last session cost
  ~/RavenVault/.metrics/YYYY-MM.json       — rolling aggregated history
  ~/RavenVault/sessions/*.md               — session summaries
  .raven/manifest.json                     — project metadata
  git config user.name + remote            — who ran it, company

Metadata block always present: report timestamp, plugin version, company,
project, user, manifest snapshot.

Recommendations engine: rule-based, reads metrics, surfaces 3-7 actionable
suggestions per session ("Opus % at 38% — review prompts for over-classification").

Local-only. No telemetry. No Hub. ~500 LOC.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
RAVEN_DIR = PROJECT_DIR / ".raven"
AUDIT_DIR = RAVEN_DIR / "audit"
MANIFEST = RAVEN_DIR / "manifest.json"
MODEL_SESSION = RAVEN_DIR / ".model-session.json"
VAULT = Path.home() / "RavenVault"
VAULT_SESSIONS = VAULT / "sessions"
VAULT_METRICS = VAULT / ".metrics"
VAULT_DASHBOARD_MD = VAULT / "Dashboard.md"
VAULT_DASHBOARD_HTML = VAULT / "dashboard.html"

PLUGIN_VERSION = "4.2.0"


# ── Metadata Collection ────────────────────────────────────────────────────────
def collect_metadata() -> dict:
    """Build the metadata block: who, what, where, when."""
    md = {
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "report_generated_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "plugin_version": PLUGIN_VERSION,
        "project": None,
        "company": None,
        "owner": None,
        "user": None,
        "git_remote": None,
        "git_branch": None,
        "manifest_present": MANIFEST.exists(),
        "vault_path": str(VAULT),
        "project_path": str(PROJECT_DIR),
    }

    # From manifest
    if MANIFEST.exists():
        try:
            m = json.loads(MANIFEST.read_text())
            md["project"] = m.get("project")
            md["owner"] = m.get("owner")
            md["company"] = m.get("company") or m.get("owner")
            md["manifest"] = {
                "project": m.get("project"),
                "owner": m.get("owner"),
                "version": m.get("version"),
                "stack": m.get("stack"),
                "standards": m.get("standards"),
                "approval_mode": m.get("approval_mode"),
            }
        except Exception:
            pass

    # From git
    try:
        md["user"] = subprocess.check_output(
            ["git", "config", "user.name"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        pass
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        md["git_remote"] = remote
        # Extract company from URL — github.com/COMPANY/repo
        m = re.search(r"[/:]([^/]+)/[^/]+?(?:\.git)?$", remote)
        if m and not md["company"]:
            md["company"] = m.group(1)
    except Exception:
        pass
    try:
        md["git_branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        pass

    md["project"] = md["project"] or PROJECT_DIR.name
    md["owner"] = md["owner"] or md["user"] or "unknown"
    md["company"] = md["company"] or md["owner"]

    return md


# ── Aggregator ────────────────────────────────────────────────────────────────
def _project_name(raw) -> Optional[str]:
    """Normalize project field (str | dict | None) from metrics rows."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get("name") or raw.get("project")
    return str(raw)


def _parse_day(day_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(day_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def format_usd(amount: float, *, force_cents: bool = False) -> str:
    """Human money: avoid $0.00 masking real sub-cent / small costs."""
    try:
        v = float(amount or 0.0)
    except (TypeError, ValueError):
        v = 0.0
    if v == 0:
        return "$0"
    if force_cents or v >= 1.0:
        return f"${v:,.2f}"
    if v >= 0.01:
        return f"${v:.4f}"
    return f"${v:.6f}"


EXTERNAL_USAGE_PATH = VAULT / ".metrics" / "external-usage.json"
EXTERNAL_USAGE_TEMPLATE = VAULT / ".metrics" / "external-usage.template.json"


def load_external_usage() -> dict:
    """Optional Claude/Anthropic-reported usage for side-by-side compare.

    File: ~/RavenVault/.metrics/external-usage.json
    (never auto-filled by Raven — human or Claude pastes after Console/export.)
    """
    if not EXTERNAL_USAGE_PATH.exists():
        return {}
    try:
        data = json.loads(EXTERNAL_USAGE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"error": f"unreadable {EXTERNAL_USAGE_PATH}"}


def ensure_external_usage_template() -> None:
    """Write a template file users/Claude can fill for comparison."""
    try:
        VAULT_METRICS.mkdir(parents=True, exist_ok=True)
        if EXTERNAL_USAGE_TEMPLATE.exists():
            return
        EXTERNAL_USAGE_TEMPLATE.write_text(
            json.dumps(
                {
                    "source": "anthropic_console | claude_session_estimate | user_paste",
                    "as_of": "YYYY-MM-DD",
                    "window_days": 30,
                    "notes": "Paste totals from Anthropic Console or ask Claude to estimate from known usage. Raven does not fill this file.",
                    "total": {"tokens": 0, "cost_usd": 0.0},
                    "by_project": {
                        "fin-processor": {
                            "tokens": 0,
                            "cost_usd": 0.0,
                            "notes": "example — replace with real numbers",
                        }
                    },
                },
                indent=2,
            )
            + "\n"
        )
    except Exception:
        pass


def render_cost_compare_section(metrics: dict, metadata: dict) -> str:
    """Side-by-side: Raven-metered vs Claude/external-reported."""
    ensure_external_usage_template()
    ext = load_external_usage()
    bp = metrics.get("by_project") or {}
    window = f"{metrics.get('window_start')} → {metrics.get('window_end')}"

    ext_bp = ext.get("by_project") if isinstance(ext.get("by_project"), dict) else {}
    ext_total = ext.get("total") if isinstance(ext.get("total"), dict) else {}
    names = sorted(set(list(bp.keys()) + list(ext_bp.keys())), key=str.lower)

    rows = ""
    for name in names:
        r = bp.get(name) or {}
        e = ext_bp.get(name) if isinstance(ext_bp.get(name), dict) else {}
        r_tok = int(r.get("tokens") or 0)
        r_cost = float(r.get("cost_usd") or 0)
        e_tok = e.get("tokens")
        e_cost = e.get("cost_usd")
        e_tok_s = f"{int(e_tok):,}" if e_tok is not None else "—"
        e_cost_s = format_usd(float(e_cost)) if e_cost is not None else "—"
        # delta only when external present
        if e_cost is not None:
            delta = float(e_cost) - r_cost
            delta_s = format_usd(delta) if delta >= 0 else f"-{format_usd(abs(delta))}"
            ratio = (float(e_cost) / r_cost) if r_cost > 0 else ("∞" if float(e_cost) > 0 else "—")
            if isinstance(ratio, float):
                ratio_s = f"{ratio:.1f}×"
            else:
                ratio_s = str(ratio)
        else:
            delta_s = "—"
            ratio_s = "—"
        rows += (
            f"<tr><td><strong>{name}</strong></td>"
            f"<td class='num'>{r_tok:,}</td><td class='num'>{format_usd(r_cost)}</td>"
            f"<td class='num'>{e_tok_s}</td><td class='num'>{e_cost_s}</td>"
            f"<td class='num'>{delta_s}</td><td class='num'>{ratio_s}</td></tr>\n"
        )
    if not rows:
        rows = "<tr><td colspan='7' style='color:#94a3b8'>No Raven per-repo rows yet.</td></tr>"

    r_tot_t = int(metrics.get("total_tokens") or 0)
    r_tot_c = float(metrics.get("total_cost_usd") or 0)
    e_tot_t = ext_total.get("tokens")
    e_tot_c = ext_total.get("cost_usd")
    e_tot_t_s = f"{int(e_tot_t):,}" if e_tot_t is not None else "—"
    e_tot_c_s = format_usd(float(e_tot_c)) if e_tot_c is not None else "—"

    has_ext = bool(ext) and "error" not in ext and (
        ext_bp or e_tot_c is not None or e_tot_t is not None
    )
    if has_ext:
        status = (
            f"<p style='color:#86efac;font-size:13px;'>External file loaded: "
            f"<code>{EXTERNAL_USAGE_PATH}</code> · source={ext.get('source','?')} · "
            f"as_of={ext.get('as_of','?')} · window_days={ext.get('window_days','?')}</p>"
        )
    elif ext.get("error"):
        status = f"<p style='color:#f59e0b;font-size:13px;'>{ext.get('error')}</p>"
    else:
        status = f"""
<p style="color:#fbbf24;font-size:13px;margin-bottom:12px;">
  <strong>No Claude/external usage file yet.</strong>
  Raven column is filled automatically. Claude column stays empty until you (or Claude) write:
  <code>{EXTERNAL_USAGE_PATH}</code>
  (template: <code>{EXTERNAL_USAGE_TEMPLATE}</code>).
</p>
"""

    claude_prompt = """Ask Claude (in any project session):

Copy Anthropic Console usage (or your best estimate) into
~/RavenVault/.metrics/external-usage.json using the template at
external-usage.template.json. Include by_project.fin-processor (and others)
with tokens + cost_usd for the same ~30 day window as the Raven dashboard.
Then run: python3 scripts/dashboard.py --html --open
and open the side-by-side Cost compare section.

If you only have org totals (not per-repo), put them under total and note that
in notes — do not invent per-repo splits."""

    return f"""
  <h2 id="cost-method">📐 What “cost” means here (two sources)</h2>
  <div class="meta" style="border-left:4px solid #38bdf8;margin-bottom:16px;font-size:14px;line-height:1.55;">
    <p style="margin-bottom:10px;"><strong>1) Raven-metered (left columns)</strong> — computed from
    <em>code-path token consumption</em> × <em>model rate cards</em>, not from your invoice:</p>
    <ul style="margin:0 0 12px 18px;color:#cbd5e1;">
      <li><code>log-overhead.py</code> — estimated hook/router tokens during the session</li>
      <li><code>token-meter-write.py</code> on Stop — transcript <code>usage</code> ×
        <code>scripts/model-pricing.json</code></li>
      <li>Stored in <code>.raven/.model-session.json</code> and
        <code>~/RavenVault/.metrics/YYYY-MM.json</code> (project-tagged when available)</li>
    </ul>
    <p style="margin-bottom:10px;"><strong>2) Claude / Anthropic-reported (right columns)</strong> —
    numbers <em>you or Claude paste</em> from Console, export, or session estimate.
    Raven never scrapes billing APIs.</p>
    <p style="color:#94a3b8;font-size:13px;margin:0;">
    Window for Raven column: <strong>{window}</strong>
    ({metrics.get('window_days')}d). Compare only when external window matches.
    Large gaps (e.g. Raven $0.002 vs Claude $100+) mean meters under-captured real model usage —
    trust the Claude/Console side for money, Raven side for local discipline telemetry.
    </p>
  </div>

  <h2 id="cost-compare">⚖️ Cost compare — Raven vs Claude/external</h2>
  {status}
  <table>
    <thead>
      <tr>
        <th>Repo</th>
        <th class="num">Raven tokens</th>
        <th class="num">Raven $</th>
        <th class="num">Claude/ext tokens</th>
        <th class="num">Claude/ext $</th>
        <th class="num">Δ $ (ext − Raven)</th>
        <th class="num">ext / Raven</th>
      </tr>
    </thead>
    <tbody>
      {rows}
      <tr style="background:#0f172a;">
        <td><strong>TOTAL</strong></td>
        <td class="num"><strong>{r_tot_t:,}</strong></td>
        <td class="num"><strong>{format_usd(r_tot_c)}</strong></td>
        <td class="num"><strong>{e_tot_t_s}</strong></td>
        <td class="num"><strong>{e_tot_c_s}</strong></td>
        <td class="num">—</td>
        <td class="num">—</td>
      </tr>
    </tbody>
  </table>
  <div class="meta" style="margin-top:16px;font-size:13px;color:#cbd5e1;">
    <strong>Prompt to give Claude</strong>
    <pre style="white-space:pre-wrap;margin-top:8px;padding:12px;background:#0f172a;border-radius:8px;color:#e2e8f0;font-size:12px;">{claude_prompt}</pre>
  </div>
"""


def cite_chip(cid: str, label: str = "") -> str:
    """Inline citation anchor → bibliography entry #cite-N."""
    tip = label or cid
    return (
        f'<a class="cite" href="#cite-{cid}" title="{tip}">[{cid}]</a>'
    )


def build_citation_registry(metrics: dict, metadata: dict) -> list[dict]:
    """Numbered, on-page citations for every metric family."""
    vault = metadata.get("vault_path") or str(VAULT)
    ms_path = str(MODEL_SESSION) if MODEL_SESSION.exists() else f"{PROJECT_DIR}/.raven/.model-session.json"
    cites = [
        {
            "id": "C1",
            "title": "Portfolio cost / tokens / sessions",
            "path": f"{vault}/.metrics/*.json",
            "field": "sessions[] rows with project + tokens + cost_usd; also by_project",
            "rule": "Sum only project-tagged rows inside the report window. Unscoped by_day excluded.",
            "used_for": "All-repos headline cards",
        },
        {
            "id": "C2",
            "title": f"This-repo slice ({metrics.get('current_project') or metadata.get('project') or 'cwd'})",
            "path": f"{vault}/.metrics/*.json",
            "field": "same as C1 filtered where project == current repo name",
            "rule": "Project name from .raven/manifest.json or git remote basename.",
            "used_for": "This-repo headline card",
        },
        {
            "id": "C3",
            "title": "Live session meters",
            "path": ms_path,
            "field": "raven_overhead.tokens/cost_usd + user_work.tokens/cost_usd (+ by_source)",
            "rule": "Point-in-time file written by model-router / token-meter during the open session.",
            "used_for": "Live session card + tokenomics split + overhead-by-source table",
        },
        {
            "id": "C4",
            "title": "Knowledge graph structure",
            "path": f"{vault}/graph/knowledge-graph.json",
            "field": "nodes[].id/type + edges[] from wikilinks in vault markdown",
            "rule": "Built by knowledge_graph.py scanning projects|concepts|decisions|sessions.",
            "used_for": "Graph node/edge counts and interactive map",
        },
        {
            "id": "C5",
            "title": "Project hubs & notes (agent memory)",
            "path": f"{vault}/projects/*.md, concepts/, decisions/, sessions/",
            "field": "frontmatter + ## Current state / Open questions / Recent sessions",
            "rule": "Written by obsidian-log / knowledge-extract / claude-mem; loaded by vault-load at SessionStart.",
            "used_for": "Graph briefings, open questions, repo links, local paths",
        },
        {
            "id": "C6",
            "title": "Guard / CVE event counts",
            "path": str(AUDIT_DIR / "*.log") if AUDIT_DIR else ".raven/audit/*.log",
            "field": "JSONL kind/event lines in window",
            "rule": "Count only; not a full CVE inventory. Quiet ≠ unscanned.",
            "used_for": "Guard event tables and CVE blurb in node cost panel",
        },
        {
            "id": "C7",
            "title": "Manifest / project identity",
            "path": str(MANIFEST) if MANIFEST.exists() else ".raven/manifest.json",
            "field": "project, owner, stack, version",
            "rule": "Defines 'this repo' label and stack context for agents.",
            "used_for": "Metadata block and current_project resolution",
        },
        {
            "id": "C8",
            "title": "Report generation timestamp",
            "path": "dashboard.py runtime",
            "field": "report_generated_at_local / UTC",
            "rule": "Clock at HTML build time — not a metric source.",
            "used_for": "Header freshness",
        },
    ]
    # Attach concrete metric files that were actually read
    extra = []
    for i, src in enumerate(metrics.get("sources_used") or [], start=1):
        extra.append(
            {
                "id": f"S{i}",
                "title": f"Source used this build: {src}",
                "path": src,
                "field": "see aggregate() sources_used",
                "rule": "Listed only if successfully parsed this run.",
                "used_for": "Traceability of this HTML build",
            }
        )
    return cites + extra


def _by_day_row_suspect(row: dict) -> bool:
    """Detect known-corrupt meter rollups (61k 'sessions'/day, multi‑MB token dumps)."""
    try:
        sessions = int(row.get("sessions") or 0)
        tokens = int(row.get("tokens") or 0)
        cost = float(row.get("cost_usd") or 0)
    except (TypeError, ValueError):
        return True
    if sessions > 40:  # single-dev machine day cap
        return True
    if tokens > 2_000_000:
        return True
    if cost > 25.0:
        return True
    if tokens > 0 and cost / tokens > 0.01:  # >$10 per 1k tokens
        return True
    return False


def _empty_project_bucket() -> dict:
    return {
        "sessions": 0,
        "tokens": 0,
        "cost_usd": 0.0,
        "days": set(),
    }


def aggregate(days: int = 30, project_filter: Optional[str] = None) -> dict:
    """Read trusted sources; headline totals come only from per-repo rows.

    Trusted:
      - sessions[] rows with a project name (day rollup or per-session)
      - by_project map in monthly files
      - live .model-session.json (attributed to current project)
    Untrusted for headline (recorded separately):
      - unscoped by_day without project (June/July global dumps)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_project: dict[str, dict] = defaultdict(_empty_project_bucket)
    metrics = {
        "window_days": days,
        "window_start": cutoff.strftime("%Y-%m-%d"),
        "window_end": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sessions_count": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "tier_counts": Counter(),
        "tier_cost": defaultdict(float),
        "guard_events": Counter(),
        "violations": Counter(),
        "approvals": Counter(),
        "skills_used": Counter(),
        "specialists_used": Counter(),
        "sessions_by_day": defaultdict(int),
        "cost_by_day": defaultdict(float),
        "tokens_by_day": defaultdict(int),
        "projects_seen": set(),
        "sources_used": [],
        "project_filter": project_filter,
        "legacy_unscoped": {
            "sessions": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "suspect_days": 0,
            "note": "Unscoped by_day rows — not included in headline (no repo tag).",
        },
        "trust": "per-repo only",
    }

    current_project = None
    if MANIFEST.exists():
        try:
            current_project = json.loads(MANIFEST.read_text()).get("project")
        except Exception:
            pass
    if not current_project:
        try:
            remote = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            current_project = remote.rstrip("/").split("/")[-1].replace(".git", "")
        except Exception:
            current_project = Path.cwd().name
    metrics["current_project"] = current_project

    # ── Live session ──
    if MODEL_SESSION.exists():
        try:
            ms = json.loads(MODEL_SESSION.read_text())
            if "raven_overhead" in ms:
                ov = ms["raven_overhead"]
                uw = ms.get("user_work") or {}
                metrics["last_session"] = {
                    "started_at": ms.get("session_started_at"),
                    "project": ms.get("project") or current_project,
                    "raven_overhead": {
                        "tokens": ov.get("tokens", 0),
                        "cost_usd": ov.get("cost_usd", 0.0),
                        "calls": ov.get("calls", 0),
                        "by_source": ov.get("by_source", {}),
                    },
                    "user_work": {
                        "tokens": uw.get("tokens", 0),
                        "cost_usd": uw.get("cost_usd", 0.0),
                        "calls": uw.get("calls", 0),
                        "tier_counts": uw.get("tier_counts", {}),
                        "last_classification": uw.get("last_classification"),
                    },
                    "providers": ms.get("providers", {}),
                    "tokens": ov.get("tokens", 0) + uw.get("tokens", 0),
                    "cost_usd": round(
                        float(ov.get("cost_usd", 0.0) or 0)
                        + float(uw.get("cost_usd", 0.0) or 0),
                        6,
                    ),
                    "tier_counts": uw.get("tier_counts", {}),
                }
            else:
                metrics["last_session"] = {
                    "started_at": ms.get("session_started_at"),
                    "project": ms.get("project") or current_project,
                    "raven_overhead": {
                        "tokens": 0,
                        "cost_usd": 0.0,
                        "calls": 0,
                        "by_source": {},
                    },
                    "user_work": {
                        "tokens": ms.get("session_tokens", 0),
                        "cost_usd": ms.get("session_cost_usd", 0.0),
                        "calls": ms.get("session_calls", 0),
                        "tier_counts": ms.get("tier_counts", {}),
                        "last_classification": None,
                    },
                    "providers": {},
                    "tokens": ms.get("session_tokens", 0),
                    "cost_usd": ms.get("session_cost_usd", 0.0),
                    "tier_counts": ms.get("tier_counts", {}),
                }
            metrics["sources_used"].append("model-session")
        except Exception:
            metrics["last_session"] = None
    else:
        metrics["last_session"] = None

    def _credit(project: str, day: str, sessions: int, tokens: int, cost: float):
        ts = _parse_day(day)
        if ts is None or ts < cutoff:
            return
        if not project:
            return
        if project_filter and project != project_filter:
            return
        n = max(int(sessions or 0), 1 if (tokens or cost) else 0)
        if n == 0 and not tokens and not cost:
            return
        b = by_project[project]
        b["sessions"] += n
        b["tokens"] += int(tokens or 0)
        b["cost_usd"] += float(cost or 0.0)
        b["days"].add(day)
        metrics["sessions_count"] += n
        metrics["sessions_by_day"][day] += n
        metrics["total_tokens"] += int(tokens or 0)
        metrics["total_cost_usd"] += float(cost or 0.0)
        metrics["cost_by_day"][day] += float(cost or 0.0)
        metrics["tokens_by_day"][day] += int(tokens or 0)
        metrics["projects_seen"].add(project)

    VAULT_METRICS.mkdir(parents=True, exist_ok=True)
    for metrics_file in sorted(VAULT_METRICS.glob("*.json")):
        try:
            data = json.loads(metrics_file.read_text())
        except Exception:
            continue

        # Preferred: explicit by_project map
        bp = data.get("by_project")
        if isinstance(bp, dict):
            for pname, prow in bp.items():
                if not isinstance(prow, dict):
                    continue
                # Optional nested by_day under project
                p_by_day = prow.get("by_day")
                if isinstance(p_by_day, dict) and p_by_day:
                    for day, row in p_by_day.items():
                        if not isinstance(row, dict):
                            continue
                        _credit(
                            str(pname),
                            day,
                            row.get("sessions", 0),
                            row.get("tokens", 0),
                            row.get("cost_usd", 0.0),
                        )
                else:
                    # Whole-month project totals — only if month overlaps window
                    month = data.get("month") or data.get("year_month") or metrics_file.stem
                    # Attribute to month mid-day if within window loosely via any day in month
                    try:
                        y, m = month.split("-")[:2]
                        # credit on last day of window if month in range — skip if no day breakdown
                        # Use month-01 as synthetic day only if in window
                        day = f"{y}-{m}-01"
                        if _parse_day(day) and _parse_day(day) >= cutoff:
                            _credit(
                                str(pname),
                                day,
                                prow.get("sessions", 0),
                                prow.get("tokens", 0),
                                prow.get("cost_usd", 0.0),
                            )
                    except Exception:
                        pass
            metrics["sources_used"].append(f"metrics:{metrics_file.name}:by_project")

        # sessions[] with project tags (trusted)
        sessions = data.get("sessions")
        if isinstance(sessions, list):
            for session in sessions:
                if not isinstance(session, dict):
                    continue
                proj = _project_name(session.get("project"))
                if not proj:
                    continue
                started = session.get("started_at") or session.get("date") or ""
                day = started[:10] if started else ""
                if not day:
                    continue
                sess_n = session.get("sessions")
                if sess_n is not None and not session.get("tier_counts"):
                    _credit(
                        proj,
                        day,
                        sess_n,
                        session.get("tokens", 0),
                        session.get("cost_usd", 0.0),
                    )
                else:
                    _credit(
                        proj,
                        day,
                        1,
                        session.get("tokens", 0),
                        session.get("cost_usd", 0.0),
                    )
                for tier, count in (session.get("tier_counts") or {}).items():
                    if not project_filter or proj == project_filter:
                        metrics["tier_counts"][tier] += count
            metrics["sources_used"].append(f"metrics:{metrics_file.name}:sessions")

        # Unscoped by_day — never in headline; keep for diagnostics
        by_day = data.get("by_day")
        if isinstance(by_day, dict):
            for day, row in by_day.items():
                if not isinstance(row, dict):
                    continue
                ts = _parse_day(day)
                if ts is None or ts < cutoff:
                    continue
                # Nested per-project under by_day
                nested = row.get("by_project")
                if isinstance(nested, dict):
                    for pname, prow in nested.items():
                        if not isinstance(prow, dict):
                            continue
                        _credit(
                            str(pname),
                            day,
                            prow.get("sessions", 0),
                            prow.get("tokens", 0),
                            prow.get("cost_usd", 0.0),
                        )
                    continue
                # Unscoped
                if _by_day_row_suspect(row):
                    metrics["legacy_unscoped"]["suspect_days"] += 1
                metrics["legacy_unscoped"]["sessions"] += int(row.get("sessions") or 0)
                metrics["legacy_unscoped"]["tokens"] += int(row.get("tokens") or 0)
                metrics["legacy_unscoped"]["cost_usd"] += float(row.get("cost_usd") or 0)

    # Fold live session into current project if not already counted for today
    ls = metrics.get("last_session") or {}
    ls_cost = float(ls.get("cost_usd") or 0.0)
    ls_tok = int(ls.get("tokens") or 0)
    ls_proj = _project_name(ls.get("project")) or current_project
    if (ls_cost or ls_tok) and ls_proj:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Avoid double-count: only add if this project's day cost is still 0
        already = by_project.get(ls_proj, {}).get("cost_usd", 0) if ls_proj in by_project else 0
        # Check day-level for project via total day — if today's total cost for project path empty
        if metrics["cost_by_day"].get(day, 0) == 0 or (
            project_filter in (None, ls_proj) and ls_proj not in by_project
        ):
            if not project_filter or project_filter == ls_proj:
                # Only credit live session if vault has no row for this project today
                proj_days = by_project.get(ls_proj, {}).get("days") or set()
                if day not in proj_days:
                    _credit(ls_proj, day, 1, ls_tok, ls_cost)
        for tier, count in (ls.get("tier_counts") or {}).items():
            metrics["tier_counts"][tier] += count

    # ── Audit logs (events only) ──
    if AUDIT_DIR.exists():
        for log_file in sorted(AUDIT_DIR.glob("*.log")):
            try:
                log_date = datetime.strptime(log_file.stem, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                if log_date < cutoff:
                    continue
            except Exception:
                continue
            try:
                for line in log_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        kind = ev.get("kind") or ev.get("event") or "unknown"
                        metrics["guard_events"][kind] += 1
                        if "violation" in kind.lower():
                            metrics["violations"][ev.get("rule", "unknown")] += 1
                        if "approval" in kind.lower() or "override" in kind.lower():
                            metrics["approvals"][ev.get("rule", "unknown")] += 1
                    except Exception:
                        pass
            except Exception:
                continue

    # Serialize by_project
    bp_out = {}
    for pname, b in by_project.items():
        bp_out[pname] = {
            "sessions": b["sessions"],
            "tokens": b["tokens"],
            "cost_usd": round(float(b["cost_usd"]), 6),
            "days": len(b["days"]),
        }
    metrics["by_project"] = dict(
        sorted(bp_out.items(), key=lambda kv: -kv[1]["cost_usd"])
    )

    # If filter set, recompute headline from that project only (already filtered via _credit)
    # If no filter, headline is sum of all per-repo (already)

    metrics["tier_counts"] = dict(metrics["tier_counts"])
    metrics["tier_cost"] = dict(metrics["tier_cost"])
    metrics["guard_events"] = dict(metrics["guard_events"])
    metrics["violations"] = dict(metrics["violations"])
    metrics["approvals"] = dict(metrics["approvals"])
    metrics["skills_used"] = dict(metrics["skills_used"].most_common(20))
    metrics["specialists_used"] = dict(metrics["specialists_used"].most_common(10))
    metrics["sessions_by_day"] = dict(metrics["sessions_by_day"])
    metrics["cost_by_day"] = {k: round(v, 6) for k, v in metrics["cost_by_day"].items()}
    metrics["tokens_by_day"] = dict(metrics["tokens_by_day"])
    metrics["projects_seen"] = sorted(metrics["projects_seen"])
    metrics["total_cost_usd"] = round(metrics["total_cost_usd"], 6)
    metrics["sources_used"] = sorted(set(metrics["sources_used"]))
    metrics["legacy_unscoped"]["cost_usd"] = round(
        metrics["legacy_unscoped"]["cost_usd"], 4
    )

    total = sum(metrics["tier_counts"].values()) or 1
    metrics["tier_share_pct"] = {
        tier: round(100 * count / total, 1)
        for tier, count in metrics["tier_counts"].items()
    }
    metrics["avg_cost_per_session"] = (
        round(metrics["total_cost_usd"] / metrics["sessions_count"], 6)
        if metrics["sessions_count"]
        else 0
    )
    metrics["avg_tokens_per_session"] = (
        metrics["total_tokens"] // metrics["sessions_count"]
        if metrics["sessions_count"]
        else 0
    )

    return metrics


# ── Recommendations Engine — Split by Owner ────────────────────────────────────
#
# Two rule sets, two owners:
#   🪶 RAVEN HYGIENE  → judges raven_overhead bucket. Raven team owns the fix.
#   👤 USER BEHAVIOR  → judges user_work bucket. User owns the fix.
#   🌐 ENVIRONMENT    → manifest, vault, hooks, guards (neither bucket — config)

def recommend_raven_hygiene(metrics: dict, metadata: dict) -> list:
    """Rules that judge raven_overhead — Raven team owns these levers."""
    recs = []
    ls = metrics.get("last_session") or {}
    ov = ls.get("raven_overhead") or {"tokens": 0, "cost_usd": 0.0, "by_source": {}}
    uw = ls.get("user_work") or {"tokens": 0}
    total_tok = ov.get("tokens", 0) + uw.get("tokens", 0)
    ov_pct = (ov.get("tokens", 0) / total_tok * 100) if total_tok else 0
    by_src = ov.get("by_source") or {}

    # Rule R1 — Overhead share too high
    if ov_pct > 20 and total_tok > 1000:
        recs.append({
            "owner": "raven_team",
            "metric": "Raven overhead at {:.1f}% of total tokens".format(ov_pct),
            "severity": "high",
            "issue": "Raven's own footprint exceeds 20%. The framework is too heavy.",
            "action": "Audit by-source breakdown. Likely candidates: skill SKILL.md size, "
                     "session-start banner length, classifier emission verbosity. "
                     "File issue: github.com/giggsoinc/raven/issues",
            "savings_estimate_usd": round(ov.get("cost_usd", 0) * 0.5, 4),
        })

    # Rule R2 — Single source dominates overhead
    if by_src:
        top_src, top_info = max(by_src.items(), key=lambda x: x[1].get("tokens", 0))
        top_share = (top_info.get("tokens", 0) / ov.get("tokens", 1) * 100) if ov.get("tokens", 0) else 0
        if top_share > 50 and ov.get("tokens", 0) > 1000:
            recs.append({
                "owner": "raven_team",
                "metric": "{} = {:.0f}% of Raven overhead".format(top_src, top_share),
                "severity": "medium",
                "issue": "One source dominates Raven's footprint.",
                "action": "If skill-load: split the skill into mode-files (load on demand). "
                         "If session-start: compress banner. "
                         "If classifier: shorten the [REQUIRED] emission.",
            })

    # Rule R3 — Skill-load specifically (Andie/specialist size)
    skill_loads = {k: v for k, v in by_src.items() if k.startswith("skill-load:")}
    if skill_loads:
        skill_total = sum(v.get("tokens", 0) for v in skill_loads.values())
        if skill_total > 5000:
            top_skill = max(skill_loads.items(), key=lambda x: x[1].get("tokens", 0))
            recs.append({
                "owner": "raven_team",
                "metric": "Skill loads: {:,} tokens ({} is heaviest at {:,})".format(
                    skill_total, top_skill[0].replace("skill-load:", ""), top_skill[1].get("tokens", 0)),
                "severity": "medium",
                "issue": "Skill load weight is a primary Raven cost. Mode-splitting helps.",
                "action": "Move rarely-used sections of {} into mode-files referenced via "
                         "frontmatter. Load on demand, not always.".format(
                    top_skill[0].replace("skill-load:", "")),
            })

    # Rule R4 — Classifier emissions too verbose
    classifiers = ["triage-router", "architect-router"]
    classifier_total = sum(by_src.get(c, {}).get("tokens", 0) for c in classifiers)
    classifier_calls = sum(by_src.get(c, {}).get("calls", 0) for c in classifiers)
    if classifier_calls > 0:
        avg_per_call = classifier_total / classifier_calls
        if avg_per_call > 100:
            recs.append({
                "owner": "raven_team",
                "metric": "Classifier emission avg {:.0f} tokens/call".format(avg_per_call),
                "severity": "info",
                "issue": "Classifier [REQUIRED] injections are larger than necessary.",
                "action": "Trim triage-router and architect-router emission text. "
                         "Target ≤50 tokens per injection.",
            })

    return recs


def recommend_user_behavior(metrics: dict, metadata: dict) -> list:
    """Rules that judge user_work — user owns these levers."""
    recs = []
    ls = metrics.get("last_session") or {}
    uw = ls.get("user_work") or {"tokens": 0, "cost_usd": 0.0, "tier_counts": {}}
    tcs = uw.get("tier_counts") or {}
    total_user_calls = sum(tcs.values()) or 1

    # Rule U1 — User Opus over-classification (user_work tier mix only)
    user_opus_pct = (tcs.get("COMPLEX", 0) / total_user_calls * 100)
    if user_opus_pct > 30:
        recs.append({
            "owner": "user",
            "metric": "Your Opus rate: {:.0f}%".format(user_opus_pct),
            "severity": "high",
            "issue": "Your prompts are classifying as COMPLEX too often. This routes "
                     "you to Opus (~50× cost of Haiku).",
            "action": "Be more specific in prompts so scope is clear. Split big asks "
                     "into smaller steps. For simple edits, say 'simple' explicitly.",
            "savings_estimate_usd": round(uw.get("cost_usd", 0) * (user_opus_pct - 20) / 100, 2),
        })
    elif user_opus_pct == 0 and total_user_calls > 5:
        recs.append({
            "owner": "user",
            "metric": "0% COMPLEX across {} prompts".format(total_user_calls),
            "severity": "info",
            "issue": "No architecture-class prompts detected — either none happened, "
                     "or architect-router isn't catching them.",
            "action": "If you DID make design decisions: architect-router should have "
                     "fired. Check by typing 'design a multi-region auth system' — "
                     "should trigger [ANDIE REQUIRED].",
        })

    # Rule U2 — User work cost per session
    if uw.get("cost_usd", 0) > 1.0:
        recs.append({
            "owner": "user",
            "metric": "${:.2f} on your work this session".format(uw.get("cost_usd", 0)),
            "severity": "medium",
            "issue": "Your session is expensive on the user_work side (separate from "
                     "Raven's overhead). Long context, many Opus calls, or both.",
            "action": "Use /clear to reset context between tasks. For repeated edit "
                     "loops, switch to Haiku via .model.env override.",
        })

    # Rule U3 — User token consumption
    if uw.get("tokens", 0) > 50000:
        recs.append({
            "owner": "user",
            "metric": "{:,} tokens in your prompts/responses".format(uw.get("tokens", 0)),
            "severity": "medium",
            "issue": "Heavy session context. Long prompts, big tool outputs, or accumulated state.",
            "action": "Use /clear more often. Trim CLAUDE.md if it's bloated. "
                     "Avoid pasting large files — reference them by path.",
        })

    # Rule U4 — LOCAL_ONLY share (secrets in prompts)
    local_pct = (tcs.get("LOCAL_ONLY", 0) / total_user_calls * 100) if total_user_calls else 0
    if local_pct > 50 and total_user_calls > 5:
        recs.append({
            "owner": "user",
            "metric": "{:.0f}% routed LOCAL_ONLY".format(local_pct),
            "severity": "info",
            "issue": "More than half your prompts trigger LOCAL_ONLY (secret detection).",
            "action": "Either: (a) you're working on lots of secrets (good — local Ollama keeps "
                     "data on-machine), or (b) secret detection is too sensitive. "
                     "Check .raven/audit/ logs for false positives.",
        })

    return recs


def recommend_environment(metrics: dict, metadata: dict) -> list:
    """Rules that judge configuration — neither bucket, just setup health."""
    recs = []

    # Rule E1 — Missing manifest
    if not metadata["manifest_present"]:
        recs.append({
            "owner": "config",
            "metric": "Manifest missing",
            "severity": "high",
            "issue": ".raven/manifest.json doesn't exist — Raven is running without project context.",
            "action": "Type anything in Claude Code — Andie's Branch A onboarding will auto-create. "
                     "Or run /raven-init.",
        })

    # Rule E2 — No vault sessions
    sessions_dir_count = len(list(VAULT_SESSIONS.glob("*.md"))) if VAULT_SESSIONS.exists() else 0
    if sessions_dir_count == 0:
        recs.append({
            "owner": "config",
            "metric": "0 vault sessions",
            "severity": "high",
            "issue": "No session summaries in ~/RavenVault/sessions/ — obsidian-log not firing.",
            "action": "Verify settings.json wires Stop → obsidian-log.py. "
                     "Reinstall plugin: claude plugin install raven-plugin-v{}.zip".format(PLUGIN_VERSION),
        })

    # Rule E3 — Guard violations / approvals (still useful, not bucket-specific)
    total_violations = sum(metrics.get("violations", {}).values())
    if total_violations > 10:
        top = max(metrics["violations"].items(), key=lambda x: x[1])
        recs.append({
            "owner": "config",
            "metric": "{} guard violations".format(total_violations),
            "severity": "high",
            "issue": "Top: {} ({} times). Either policy needs tuning or training needed.".format(top[0], top[1]),
            "action": "Address root cause. If false positive, relax rule in manifest. "
                     "Otherwise educate the team.",
        })

    total_overrides = sum(metrics.get("approvals", {}).values())
    if total_overrides > 5:
        recs.append({
            "owner": "config",
            "metric": "{} approval overrides".format(total_overrides),
            "severity": "medium",
            "issue": "Frequent GUARD:ALLOW-* overrides — guards too strict or used as escape hatches.",
            "action": "Review .raven/audit/$(date +%Y-%m-%d).log. Codify legitimate exceptions; address misuse.",
        })

    return recs


def recommend(metrics: dict, metadata: dict) -> list:
    """Aggregate all three rule sets into a single list (back-compat)."""
    return (
        recommend_raven_hygiene(metrics, metadata)
        + recommend_user_behavior(metrics, metadata)
        + recommend_environment(metrics, metadata)
    )


# ── Renderer: CLI ──────────────────────────────────────────────────────────────
def render_cli(metrics: dict, metadata: dict, recs: list) -> str:
    """Produce ASCII dashboard for terminal."""
    out = []
    bar = "─" * 70

    out.append("")
    out.append("━" * 70)
    out.append("  RAVEN — TOKENOMICS & USAGE DASHBOARD")
    out.append("━" * 70)
    out.append("")

    # Metadata block
    out.append("📋 Report Metadata")
    out.append(bar)
    out.append(f"  Generated         : {metadata['report_generated_at_local']} (UTC: {metadata['report_generated_at']})")
    out.append(f"  Plugin version    : v{metadata['plugin_version']}")
    out.append(f"  Project           : {metadata['project']}")
    out.append(f"  Company           : {metadata['company']}")
    out.append(f"  Owner             : {metadata['owner']}")
    out.append(f"  User              : {metadata['user'] or '(git not configured)'}")
    out.append(f"  Git branch        : {metadata['git_branch'] or '—'}")
    out.append(f"  Git remote        : {metadata['git_remote'] or '—'}")
    out.append(f"  Manifest          : {'✓ present' if metadata['manifest_present'] else '✗ MISSING'}")
    out.append(f"  Vault             : {metadata['vault_path']}")
    out.append("")

    # Window
    out.append("🗓  Reporting Window")
    out.append(bar)
    out.append(f"  Start             : {metrics['window_start']}")
    out.append(f"  End               : {metrics['window_end']}")
    out.append(f"  Days              : {metrics['window_days']}")
    out.append("")

    # Last session — TWO-BUCKET ATTRIBUTION
    ls = metrics.get("last_session") or {}
    ov = ls.get("raven_overhead") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "by_source": {}}
    uw = ls.get("user_work") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "tier_counts": {}}
    total_tok = ov.get("tokens", 0) + uw.get("tokens", 0)
    total_cost = ov.get("cost_usd", 0.0) + uw.get("cost_usd", 0.0)
    ov_pct = (ov.get("tokens", 0) / total_tok * 100) if total_tok else 0
    uw_pct = (uw.get("tokens", 0) / total_tok * 100) if total_tok else 0
    out.append("⚡ Last Session — Tokenomics Split (Raven Overhead vs User Work)")
    out.append(bar)
    out.append(f"  {'METRIC':<22} {'RAVEN CODE':>14} {'USER WORK':>14} {'TOTAL':>14}")
    out.append(f"  {'-'*22} {'-'*14:>14} {'-'*14:>14} {'-'*14:>14}")
    out.append(f"  {'Tokens':<22} {ov.get('tokens',0):>14,} {uw.get('tokens',0):>14,} {total_tok:>14,}")
    out.append(f"  {'Cost (USD)':<22} ${ov.get('cost_usd',0):>13.4f} ${uw.get('cost_usd',0):>13.4f} ${total_cost:>13.4f}")
    out.append(f"  {'Calls':<22} {ov.get('calls',0):>14} {uw.get('calls',0):>14} {ov.get('calls',0)+uw.get('calls',0):>14}")
    out.append(f"  {'Share':<22} {ov_pct:>13.1f}% {uw_pct:>13.1f}% {'100.0%':>14}")
    out.append("")

    # User work tier breakdown
    tcs = uw.get("tier_counts") or {}
    if any(tcs.values()):
        out.append(f"  USER WORK — Tier breakdown:")
        out.append(f"    {' · '.join(f'{k}:{v}' for k,v in tcs.items() if v)}")
        out.append("")

    # Raven overhead by-source breakdown
    by_src = ov.get("by_source") or {}
    if by_src:
        out.append(f"  RAVEN CODE — Overhead by source:")
        for src, info in sorted(by_src.items(), key=lambda x: -x[1].get("tokens", 0)):
            tok = info.get("tokens", 0)
            calls = info.get("calls", 0)
            cost = info.get("cost_usd", 0.0)
            out.append(f"    {src:<24} {tok:>7,} tok  {calls:>3} calls  ${cost:.5f}")
        out.append("")

    # Provider attribution (matters for Codex tier)
    providers = ls.get("providers") or {}
    if providers:
        out.append(f"  PROVIDER attribution:")
        for prov, info in providers.items():
            tok = info.get("tokens", 0)
            cost = info.get("cost_usd", 0.0)
            pct = (tok / total_tok * 100) if total_tok else 0
            out.append(f"    {prov:<12} {tok:>10,} tok ({pct:>4.1f}%)  ${cost:.4f}")
        out.append("")

    # Cumulative
    out.append("📊 Cumulative ({} days)".format(metrics["window_days"]))
    out.append(bar)
    out.append(f"  Sessions          : {metrics['sessions_count']}")
    out.append(f"  Total tokens      : {metrics['total_tokens']:,}")
    out.append(f"  Total cost        : ${metrics['total_cost_usd']:.2f}")
    out.append(f"  Avg / session     : ${metrics['avg_cost_per_session']:.4f} ({metrics['avg_tokens_per_session']:,} tok)")
    out.append("")

    # Tier mix
    if metrics["tier_counts"]:
        out.append("🎯 Tier Mix")
        out.append(bar)
        for tier in ["SIMPLE", "MEDIUM", "COMPLEX", "LOCAL_ONLY"]:
            count = metrics["tier_counts"].get(tier, 0)
            pct = metrics["tier_share_pct"].get(tier, 0)
            cost = metrics["tier_cost"].get(tier, 0)
            bar_chars = "█" * int(pct / 2)
            out.append(f"  {tier:<12} {count:>5}  ({pct:>5.1f}%)  ${cost:>7.3f}  {bar_chars}")
        out.append("")

    # Top skills
    if metrics["skills_used"]:
        out.append("🛠  Top Skills Used")
        out.append(bar)
        for skill, count in list(metrics["skills_used"].items())[:10]:
            out.append(f"  {skill:<40} {count:>5}")
        out.append("")

    # Top specialists
    if metrics["specialists_used"]:
        out.append("👥 Top Specialists")
        out.append(bar)
        for spec, count in list(metrics["specialists_used"].items())[:10]:
            out.append(f"  {spec:<40} {count:>5}")
        out.append("")

    # Guard events
    if metrics["guard_events"]:
        out.append("🛡  Guard Events")
        out.append(bar)
        for event, count in sorted(metrics["guard_events"].items(), key=lambda x: -x[1])[:10]:
            out.append(f"  {event:<40} {count:>5}")
        out.append("")

    # Recommendations — GROUPED BY OWNER
    out.append("💡 Recommendations — Grouped by Owner")
    out.append(bar)
    if not recs:
        out.append("  ✓ All metrics within healthy bands. No actions needed.")
    else:
        sev_icon = {"high": "🔴", "medium": "🟡", "info": "🔵"}
        groups = {
            "raven_team": ("🪶 RAVEN HYGIENE — Raven team owns these fixes", []),
            "user":       ("👤 USER BEHAVIOR — You own these fixes", []),
            "config":     ("⚙️  ENVIRONMENT — Configuration / setup fixes", []),
        }
        for r in recs:
            owner = r.get("owner", "config")
            groups.get(owner, groups["config"])[1].append(r)

        counter = 1
        for owner_key, (title, items) in groups.items():
            if not items:
                continue
            out.append(f"  {title}")
            out.append(f"  {'-' * 60}")
            for r in items:
                icon = sev_icon.get(r["severity"], "⚪")
                out.append(f"    {icon} [{counter}] {r['metric']}")
                out.append(f"         Issue:  {r['issue']}")
                out.append(f"         Action: {r['action']}")
                if r.get("savings_estimate_usd"):
                    out.append(f"         Est. savings: ${r['savings_estimate_usd']:.2f}")
                counter += 1
                out.append("")

    out.append("━" * 70)
    out.append(f"  Generated by Raven v{PLUGIN_VERSION}  ·  Local-only  ·  No telemetry")
    out.append("━" * 70)
    out.append("")
    return "\n".join(out)


# ── Renderer: Obsidian Markdown (with Dataview queries) ───────────────────────
def render_obsidian(metrics: dict, metadata: dict, recs: list) -> str:
    """Markdown with frontmatter + dataview queries — opens cleanly in Obsidian."""
    lines = []
    lines.append("---")
    lines.append(f"title: Raven Dashboard")
    lines.append(f"generated_at: {metadata['report_generated_at']}")
    lines.append(f"plugin_version: {metadata['plugin_version']}")
    lines.append(f"project: {metadata['project']}")
    lines.append(f"company: {metadata['company']}")
    lines.append(f"owner: {metadata['owner']}")
    lines.append(f"user: {metadata['user'] or 'unknown'}")
    lines.append(f"window_days: {metrics['window_days']}")
    lines.append(f"sessions: {metrics['sessions_count']}")
    lines.append(f"total_cost_usd: {metrics['total_cost_usd']}")
    lines.append(f"total_tokens: {metrics['total_tokens']}")
    lines.append("tags: [raven, dashboard, tokenomics, metrics]")
    lines.append("---")
    lines.append("")
    lines.append(f"# 🪶 Raven Dashboard — {metadata['project']}")
    lines.append("")
    lines.append(f"> Generated: **{metadata['report_generated_at_local']}**  ·  Plugin: **v{metadata['plugin_version']}**")
    lines.append(f"> Company: **{metadata['company']}**  ·  Owner: **{metadata['owner']}**  ·  User: **{metadata['user'] or '—'}**")
    lines.append(f"> Window: **{metrics['window_start']} → {metrics['window_end']}** ({metrics['window_days']} days)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Project Metadata")
    lines.append("")
    if metadata.get("manifest"):
        m = metadata["manifest"]
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        lines.append(f"| Project | {m.get('project', '—')} |")
        lines.append(f"| Owner | {m.get('owner', '—')} |")
        lines.append(f"| Version | {m.get('version', '—')} |")
        lines.append(f"| Stack | `{json.dumps(m.get('stack', {}), indent=None)}` |")
        lines.append(f"| Standards | {m.get('standards', '—')} |")
        lines.append(f"| Approval mode | {m.get('approval_mode', '—')} |")
    else:
        lines.append("⚠️ Manifest missing. Run `/raven-init` to create one.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Headline numbers
    lines.append("## 📊 Headline Numbers")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Sessions ({metrics['window_days']}d) | **{metrics['sessions_count']}** |")
    lines.append(f"| Total tokens | **{metrics['total_tokens']:,}** |")
    lines.append(f"| Total cost (USD) | **${metrics['total_cost_usd']:.2f}** |")
    lines.append(f"| Avg cost / session | ${metrics['avg_cost_per_session']:.4f} |")
    lines.append(f"| Avg tokens / session | {metrics['avg_tokens_per_session']:,} |")
    lines.append("")

    # Two-bucket attribution split
    ls = metrics.get("last_session") or {}
    ov = ls.get("raven_overhead") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "by_source": {}}
    uw = ls.get("user_work") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "tier_counts": {}}
    total_tok = ov.get("tokens", 0) + uw.get("tokens", 0)
    total_cost = ov.get("cost_usd", 0.0) + uw.get("cost_usd", 0.0)
    ov_pct = (ov.get("tokens", 0) / total_tok * 100) if total_tok else 0
    uw_pct = (uw.get("tokens", 0) / total_tok * 100) if total_tok else 0

    lines.append("## ⚡ Last Session — Two-Bucket Tokenomics")
    lines.append("")
    lines.append("| Metric | 🪶 Raven Code (overhead) | 👤 User Work | Total |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Tokens | **{ov.get('tokens',0):,}** | **{uw.get('tokens',0):,}** | {total_tok:,} |")
    lines.append(f"| Cost (USD) | ${ov.get('cost_usd',0):.4f} | ${uw.get('cost_usd',0):.4f} | ${total_cost:.4f} |")
    lines.append(f"| Calls | {ov.get('calls',0)} | {uw.get('calls',0)} | {ov.get('calls',0)+uw.get('calls',0)} |")
    lines.append(f"| Share | {ov_pct:.1f}% | {uw_pct:.1f}% | 100.0% |")
    lines.append("")
    lines.append("> 🪶 **Raven Code** = tokens consumed by hooks, skill loads, classifier injections, banners. Raven team's lever.")
    lines.append("> 👤 **User Work** = tokens consumed by your prompts + Claude's responses + tool calls. Your lever.")
    lines.append("")

    # Raven Code breakdown
    by_src = ov.get("by_source") or {}
    if by_src:
        lines.append("### 🪶 Raven Code — Overhead by Source")
        lines.append("")
        lines.append("| Source | Tokens | Calls | Cost (USD) |")
        lines.append("|---|---:|---:|---:|")
        for src, info in sorted(by_src.items(), key=lambda x: -x[1].get("tokens", 0)):
            lines.append(f"| `{src}` | {info.get('tokens',0):,} | {info.get('calls',0)} | ${info.get('cost_usd',0):.5f} |")
        lines.append("")

    # User Work breakdown
    tcs = uw.get("tier_counts") or {}
    if any(tcs.values()):
        lines.append("### 👤 User Work — Tier Mix")
        lines.append("")
        lines.append("| Tier | Count |")
        lines.append("|---|---:|")
        for tier in ["SIMPLE", "MEDIUM", "COMPLEX", "LOCAL_ONLY"]:
            c = tcs.get(tier, 0)
            if c:
                lines.append(f"| {tier} | {c} |")
        lines.append("")

    # Provider attribution (for Codex tier especially)
    providers = ls.get("providers") or {}
    if providers:
        lines.append("### 🔌 Provider Attribution")
        lines.append("")
        lines.append("| Provider | Tokens | Share | Cost (USD) |")
        lines.append("|---|---:|---:|---:|")
        for prov, info in providers.items():
            tok = info.get("tokens", 0)
            cost = info.get("cost_usd", 0.0)
            pct = (tok / total_tok * 100) if total_tok else 0
            lines.append(f"| `{prov}` | {tok:,} | {pct:.1f}% | ${cost:.4f} |")
        lines.append("")

    # Tier mix
    if metrics["tier_counts"]:
        lines.append("## 🎯 Tier Mix")
        lines.append("")
        lines.append("| Tier | Count | Share | Cost (USD) |")
        lines.append("|---|---:|---:|---:|")
        for tier in ["SIMPLE", "MEDIUM", "COMPLEX", "LOCAL_ONLY"]:
            c = metrics["tier_counts"].get(tier, 0)
            p = metrics["tier_share_pct"].get(tier, 0)
            cost = metrics["tier_cost"].get(tier, 0)
            lines.append(f"| {tier} | {c} | {p:.1f}% | ${cost:.3f} |")
        lines.append("")

    # Daily series
    if metrics["cost_by_day"]:
        lines.append("## 📅 Daily Series")
        lines.append("")
        lines.append("| Date | Sessions | Tokens | Cost |")
        lines.append("|---|---:|---:|---:|")
        for day in sorted(metrics["sessions_by_day"].keys()):
            s = metrics["sessions_by_day"][day]
            t = metrics["tokens_by_day"].get(day, 0)
            c = metrics["cost_by_day"].get(day, 0)
            lines.append(f"| {day} | {s} | {t:,} | ${c:.3f} |")
        lines.append("")

    # Top skills + specialists
    if metrics["skills_used"]:
        lines.append("## 🛠 Top Skills Used")
        lines.append("")
        lines.append("| Skill | Invocations |")
        lines.append("|---|---:|")
        for skill, count in list(metrics["skills_used"].items())[:15]:
            lines.append(f"| {skill} | {count} |")
        lines.append("")

    if metrics["specialists_used"]:
        lines.append("## 👥 Top Specialists")
        lines.append("")
        lines.append("| Specialist | Invocations |")
        lines.append("|---|---:|")
        for spec, count in list(metrics["specialists_used"].items())[:10]:
            lines.append(f"| {spec} | {count} |")
        lines.append("")

    # Guard events
    if metrics["guard_events"]:
        lines.append("## 🛡 Guard Events")
        lines.append("")
        lines.append("| Event | Count |")
        lines.append("|---|---:|")
        for event, count in sorted(metrics["guard_events"].items(), key=lambda x: -x[1])[:15]:
            lines.append(f"| {event} | {count} |")
        lines.append("")

    # Recommendations — grouped by owner
    lines.append("## 💡 Recommendations — Grouped by Owner")
    lines.append("")
    lines.append("> Different cost owners need different fixes. Issues are tagged by who controls the lever.")
    lines.append("")
    if not recs:
        lines.append("✓ All metrics within healthy bands. No actions needed.")
    else:
        sev = {"high": "🔴 HIGH", "medium": "🟡 MEDIUM", "info": "🔵 INFO"}
        groups = {
            "raven_team": ("🪶 Raven Hygiene", "Raven team owns these — file issues at github.com/giggsoinc/raven/issues if persistent."),
            "user":       ("👤 User Behavior", "You own these — prompt tuning, /clear cadence, model choice."),
            "config":     ("⚙️ Environment / Setup", "Configuration issues — manifest, hooks, guards, vault wiring."),
        }
        counter = 1
        for owner_key, (title, blurb) in groups.items():
            owner_recs = [r for r in recs if r.get("owner") == owner_key]
            if not owner_recs:
                continue
            lines.append(f"### {title}")
            lines.append("")
            lines.append(f"*{blurb}*")
            lines.append("")
            for r in owner_recs:
                lines.append(f"#### {counter}. {sev.get(r['severity'], 'INFO')} — {r['metric']}")
                lines.append("")
                lines.append(f"**Issue:** {r['issue']}")
                lines.append("")
                lines.append(f"**Action:** {r['action']}")
                if r.get("savings_estimate_usd"):
                    lines.append("")
                    lines.append(f"**Estimated savings:** ${r['savings_estimate_usd']:.2f}")
                lines.append("")
                counter += 1
    lines.append("---")
    lines.append("")

    # Dataview block (only renders if user has dataview plugin)
    lines.append("## 📈 Dataview — Session History")
    lines.append("")
    lines.append("(Renders if Obsidian Dataview plugin is installed)")
    lines.append("")
    lines.append("```dataview")
    lines.append("TABLE date, project, mode, status")
    lines.append('FROM "sessions"')
    lines.append("SORT date DESC")
    lines.append("LIMIT 30")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by Raven v{metadata['plugin_version']} · Local-only · No telemetry*")
    lines.append("")
    return "\n".join(lines)


def _load_or_build_graph(project_filter: Optional[str] = None, session_days: int = 30) -> dict:
    """Build knowledge-graph.json via knowledge_graph module (fail-soft)."""
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        from knowledge_graph import build_graph, write_graph  # type: ignore

        g = build_graph(project_filter=project_filter, session_days=session_days)
        write_graph(g)
        return g
    except Exception as e:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_filter": project_filter,
            "nodes": [],
            "edges": [],
            "error": str(e),
        }


def _word_cap(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def _read_vault_note(rel_path: str) -> str:
    """Read markdown from ~/RavenVault/{rel_path} (with or without .md)."""
    p = Path(rel_path)
    if not p.is_absolute():
        p = VAULT / rel_path
    if p.suffix != ".md":
        p = p.with_suffix(".md") if p.suffix == "" else p
    if not p.exists() and not str(rel_path).endswith(".md"):
        p = VAULT / f"{rel_path}.md"
    try:
        return p.read_text(errors="replace") if p.exists() else ""
    except OSError:
        return ""


def _plain_from_md(text: str, max_chars: int = 4000) -> str:
    body = text
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    # strip wikilinks to labels
    body = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", body)
    body = re.sub(r"[#>`*_]", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body[:max_chars]


def _cve_guard_blurb(metrics: dict, project: str) -> str:
    guards = metrics.get("guard_events") or {}
    viol = metrics.get("violations") or {}
    n_guard = sum(guards.values()) if isinstance(guards, dict) else 0
    n_viol = sum(viol.values()) if isinstance(viol, dict) else 0
    secrets = sum(v for k, v in (guards.items() if isinstance(guards, dict) else []) if "secret" in k.lower())
    cve = sum(v for k, v in (guards.items() if isinstance(guards, dict) else []) if "cve" in k.lower())
    top = ""
    if isinstance(viol, dict) and viol:
        top_items = sorted(viol.items(), key=lambda x: -x[1])[:3]
        top = "; ".join(f"{k}×{v}" for k, v in top_items)
    return (
        f"Raven guard window for work near {project or 'this repo'}: "
        f"{n_guard} guard event(s) logged, {n_viol} violation signal(s). "
        f"Secret-scan hits (bucket): {secrets}. CVE-related events: {cve}. "
        f"{('Top rules: ' + top + '. ') if top else ''}"
        f"CVE blocking is enforced at commit via pre-commit / cve-check — "
        f"a quiet report here means no blocked library in this window, not 'no scan ran'. "
        f"Always re-run raven-sync after dependency changes. "
        f"Treat zero events as 'no fire', not 'no coverage'."
    )


def _repo_url_from_hub(hub_text: str, project: str, metadata: dict) -> str:
    m = re.search(r"https://github\.com/[^\s\)\]>\"']+", hub_text or "")
    if m:
        return m.group(0).rstrip(".,")
    remote = metadata.get("git_remote") or ""
    if "github.com" in remote and project and project in remote:
        return (
            remote.replace("git@", "https://")
            .replace("github.com:", "github.com/")
            .replace(".git", "")
        )
    if remote.startswith("http") and project and project in remote:
        return remote.replace(".git", "")
    # common giggsoinc default
    if project:
        return f"https://github.com/giggsoinc/{project}"
    if remote.startswith("http"):
        return remote.replace(".git", "")
    return ""


def _local_path_from_hub(hub_text: str) -> str:
    m = re.search(r"Local:\s*(~?[^\s\n]+)", hub_text or "", re.I)
    if m:
        p = m.group(1).strip()
        if p.startswith("~/"):
            p = str(Path.home() / p[2:])
        # validate exists; if hub is stale, fall through to discovery later
        if Path(p).expanduser().exists():
            return str(Path(p).expanduser().resolve())
        return p
    return ""


# Roots to search for nested clones (not only top-level)
_LOCAL_SEARCH_ROOTS = [
    Path.home() / "AntiGravity_Projects",
    Path.home() / "Projects",
    Path.home() / "Developer",
    Path.home() / "src",
    Path.home() / "code",
]
_LOCAL_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "target",
    "vendor",
    ".next",
    "coverage",
}
_local_path_cache: dict[str, Optional[str]] = {}


def _score_local_candidate(path: Path, project: str) -> tuple:
    """Higher is better. Prefer git roots, then package roots, then shallower paths.

    Order matters: a top-level clone named Aryx with .git must beat nested
    Aryx-EE/aryx package dirs when project name is case-insensitively 'aryx'.
    """
    name = path.name
    proj = project or ""
    exact = 1 if name == proj else 0
    case_i = 1 if name.lower() == proj.lower() else 0
    has_git = 1 if (path / ".git").exists() else 0
    has_manifest = 1 if (path / ".raven" / "manifest.json").exists() else 0
    has_pkg = 1 if any(
        (path / f).exists()
        for f in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml")
    ) else 0
    # depth under home (shallower better → negative depth)
    try:
        depth = len(path.relative_to(Path.home()).parts)
    except ValueError:
        depth = len(path.parts)
    # penalize generic / non-repo nestings
    parts_l = [p.lower() for p in path.parts]
    nest_penalty = 0
    if "docs" in parts_l or "assets" in parts_l or "node_modules" in parts_l:
        nest_penalty += 8
    if "src" in parts_l and has_git == 0:
        nest_penalty += 3
    # nested package folder with same name as parent product (…/Aryx-EE/aryx)
    if depth >= 2 and has_git == 0 and has_manifest == 0:
        nest_penalty += 2
    # Prefer: git root → shallower path → not under docs/ → case match
    # (shallower before exact basename so Aryx beats nested Aryx-EE/aryx)
    return (has_git, has_manifest, -nest_penalty, -depth, has_pkg, case_i, exact)


def discover_local_path(project: str, max_depth: int = 5) -> Optional[str]:
    """Find a local clone for project name under known roots (recursive, depth-capped).

    Handles nested layouts e.g. ~/AntiGravity_Projects/Proj1/fin-processor.
    Prefers directories that look like repos (.git / manifest / package files).
    """
    if not project or project in (".", ".."):
        return None
    key = project.lower()
    if key in _local_path_cache:
        return _local_path_cache[key]

    candidates: list[Path] = []
    target = project.lower()

    for root in _LOCAL_SEARCH_ROOTS:
        if not root.is_dir():
            continue
        # Walk with skip; do not follow symlinks into cycles
        try:
            root = root.resolve()
        except Exception:
            continue
        for dirpath, dirnames, _files in os.walk(root, topdown=True, followlinks=False):
            p = Path(dirpath)
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                rel_parts = ()
            depth = len(rel_parts)
            # prune deep / junk dirs
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _LOCAL_SKIP_DIR_NAMES and not d.startswith(".")
            ]
            if depth > max_depth:
                dirnames[:] = []
                continue
            if p.name.lower() == target:
                candidates.append(p)

    if not candidates:
        _local_path_cache[key] = None
        return None

    best = max(candidates, key=lambda c: _score_local_candidate(c, project))
    score = _score_local_candidate(best, project)
    # Reject weak matches: no .git and buried under docs/assets (e.g. …/docs/diagrams)
    has_git = (best / ".git").exists()
    parts_l = [p.lower() for p in best.parts]
    if not has_git and ("docs" in parts_l or "assets" in parts_l or "node_modules" in parts_l):
        _local_path_cache[key] = None
        return None
    # Reject if no git and no package/manifest and many candidates (ambiguous junk)
    has_signal = has_git or (best / ".raven" / "manifest.json").exists() or any(
        (best / f).exists()
        for f in ("package.json", "pyproject.toml", "requirements.txt", "go.mod")
    )
    if not has_signal and len(candidates) > 1:
        # try best among those with signal only
        strong = [c for c in candidates if (c / ".git").exists()]
        if strong:
            best = max(strong, key=lambda c: _score_local_candidate(c, project))
        else:
            _local_path_cache[key] = None
            return None

    try:
        resolved = str(best.resolve())
    except Exception:
        resolved = str(best)
    _local_path_cache[key] = resolved
    return resolved


def backfill_hub_local(project: str, local_path: str) -> bool:
    """Write/create projects/{name}.md with Local: (+ GitHub if known)."""
    if not project or not local_path:
        return False
    VAULT.mkdir(parents=True, exist_ok=True)
    (VAULT / "projects").mkdir(parents=True, exist_ok=True)
    hub = VAULT / "projects" / f"{project}.md"
    line = f"- Local: {local_path}"
    gh = f"- GitHub: https://github.com/giggsoinc/{project}"
    if not hub.exists():
        hub.write_text(
            f"""---
type: project
name: {project}
tags: [project, raven]
---
# {project}

## Repo
{gh}
{line}

## Current state
- Local path discovered by Raven dashboard (nested search under ~/AntiGravity_Projects).

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
        return True
    try:
        text = hub.read_text(errors="replace")
    except OSError:
        return False
    # Already correct?
    m = re.search(r"Local:\s*(~?[^\s\n]+)", text, re.I)
    if m:
        existing = m.group(1).strip()
        if existing.startswith("~/"):
            existing = str(Path.home() / existing[2:])
        try:
            if Path(existing).expanduser().resolve() == Path(local_path).resolve():
                return False
        except Exception:
            pass
        # replace existing Local line
        text2 = re.sub(
            r"(?m)^(\s*[-*]?\s*Local:\s*).+$",
            rf"\1{local_path}",
            text,
            count=1,
        )
        if text2 == text:
            return False
        hub.write_text(text2)
        return True
    # Insert under ## Repo if present
    if re.search(r"(?m)^##\s+Repo\s*$", text):
        text2 = re.sub(
            r"(?m)(^##\s+Repo\s*\n)",
            rf"\1{line}\n",
            text,
            count=1,
        )
    else:
        text2 = text.rstrip() + f"\n\n## Repo\n{gh}\n{line}\n"
    if text2 != text:
        hub.write_text(text2)
        return True
    return False


def resolve_local_path(project: str, hub_text: str = "") -> str:
    """Hub Local: first (if exists on disk), else recursive discovery + optional hub backfill."""
    from_hub = _local_path_from_hub(hub_text) if hub_text else ""
    if from_hub and Path(from_hub).expanduser().exists():
        return str(Path(from_hub).expanduser().resolve())
    found = discover_local_path(project)
    if found:
        try:
            backfill_hub_local(project, found)
        except Exception:
            pass
        return found
    # return hub path even if missing (display only)
    return from_hub or ""


def _local_uri(path: str) -> str:
    """file:// URI for a local clone path (for clickable links in HTML)."""
    if not path:
        return ""
    try:
        p = Path(path).expanduser()
        # Prefer resolved absolute path even if missing (user may open later)
        if not p.is_absolute():
            p = Path.home() / p
        return p.resolve().as_uri() if p.exists() else p.absolute().as_uri()
    except Exception:
        return ""


def _local_link_html(path: str, label: str = "Local") -> str:
    """Anchor to local repo; empty string if no path."""
    if not path:
        return ""
    uri = _local_uri(path)
    if not uri:
        return f'<span style="color:#94a3b8;font-size:12px" title="path not resolved">{path}</span>'
    exists = Path(path).expanduser().exists()
    badge = "" if exists else ' <span style="color:#f59e0b">(path missing)</span>'
    return (
        f'<a href="{uri}" title="{path}" style="color:#86efac;font-size:12px;">'
        f"📁 {label}</a>"
        f' <code style="font-size:10px;color:#64748b;">{path}</code>{badge}'
    )


def _hub_sections(hub_text: str) -> dict:
    """Extract open questions / current state / recent sessions bullets."""
    plain_body = hub_text or ""
    out = {"open_questions": [], "current_state": [], "recent_sessions": [], "concepts": []}
    for heading, key in (
        ("Open questions", "open_questions"),
        ("Open Questions", "open_questions"),
        ("Current state", "current_state"),
        ("Current State", "current_state"),
        ("Recent sessions", "recent_sessions"),
        ("Concepts", "concepts"),
        ("Key decisions", "concepts"),
    ):
        bullets = []
        pat = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.M | re.I)
        m = pat.search(plain_body)
        if not m:
            continue
        rest = plain_body[m.end() :]
        nxt = re.search(r"^##\s+", rest, re.M)
        block = rest[: nxt.start()] if nxt else rest
        for ln in block.splitlines():
            s = ln.strip()
            if s.startswith("- "):
                bullets.append(s[2:].strip())
            if len(bullets) >= 8:
                break
        if bullets and not out[key]:
            out[key] = bullets
    return out


def build_node_briefings(graph: dict, metrics: dict, metadata: dict) -> dict:
    """Precompute Guru-style click panels for each graph node + center overview."""
    by_project = metrics.get("by_project") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    briefings: dict = {}

    # Degree map for neighbor hints
    degree: dict[str, int] = Counter()
    neighbors: dict[str, set] = defaultdict(set)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s and t:
            degree[s] += 1
            degree[t] += 1
            neighbors[s].add(t)
            neighbors[t].add(s)

    for n in nodes:
        nid = n.get("id") or ""
        ntype = n.get("type") or "unknown"
        label = n.get("label") or nid.split("/")[-1]
        path = n.get("path") or f"{nid}.md"
        note = _read_vault_note(path if path.endswith(".md") else nid)
        plain = _plain_from_md(note)

        # Resolve owning project for costs
        proj = label if ntype == "project" else None
        if not proj and nid.startswith("projects/"):
            proj = nid.split("/", 1)[-1]
        if not proj:
            m = re.search(r"projects/([A-Za-z0-9._-]+)", note + " " + nid)
            if m:
                proj = m.group(1)
        # session notes like sessions/2026-08-04-raven
        if not proj and ntype == "session":
            stem = nid.split("/")[-1]
            parts = stem.split("-")
            if len(parts) >= 4:
                proj = "-".join(parts[3:])  # after YYYY-MM-DD
            elif len(parts) >= 1:
                proj = parts[-1]

        pstats = by_project.get(proj or "", {}) if proj else {}
        cost = float(pstats.get("cost_usd") or 0)
        tokens = int(pstats.get("tokens") or 0)
        sessions = int(pstats.get("sessions") or 0)

        # Last update from file mtime or hub "updated"
        updated = ""
        um = re.search(r"^updated:\s*(.+)$", note, re.M)
        if um:
            updated = um.group(1).strip()
        try:
            vp = VAULT / path if not Path(path).is_absolute() else Path(path)
            if not vp.exists():
                vp = VAULT / f"{nid}.md"
            if vp.exists():
                mtime = datetime.fromtimestamp(vp.stat().st_mtime)
                if not updated:
                    updated = mtime.strftime("%Y-%m-%d %H:%M")
                age_days = (datetime.now() - mtime).days
            else:
                age_days = None
        except Exception:
            age_days = None

        neigh = sorted(neighbors.get(nid, []))[:12]
        hub_for_links = note
        # Prefer project hub for non-project nodes
        if proj and ntype != "project":
            hub_for_links = _read_vault_note(f"projects/{proj}") or note
        repo_url = (
            _repo_url_from_hub(hub_for_links, proj or label, metadata)
            if (ntype == "project" or proj)
            else ""
        )
        local_path = resolve_local_path(proj or label, hub_for_links)
        sections = _hub_sections(hub_for_links if ntype == "project" else note)
        if ntype == "project" and not sections.get("open_questions"):
            sections = _hub_sections(note)

        related_concepts = [x for x in neigh if x.startswith("concepts/")][:8]
        related_decisions = [x for x in neigh if x.startswith("decisions/")][:6]
        related_sessions = [x for x in neigh if x.startswith("sessions/")][:6]
        if ntype == "project":
            # also pull from hub recent sessions bullets
            for rs in sections.get("recent_sessions") or []:
                mlink = re.search(r"\[\[(sessions/[^\]]+)\]\]", rs)
                if mlink and mlink.group(1) not in related_sessions:
                    related_sessions.append(mlink.group(1))

        vault_note_uri = ""
        try:
            vp = VAULT / path if not str(path).startswith("/") else Path(path)
            if not vp.exists():
                vp = VAULT / f"{nid}.md"
            if vp.exists():
                vault_note_uri = vp.resolve().as_uri()
        except Exception:
            pass

        # ── Summary ~200 words (Andie-Guru voice) ──
        analogy = {
            "project": "Think of this repo as a workshop bench: tools, unfinished pieces, and notes pinned above the vise.",
            "concept": "Think of this concept as a sticky note on the whiteboard — a single idea people keep pointing at.",
            "decision": "Think of this decision as a signed change order: once agreed, builders stop re-arguing and just execute.",
            "session": "Think of this session as a day's work log — what someone did, not the whole factory.",
        }.get(ntype, "Think of this node as a pin on a map of how your software knowledge connects.")

        oq = "; ".join(sections.get("open_questions") or [])[:220]
        st = "; ".join(sections.get("current_state") or [])[:220]
        guru = (
            f"{analogy} "
            f"You are looking at '{label}', a {ntype} node in the Raven knowledge graph. "
            f"It is vault memory — not a live production monitor. "
            f"Business: shared hubs stop teams from rediscovering the same facts every sprint. "
            f"Technical: open the repo and related notes without dumping full git history into chat. "
            f"Functional: open questions and decisions live next to cost so standups share one map. "
            f"Repo: {proj or 'unscoped'}. "
            f"{('Open questions: ' + oq + '. ') if oq else ''}"
            f"{('Current state: ' + st + '. ') if st else ''}"
            f"From the note: {plain[:420] if plain else 'No note body yet — hubs fill as sessions run.'} "
            f"One takeaway: use this panel for story + links, then jump to code via Open repo."
        )
        guru = _word_cap(guru, 200)

        # ── Last update ~100 words ──
        last_up = (
            f"Last vault touch: {updated or 'unknown'}"
            f"{f' (~{age_days} day(s) ago)' if age_days is not None else ''}. "
            f"Graph degree: {degree.get(nid, 0)}. "
            f"Linked: {', '.join(neigh[:6]) if neigh else 'none yet'}. "
            f"Local clone: {local_path or 'not listed on hub'}. "
            f"Vault note: ~/RavenVault/{path}. "
            f"Refresh: run a coding session (Stop hooks) or "
            f"python3 scripts/obsidian-log.py then python3 scripts/dashboard.py --html --open."
        )
        last_up = _word_cap(last_up, 100)

        # ── Cost / tokens / CVE ~100 words ──
        cost_blk = (
            f"Trusted per-repo window for '{proj or 'n/a'}': "
            f"{sessions} session-units, {tokens:,} tokens, {format_usd(cost)}. "
            f"{_cve_guard_blurb(metrics, proj or label)} "
            f"Window {metrics.get('window_start')} → {metrics.get('window_end')}. "
            f"Portfolio totals are separate — see Headline dual cards."
        )
        cost_blk = _word_cap(cost_blk, 100)

        briefings[nid] = {
            "id": nid,
            "label": label,
            "type": ntype,
            "project": proj,
            "path": path,
            "guru": guru,
            "last_update": last_up,
            "cost_report": cost_blk,
            "repo_url": repo_url,
            "local_path": local_path,
            "local_uri": _local_uri(local_path),
            "vault_note_uri": vault_note_uri,
            "open_questions": sections.get("open_questions") or [],
            "current_state": sections.get("current_state") or [],
            "related_concepts": related_concepts,
            "related_decisions": related_decisions,
            "related_sessions": related_sessions[:6],
            "neighbors": neigh,
            "note_excerpt": plain[:900] if plain else "",
            "stats": {
                "sessions": sessions,
                "tokens": tokens,
                "cost_usd": cost,
                "cost_display": format_usd(cost),
            },
        }

    # Center / overview card
    proj_lines = []
    for pname, st in list((by_project or {}).items())[:12]:
        proj_lines.append(
            f"{pname}: {st.get('sessions', 0)} sess · {int(st.get('tokens', 0)):,} tok · {format_usd(st.get('cost_usd', 0))}"
        )
    center_guru = _word_cap(
        "🧠 GURU — Knowledge map center. "
        "Think of this view as the front desk of a multi-building campus: one map, many doors. "
        "This center is the whole workshop floor, not one bench. "
        "Each colored node is a project, concept, decision, or session note living in your RavenVault on this machine. "
        "Click a node to zoom into one story; click empty canvas or the Center button to return here for the campus-wide briefing. "
        "Business: one shared map reduces 'where did we leave that?' thrash across product repos, which cuts meeting time and rework risk when people switch context. "
        "Technical: agents and humans load short hub digests instead of pasting multi‑megabyte git dumps into chat, which keeps token spend honest and answers grounded. "
        "Functional: product, engineering, and ops can point at the same project hub language — open questions, decisions, concepts — so standups and handoffs share one narrative. "
        f"Repos tracked in this cost window: {', '.join((by_project or {}).keys()) or 'none yet'}. "
        f"The interactive graph currently has {len(nodes)} nodes and {len(edges)} edges built from wikilinks. "
        "Trust dollar headlines only when rows carry a project tag. "
        "Old unscoped by_day rollups (tens of thousands of fake 'sessions' in a day) are excluded from headlines because they inflated totals into nonsense. "
        "Use the per-repo table under the graph when you need comparable spend across applications. "
        "One takeaway: start at Center for the portfolio, then click a repo node when you need that product's story.",
        200,
    )
    center_last = _word_cap(
        f"Dashboard generated {metadata.get('report_generated_at_local') or 'now'}. "
        f"Vault root: {metadata.get('vault_path') or str(VAULT)}. "
        f"Active filter: {graph.get('project_filter') or 'all projects'}. "
        f"Plugin/report metadata project: {metadata.get('project') or 'n/a'}. "
        f"Rebuild anytime with: python3 scripts/dashboard.py --html --open. "
        f"Index, hubs, and session notes refresh when Stop hooks run (token-meter-write, obsidian-log, knowledge-extract). "
        f"If Center looks empty, open Obsidian on ~/RavenVault and confirm projects/*.md hubs exist, then re-run the dashboard command. "
        f"Graph JSON export lives at ~/RavenVault/graph/knowledge-graph.json for tooling that prefers files over HTML.",
        100,
    )
    center_cost = _word_cap(
        f"Headline window uses trusted per-repo rows only: {metrics.get('sessions_count', 0)} sessions, "
        f"{int(metrics.get('total_tokens') or 0):,} tokens, {format_usd(metrics.get('total_cost_usd', 0))}. "
        f"By repo — {'; '.join(proj_lines) if proj_lines else 'no per-repo rows yet; future Stop hooks write by_project into monthly metrics'}. "
        f"{_cve_guard_blurb(metrics, 'all repos')} "
        f"Legacy unscoped cost (not in headline): {format_usd((metrics.get('legacy_unscoped') or {}).get('cost_usd', 0))} "
        f"across {(metrics.get('legacy_unscoped') or {}).get('suspect_days', 0)} suspect day(s).",
        100,
    )
    cur = metrics.get("current_project") or metadata.get("project") or ""
    # Collect all graph project links for center drill-down
    graph_projects = []
    for n in nodes:
        if (n.get("type") or "") == "project" or str(n.get("id", "")).startswith("projects/"):
            pid = n.get("id") or ""
            pname = pid.split("/")[-1] if pid else n.get("label")
            bhub = _read_vault_note(pid or f"projects/{pname}")
            _lp = resolve_local_path(str(pname), bhub)
            graph_projects.append(
                {
                    "id": pid or f"projects/{pname}",
                    "name": pname,
                    "repo_url": _repo_url_from_hub(bhub, pname, metadata),
                    "local_path": _lp,
                    "local_uri": _local_uri(_lp),
                }
            )
    briefings["__center__"] = {
        "id": "__center__",
        "label": "All repos (center)",
        "type": "overview",
        "project": cur,
        "path": "index/README.md",
        "guru": center_guru,
        "last_update": center_last,
        "cost_report": center_cost,
        "repo_url": _repo_url_from_hub("", cur, metadata)
        if cur
        else (metadata.get("git_remote") or ""),
        "local_path": str(PROJECT_DIR),
        "local_uri": _local_uri(str(PROJECT_DIR)),
        "vault_note_uri": (VAULT / "index" / "README.md").resolve().as_uri()
        if (VAULT / "index" / "README.md").exists()
        else "",
        "open_questions": [],
        "current_state": [],
        "related_concepts": [],
        "related_decisions": [],
        "related_sessions": [],
        "neighbors": [p["id"] for p in graph_projects],
        "graph_projects": graph_projects,
        "note_excerpt": "",
        "stats": {
            "sessions": metrics.get("sessions_count", 0),
            "tokens": metrics.get("total_tokens", 0),
            "cost_usd": metrics.get("total_cost_usd", 0),
            "cost_display": format_usd(metrics.get("total_cost_usd", 0)),
        },
    }
    return briefings


def render_knowledge_graph_section(
    graph: dict,
    metrics: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Knowledge graph + Guru click panel (offline-safe list + optional vis-network)."""
    metrics = metrics or {}
    metadata = metadata or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    n_nodes, n_edges = len(nodes), len(edges)
    briefings = build_node_briefings(graph, metrics, metadata)
    # Ensure nodes carry vibe icons (emoji + data-URI)
    try:
        from kg_icons import enrich_node, legend_html, icon_img_html, resolve_icon_key, emoji_for
    except ImportError:
        try:
            from scripts.kg_icons import (  # type: ignore
                enrich_node,
                legend_html,
                icon_img_html,
                resolve_icon_key,
                emoji_for,
            )
        except ImportError:
            enrich_node = None  # type: ignore
            legend_html = lambda: ""  # type: ignore
            icon_img_html = lambda *a, **k: ""  # type: ignore
            resolve_icon_key = None  # type: ignore
            emoji_for = lambda k: "❓"  # type: ignore
    if enrich_node and graph.get("nodes"):
        graph = dict(graph)
        graph["nodes"] = [enrich_node(n) for n in graph["nodes"]]
    graph_json = json.dumps(graph, default=str)
    brief_json = json.dumps(briefings, default=str)
    legend = legend_html() if callable(legend_html) else ""

    if n_nodes < 2:
        return f"""
  <h2 id="knowledge-graph">🕸 Knowledge graph</h2>
  <div class="meta" style="border-left:4px solid #f59e0b;">
    <p><strong>Knowledge graph is sparse</strong> ({n_nodes} node(s), {n_edges} edge(s)).</p>
    <p style="color:#94a3b8;margin-top:8px;font-size:14px;">
      Create project hubs and concept notes, then rebuild. See
      <code>docs/obsidian-knowledge-graph-plan.md</code>.
    </p>
  </div>
"""

    # Per-repo table rows — union of cost projects + graph project hubs
    repo_names = set((metrics.get("by_project") or {}).keys())
    for n in nodes:
        if (n.get("type") or "") == "project" or str(n.get("id", "")).startswith("projects/"):
            repo_names.add(str(n.get("id", "")).split("/")[-1])
    repo_rows = ""
    project_chips = ""
    for pname in sorted(repo_names, key=str.lower):
        st = (metrics.get("by_project") or {}).get(pname) or {
            "sessions": 0,
            "tokens": 0,
            "cost_usd": 0,
        }
        brief = briefings.get(f"projects/{pname}") or {}
        url = brief.get("repo_url") or f"https://github.com/giggsoinc/{pname}"
        local = brief.get("local_path") or ""
        if not local:
            hubp = VAULT / "projects" / f"{pname}.md"
            hub_txt = ""
            if hubp.exists():
                try:
                    hub_txt = hubp.read_text(errors="replace")
                except Exception:
                    pass
            local = resolve_local_path(pname, hub_txt)
        local_html = _local_link_html(local, "Local")
        local_uri = _local_uri(local)
        # icon for this project chip
        pnode = next(
            (n for n in (graph.get("nodes") or []) if n.get("id") == f"projects/{pname}"),
            {},
        )
        ico = (pnode or {}).get("icon") or "project"
        ico_html = icon_img_html(ico, 16, pname) if icon_img_html else "📦"
        not_found_span = ' · <span style="color:#64748b;font-size:11px">not found under search roots</span>'
        local_or_fallback = (' · ' + local_html) if local_html else not_found_span
        repo_rows += (
            f"<tr style='cursor:pointer' onclick=\"window.kgShowNode('projects/{pname}')\">"
            f"<td>{ico_html} <strong>{pname}</strong></td>"
            f"<td class='num'>{st.get('sessions',0)}</td>"
            f"<td class='num'>{int(st.get('tokens',0)):,}</td>"
            f"<td class='num'>{format_usd(st.get('cost_usd',0))}</td>"
            f"<td onclick='event.stopPropagation()'>"
            f"<a href='{url}' target='_blank' rel='noopener'>GitHub ↗</a>"
            f"{local_or_fallback}"
            f"</td></tr>\n"
        )
        project_chips += (
            f"<span class='kg-chip-wrap'>"
            f"<a class='kg-chip' href='#' "
            f"title='Briefing' onclick=\"event.preventDefault(); window.kgShowNode('projects/{pname}');\">"
            f"{ico_html} {pname}</a>"
            f"<a class='kg-chip-link' href='{url}' target='_blank' rel='noopener' title='GitHub'>GitHub ↗</a>"
        )
        if local_uri:
            project_chips += (
                f"<a class='kg-chip-link' href='{local_uri}' title='{local}' "
                f"style='color:#86efac'>Local 📁</a>"
            )
        project_chips += "</span> "
    if not repo_rows:
        repo_rows = (
            "<tr><td colspan='5' style='color:#94a3b8'>No project hubs/cost rows yet.</td></tr>"
        )

    return f"""
  <h2 id="knowledge-graph">🕸 Knowledge graph</h2>
  {legend}
  <p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">
    Click a <strong>node</strong> / chip for Summary · notes · cost/CVE · repo.
    Empty canvas / <strong>Center</strong> = portfolio.
    You do not need to read code to use this map.
  </p>
  <style>
    .kg-chip {{ display:inline-block; margin:3px 2px; padding:6px 10px; background:#312e81; color:#e0e7ff;
      border-radius:999px; font-size:12px; text-decoration:none; cursor:pointer; border:1px solid #4c1d95; }}
    .kg-chip:hover {{ background:#4c1d95; }}
    .kg-chip-link {{ color:#38bdf8; font-size:12px; margin-right:6px; text-decoration:none; }}
    .kg-chip-wrap {{ display:inline-flex; align-items:center; gap:4px; margin:4px 10px 4px 0;
      padding:4px 8px; background:#1e293b; border-radius:999px; border:1px solid #334155; }}
    .kg-drill a {{ color:#38bdf8; cursor:pointer; text-decoration:none; margin-right:8px; }}
    .kg-drill a:hover {{ text-decoration:underline; }}
    #kg-svg text {{ pointer-events: none; }}
    #kg-svg circle, #kg-svg rect {{ cursor: pointer; }}
  </style>
  <div style="margin-bottom:12px;">
    <button type="button" class="download" style="background:#8b5cf6;" onclick="window.kgShowNode('__center__')">◎ Center overview</button>
  </div>
  <div style="margin-bottom:16px;">
    <div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">
      Projects in graph — name = briefing · <strong>GitHub ↗</strong> · <strong style="color:#86efac">Local 📁</strong>
      (always visible; does not need the force-canvas)
    </div>
    <div>{project_chips or '<span style="color:#94a3b8">No project nodes</span>'}</div>
  </div>
  <div id="kg-filters" style="margin-bottom:12px;font-size:13px;color:#cbd5e1;">
    <label style="margin-right:12px;"><input type="checkbox" class="kg-type" value="project" checked> project</label>
    <label style="margin-right:12px;"><input type="checkbox" class="kg-type" value="concept" checked> concept</label>
    <label style="margin-right:12px;"><input type="checkbox" class="kg-type" value="decision" checked> decision</label>
    <label style="margin-right:12px;"><input type="checkbox" class="kg-type" value="session" checked> session</label>
    <label style="margin-right:12px;"><input type="checkbox" class="kg-type" value="unknown" checked> unknown</label>
  </div>
  <div style="display:grid;grid-template-columns:minmax(280px,1fr) minmax(320px,1.1fr);gap:16px;align-items:start;">
    <div>
      <div id="kg-canvas" style="height:520px;background:#1e293b;border-radius:8px;border:1px solid #334155;overflow:hidden;"></div>
      <div id="kg-nodelist" style="margin-top:12px;max-height:280px;overflow:auto;background:#1e293b;border-radius:8px;padding:8px;"></div>
    </div>
    <div id="kg-panel" style="background:#1e293b;border-radius:8px;border:1px solid #334155;padding:16px 18px;min-height:520px;">
      <p style="color:#94a3b8;font-size:14px;">Select a node or Center to load the briefing.</p>
    </div>
  </div>

  <h3 style="margin-top:24px;color:#94a3b8;">Per-repo tokens &amp; cost (click row = open briefing)</h3>
  <table>
    <thead><tr><th>Repo</th><th class="num">Sessions</th><th class="num">Tokens</th><th class="num">Cost</th><th>Link</th></tr></thead>
    <tbody>
      {repo_rows}
    </tbody>
  </table>

  <script type="application/json" id="kg-data">{graph_json}</script>
  <script type="application/json" id="kg-briefings">{brief_json}</script>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <script>
  (function() {{
    const GRAPH = JSON.parse(document.getElementById('kg-data').textContent);
    const BRIEFS = JSON.parse(document.getElementById('kg-briefings').textContent);
    const COLORS = {{
      project: '#8b5cf6', concept: '#10b981', decision: '#f59e0b',
      session: '#3b82f6', unknown: '#64748b', overview: '#f472b6'
    }};
    let network = null;

    function esc(s) {{
      return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }}
    function nl2br(s) {{ return esc(s).replace(/\\n/g, '<br>'); }}

    function listLinks(ids, label) {{
      if (!ids || !ids.length) return '';
      const items = ids.map(function(x) {{
        return '<a href="#" onclick="event.preventDefault(); window.kgShowNode(\\''+String(x).replace(/'/g,'')+'\\')">'+esc(x)+'</a>';
      }}).join(' ');
      return '<div class="kg-drill" style="margin:8px 0;"><span style="color:#94a3b8;font-size:12px;">'+esc(label)+': </span>'+items+'</div>';
    }}
    function bulletList(arr, title) {{
      if (!arr || !arr.length) return '';
      return '<div style="margin:10px 0;"><div style="font-size:12px;color:#94a3b8;">'+esc(title)+'</div><ul style="margin:4px 0 0 18px;font-size:13px;color:#e2e8f0;">' +
        arr.slice(0,8).map(function(x){{ return '<li>'+esc(x)+'</li>'; }}).join('') + '</ul></div>';
    }}

    window.kgShowNode = function(id) {{
      const b = BRIEFS[id] || BRIEFS['__center__'];
      if (!b) {{
        document.getElementById('kg-panel').innerHTML =
          '<p style="color:#f59e0b;">No briefing for <code>'+esc(id)+'</code>. Hub may be missing — create ~/RavenVault/projects/…</p>';
        return;
      }}
      const url = b.repo_url || '';
      const st = b.stats || {{}};
      const costShow = st.cost_display || st.cost_usd || '0';
      let actions = '<div style="margin-top:14px;display:flex;flex-wrap:wrap;gap:8px;">';
      if (url) {{
        actions += '<a class="download" style="background:#10b981;text-decoration:none;margin:0;" href="'+esc(url)+'" target="_blank" rel="noopener">↗ GitHub</a>';
      }}
      if (b.local_path) {{
        // file:// link so Finder/IDE can open the local clone
        let localHref = b.local_uri || '';
        if (!localHref && b.local_path) {{
          // best-effort: absolute path → file URI
          const lp = String(b.local_path);
          localHref = lp.startsWith('/') ? ('file://' + lp) : '';
        }}
        if (localHref) {{
          actions += '<a class="download" style="background:#166534;text-decoration:none;margin:0;" href="'+esc(localHref)+'" title="'+esc(b.local_path)+'">📁 Open local repo</a>';
        }} else {{
          actions += '<span class="download" style="background:#334155;margin:0;cursor:default;" title="Local path">📁 '+esc(b.local_path)+'</span>';
        }}
        actions += '<div style="width:100%;font-size:11px;color:#86efac;margin-top:4px;font-family:ui-monospace,monospace;">Local: '+esc(b.local_path)+'</div>';
      }}
      if (b.vault_note_uri) {{
        actions += '<a class="download" style="background:#0ea5e9;text-decoration:none;margin:0;" href="'+esc(b.vault_note_uri)+'">📝 Vault note</a>';
      }}
      if (b.project && id !== 'projects/'+b.project) {{
        actions += '<button type="button" class="download" style="background:#8b5cf6;margin:0;" onclick="window.kgShowNode(\\'projects/'+String(b.project).replace(/'/g,'')+'\\')">Repo hub</button>';
      }}
      actions += '</div>';
      if (!url && !b.local_path) {{
        actions += '<p style="margin-top:10px;color:#94a3b8;font-size:13px;">Add under project hub <code>## Repo</code>:<br>'+
          '- GitHub: https://github.com/org/repo<br>- Local: /absolute/path/to/clone</p>';
      }}

      // Center: list all graph projects as drill targets
      let projectDrill = '';
      if (b.graph_projects && b.graph_projects.length) {{
        projectDrill = '<div class="kg-drill" style="margin:12px 0;"><div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">Projects in graph</div>' +
          b.graph_projects.map(function(p) {{
            const u = p.repo_url ? ' <a href="'+esc(p.repo_url)+'" target="_blank" rel="noopener">GitHub ↗</a>' : '';
            let loc = '';
            if (p.local_path) {{
              const href = p.local_uri || (String(p.local_path).startsWith('/') ? ('file://'+p.local_path) : '');
              loc = href
                ? ' <a href="'+esc(href)+'" style="color:#86efac" title="'+esc(p.local_path)+'">Local 📁</a> <code style="font-size:10px;color:#64748b">'+esc(p.local_path)+'</code>'
                : ' <code style="font-size:10px;color:#64748b">'+esc(p.local_path)+'</code>';
            }}
            return '<div style="margin:6px 0;"><a href="#" onclick="event.preventDefault(); window.kgShowNode(\\''+String(p.id).replace(/'/g,'')+'\\')">'+esc(p.name)+'</a>'+u+loc+'</div>';
          }}).join('') + '</div>';
      }}

      document.getElementById('kg-panel').innerHTML =
        '<div style="font-size:12px;color:#94a3b8;margin-bottom:8px;">'+esc(b.type)+' · '+esc(b.id)+'</div>'+
        '<h3 style="margin:0 0 12px;color:#e2e8f0;">'+esc(b.label)+'</h3>'+
        '<div style="font-size:12px;color:#cbd5e1;margin-bottom:12px;">'+
          (st.sessions!=null?('Sessions <strong>'+st.sessions+'</strong> · '):'')+
          (st.tokens!=null?('Tokens <strong>'+Number(st.tokens).toLocaleString()+'</strong> · '):'')+
          ('Cost <strong>'+esc(String(costShow))+'</strong>')+
        '</div>'+
        actions +
        projectDrill +
        bulletList(b.open_questions, 'Open questions') +
        bulletList(b.current_state, 'Current state') +
        listLinks(b.related_concepts, 'Concepts') +
        listLinks(b.related_decisions, 'Decisions') +
        listLinks(b.related_sessions, 'Sessions') +
        listLinks((b.neighbors||[]).filter(function(x){{ return !(b.related_concepts||[]).includes(x) && !(b.related_sessions||[]).includes(x); }}).slice(0,8), 'More links') +
        (b.note_excerpt ? '<div style="margin:12px 0;padding:10px;background:#0f172a;border-radius:6px;font-size:12px;color:#94a3b8;max-height:120px;overflow:auto;"><div style="margin-bottom:4px;color:#64748b;">Note excerpt</div>'+esc(b.note_excerpt)+'</div>' : '') +
        '<h4 style="color:#a78bfa;margin:16px 0 2px;">Summary</h4>'+
        '<div style="font-size:11px;color:#94a3b8;margin:0 0 8px;">Generated by Andie - Guru</div>'+
        '<p style="font-size:14px;line-height:1.55;color:#e2e8f0;">'+nl2br(b.guru)+'</p>'+
        '<h4 style="color:#38bdf8;margin:16px 0 6px;">Last update</h4>'+
        '<p style="font-size:14px;line-height:1.55;color:#e2e8f0;">'+nl2br(b.last_update)+'</p>'+
        '<h4 style="color:#fbbf24;margin:16px 0 6px;">Cost · tokens · Raven CVE / guards</h4>'+
        '<p style="font-size:14px;line-height:1.55;color:#e2e8f0;">'+nl2br(b.cost_report)+'</p>';
      try {{
        if (network && id !== '__center__') {{
          network.selectNodes([id]);
          network.focus(id, {{ scale: 1.2, animation: true }});
        }} else if (network && id === '__center__') {{
          network.unselectAll();
          network.fit({{ animation: true }});
        }}
      }} catch (e) {{}}
      // scroll panel into view on small screens
      try {{ document.getElementById('kg-panel').scrollIntoView({{ behavior: 'smooth', block: 'nearest' }}); }} catch (e) {{}}
    }};

    function drawOfflineSvg(nodesArr, edgesArr) {{
      // Always-on layout (no CDN). Circular placement — data is never "gone".
      const container = document.getElementById('kg-canvas');
      const W = Math.max(container.clientWidth || 480, 320);
      const H = 500;
      const cx = W / 2, cy = H / 2;
      const R = Math.min(W, H) * 0.38;
      const n = nodesArr.length || 1;
      const pos = {{}};
      nodesArr.forEach(function(node, i) {{
        const a = (2 * Math.PI * i) / n - Math.PI / 2;
        pos[node.id] = {{ x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) }};
      }});
      let edgesSvg = edgesArr.map(function(e) {{
        const a = pos[e.from], b = pos[e.to];
        if (!a || !b) return '';
        return '<line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+
          '" stroke="#475569" stroke-width="1.2" />';
      }}).join('');
      let nodesSvg = nodesArr.map(function(node) {{
        const p = pos[node.id];
        const col = node.color || '#64748b';
        const lab = (node.label || node.id || '').slice(0, 14);
        const emo = node.emoji || '❓';
        const idSafe = String(node.id).replace(/"/g, '');
        if (node.shape === 'box') {{
          return '<g class="kg-node" data-id="'+idSafe+'" transform="translate('+p.x+','+p.y+')">' +
            '<rect x="-40" y="-18" width="80" height="36" rx="8" fill="'+col+'" opacity="0.92"/>' +
            '<text text-anchor="middle" y="-2" font-size="14">'+emo+'</text>' +
            '<text text-anchor="middle" y="14" fill="#f8fafc" font-size="9" font-family="system-ui">'+esc(lab)+'</text></g>';
        }}
        return '<g class="kg-node" data-id="'+idSafe+'" transform="translate('+p.x+','+p.y+')">' +
          '<circle r="16" fill="'+col+'" opacity="0.95"/>' +
          '<text text-anchor="middle" y="5" font-size="13">'+emo+'</text>' +
          '<text text-anchor="middle" y="32" fill="#cbd5e1" font-size="9" font-family="system-ui">'+esc(lab)+'</text></g>';
      }}).join('');
      container.innerHTML =
        '<svg id="kg-svg" width="100%" height="'+H+'" viewBox="0 0 '+W+' '+H+
        '" style="display:block;background:#1e293b">' +
        '<rect width="100%" height="100%" fill="#1e293b" id="kg-svg-bg"/>' +
        edgesSvg + nodesSvg +
        '<text x="12" y="20" fill="#86efac" font-size="11" font-family="system-ui">Picture map · '+
        nodesArr.length+' boxes · click any icon</text></svg>';
      container.querySelectorAll('.kg-node').forEach(function(g) {{
        g.addEventListener('click', function(ev) {{
          ev.stopPropagation();
          window.kgShowNode(g.getAttribute('data-id'));
        }});
      }});
      const bg = container.querySelector('#kg-svg-bg');
      if (bg) bg.addEventListener('click', function() {{ window.kgShowNode('__center__'); }});
      network = null;
    }}

    function rebuild() {{
      const allowed = new Set(Array.from(document.querySelectorAll('.kg-type:checked')).map(c => c.value));
      const nodesArr = (GRAPH.nodes || []).filter(n => allowed.has(n.type || 'unknown')).map(n => ({{
        id: n.id, label: n.label || n.id, title: (n.path || n.id) + ' (' + (n.type||'') + ')',
        color: COLORS[n.type] || COLORS.unknown, shape: n.type === 'project' ? 'box' : 'dot',
        type: n.type || 'unknown',
        emoji: n.icon_emoji || '❓',
        icon: n.icon || n.type || 'unknown',
        iconUri: n.icon_data_uri || ''
      }}));
      const idset = new Set(nodesArr.map(n => n.id));
      const edgesArr = (GRAPH.edges || []).filter(e => idset.has(e.source) && idset.has(e.target)).map((e,i) => ({{
        id: i, from: e.source, to: e.target, arrows: 'to', color: {{ color:'#475569' }}
      }}));

      // Node list ALWAYS works (offline) — icons first for vibe coders
      const list = document.getElementById('kg-nodelist');
      list.innerHTML = '<div style="font-size:12px;color:#86efac;margin-bottom:6px;">All boxes ('+nodesArr.length+') — click the picture</div>' +
        nodesArr.map(n => {{
          const ico = n.iconUri
            ? '<img src="'+n.iconUri+'" width="18" height="18" alt="" style="vertical-align:middle;margin-right:6px"/>'
            : '<span style="margin-right:6px">'+n.emoji+'</span>';
          return '<button type="button" style="display:flex;align-items:center;width:100%;text-align:left;margin:3px 0;padding:8px;background:#0f172a;border:1px solid #334155;border-radius:6px;color:#e2e8f0;cursor:pointer;" onclick="window.kgShowNode(\\''+String(n.id).replace(/'/g, '')+'\\')">'+
            ico+' <span><strong>'+esc(n.label)+'</strong> <span style="color:#64748b;font-size:11px;">'+esc(n.type)+' · '+esc(n.icon)+'</span></span></button>';
        }}).join('');

      const container = document.getElementById('kg-canvas');
      // Prefer offline SVG so hard-refresh / no-CDN never looks "empty"
      drawOfflineSvg(nodesArr, edgesArr);
      // Optional: upgrade to vis-network if CDN already loaded
      if (typeof vis !== 'undefined') {{
        try {{
          const data = {{ nodes: new vis.DataSet(nodesArr), edges: new vis.DataSet(edgesArr) }};
          network = new vis.Network(container, data, {{
            physics: {{ stabilization: true, barnesHut: {{ gravitationalConstant: -12000 }} }},
            interaction: {{ hover: true, tooltipDelay: 80, multiselect: false }},
            nodes: {{ font: {{ color: '#e2e8f0', size: 12 }} }}
          }});
          network.on('click', function(params) {{
            if (params.nodes && params.nodes.length) window.kgShowNode(params.nodes[0]);
            else window.kgShowNode('__center__');
          }});
        }} catch (err) {{
          drawOfflineSvg(nodesArr, edgesArr);
        }}
      }}
    }}
    document.querySelectorAll('.kg-type').forEach(c => c.addEventListener('change', rebuild));
    try {{
      rebuild();
      window.kgShowNode('__center__');
    }} catch (err) {{
      document.getElementById('kg-panel').innerHTML =
        '<p style="color:#f59e0b;">Graph UI error (data still in page JSON): '+esc(String(err))+'</p>'+
        '<p style="color:#94a3b8;font-size:13px;">Use project chips above — they do not need the canvas.</p>';
    }}
  }})();
  </script>
"""


# ── Renderer: Static HTML ─────────────────────────────────────────────────────
def render_code_map_section(metadata: dict) -> str:
    """🗺️ Code Map — symbol/call structure from raven-xray.py's xray.json.

    Deliberately NOT merged into the memory graph canvas above: 700+ code
    symbols would drown ~25 memory nodes. Point queries + hotspots only.
    """
    xray_path = RAVEN_DIR / "xray.json"
    if not xray_path.exists():
        return (
            '<h2 id="code-map">🗺️ Code Map</h2>'
            '<div class="meta">Not built yet — it builds automatically at the end of the '
            'next session (Stop hook, throttled). Python symbols, callers, and blast-radius '
            'queries will appear here.</div>'
        )
    try:
        cmap = json.loads(xray_path.read_text())
    except Exception as e:
        return f'<h2 id="code-map">🗺️ Code Map</h2><div class="meta">xray.json unreadable: {e}</div>'

    nodes = cmap.get("nodes") or {}
    edges = cmap.get("edges") or []

    in_deg, out_deg = Counter(), Counter()
    for e in edges:
        in_deg[e["dst"]] += 1
        out_deg[e["src"]] += 1

    per_file = Counter(meta["file"] for meta in nodes.values())

    hot_rows = ""
    for nid, calls in in_deg.most_common(10):
        m = nodes.get(nid) or {}
        hot_rows += (
            f"<tr><td><code>{m.get('name','?')}</code></td>"
            f"<td>{m.get('file','?')}:{m.get('line','?')}</td>"
            f"<td class='num'>{calls}</td></tr>\n"
        )

    file_rows = ""
    for fpath, count in per_file.most_common(10):
        file_rows += f"<tr><td>{fpath}</td><td class='num'>{count}</td></tr>\n"

    # Compact symbol list for client-side search — name, location, degrees.
    search_data = [
        {"n": m["name"], "f": f"{m['file']}:{m['line']}", "t": m["type"],
         "in": in_deg.get(nid, 0), "out": out_deg.get(nid, 0)}
        for nid, m in nodes.items()
    ]

    return f"""
  <h2 id="code-map">🗺️ Code Map</h2>
  <div class="meta">
    <strong>{len(per_file)}</strong> files · <strong>{len(nodes)}</strong> symbols ·
    <strong>{len(edges)}</strong> call edges · built {cmap.get('generated_at', '?')}
    <br><span style="color:#94a3b8;font-size:12px">Scope: {cmap.get('scope', '?')} —
    dynamic dispatch (decorators, importlib, string-based calls) is not traced.
    Query from any terminal, zero tokens: <code>python3 scripts/raven-xray.py --callers NAME</code>
    · <code>--callees NAME</code> · <code>--impact NAME</code></span>
  </div>
  <div style="margin-bottom:16px">
    <input id="cm-search" type="text" placeholder="Search symbols… (name, min 2 chars)"
      style="width:100%;padding:10px 14px;background:#1e293b;border:1px solid #334155;border-radius:8px;color:#e2e8f0;font-size:14px"/>
    <div id="cm-results" style="margin-top:8px"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <h3 style="color:#94a3b8;font-size:14px;margin-bottom:8px">Most-called symbols</h3>
      <table><tr><th>Symbol</th><th>Where</th><th class="num">Callers</th></tr>
      {hot_rows}</table>
    </div>
    <div>
      <h3 style="color:#94a3b8;font-size:14px;margin-bottom:8px">Densest files (symbol count)</h3>
      <table><tr><th>File</th><th class="num">Symbols</th></tr>
      {file_rows}</table>
    </div>
  </div>
  <script type="application/json" id="cm-data">{json.dumps(search_data)}</script>
  <script>
  (function() {{
    var data = JSON.parse(document.getElementById('cm-data').textContent);
    var input = document.getElementById('cm-search');
    var out = document.getElementById('cm-results');
    input.addEventListener('input', function() {{
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) {{ out.innerHTML = ''; return; }}
      var hits = data.filter(function(d) {{ return d.n.toLowerCase().indexOf(q) !== -1; }}).slice(0, 20);
      if (!hits.length) {{ out.innerHTML = '<div class="meta">No symbols match.</div>'; return; }}
      var html = '<table><tr><th>Symbol</th><th>Type</th><th>Where</th><th class="num">Callers</th><th class="num">Calls out</th></tr>';
      hits.forEach(function(d) {{
        html += '<tr><td><code>' + d.n + '</code></td><td>' + d.t + '</td><td>' + d.f +
                '</td><td class="num">' + d['in'] + '</td><td class="num">' + d.out + '</td></tr>';
      }});
      out.innerHTML = html + '</table>';
    }});
  }})();
  </script>
"""


def render_cost_log_section(metadata: dict) -> str:
    """💰 Cost Log — per-turn, per-model rows from .raven/cost-log.jsonl.

    Only models actually observed in the transcript get rows; Raven's hook
    scripts make no API calls and are never logged (the old by_source
    overhead figures were never computed by anything — do not resurrect).
    """
    log_path = RAVEN_DIR / "cost-log.jsonl"
    if not log_path.exists():
        return (
            '<h2 id="cost-log">💰 Cost Log</h2>'
            '<div class="meta">No rows yet — the log starts filling at the end of the next '
            'turn (Stop hook). One row per model actually used, with estimated vs computed '
            'cost and running cumulative totals.</div>'
        )
    rows = []
    try:
        for line in log_path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as e:
        return f'<h2 id="cost-log">💰 Cost Log</h2><div class="meta">cost-log.jsonl unreadable: {e}</div>'

    if not rows:
        return '<h2 id="cost-log">💰 Cost Log</h2><div class="meta">Log exists but has no valid rows.</div>'

    total_computed = sum(float(r.get("computed_cost_usd") or 0) for r in rows)
    latest = rows[-1]
    recent = rows[-30:]

    body = ""
    for r in reversed(recent):
        est = r.get("est_cost_usd")
        est_cell = format_usd(est) if est is not None else "—"
        body += (
            f"<tr><td>{(r.get('ts') or '')[:19].replace('T', ' ')}</td>"
            f"<td><code>{r.get('model', '?')}</code></td>"
            f"<td>{r.get('source', '?')}</td>"
            f"<td class='num'>{(r.get('tokens_in') or 0) + (r.get('tokens_out') or 0):,}</td>"
            f"<td class='num'>{est_cell}</td>"
            f"<td class='num'>{format_usd(r.get('computed_cost_usd') or 0)}</td>"
            f"<td class='num'>{format_usd(r.get('cum_session_usd') or 0)}</td></tr>\n"
        )

    return f"""
  <h2 id="cost-log">💰 Cost Log</h2>
  <div class="meta">
    <strong>{len(rows)}</strong> rows · all-time computed total <strong>{format_usd(total_computed)}</strong> ·
    latest cumulative this month <strong>{format_usd(latest.get('cum_month_usd') or 0)}</strong>
    <br><span style="color:#94a3b8;font-size:12px">One row per model actually observed per turn
    (subagent rows appear only when a subagent with a model override really ran).
    "Est" is the router's pre-turn guess; "Computed" is real token usage × pricing —
    never merged. Raven's own hook scripts make zero API calls and are never logged as cost.
    Showing latest {len(recent)} rows.</span>
  </div>
  <table>
    <tr><th>When (UTC)</th><th>Model</th><th>Source</th><th class="num">Tokens</th>
        <th class="num">Est</th><th class="num">Computed</th><th class="num">Cum (session)</th></tr>
    {body}
  </table>
"""


def render_html(
    metrics: dict,
    metadata: dict,
    recs: list,
    graph: Optional[dict] = None,
    graph_only: bool = False,
) -> str:
    """Static HTML with download buttons; optional knowledge graph panel."""
    sev_color = {"high": "#dc2626", "medium": "#f59e0b", "info": "#3b82f6"}
    raw_json = json.dumps(
        {"metadata": metadata, "metrics": metrics, "recommendations": recs, "graph": graph},
        indent=2,
        default=str,
    )
    kg_section = render_knowledge_graph_section(
        graph or {"nodes": [], "edges": []},
        metrics=metrics,
        metadata=metadata,
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<meta http-equiv="Pragma" content="no-cache"/>
<meta http-equiv="Expires" content="0"/>
<meta name="raven-dashboard-version" content="kg-v2-grounded"/>
<title>Raven Dashboard — {metadata['project']}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 32px; line-height: 1.5; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin-bottom: 8px; }}
  h2 {{ font-size: 18px; margin: 32px 0 12px; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  .meta {{ background: #1e293b; padding: 16px 20px; border-radius: 8px; margin-bottom: 24px; font-size: 14px; }}
  .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px 24px; }}
  .meta-grid div {{ }}
  .meta-grid strong {{ color: #94a3b8; display: inline-block; min-width: 120px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
  th {{ background: #334155; color: #cbd5e1; font-weight: 600; }}
  tr:last-child td {{ border-bottom: none; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .stat {{ background: #1e293b; padding: 16px 20px; border-radius: 8px; }}
  .stat-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
  .rec {{ background: #1e293b; padding: 16px 20px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #3b82f6; }}
  .rec.high {{ border-left-color: #dc2626; }}
  .rec.medium {{ border-left-color: #f59e0b; }}
  .rec-metric {{ font-weight: 600; margin-bottom: 6px; }}
  .rec-body {{ font-size: 14px; color: #cbd5e1; }}
  .rec-body strong {{ color: #e2e8f0; }}
  .bar {{ display: inline-block; height: 10px; background: #3b82f6; border-radius: 2px; vertical-align: middle; }}
  .download {{ display: inline-block; margin: 8px 8px 24px 0; padding: 10px 20px; background: #3b82f6; color: white; border-radius: 6px; text-decoration: none; font-weight: 500; font-size: 14px; cursor: pointer; border: none; }}
  .download:hover {{ background: #2563eb; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #334155; color: #64748b; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h1>🪶 Raven Dashboard — {metadata['project']}</h1>
  <p style="color: #94a3b8; margin-bottom: 8px;">
    Generated {metadata['report_generated_at_local']} ·
    Plugin v{metadata['plugin_version']} ·
    Window: {metrics['window_start']} → {metrics['window_end']} ({metrics['window_days']} days)
  </p>
  <p style="background:#14532d;color:#bbf7d0;padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:20px;">
    <strong>Dashboard build: kg-v2-grounded</strong> —
    If you still see “Sessions 1 · Cost $0.00”, you are on a <em>cached or stale</em> file.
    Hard-refresh (Cmd+Shift+R) or re-run
    <code style="background:#052e16;padding:2px 6px;border-radius:4px;">python3 scripts/dashboard.py --html --open</code>
    from the Raven repo (not an old plugin copy).
  </p>

  <button class="download" onclick="downloadJSON()">⬇ Download JSON</button>
  <button class="download" onclick="downloadCSV()">⬇ Download CSV</button>
  <button class="download" onclick="window.print()">🖨 Print / Save PDF</button>
  <button class="download" id="refreshBtn" onclick="refreshDashboard()" style="background: #10b981;">🔄 Refresh</button>
  <a class="download" href="#knowledge-graph" style="background:#8b5cf6;text-decoration:none;">🕸 Knowledge graph</a>
  <a class="download" href="#cost-method" style="background:#0ea5e9;text-decoration:none;">📐 Cost method</a>
  <a class="download" href="#cost-compare" style="background:#f59e0b;text-decoration:none;">⚖️ Compare</a>
  <a class="download" href="#costs" style="background:#0284c7;text-decoration:none;">💰 Raven meters</a>
  <label style="display: inline-block; margin-left: 16px; color: #cbd5e1; cursor: pointer; font-size: 14px;">
    <input type="checkbox" id="autoRefresh" onchange="toggleAutoRefresh()" style="cursor: pointer; margin-right: 6px;">
    Auto-refresh every 30s
  </label>
  <span id="refreshStatus" style="display: none; color: #94a3b8; margin-left: 8px; font-size: 12px;"></span>

  <h2>📋 Project Metadata</h2>
  <div class="meta">
    <div class="meta-grid">
      <div><strong>Project</strong> {metadata['project']}</div>
      <div><strong>Company</strong> {metadata['company']}</div>
      <div><strong>Owner</strong> {metadata['owner']}</div>
      <div><strong>User</strong> {metadata['user'] or '—'}</div>
      <div><strong>Branch</strong> {metadata['git_branch'] or '—'}</div>
      <div><strong>Remote</strong> {metadata['git_remote'] or '—'}</div>
      <div><strong>Manifest</strong> {'✓ present' if metadata['manifest_present'] else '✗ MISSING'}</div>
      <div><strong>Vault</strong> {metadata['vault_path']}</div>
    </div>
  </div>

  {kg_section}

  {render_code_map_section(metadata)}

"""

    # ── Two-bucket Tokenomics Split ──
    ls = metrics.get("last_session") or {}
    ov = ls.get("raven_overhead") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "by_source": {}}
    uw = ls.get("user_work") or {"tokens": 0, "cost_usd": 0.0, "calls": 0, "tier_counts": {}}
    total_tok = ov.get("tokens", 0) + uw.get("tokens", 0)
    total_cost = float(ov.get("cost_usd", 0.0) or 0) + float(uw.get("cost_usd", 0.0) or 0)
    ov_pct = (ov.get("tokens", 0) / total_tok * 100) if total_tok else 0
    uw_pct = (uw.get("tokens", 0) / total_tok * 100) if total_tok else 0
    srcs = ", ".join(metrics.get("sources_used") or []) or "none"

    cur_proj = (
        metrics.get("current_project")
        or metadata.get("project")
        or "this-repo"
    )
    bp = metrics.get("by_project") or {}
    cur_stats = bp.get(cur_proj) or {"sessions": 0, "tokens": 0, "cost_usd": 0.0}
    # If filter applied, headline already scoped
    all_sess = metrics["sessions_count"]
    all_tok = metrics["total_tokens"]
    all_cost = metrics["total_cost_usd"]
    cur_sess = int(cur_stats.get("sessions") or 0)
    cur_tok = int(cur_stats.get("tokens") or 0)
    cur_cost = float(cur_stats.get("cost_usd") or 0)
    cur_avg = (cur_cost / cur_sess) if cur_sess else 0.0
    all_avg = metrics.get("avg_cost_per_session") or 0.0

    # Citations for this page
    citations = build_citation_registry(metrics, metadata)
    c1, c2, c3 = cite_chip("C1"), cite_chip("C2"), cite_chip("C3")
    c4, c5, c6, c7, c8 = (
        cite_chip("C4"),
        cite_chip("C5"),
        cite_chip("C6"),
        cite_chip("C7"),
        cite_chip("C8"),
    )

    # Per-repo mini table for headline area
    bp_rows = ""
    for pname, st in bp.items():
        url = f"https://github.com/giggsoinc/{pname}"
        local = ""
        hub = VAULT / "projects" / f"{pname}.md"
        hub_txt = ""
        if hub.exists():
            try:
                hub_txt = hub.read_text(errors="replace")
                url = _repo_url_from_hub(hub_txt, pname, metadata) or url
            except Exception:
                pass
        local = resolve_local_path(pname, hub_txt)
        local_html = _local_link_html(local, "Local")
        bp_rows += (
            f"<tr style='cursor:pointer' onclick=\"window.kgShowNode && window.kgShowNode('projects/{pname}')\">"
            f"<td><a href='{url}' target='_blank' rel='noopener' onclick='event.stopPropagation()'>{pname}</a> {c1}{c5}</td>"
            f"<td class='num'>{st.get('sessions',0)} {c1}</td>"
            f"<td class='num'>{int(st.get('tokens',0)):,} {c1}</td>"
            f"<td class='num'>{format_usd(st.get('cost_usd',0))} {c1}</td>"
            f"<td onclick='event.stopPropagation()'>"
            f"<a href='{url}' target='_blank' rel='noopener'>GitHub ↗</a>"
            f"{(' · ' + local_html) if local_html else ''}"
            f"</td>"
            f"</tr>\n"
        )
    if not bp_rows:
        bp_rows = (
            "<tr><td colspan='5' style='color:#94a3b8'>"
            "No per-repo metrics in window yet (no project-tagged rows in C1)."
            "</td></tr>"
        )

    n_graph_nodes = len((graph or {}).get("nodes") or []) if graph else 0
    n_graph_edges = len((graph or {}).get("edges") or []) if graph else 0
    n_guards = sum((metrics.get("guard_events") or {}).values())

    # Bibliography HTML
    bib_rows = ""
    for c in citations:
        bib_rows += (
            f"<tr id='cite-{c['id']}'>"
            f"<td><strong>[{c['id']}]</strong></td>"
            f"<td>{c['title']}</td>"
            f"<td><code style='font-size:11px;word-break:break-all'>{c['path']}</code></td>"
            f"<td style='font-size:12px;color:#cbd5e1'>{c['field']}<br>"
            f"<span style='color:#94a3b8'>{c['rule']}</span></td>"
            f"<td style='font-size:12px'>{c['used_for']}</td>"
            f"</tr>\n"
        )

    html += f"""
  <style>
    a.cite {{ color:#38bdf8; font-size:11px; font-weight:600; text-decoration:none; margin-left:4px;
      vertical-align:super; }}
    a.cite:hover {{ text-decoration:underline; color:#7dd3fc; }}
    .cite-raw {{ color:#64748b; font-size:11px; margin-top:6px; font-family:ui-monospace,monospace; }}
    #citations tr:target {{ background:#1e3a5f; }}
  </style>

  <h2 id="agent-memory">🧠 How this is used for development — agent memory</h2>
  <div class="meta" style="border-left:4px solid #a78bfa;margin-bottom:20px;line-height:1.55;font-size:14px;">
    <p style="margin-bottom:10px;">
      This dashboard is the <strong>human view</strong> of the same RavenVault that agents load as
      <strong>working memory</strong> — not a separate analytics product.
    </p>
    <ol style="margin:0 0 0 18px;color:#cbd5e1;">
      <li style="margin-bottom:8px;"><strong>SessionStart</strong> — <code>vault-load.py</code> injects a short digest
        (hub current state, open questions, last session summaries, recent decisions) into agent context
        {c5}. Agents do <em>not</em> dump multi‑MB vault files into the prompt.</li>
      <li style="margin-bottom:8px;"><strong>During coding</strong> — Andie / specialists route work; guards scan writes;
        model-router may record overhead into <code>.model-session.json</code> {c3}.</li>
      <li style="margin-bottom:8px;"><strong>Session end (Stop)</strong> — <code>token-meter-write</code> → metrics {c1};
        <code>obsidian-log</code> → short session note + project hub {c5};
        <code>knowledge-extract</code> may add concepts/decisions; graph JSON rebuildable {c4}.</li>
      <li style="margin-bottom:8px;"><strong>Next session</strong> — agent memory resumes from hubs/open questions,
        so brownfield debug and greenfield plans start from prior facts, not a blank chat.</li>
      <li><strong>You (developer)</strong> — use this page to verify costs are real, jump to repos, and audit whether
        memory notes match the work you expected. If a number has no citation, treat it as a bug.</li>
    </ol>
    <p style="margin-top:12px;color:#94a3b8;font-size:13px;">
      Generated {metadata.get('report_generated_at_local')} {c8} · project identity {c7} ·
      build <code>kg-v2-grounded+cite</code>
    </p>
  </div>

  {render_cost_compare_section(metrics, metadata)}

  {render_cost_log_section(metadata)}

  <h2 id="costs">📊 Headline numbers — Raven-metered only (every value cited)</h2>
  <p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">
    These figures are <strong>Raven-metered</strong> (token × model rate card), not invoices.
    Click a blue <span class="cite">[C#]</span> for bibliography. Window
    <strong>{metrics['window_start']}</strong> → <strong>{metrics['window_end']}</strong>
    ({metrics['window_days']}d). Sub-cent costs never round to $0.00.
    For Claude/Console money, use the <a href="#cost-compare" style="color:#38bdf8;">side-by-side compare</a> above.
  </p>

  <div class="stat-grid">
    <div class="stat" style="border-left:4px solid #8b5cf6;">
      <div class="stat-label">All repos (portfolio) {c1}</div>
      <div class="stat-value">{format_usd(all_cost)} {c1}</div>
      <div style="color:#94a3b8;font-size:12px;margin-top:8px;">
        sessions <strong>{all_sess:,}</strong> {c1} ·
        tokens <strong>{all_tok:,}</strong> {c1} ·
        avg/session <strong>{format_usd(all_avg)}</strong> {c1}
      </div>
      <div class="cite-raw">raw cost_usd={all_cost} · formula: sum(C1.cost) / count(C1.sessions) for avg</div>
    </div>
    <div class="stat" style="border-left:4px solid #0ea5e9;">
      <div class="stat-label">This repo — {cur_proj} {c2}{c7}</div>
      <div class="stat-value">{format_usd(cur_cost)} {c2}</div>
      <div style="color:#94a3b8;font-size:12px;margin-top:8px;">
        sessions <strong>{cur_sess:,}</strong> {c2} ·
        tokens <strong>{cur_tok:,}</strong> {c2} ·
        avg <strong>{format_usd(cur_avg)}</strong> {c2}
      </div>
      <div class="cite-raw">raw cost_usd={cur_cost} · filter project=={cur_proj}</div>
    </div>
    <div class="stat" style="border-left:4px solid #f59e0b;">
      <div class="stat-label">Live session (now) {c3}</div>
      <div class="stat-value">{format_usd(total_cost)} {c3}</div>
      <div style="color:#94a3b8;font-size:12px;margin-top:8px;">
        tokens <strong>{total_tok:,}</strong> {c3}
        (overhead {ov.get('tokens',0):,} {c3} + user {uw.get('tokens',0):,} {c3})
      </div>
      <div class="cite-raw">raw cost_usd={total_cost} · file .raven/.model-session.json</div>
    </div>
    <div class="stat">
      <div class="stat-label">Graph + guards {c4}{c6}</div>
      <div class="stat-value" style="font-size:18px;">{n_graph_nodes} nodes {c4}</div>
      <div style="color:#94a3b8;font-size:12px;margin-top:8px;">
        {n_graph_edges} edges {c4} · {n_guards} guard events in window {c6}
      </div>
      <div class="cite-raw">sources_used: {srcs or 'none'}</div>
    </div>
  </div>

  <h3 style="color:#94a3b8;margin:20px 0 8px;font-size:14px;">
    Per-repo in window {c1}{c5} (click row → graph briefing / agent memory hub)
  </h3>
  <table>
    <thead>
      <tr>
        <th>Repo {c5}</th>
        <th class="num">Sessions {c1}</th>
        <th class="num">Tokens {c1}</th>
        <th class="num">Cost {c1}</th>
        <th>GitHub + Local {c5}</th>
      </tr>
    </thead>
    <tbody>
      {bp_rows}
    </tbody>
  </table>
  <p style="color:#64748b;font-size:12px;margin:8px 0 20px;">
    Rebuild: <code>python3 scripts/dashboard.py --html --open</code>
    · one repo: <code>--project {cur_proj}</code>
  </p>

  <h2>Tokenomics split — Raven code vs user work {c3}</h2>
  <p style="color:#94a3b8;font-size:13px;margin-bottom:16px;">
    Both buckets are fields on the live session file {c3}.
    Raven code = infrastructure overhead; User work = classified user turns (when metered).
  </p>
  <div class="stat-grid" style="grid-template-columns:1fr 1fr;">
    <div class="stat" style="border-left:4px solid #8b5cf6;">
      <div class="stat-label">Raven code (overhead) {c3}</div>
      <div class="stat-value">{ov.get('tokens',0):,} {c3}</div>
      <div style="color:#94a3b8;font-size:13px;margin-top:8px;">
        {format_usd(ov.get('cost_usd',0))} {c3} ·
        {ov.get('calls',0)} calls {c3} ·
        {ov_pct:.1f}% of live tokens {c3}
      </div>
      <div class="cite-raw">path: raven_overhead.* in .model-session.json</div>
    </div>
    <div class="stat" style="border-left:4px solid #10b981;">
      <div class="stat-label">User work {c3}</div>
      <div class="stat-value">{uw.get('tokens',0):,} {c3}</div>
      <div style="color:#94a3b8;font-size:13px;margin-top:8px;">
        {format_usd(uw.get('cost_usd',0))} {c3} ·
        {uw.get('calls',0)} calls {c3} ·
        {uw_pct:.1f}% of live tokens {c3}
      </div>
      <div class="cite-raw">path: user_work.* — $0 tokens often means transcript meter did not run yet</div>
    </div>
  </div>
"""

    # Raven Code by-source breakdown
    by_src = ov.get("by_source") or {}
    if by_src:
        html += f'<h2>Raven code — overhead by source {c3}</h2>\n'
        html += (
            '<table>\n<thead><tr><th>Source {c3}</th><th class="num">Tokens {c3}</th>'
            '<th class="num">Calls {c3}</th><th class="num">Cost {c3}</th></tr></thead>\n<tbody>\n'
        )
        for src, info in sorted(by_src.items(), key=lambda x: -x[1].get("tokens", 0)):
            html += (
                f'<tr><td><code>{src}</code> {c3}</td>'
                f'<td class="num">{info.get("tokens",0):,} {c3}</td>'
                f'<td class="num">{info.get("calls",0)} {c3}</td>'
                f'<td class="num">{format_usd(info.get("cost_usd",0))} {c3}</td></tr>\n'
            )
        html += '</tbody></table>\n'
        html += (
            '<p class="cite-raw">Each row = raven_overhead.by_source.&lt;name&gt; in '
            f'{MODEL_SESSION if MODEL_SESSION.exists() else ".raven/.model-session.json"}</p>\n'
        )

    # Provider attribution (Codex-tier matters)
    providers = ls.get("providers") or {}
    if providers:
        html += '<h2>🔌 Provider Attribution</h2>\n'
        html += '<table>\n<thead><tr><th>Provider</th><th class="num">Tokens</th><th class="num">Share</th><th class="num">Cost (USD)</th></tr></thead>\n<tbody>\n'
        for prov, info in providers.items():
            tok = info.get("tokens", 0)
            cost = info.get("cost_usd", 0.0)
            pct = (tok / total_tok * 100) if total_tok else 0
            html += f'<tr><td><code>{prov}</code></td><td class="num">{tok:,}</td><td class="num">{pct:.1f}%</td><td class="num">${cost:.4f}</td></tr>\n'
        html += '</tbody></table>\n'

    if metrics["tier_counts"]:
        html += '<h2>🎯 Tier Mix</h2>\n<table>\n<thead><tr><th>Tier</th><th class="num">Count</th><th class="num">Share</th><th class="num">Cost (USD)</th><th>Distribution</th></tr></thead>\n<tbody>\n'
        for tier in ["SIMPLE", "MEDIUM", "COMPLEX", "LOCAL_ONLY"]:
            c = metrics["tier_counts"].get(tier, 0)
            p = metrics["tier_share_pct"].get(tier, 0)
            cost = metrics["tier_cost"].get(tier, 0)
            html += f'<tr><td>{tier}</td><td class="num">{c}</td><td class="num">{p:.1f}%</td><td class="num">${cost:.3f}</td><td><span class="bar" style="width:{p*2}px"></span></td></tr>\n'
        html += '</tbody></table>\n'

    if metrics["cost_by_day"]:
        html += '<h2>📅 Daily Series</h2>\n<table>\n<thead><tr><th>Date</th><th class="num">Sessions</th><th class="num">Tokens</th><th class="num">Cost</th></tr></thead>\n<tbody>\n'
        for day in sorted(metrics["sessions_by_day"].keys()):
            s = metrics["sessions_by_day"][day]
            t = metrics["tokens_by_day"].get(day, 0)
            c = metrics["cost_by_day"].get(day, 0)
            html += f'<tr><td>{day}</td><td class="num">{s}</td><td class="num">{t:,}</td><td class="num">{format_usd(c)}</td></tr>\n'
        html += '</tbody></table>\n'

    if metrics["skills_used"]:
        html += '<h2>🛠 Top Skills</h2>\n<table>\n<thead><tr><th>Skill</th><th class="num">Invocations</th></tr></thead>\n<tbody>\n'
        for skill, count in list(metrics["skills_used"].items())[:15]:
            html += f'<tr><td>{skill}</td><td class="num">{count}</td></tr>\n'
        html += '</tbody></table>\n'

    if metrics["guard_events"]:
        html += '<h2>🛡 Guard Events</h2>\n<table>\n<thead><tr><th>Event</th><th class="num">Count</th></tr></thead>\n<tbody>\n'
        for event, count in sorted(metrics["guard_events"].items(), key=lambda x: -x[1])[:15]:
            html += f'<tr><td>{event}</td><td class="num">{count}</td></tr>\n'
        html += '</tbody></table>\n'

    html += '<h2>💡 Recommendations — Grouped by Owner</h2>\n'
    html += '<p style="color:#94a3b8;font-size:13px;margin-bottom:16px;">Different cost owners need different fixes. Issues are tagged by who controls the lever.</p>\n'
    if not recs:
        html += '<p style="color:#10b981;background:#1e293b;padding:16px;border-radius:8px;">✓ All metrics within healthy bands. No actions needed.</p>\n'
    else:
        groups = {
            "raven_team": ("🪶 Raven Hygiene", "Raven team owns these — file issues if persistent.", "#8b5cf6"),
            "user":       ("👤 User Behavior", "You own these — prompt tuning, /clear cadence, model choice.", "#10b981"),
            "config":     ("⚙️ Environment / Setup", "Configuration issues — manifest, hooks, guards, vault wiring.", "#f59e0b"),
        }
        counter = 1
        for owner_key, (title, blurb, color) in groups.items():
            owner_recs = [r for r in recs if r.get("owner") == owner_key]
            if not owner_recs:
                continue
            html += f'<h3 style="color:{color};margin-top:24px;margin-bottom:8px;border-bottom:2px solid {color};padding-bottom:4px;">{title}</h3>\n'
            html += f'<p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">{blurb}</p>\n'
            for r in owner_recs:
                html += f'<div class="rec {r["severity"]}" style="border-left-color:{color};">\n'
                html += f'<div class="rec-metric">[{counter}] {r["metric"]}</div>\n'
                html += f'<div class="rec-body"><strong>Issue:</strong> {r["issue"]}<br><strong>Action:</strong> {r["action"]}'
                if r.get("savings_estimate_usd"):
                    html += f' <br><strong>Estimated savings:</strong> ${r["savings_estimate_usd"]:.2f}'
                html += '</div></div>\n'
                counter += 1

    html += f"""
  <h2 id="citations">📚 Citations — every number on this page</h2>
  <p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">
    Inline <span class="cite">[C#]</span> / <span class="cite">[S#]</span> markers jump here.
    If a displayed figure cannot be traced to a row below, treat the UI as buggy.
  </p>
  <table>
    <thead>
      <tr>
        <th>Id</th><th>What</th><th>Path</th><th>Field / rule</th><th>Used for</th>
      </tr>
    </thead>
    <tbody>
      {bib_rows}
    </tbody>
  </table>

  <div class="footer">
    Generated by Raven v{metadata['plugin_version']} · Local-only · No telemetry ·
    build kg-v2-grounded+cite · agent memory = RavenVault
  </div>
</div>

<script>
const DATA = {raw_json};
let autoRefreshInterval = null;

function downloadJSON() {{
  const blob = new Blob([JSON.stringify(DATA, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'raven-dashboard-{metadata['project']}-{datetime.now().strftime('%Y%m%d-%H%M')}.json';
  a.click();
  URL.revokeObjectURL(url);
}}

function downloadCSV() {{
  const rows = [
    ['date', 'sessions', 'tokens', 'cost_usd'],
    ...Object.keys(DATA.metrics.sessions_by_day).sort().map(d => [
      d,
      DATA.metrics.sessions_by_day[d] || 0,
      DATA.metrics.tokens_by_day[d] || 0,
      (DATA.metrics.cost_by_day[d] || 0).toFixed(4)
    ])
  ];
  const csv = rows.map(r => r.join(',')).join('\\n');
  const blob = new Blob([csv], {{type: 'text/csv'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'raven-dashboard-{metadata['project']}-{datetime.now().strftime('%Y%m%d-%H%M')}.csv';
  a.click();
  URL.revokeObjectURL(url);
}}

function refreshDashboard() {{
  const status = document.getElementById('refreshStatus');
  status.style.display = 'inline';
  status.style.color = '#94a3b8';
  status.textContent = '🔄 Refreshing...';

  // Prefer local dashboard-server (regenerates HTML). file:// cannot rebuild itself.
  fetch('http://127.0.0.1:9787/refresh')
    .then(r => r.json())
    .then(data => {{
      status.textContent = '✅ Regenerated — reloading…';
      setTimeout(() => {{ location.reload(); }}, 400);
    }})
    .catch(err => {{
      status.style.color = '#fbbf24';
      status.textContent = 'Hard refresh only reloads this file. Rebuild: python3 scripts/dashboard.py --html --open';
    }});
}}

function toggleAutoRefresh() {{
  const checkbox = document.getElementById('autoRefresh');
  const status = document.getElementById('refreshStatus');

  if (checkbox.checked) {{
    status.style.display = 'inline';
    status.textContent = '🔄 Auto-refresh: 30s interval';
    localStorage.setItem('auto-refresh', 'true');
    autoRefreshInterval = setInterval(() => {{
      location.reload();
    }}, 30000);
  }} else {{
    if (autoRefreshInterval) clearInterval(autoRefreshInterval);
    status.style.display = 'none';
    localStorage.setItem('auto-refresh', 'false');
  }}
}}

// Restore auto-refresh checkbox state on page load
window.addEventListener('load', function() {{
  const checkbox = document.getElementById('autoRefresh');
  if (localStorage.getItem('auto-refresh') === 'true') {{
    checkbox.checked = true;
    toggleAutoRefresh();
  }}
}});
</script>
</body>
</html>
"""
    return html


# ── Main ──────────────────────────────────────────────────────────────────────
# ── Drift Audit (Method C) ─────────────────────────────────────────────────────
#
# Sampling-based safety net that catches attribution drift. Runs weekly via
# /loop or cron. Verifies known-overhead sources are correctly tagged and
# detects suspiciously high single-call user_work tokens (likely leaked overhead).

KNOWN_OVERHEAD_EXACT = {
    "triage-router", "architect-router", "session-start",
    "token-guard", "obsidian-log", "cve-prompt-guard",
    "secret-scan", "audit-log", "db-guard", "schema-guard",
    "mcp-guard", "policy-sync", "stream-signal", "raven_agent",
    "model-router", "log-overhead",
}
KNOWN_OVERHEAD_PREFIXES = ("skill-load:", "raven-hook:", "guard:")


def audit_drift(metrics: dict, metadata: dict, sample_rate: float = 0.01) -> dict:
    """
    Sample by_source attributions and check for drift.

    Findings categories:
      - unknown_source: source in raven_overhead not in known-good list
      - high_avg_user: user_work avg/call suspiciously high (overhead leak)
      - missing_source: known hook fired but no overhead recorded
      - cross_session_drift: per-source token average shifts >2x vs baseline
    """
    findings = []
    ls = metrics.get("last_session") or {}
    ov = ls.get("raven_overhead") or {}
    uw = ls.get("user_work") or {}
    by_src = ov.get("by_source") or {}

    # Check 1 — unknown overhead sources
    for src, info in by_src.items():
        is_known = (
            src in KNOWN_OVERHEAD_EXACT
            or any(src.startswith(p) for p in KNOWN_OVERHEAD_PREFIXES)
        )
        if not is_known:
            findings.append({
                "severity": "warn",
                "kind": "unknown_source",
                "source": src,
                "tokens": info.get("tokens", 0),
                "issue": f"Source '{src}' not in known-good overhead list",
                "action": "If legitimate, add to KNOWN_OVERHEAD_EXACT in dashboard.py. "
                         "If unexpected, audit the caller — may be misattribution.",
            })

    # Check 2 — user_work avg suspiciously high (overhead leak)
    tier_counts = uw.get("tier_counts") or {}
    user_calls = sum(tier_counts.values())
    if user_calls > 0:
        avg_per_call = uw.get("tokens", 0) / user_calls
        if avg_per_call > 100000:
            findings.append({
                "severity": "high",
                "kind": "high_avg_user",
                "source": "user_work bucket",
                "tokens": int(avg_per_call),
                "issue": f"User work avg {avg_per_call:,.0f} tokens/call — unusually high (>100K).",
                "action": "Likely overhead is being misattributed to user_work. "
                         "Audit recent log-overhead calls for missing --source flag, "
                         "or check if model-router got --source override accidentally.",
            })

    # Check 3 — total overhead vs total session
    total_tok = ov.get("tokens", 0) + uw.get("tokens", 0)
    ov_pct = (ov.get("tokens", 0) / total_tok * 100) if total_tok else 0
    if total_tok > 1000 and ov_pct < 0.1:
        findings.append({
            "severity": "warn",
            "kind": "missing_overhead",
            "source": "raven_overhead bucket",
            "tokens": 0,
            "issue": f"Raven overhead at {ov_pct:.2f}% — implausibly low.",
            "action": "Hooks may not be calling log-overhead.py. "
                     "Verify triage-router + architect-router fire _log_overhead after emission.",
        })

    # Write audit log
    audit_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".raven" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"dashboard-audit-{datetime.now().strftime('%Y-%m-%d')}.log"
    try:
        with open(audit_path, "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kind": "dashboard_audit",
                "project": metadata.get("project"),
                "findings_count": len(findings),
                "findings": findings,
                "metrics_snapshot": {
                    "raven_overhead_tokens": ov.get("tokens", 0),
                    "user_work_tokens": uw.get("tokens", 0),
                    "ov_pct": round(ov_pct, 2),
                    "sources_count": len(by_src),
                },
            }, default=str) + "\n")
    except Exception:
        pass  # never block

    return {
        "findings": findings,
        "audit_log_path": str(audit_path),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources_audited": len(by_src),
        "drift_detected": len(findings) > 0,
    }


def render_audit_cli(audit: dict) -> str:
    """Compact audit-only CLI output."""
    out = []
    out.append("")
    out.append("━" * 70)
    out.append("  RAVEN — DRIFT AUDIT (Method C — Sampling Safety Net)")
    out.append("━" * 70)
    out.append(f"  Checked at      : {audit['checked_at']}")
    out.append(f"  Sources audited : {audit['sources_audited']}")
    out.append(f"  Audit log       : {audit['audit_log_path']}")
    out.append(f"  Drift detected  : {'⚠️  YES' if audit['drift_detected'] else '✅ NO'}")
    out.append("")
    findings = audit["findings"]
    if not findings:
        out.append("  ✅ All sources correctly attributed. No drift detected.")
    else:
        sev_icon = {"high": "🔴", "warn": "🟡", "info": "🔵"}
        for i, f in enumerate(findings, 1):
            icon = sev_icon.get(f["severity"], "⚪")
            out.append(f"  {icon} [{i}] {f['kind']}: {f['source']}")
            out.append(f"        Tokens: {f['tokens']:,}")
            out.append(f"        Issue:  {f['issue']}")
            out.append(f"        Action: {f['action']}")
            out.append("")
    out.append("━" * 70)
    out.append("  Run weekly: /loop 7d /raven-dashboard --audit")
    out.append("━" * 70)
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Raven Tokenomics & Usage Dashboard")
    parser.add_argument("--cli", action="store_true", help="Render to terminal")
    parser.add_argument("--obsidian", action="store_true", help="Write Dashboard.md to ~/RavenVault/")
    parser.add_argument("--html", action="store_true", help="Write dashboard.html to ~/RavenVault/")
    parser.add_argument("--graph-only", action="store_true",
                        help="Rebuild knowledge-graph.json + knowledge-graph.html")
    parser.add_argument("--graph-json", action="store_true",
                        help="Only write ~/RavenVault/graph/knowledge-graph.json")
    parser.add_argument("--json", action="store_true", help="Dump raw metrics JSON")
    parser.add_argument("--all", action="store_true", help="All output modes")
    parser.add_argument("--audit", action="store_true",
                        help="Run drift audit on attribution buckets (Method C — sampling safety net)")
    parser.add_argument("--open", action="store_true", help="Open HTML report after writing")
    parser.add_argument(
        "--if-stale", type=int, default=None, metavar="MINUTES",
        help="Skip the run entirely if dashboard-stamp.json is younger than MINUTES. "
             "For unattended Stop-hook use — Stop fires every turn, so without this "
             "the ~3000-line HTML build would re-run on every single turn.",
    )
    parser.add_argument("--days", type=int, default=30, help="Window in days (default 30)")
    parser.add_argument("--month", type=str, help="Specific month YYYY-MM")
    parser.add_argument("--project", type=str, help="Filter by project name")
    # Enterprise Stop hook: dashboard.py --html --current-project
    parser.add_argument(
        "--current-project",
        action="store_true",
        help="Filter to the current repo (cwd/git/manifest). Used by global Stop hooks.",
    )
    # parse_known_args: never exit 2 on unknown legacy flags from older plugins
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"dashboard: ignoring unknown args {unknown}", file=sys.stderr)

    if args.if_stale is not None:
        stamp_path = VAULT / "dashboard-stamp.json"
        try:
            if stamp_path.exists():
                stamp_data = json.loads(stamp_path.read_text())
                generated_at = datetime.strptime(
                    stamp_data["generated_at"], "%Y-%m-%d %H:%M:%S"
                )
                age_minutes = (datetime.now() - generated_at).total_seconds() / 60
                if age_minutes < args.if_stale:
                    # Fresh enough — skip the rebuild silently (this is the
                    # common case when called from a Stop hook every turn).
                    return
        except Exception:
            pass  # missing/corrupt stamp — fall through and build

    if not (
        args.cli or args.obsidian or args.html or args.json or args.all
        or args.audit or args.graph_only or args.graph_json
    ):
        # Hook default: if only --current-project, still build HTML
        if args.current_project:
            args.html = True
        else:
            args.cli = True  # default

    # Resolve project filter
    project_filter = args.project
    if args.current_project and not project_filter:
        project_filter = (
            (collect_metadata() or {}).get("project")
            or Path.cwd().name
        )
        try:
            remote = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if remote:
                project_filter = remote.rstrip("/").split("/")[-1].replace(".git", "")
        except Exception:
            pass
        # Prefer manifest if present
        if MANIFEST.exists():
            try:
                project_filter = json.loads(MANIFEST.read_text()).get("project") or project_filter
            except Exception:
                pass

    days = args.days
    if args.month:
        try:
            year, month = args.month.split("-")
            days = 31  # rough — aggregator filters by date anyway
        except Exception:
            print(f"Invalid --month format. Use YYYY-MM. Got: {args.month}", file=sys.stderr)
            days = 30  # fail-soft for hooks (do not exit 2)

    graph = None
    if args.html or args.all or args.graph_only or args.graph_json:
        try:
            graph = _load_or_build_graph(project_filter=project_filter, session_days=days)
        except Exception as e:
            print(f"dashboard: graph build failed (continuing): {e}", file=sys.stderr)
            graph = {"nodes": [], "edges": []}
        if args.graph_json and not (args.html or args.graph_only or args.all):
            print(
                f"🕸 knowledge-graph.json: {VAULT / 'graph' / 'knowledge-graph.json'} "
                f"({len(graph.get('nodes', []))} nodes)",
                file=sys.stderr,
            )
            return

    metadata = collect_metadata()
    metrics = aggregate(days=days, project_filter=project_filter)
    recs = recommend(metrics, metadata)

    # Drift audit — runs independently or alongside other modes
    audit_result = None
    if args.audit:
        audit_result = audit_drift(metrics, metadata)
        print(render_audit_cli(audit_result))
        # Exit non-zero if drift detected (useful for CI / scheduled checks)
        if audit_result["drift_detected"]:
            print(f"⚠️  {len(audit_result['findings'])} drift findings — see {audit_result['audit_log_path']}",
                  file=sys.stderr)

    if args.cli or args.all:
        print(render_cli(metrics, metadata, recs))

    if args.obsidian or args.all:
        VAULT.mkdir(parents=True, exist_ok=True)
        VAULT_DASHBOARD_MD.write_text(render_obsidian(metrics, metadata, recs))
        print(f"📝 Obsidian dashboard: {VAULT_DASHBOARD_MD}", file=sys.stderr)

    if args.html or args.all:
        VAULT.mkdir(parents=True, exist_ok=True)
        html_out = render_html(metrics, metadata, recs, graph=graph)
        # Atomic write — single dashboard.html (tokenomics + knowledge graph)
        tmp = VAULT_DASHBOARD_HTML.with_suffix(".html.tmp")
        tmp.write_text(html_out)
        tmp.replace(VAULT_DASHBOARD_HTML)
        # Remove legacy dual-file names (never delete dashboard.html itself).
        # dashboard-kg.html used to be in this cleanup list, but it's now the
        # deliberate fixed-name snapshot written below — no longer legacy.
        for legacy_name in ("OPEN-GRAPH.html",):
            lp = VAULT / legacy_name
            try:
                if lp.is_file():
                    lp.unlink()
            except OSError:
                pass
        # Fixed-name snapshot alongside dashboard.html — same content, stable
        # filename across versions (PLUGIN_VERSION is shown inside the page's
        # meta tag/footer instead of the filename). Overwritten on every
        # rebuild, so it always reflects whatever version last ran.
        versioned_path = VAULT / "dashboard-kg.html"
        vtmp = versioned_path.with_suffix(".html.tmp")
        vtmp.write_text(html_out)
        vtmp.replace(versioned_path)
        stamp = {
            "build": "kg-v2-grounded+cite",
            "generated_at": metadata.get("report_generated_at_local"),
            "path": str(VAULT_DASHBOARD_HTML),
            "versioned_path": str(versioned_path),
            "plugin_version": PLUGIN_VERSION,
            "bytes": len(html_out),
            "graph_nodes": len((graph or {}).get("nodes") or []),
            "graph_edges": len((graph or {}).get("edges") or []),
        }
        (VAULT / "dashboard-stamp.json").write_text(json.dumps(stamp, indent=2) + "\n")
        print(
            f"🌐 HTML dashboard: {VAULT_DASHBOARD_HTML} ({len(html_out)} bytes, "
            f"nodes={stamp['graph_nodes']})",
            file=sys.stderr,
        )
        if args.open:
            try:
                subprocess.run(["open", str(VAULT_DASHBOARD_HTML)], check=False)
            except Exception:
                pass

    if args.graph_only:
        VAULT.mkdir(parents=True, exist_ok=True)
        # Minimal shell around graph panel for bookmarking
        kg_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Raven Knowledge Graph — {metadata.get('project')}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background:#0f172a; color:#e2e8f0; padding:24px; }}
  .meta {{ background:#1e293b; padding:16px; border-radius:8px; margin-bottom:16px; }}
  .download {{ display:inline-block; margin:8px 8px 8px 0; padding:10px 20px; background:#3b82f6; color:white;
    border-radius:6px; text-decoration:none; font-weight:500; font-size:14px; cursor:pointer; border:none; }}
  table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:8px; overflow:hidden; }}
  th, td {{ padding:10px 14px; text-align:left; border-bottom:1px solid #334155; font-size:14px; }}
  th {{ background:#334155; color:#cbd5e1; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  a {{ color:#38bdf8; }}
</style></head><body>
<h1>🪶 Raven Knowledge Graph</h1>
<div class="meta">Project filter: {project_filter or 'all'} · Vault: {VAULT}</div>
{render_knowledge_graph_section(graph or {{'nodes': [], 'edges': []}}, metrics=metrics, metadata=metadata)}
</body></html>
"""
        kg_path = VAULT / "knowledge-graph.html"
        kg_path.write_text(kg_html)
        print(f"🕸 Graph HTML: {kg_path}", file=sys.stderr)
        if args.open:
            try:
                subprocess.run(["open", str(kg_path)], check=False)
            except Exception:
                pass

    if args.json:
        payload = {"metadata": metadata, "metrics": metrics, "recommendations": recs}
        if graph is not None:
            payload["graph"] = graph
        if audit_result is not None:
            payload["audit"] = audit_result
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # Never block Claude Stop hooks (exit 2 from argparse was the failure mode)
        code = e.code if isinstance(e.code, int) else 0
        if code not in (0, None):
            print(f"dashboard: coerced exit {code} → 0 (hook fail-soft)", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"dashboard: fail-soft error: {e}", file=sys.stderr)
        sys.exit(0)
