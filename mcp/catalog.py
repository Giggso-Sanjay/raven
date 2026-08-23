#!/usr/bin/env python3
"""MCP tool catalog only (keeps server.py under the 150-line gate)."""
from __future__ import annotations

TOOLS = [
    {
        "name": "raven_status",
        "description": "Check Raven manifest, version, mode, and project health",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "raven_cve_check",
        "description": "CVE check a Python library",
        "inputSchema": {
            "type": "object",
            "properties": {"library": {"type": "string"}},
            "required": ["library"],
        },
    },
    {
        "name": "raven_sync_libs",
        "description": "Sync libraries from requirements/pyproject into manifest",
        "inputSchema": {
            "type": "object",
            "properties": {"dry_run": {"type": "boolean"}},
            "required": [],
        },
    },
    {
        "name": "raven_debug",
        "description": "Health check — manifest, agents, skills, hooks",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_graph",
        "description": "OKF: filter nodes by type",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "commit": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "get_node",
        "description": "OKF: one node by id or label",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "get_neighbors",
        "description": "OKF: EXTRACTED edges for a node",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "shortest_path",
        "description": "OKF: hop path between two node ids",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
            },
            "required": ["from_id", "to_id"],
        },
    },
    {
        "name": "commit_impact",
        "description": "OKF: files/symbols a commit touched",
        "inputSchema": {
            "type": "object",
            "properties": {"sha": {"type": "string"}},
            "required": ["sha"],
        },
    },
    {
        "name": "find_gaps",
        "description": "OKF: missing purpose, unlinked commits",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "raven_violation",
        "description": "Emit a violation to the Raven audit log",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "severity": {"type": "string", "enum": ["P1", "P2", "P3"]},
                "detail": {"type": "string"},
            },
            "required": ["type", "severity", "detail"],
        },
    },
]
