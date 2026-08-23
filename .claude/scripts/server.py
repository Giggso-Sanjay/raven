#!/usr/bin/env python3
"""Shim — canonical MCP server is mcp/server.py (includes OKF graph tools)."""
import pathlib
import runpy
import sys

_root = pathlib.Path(__file__).resolve().parents[2]
_srv = _root / "mcp" / "server.py"
if not _srv.exists():
    sys.stderr.write(f"MCP server missing: {_srv}\n")
    sys.exit(1)
sys.path.insert(0, str(_srv.parent))
runpy.run_path(str(_srv), run_name="__main__")
