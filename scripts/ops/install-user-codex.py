#!/usr/bin/env python3
"""Install 5.5.1 Raven boot into Codex global config.

Codex injects ~/.codex/config.toml developer_instructions *before* project
AGENTS.md. The old 3-line "Raven: routed -> skill" protocol made Codex skip
model-router, educate, cost, and the memory card.

Also writes ~/.codex/AGENTS.md (Codex global scope, loaded first).
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODEX_HOME = Path.home() / ".codex"
BOOT = (
    "RAVEN 5.5.1 GATE (every prompt, every repo with .raven/):\n"
    "1. First session load: run `bash scripts/raven-python.sh scripts/memory/ide-boot.py` "
    "then Read only memory= if load=1. Then `model-router.py --session-start`.\n"
    "2. Every turn BEFORE any other tool: "
    "`bash scripts/raven-python.sh scripts/routing/model-router.py --prompt \"<user text>\"`.\n"
    "3. First written lines MUST be the script stdout (🔀 Router, 💰, educate=, expected=) "
    "then session= then Intent:. A reply without 🔀 is a defect.\n"
    "4. Do NOT use `Raven: routed ->` or a `what can you do` greeting as a substitute.\n"
    "5. educate=guided: briefing then STOP until go ahead.\n"
    "6. Turn end: `bash scripts/raven-python.sh scripts/session/cost_calc.py --end`.\n"
)


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    dest = path.with_suffix(path.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(path, dest)
    return dest


def patch_toml(text: str) -> str:
    needle = "developer_instructions"
    block = 'developer_instructions = """\n' + BOOT + '"""\n'
    if needle not in text:
        return block + "\n" + text
    start = text.find(needle)
    rest = text[start:]
    if '"""' in rest:
        q1 = rest.find('"""')
        q2 = rest.find('"""', q1 + 3)
        if q2 != -1:
            return text[:start] + block + rest[q2 + 3 :].lstrip("\n")
    return block + text


def main() -> int:
    print(f"install-user-codex: {CODEX_HOME}")
    cfg = CODEX_HOME / "config.toml"
    if cfg.is_file():
        bak = _backup(cfg)
        print(f"  backup {bak}")
        cfg.write_text(patch_toml(cfg.read_text(encoding="utf-8")), encoding="utf-8")
        print("  config.toml developer_instructions → 5.5.1 router/educate/cost")
    src = REPO / "AGENTS.override.md"
    dest = CODEX_HOME / "AGENTS.md"
    if src.is_file():
        if dest.is_file():
            print(f"  backup {_backup(dest)}")
        shutil.copy2(src, dest)
        print("  ~/.codex/AGENTS.md ← AGENTS.override.md")
    print("  expected first line of every Codex reply: 🔀 Router")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
