#!/usr/bin/env python3
"""Non-secret dashboard settings. No API keys. Gitignored local file."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
PATH = ROOT / ".raven" / "dashboard-settings.json"

DEFAULTS = {
    "langsmith_enabled": False,
    "langsmith_base_url": "https://smith.langchain.com",
    "langsmith_project": "",
    "airtaas_enabled": False,
    "airtaas_mcp": "",
    "airtaas_note": "Paste AIRTaaS MCP command or URL. Not shipped. Router sets redteam=airtaas on security prompts when enabled.",
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true"):
        data["langsmith_enabled"] = True
    if os.environ.get("LANGCHAIN_PROJECT"):
        data["langsmith_project"] = os.environ.get("LANGCHAIN_PROJECT") or data.get("langsmith_project") or ""
    return data


def save(patch: dict) -> dict:
    cur = load()
    for k, v in (patch or {}).items():
        if k in DEFAULTS and k != "airtaas_note":
            if k.endswith("_enabled"):
                cur[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "on", "yes")
            else:
                cur[k] = str(v).strip() if v is not None else ""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
    return cur


def public_view() -> dict:
    d = load()
    return {
        "langsmith_enabled": bool(d.get("langsmith_enabled")),
        "langsmith_base_url": d.get("langsmith_base_url") or "",
        "langsmith_project": d.get("langsmith_project") or "",
        "airtaas_enabled": bool(d.get("airtaas_enabled")),
        "airtaas_mcp": d.get("airtaas_mcp") or "",
        "airtaas_note": DEFAULTS["airtaas_note"],
    }


def obs_link() -> str:
    d = load()
    if not d.get("langsmith_enabled"):
        return ""
    base = str(d.get("langsmith_base_url") or "").rstrip("/")
    proj = str(d.get("langsmith_project") or "").strip()
    if not base:
        return ""
    if proj:
        return f"{base}/projects?search={proj}"
    return base
