#!/usr/bin/env python3
"""Ensure host glue + working python wrapper. Open dashboard on --open.

Called from /raven-init and /raven-debug so public users get AGENTS.md,
.agents/agents.md, raven-python.sh, and a dashboard without extra instructions.

  python3 scripts/ops/host-ensure.py --open
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
TARGET = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()


def _copy(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return str(dest.relative_to(TARGET))


def ensure() -> list[str]:
    done: list[str] = []
    py = ENGINE / "scripts" / "raven-python.sh"
    dest_py = TARGET / "scripts" / "raven-python.sh"
    if py.is_file():
        _copy(py, dest_py)
        dest_py.chmod(dest_py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        done.append("scripts/raven-python.sh")
    always = [
        (ENGINE / ".agents" / "agents.md", TARGET / ".agents" / "agents.md"),
        (ENGINE / "AGENTS.md", TARGET / "AGENTS.md"),
        (ENGINE / "AGENTS.override.md", TARGET / "AGENTS.override.md"),
        (ENGINE / ".cursor" / "rules" / "raven-router.mdc", TARGET / ".cursor" / "rules" / "raven-router.mdc"),
        (ENGINE / ".windsurf" / "rules" / "ide-boot.md", TARGET / ".windsurf" / "rules" / "ide-boot.md"),
        (ENGINE / ".vscode" / "raven-router.md", TARGET / ".vscode" / "raven-router.md"),
        (ENGINE / ".github" / "copilot-instructions.md", TARGET / ".github" / "copilot-instructions.md"),
    ]
    for src, dest in always:
        if src.is_file():
            done.append(_copy(src, dest))
    boot_src = ENGINE / ".raven" / "boot.json"
    boot_dst = TARGET / ".raven" / "boot.json"
    if boot_src.is_file() and not boot_dst.is_file():
        done.append(_copy(boot_src, boot_dst))
    return done


def open_dashboard() -> None:
    boot = ENGINE / "scripts" / "memory" / "ide-boot.py"
    if not boot.is_file():
        boot = TARGET / "scripts" / "memory" / "ide-boot.py"
    if not boot.is_file():
        print("host-ensure: ide-boot.py missing — skip dashboard open", file=sys.stderr)
        return
    wrap = TARGET / "scripts" / "raven-python.sh"
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(TARGET)
    if wrap.is_file():
        cmd = ["bash", str(wrap), str(boot), "--open"]
    else:
        cmd = [sys.executable, str(boot), "--open"]
    subprocess.run(cmd, cwd=str(TARGET), env=env, timeout=180)


def main() -> int:
    done = ensure()
    print("host-ensure: " + (", ".join(done) if done else "already present"))
    print('Router: bash scripts/raven-python.sh scripts/routing/model-router.py --prompt "…"')
    if "--no-open" not in sys.argv:
        open_dashboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
