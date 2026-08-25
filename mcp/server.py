#!/usr/bin/env python3
"""Raven MCP stdio server. Tools live in catalog.py / dispatch.py.

Claude Code:  claude mcp add raven -- python3 ~/.raven/mcp/server.py
Codex:        Settings → MCP Servers → python3 ~/.raven-codex/mcp/server.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from dispatch import handle  # noqa: E402


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def read() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line.strip())


def main() -> None:
    while True:
        req = read()
        if req is None:
            break
        msg_id = req.get("id")
        try:
            result = handle(req.get("method") or "", req.get("params") or {})
            send({"jsonrpc": "2.0", "id": msg_id, "result": result})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
