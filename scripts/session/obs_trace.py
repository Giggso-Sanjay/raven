#!/usr/bin/env python3
"""OSS observability emit — metadata only (no prompt/response text).

Writes ~/RavenVault/obs/runs.jsonl (not the git repo).
If LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are in the environment, POSTs
a Langfuse-compatible ingestion event to the Settings open-source URL.
Fail-soft, 0.4s timeout. No new pip.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VAULT_OBS = Path.home() / "RavenVault" / "obs" / "runs.jsonl"


def emit(rec: dict) -> None:
    rec = dict(rec or {})
    rec.setdefault("ts", datetime.now(timezone.utc).isoformat())
    try:
        VAULT_OBS.parent.mkdir(parents=True, exist_ok=True)
        with VAULT_OBS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError:
        pass
    _langfuse_post(rec)


def _langfuse_post(rec: dict) -> None:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY") or ""
    sk = os.environ.get("LANGFUSE_SECRET_KEY") or ""
    if not pk or not sk:
        return
    try:
        import sys
        dash = Path(__file__).resolve().parents[1] / "dashboard"
        if str(dash) not in sys.path:
            sys.path.insert(0, str(dash))
        from dash_settings import load, obs_link
        st = load()
        if (st.get("observability") or "off") == "off":
            return
        host = (obs_link() or st.get("opensource_base_url") or "").rstrip("/")
        if not host:
            return
        url = host + "/api/public/ingestion"
        rid = rec.get("obs_run_id") or rec.get("ts")
        payload = {
            "batch": [{
                "id": str(rid),
                "type": "trace-create",
                "timestamp": rec.get("ts"),
                "body": {
                    "id": str(rid),
                    "name": "raven-route",
                    "metadata": {
                        "repo": rec.get("repo"),
                        "ide": rec.get("ide"),
                        "tier": rec.get("tier"),
                        "recommend": rec.get("recommend"),
                        "prompt_chars": rec.get("prompt_chars"),
                        "est_cost_usd": rec.get("est_cost_usd"),
                    },
                },
            }]
        }
        token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.4)
    except (urllib.error.URLError, TimeoutError, OSError, Exception):
        return
