#!/usr/bin/env python3
"""run-costs — local calculator + optional cloud billed pull.

Always prints the calculator. Cloud USD only if ANTHROPIC_API_KEY /
OPENAI_ADMIN_KEY / XAI_API_KEY are already in the environment (never
reads .raven/manifest.secrets.json). Fail-soft, 2s timeout.

Usage:
  python3 scripts/session/run_costs.py
  python3 scripts/session/run_costs.py --session-start
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cost_calc import calculator_spend  # noqa: E402

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
OUT = ROOT / ".raven" / ".run-costs.json"
DISCLAIMER = (
    "Calculator is local (router tokens × rates). "
    "Check actual billed cost: Costs dashboard or /run-costs."
)
TIMEOUT = 2.0


def _http_json(url: str, headers: dict) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"raw": raw[:500]}
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def _local() -> dict:
    rec = calculator_spend()
    rec["source"] = "cost_calc.calculator_spend"
    return rec


def _anthropic() -> dict:
    key = os.environ.get("ANTHROPIC_ADMIN_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
    if not key:
        return {"ok": False, "skip": "no ANTHROPIC_API_KEY / ANTHROPIC_ADMIN_API_KEY"}
    start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    url = "https://api.anthropic.com/v1/organizations/cost_report?" + urllib.parse.urlencode(
        {"starting_at": start}
    )
    code, body = _http_json(
        url,
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    return {"ok": code == 200, "http": code, "body": body, "console": "https://platform.claude.com/usage"}


def _openai() -> dict:
    key = os.environ.get("OPENAI_ADMIN_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not key:
        return {"ok": False, "skip": "no OPENAI_ADMIN_KEY / OPENAI_API_KEY"}
    start = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    url = "https://api.openai.com/v1/organization/costs?" + urllib.parse.urlencode(
        {"start_time": start, "limit": 7}
    )
    headers = {"Authorization": "Bearer " + key}
    org = os.environ.get("OPENAI_ORG_ID") or ""
    if org:
        headers["OpenAI-Organization"] = org
    code, body = _http_json(url, headers)
    return {"ok": code == 200, "http": code, "body": body, "console": "https://platform.openai.com/usage"}


def _xai() -> dict:
    key = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or ""
    if not key:
        return {"ok": False, "skip": "no XAI_API_KEY", "console": "https://console.x.ai/team/default/usage"}
    url = os.environ.get("XAI_USAGE_URL") or "https://api.x.ai/v1/usage"
    code, body = _http_json(url, {"Authorization": "Bearer " + key})
    return {
        "ok": code == 200,
        "http": code,
        "body": body,
        "console": "https://console.x.ai/team/default/billing",
    }


def run() -> dict:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
        "local": _local(),
        "cloud": {
            "anthropic": _anthropic(),
            "openai": _openai(),
            "xai": _xai(),
        },
    }
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        rec["write_error"] = str(e)
    return rec


def format_text(rec: dict) -> str:
    loc = rec.get("local") or {}
    lines = [
        DISCLAIMER,
        f"local calculator: {loc.get('kind')} ${float(loc.get('usd') or 0):.4f}"
        f" (actual ${float(loc.get('actual') or 0):.4f} + est ${float(loc.get('estimated') or 0):.4f})",
    ]
    cloud = rec.get("cloud") or {}
    for name, block in cloud.items():
        if not isinstance(block, dict):
            continue
        if block.get("ok"):
            lines.append(f"cloud {name}: http={block.get('http')} (see JSON body)")
        elif block.get("skip"):
            lines.append(f"cloud {name}: skipped ({block.get('skip')}) → {block.get('console', '')}")
        else:
            lines.append(
                f"cloud {name}: http={block.get('http')} fail-soft → {block.get('console', '')}"
            )
    lines.append("Claude /usage in-session · Grok console.x.ai · Codex platform.openai.com/usage")
    return "\n".join(lines)


def main() -> int:
    rec = run()
    print(format_text(rec), file=sys.stderr if "--session-start" in sys.argv else sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
