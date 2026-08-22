#!/usr/bin/env python3
"""Educate mode — default guided. Missing file = guided.

  .raven/educate.json  {"mode": "guided"|"off"}
  python3 scripts/memory/educate.py          # print mode=
  python3 scripts/memory/educate.py --set off
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VALID = {"guided", "off"}


def educate_path(root: Path) -> Path:
    return Path(root) / ".raven" / "educate.json"


def load_mode(root: Path) -> str:
    p = educate_path(root)
    if not p.is_file():
        return "guided"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return "guided"
    if isinstance(data, str):
        mode = data.strip().lower()
    elif isinstance(data, dict):
        mode = str(data.get("mode") or "guided").strip().lower()
    else:
        return "guided"
    if mode in ("auto", "lucky"):
        return "off"
    return mode if mode in VALID else "guided"


def save_mode(root: Path, mode: str) -> str:
    mode = "off" if mode in ("auto", "lucky", "off") else "guided"
    p = educate_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": mode}, indent=2) + "\n", encoding="utf-8")
    return mode


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    args = sys.argv[1:]
    if args[:1] == ["--set"] and len(args) >= 2:
        print(f"mode={save_mode(root, args[1])}")
        return 0
    print(f"mode={load_mode(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
