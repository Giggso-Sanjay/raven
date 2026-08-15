#!/usr/bin/env python3
"""
kg_icons.py — tiny SVG icons for Raven knowledge graph (vibe-coder UI).

Icons ship in assets/kg-icons/*.svg and are inlined as data-URIs so
file:// dashboards work offline with no CDN.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional

# Resolve icons next to repo root (scripts/../assets/kg-icons)
_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "kg-icons"

# node type → default icon key
TYPE_ICONS = {
    "project": "project",
    "concept": "concept",
    "decision": "decision",
    "session": "session",
    "overview": "workflow",
    "unknown": "unknown",
}

# keyword in id/label/path → icon (first match wins; order matters)
KEYWORD_ICONS: list[tuple[re.Pattern, str]] = [
    # Use word-ish boundaries so "sso" does not match inside "processor"
    (re.compile(r"(login|sign[-_]?in|oauth|\bsso\b|password|credential|\bauth\b)", re.I), "login"),
    (re.compile(r"(secur|guard|\bcve\b|secret|\bvault\b|encrypt|permission|\brbac\b)", re.I), "security"),
    (re.compile(r"(database|postgres|oracle|\bsql\b|mongo|redis|\bdb\b)", re.I), "database"),
    (re.compile(r"(\bapi\b|endpoint|\brest\b|graphql|grpc|router)", re.I), "api"),
    (re.compile(r"(\bui\b|frontend|react|\bvue\b|screen|report|dashboard|\bcss\b)", re.I), "ui"),
    (re.compile(r"(payment|billing|money|\bcard\b|credit|invoice|stripe)", re.I), "money"),
    (re.compile(r"(cloud|\baws\b|azure|\bgcp\b|\boci\b|\bs3\b|deploy)", re.I), "cloud"),
    (re.compile(r"(workflow|pipeline|orchestr|kafka|queue|stream)", re.I), "workflow"),
    (re.compile(r"(\betl\b|analytics|metric|\btoken\b)", re.I), "data"),
    (re.compile(r"(module|service|backend|python|java|\.py\b)", re.I), "code"),
    (re.compile(r"(session|meeting|standup)", re.I), "session"),
    (re.compile(r"(decision|\badr\b|chose|decided)", re.I), "decision"),
    (re.compile(r"(concept|\bidea\b)", re.I), "concept"),
]

# emoji fallbacks when SVG missing (still readable for vibe coders)
EMOJI = {
    "project": "📦",
    "concept": "💡",
    "decision": "✅",
    "session": "⏱️",
    "login": "🔐",
    "security": "🛡️",
    "database": "🗄️",
    "api": "🔌",
    "ui": "🖥️",
    "cloud": "☁️",
    "money": "💳",
    "data": "📊",
    "workflow": "🔄",
    "code": "💻",
    "unknown": "❓",
}

# plain-English labels for the legend
LEGEND = [
    ("project", "App / whole repo"),
    ("concept", "Idea / system piece"),
    ("decision", "Choice we locked in"),
    ("session", "A day of work"),
    ("login", "Login / auth"),
    ("security", "Security / guards"),
    ("database", "Database"),
    ("api", "API / backend calls"),
    ("ui", "Screens / UI"),
    ("money", "Money / payments"),
    ("cloud", "Cloud / deploy"),
    ("workflow", "Pipeline / flow"),
    ("code", "Code / module"),
    ("data", "Data / metrics"),
    ("unknown", "Not labeled yet"),
]

_svg_cache: dict[str, str] = {}
_data_uri_cache: dict[str, str] = {}


def icon_dir() -> Path:
    return _ICON_DIR


def list_icon_keys() -> list[str]:
    if not _ICON_DIR.is_dir():
        return list(EMOJI.keys())
    return sorted(p.stem for p in _ICON_DIR.glob("*.svg"))


def load_svg(key: str) -> str:
    """Raw SVG markup for key, or empty string."""
    if key in _svg_cache:
        return _svg_cache[key]
    path = _ICON_DIR / f"{key}.svg"
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            _svg_cache[key] = text
            return text
        except OSError:
            pass
    _svg_cache[key] = ""
    return ""


def data_uri(key: str, color: str = "#e2e8f0") -> str:
    """data:image/svg+xml;base64,... for HTML img src (offline-safe)."""
    cache_key = f"{key}|{color}"
    if cache_key in _data_uri_cache:
        return _data_uri_cache[cache_key]
    svg = load_svg(key)
    if not svg:
        # minimal circle fallback
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            f'<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="2"/></svg>'
        )
    # force stroke color for dark UI
    svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
    if "stroke=" not in svg:
        svg = svg.replace("<svg ", f'<svg stroke="{color}" ')
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    uri = f"data:image/svg+xml;base64,{b64}"
    _data_uri_cache[cache_key] = uri
    return uri


def emoji_for(key: str) -> str:
    return EMOJI.get(key, EMOJI["unknown"])


def resolve_icon_key(
    *,
    ntype: str = "",
    label: str = "",
    node_id: str = "",
    path: str = "",
    explicit: Optional[str] = None,
    tags: Optional[list] = None,
) -> str:
    """Pick icon key from frontmatter icon= or type + keywords."""
    if explicit:
        ex = str(explicit).strip().lower().replace(".svg", "")
        if load_svg(ex) or ex in EMOJI:
            return ex
    blob = " ".join(
        [
            ntype or "",
            label or "",
            node_id or "",
            path or "",
            " ".join(tags or []),
        ]
    )
    for rx, key in KEYWORD_ICONS:
        if rx.search(blob):
            return key
    return TYPE_ICONS.get((ntype or "").lower(), "unknown")


def enrich_node(node: dict) -> dict:
    """Add icon, icon_emoji, icon_data_uri onto a graph node dict."""
    n = dict(node)
    key = resolve_icon_key(
        ntype=str(n.get("type") or ""),
        label=str(n.get("label") or ""),
        node_id=str(n.get("id") or ""),
        path=str(n.get("path") or ""),
        explicit=n.get("icon"),
        tags=n.get("tags") if isinstance(n.get("tags"), list) else None,
    )
    n["icon"] = key
    n["icon_emoji"] = emoji_for(key)
    n["icon_data_uri"] = data_uri(key)
    return n


def legend_html() -> str:
    """HTML legend strip for vibe coders."""
    parts = [
        '<div class="kg-legend" style="display:flex;flex-wrap:wrap;gap:10px 14px;'
        "margin:10px 0 14px;padding:12px 14px;background:#0f172a;border-radius:8px;"
        'border:1px solid #334155;font-size:12px;color:#cbd5e1;">'
        '<div style="width:100%;font-weight:600;color:#86efac;margin-bottom:4px;">'
        "📖 Picture dictionary (icons = what the box means)</div>"
    ]
    for key, plain in LEGEND:
        uri = data_uri(key)
        em = emoji_for(key)
        parts.append(
            f'<span style="display:inline-flex;align-items:center;gap:5px;" title="{key}">'
            f'<img src="{uri}" width="18" height="18" alt="{key}" style="vertical-align:middle"/>'
            f"<span>{em} {plain}</span></span>"
        )
    parts.append("</div>")
    return "".join(parts)


def icon_img_html(key: str, size: int = 18, alt: str = "") -> str:
    uri = data_uri(key)
    a = alt or key
    return (
        f'<img class="kg-ico" src="{uri}" width="{size}" height="{size}" '
        f'alt="{a}" title="{a}" style="vertical-align:middle;flex-shrink:0"/>'
    )
