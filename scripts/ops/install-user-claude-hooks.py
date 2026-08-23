#!/usr/bin/env python3
"""Rewire ~/.claude global hooks to 5.5+ router + deny-mode educate.

Claude Code often loads user-global settings.json instead of the project
.claude/settings.json. The v5.0 global wrapper read `userMessage` (empty) and
used an advisory push-gate. This installer:

  - Backs up ~/.claude/settings.json and ~/.claude/scripts/push-gate.py
  - Points UserPromptSubmit at project model-router.py --hook (stdin JSON)
  - Copies the repo deny-mode push-gate.py

Usage:
  python3 scripts/ops/install-user-claude-hooks.py
  python3 scripts/ops/install-user-claude-hooks.py --dry-run
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOME_CLAUDE = Path.home() / ".claude"
ROUTER_CMD = (
    'python3 "${CLAUDE_PROJECT_DIR:-.}/scripts/routing/model-router.py" --hook '
    '2>/dev/null || python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/routing/model-router.py" --hook '
    "2>/dev/null || true"
)


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, dest)
    return dest


def patch_settings(data: dict) -> tuple[dict, bool]:
    changed = False
    hooks = data.setdefault("hooks", {})
    ups = hooks.get("UserPromptSubmit") or []
    for block in ups:
        for h in (block.get("hooks") or []):
            cmd = h.get("command") or ""
            if "model-router" in cmd and "--hook" not in cmd:
                h["command"] = ROUTER_CMD
                changed = True
            elif "model-router-hook.py" in cmd:
                h["command"] = ROUTER_CMD
                changed = True
    if not ups:
        hooks["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": ROUTER_CMD,
                        "timeout": 10,
                    }
                ]
            }
        ]
        changed = True
    return data, changed


def main() -> int:
    dry = "--dry-run" in sys.argv
    settings = HOME_CLAUDE / "settings.json"
    src_gate = REPO / ".claude" / "scripts" / "push-gate.py"
    dest_gate = HOME_CLAUDE / "scripts" / "push-gate.py"
    print(f"install-user-claude-hooks: target={HOME_CLAUDE}")
    if settings.is_file():
        data = json.loads(settings.read_text(encoding="utf-8"))
        data, changed = patch_settings(data)
        print(f"  settings.json router --hook: {'patched' if changed else 'already ok'}")
        if changed and not dry:
            bak = _backup(settings)
            print(f"  backup {bak}")
            settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        print("  skip settings.json (missing)")
    if src_gate.is_file():
        print(f"  push-gate.py ← {src_gate} (deny guided)")
        if not dry:
            dest_gate.parent.mkdir(parents=True, exist_ok=True)
            if dest_gate.is_file():
                bak = _backup(dest_gate)
                print(f"  backup {bak}")
            shutil.copy2(src_gate, dest_gate)
    else:
        print("  skip push-gate (engine file missing)")
    print("  expected UserPromptSubmit: model-router.py --hook (prompt|userMessage)")
    print("  expected PreToolUse: push-gate deny until go-ahead when educate=guided")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
