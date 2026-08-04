#!/usr/bin/env python3
"""
session-gate.py — Raven Stop hook
Fires at every session end (Stop event).
Shows: dashboard link (always), metrics, uncommitted git, open observations, open PR.
Non-blocking — systemMessage only. Always exit 0.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def _dashboard_block(when: str = "session end") -> list[str]:
    try:
        from vault_common import dashboard_link_lines

        return dashboard_link_lines(when=when)
    except Exception:
        path = pathlib.Path.home() / "RavenVault" / "dashboard.html"
        return [
            f"📊 Raven dashboard ({when}):",
            f"   {path}",
            f"   Open: file://{path}",
            "   Rebuild: python3 scripts/dashboard.py --html --open",
        ]


def git_summary() -> list[str]:
    """Return git status and recent log lines, empty list if not a git repo."""
    parts: list[str] = []
    cwd = os.getcwd()
    try:
        status = subprocess.check_output(
            ["git", "status", "--short"],
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        ).decode().strip()
        if status:
            parts.append(f"📂 Uncommitted changes:\n{status}")

        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        ).decode().strip()
        if log:
            parts.append(f"📋 Recent commits:\n{log}")
    except Exception:
        pass
    return parts


def open_observations() -> list[str]:
    """Count open Raven memory items in .raven/memory/."""
    parts: list[str] = []
    try:
        memory_dir = pathlib.Path(os.getcwd()) / ".raven" / "memory"
        if memory_dir.exists():
            count = sum(
                1
                for f in memory_dir.glob("*.md")
                if "status: open" in f.read_text(errors="ignore")
            )
            if count > 0:
                parts.append(
                    f"📋 {count} open observation(s) in .raven/memory/ "
                    f"— run /raven-harden when ready"
                )
    except Exception:
        pass
    return parts


def metrics_summary() -> list[str]:
    """Read session metrics and format summary line."""
    parts: list[str] = []
    try:
        session_file = pathlib.Path(os.getcwd()) / ".raven" / ".model-session.json"
        if session_file.exists():
            metrics = json.loads(session_file.read_text())
            # support both schemas
            if "raven_overhead" in metrics:
                ov = metrics.get("raven_overhead") or {}
                uw = metrics.get("user_work") or {}
                tokens = int(ov.get("tokens") or 0) + int(uw.get("tokens") or 0)
                cost = float(ov.get("cost_usd") or 0) + float(uw.get("cost_usd") or 0)
                raven_calls = int(ov.get("calls") or 0)
                user_calls = int(uw.get("calls") or 0)
            else:
                total = metrics.get("total", {})
                raven_calls = metrics.get("raven_code", {}).get("calls", 0)
                user_calls = metrics.get("user_work", {}).get("calls", 0)
                tokens = total.get("tokens", 0)
                cost = total.get("cost_usd", 0)

            if tokens or cost:
                token_str = f"{tokens:,}" if tokens > 999 else str(tokens)
                if cost and cost < 0.01:
                    cost_str = f"${cost:.6f}"
                else:
                    cost_str = f"${cost:.2f}"
                calls_str = f"{raven_calls} raven / {user_calls} user"
                parts.append(
                    f"📊 Session meters: {token_str} tok · {cost_str} · {calls_str} calls"
                )
    except Exception:
        pass
    return parts


def pr_summary() -> list[str]:
    """If an open/merged PR is visible for this branch, surface it + dashboard.

    When PR is MERGED or CLOSED (\"done\"), re-emphasize the dashboard link so
    the human reviews graph · costs · memory after the PR lands.
    """
    parts: list[str] = []
    cwd = os.getcwd()
    try:
        out = subprocess.check_output(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "url,title,state,number",
            ],
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            text=True,
        ).strip()
        if not out:
            return parts
        data = json.loads(out)
        url = data.get("url") or ""
        title = data.get("title") or ""
        state = (data.get("state") or "").upper()
        num = data.get("number") or ""
        if url:
            parts.append(f"🔗 PR #{num} [{state}]: {title}\n   {url}")
            done = state in ("MERGED", "CLOSED")
            when = f"PR #{num} done ({state})" if done else f"PR #{num} {state}"
            parts.extend(_dashboard_block(when=when))
            if done:
                parts.append(
                    "✅ PR done — open the dashboard now to review graph · costs · memory."
                )
            else:
                parts.append(
                    "   When this PR is done: open the dashboard to review graph · costs · memory."
                )
    except Exception:
        try:
            out = subprocess.check_output(
                ["gh", "pr", "list", "--limit", "1", "--json", "url,title,number,state"],
                stderr=subprocess.DEVNULL,
                cwd=cwd,
                text=True,
            ).strip()
            if out and out != "[]":
                rows = json.loads(out)
                if rows:
                    pr = rows[0]
                    st = (pr.get("state") or "").upper()
                    parts.append(
                        f"🔗 Open PR #{pr.get('number')} [{st}]: {pr.get('title')}\n"
                        f"   {pr.get('url')}"
                    )
                    parts.extend(_dashboard_block(when="open PR"))
                    parts.append(
                        "   When this PR is done: open the dashboard to review graph · costs · memory."
                    )
        except Exception:
            pass
    return parts


def main() -> None:
    """Collect session-end signals and emit systemMessage (always includes dashboard)."""
    sections: list[str] = []
    # Dashboard FIRST — always
    sections.append("\n".join(_dashboard_block(when="session end")))
    sections.extend(metrics_summary())
    sections.extend(pr_summary())
    sections.extend(git_summary())
    sections.extend(open_observations())

    message = "🪶 Raven — Session end\n\n" + "\n\n".join(sections)
    print(json.dumps({"systemMessage": message}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Absolute fail-soft for Stop hooks
        try:
            path = pathlib.Path.home() / "RavenVault" / "dashboard.html"
            print(
                json.dumps(
                    {
                        "systemMessage": (
                            f"🪶 Raven — Session end\n\n"
                            f"📊 Dashboard: {path}\n"
                            f"   Open: file://{path}"
                        )
                    }
                )
            )
        except Exception:
            pass
        sys.exit(0)
