#!/usr/bin/env python3
"""IDE boot router — first load only.

Detect host from env (boolean). Print one memory pointer.
Does not inject the vault. Does not parse the graph.

  python3 scripts/memory/ide-boot.py
  python3 scripts/memory/ide-boot.py --json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
BOOT = ROOT / ".raven" / "boot.json"
CARD_SCHEMA = 1
_MEM = Path(__file__).resolve().parent
if str(_MEM) not in sys.path:
    sys.path.insert(0, str(_MEM))


def _load_boot() -> dict:
    try:
        return json.loads(BOOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "memory": ".raven/memory/CARD.md",
            "default_rules": "AGENTS.md",
            "hosts": {},
        }


def detect_host(env: dict, hosts: dict) -> str:
    for name, spec in hosts.items():
        for key in spec.get("env_any") or []:
            if env.get(key):
                return name
    return "unknown"


def _project_name(root: Path) -> str:
    man = root / ".raven" / "manifest.json"
    try:
        name = json.loads(man.read_text(encoding="utf-8")).get("project")
        if name:
            return str(name)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return root.name


def _graph_html(root: Path) -> Path:
    """OKF graph iframe target (sibling of dashboard index)."""
    trees = Path.home() / "RavenVault" / "dashboard" / "trees"
    for name in (root.name, _project_name(root)):
        p = trees / f"{name}.html"
        if p.is_file():
            return p
    local = root / ".raven" / "code-xray.html"
    if local.is_file():
        return local
    return trees / f"{root.name}.html"


def _dashboard_uri(root: Path) -> str:
    html = Path.home() / "RavenVault" / "dashboard" / "raven-dashboard.html"
    try:
        uri = html.resolve().as_uri() if html.exists() else html.expanduser().absolute().as_uri()
    except Exception:
        uri = f"file://{html}"
    return f"{uri}#{_project_name(root)}"


def card_loadable(card: Path) -> bool:
    if not card.is_file():
        return False
    try:
        first = card.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
    except OSError:
        return False
    meta = {}
    for ln in first:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        meta[k.strip().lower()] = v.strip()
    if meta.get("schema") != str(CARD_SCHEMA):
        return False
    if meta.get("status", "").upper() == "INVALID":
        return False
    return True


def route(env: dict | None = None, root: Path | None = None) -> dict:
    root = root or ROOT
    env = env if env is not None else os.environ
    boot = _load_boot() if root == ROOT else {}
    if root != ROOT:
        bp = root / ".raven" / "boot.json"
        try:
            boot = json.loads(bp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            boot = {"memory": ".raven/memory/CARD.md", "default_rules": "AGENTS.md", "hosts": {}}
    hosts = boot.get("hosts") or {}
    host = detect_host(env, hosts)
    rules = (hosts.get(host) or {}).get("rules") or boot.get("default_rules") or "AGENTS.md"
    mem_rel = boot.get("memory") or ".raven/memory/CARD.md"
    card = root / mem_rel
    load = card_loadable(card)
    try:
        import educate as _edu_mod

        edu = _edu_mod.load_mode(root)
    except Exception:
        edu = "guided"
    return {
        "host": host,
        "rules": rules,
        "dashboard": _dashboard_uri(root),
        "memory": mem_rel if load else "",
        "load": 1 if load else 0,
        "okf": boot.get("okf") or ".raven/code-xray.json",
        "graph_cli": boot.get("graph_cli") or "python3 scripts/code-xray.py",
        "mcp": ",".join(boot.get("mcp_graph") or []),
        "educate": edu,
    }


MARKER = ".raven/.dashboard-opened"
# One shared vault dashboard → one browser tab, all repos/IDEs.
VAULT_LOCK = Path.home() / "RavenVault" / "dashboard" / ".browser-opened"
LOCK_TTL_SEC = 12 * 3600


def _marker(root: Path) -> Path:
    return Path(root) / ".raven" / ".dashboard-opened"


def claim_browser_open(lock_path: Path | None = None, force: bool = False) -> bool:
    """True = this process may open a tab. Exclusive. --open still claims."""
    path = lock_path or VAULT_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        try:
            path.write_text("forced\n", encoding="utf-8")
        except OSError:
            pass
        return True
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, b"opened\n")
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        if age > LOCK_TTL_SEC:
            try:
                path.write_text("opened\n", encoding="utf-8")
                return True
            except OSError:
                return False
        return False


def rebuild_dashboard(root: Path) -> None:
    """One HTML rebuild. Fail-soft. Does not open a browser."""
    env = dict(os.environ)
    env["RAVEN_DASHBOARD_NO_OPEN"] = "1"
    dash = Path(root) / "scripts" / "dashboard.py"
    if dash.is_file():
        try:
            subprocess.run(
                [sys.executable, str(dash), "--html"],
                cwd=str(root),
                timeout=180,
                capture_output=True,
                env=env,
            )
            return
        except Exception:
            pass
    xray = Path(root) / "scripts" / "code-xray.py"
    if xray.is_file():
        try:
            subprocess.run(
                [sys.executable, str(xray), "--html"],
                cwd=str(root),
                timeout=120,
                capture_output=True,
                env=env,
            )
        except Exception:
            pass


def open_dashboard(uri: str, root: Path | None = None) -> None:
    """Default browser. Builds this repo's graph HTML if missing. Fail-soft."""
    root = root or ROOT
    html = _graph_html(root)
    if not html.is_file():
        rebuild_dashboard(root)
        html = _graph_html(root)
        try:
            uri = html.resolve().as_uri() if html.exists() else uri
        except Exception:
            pass
    if not uri:
        return
    try:
        webbrowser.open(uri, new=0)
    except Exception:
        pass


def main() -> int:
    r = route()
    argv = sys.argv
    force_open = "--open" in argv
    session_start = "--session-start" in argv
    no_open = (
        "--no-open" in argv
        or "--json" in argv
        or os.environ.get("RAVEN_DASHBOARD_NO_OPEN") == "1"
    )
    if "--json" in argv:
        print(json.dumps(r, separators=(",", ":")))
    else:
        print(f"dashboard={r.get('dashboard','')}")
        print(f"host={r['host']}")
        print(f"rules={r['rules']}")
        print(f"memory={r['memory']}")
        print(f"load={r['load']}")
        print(f"okf={r.get('okf','')}")
        print(f"graph_cli={r.get('graph_cli','')}")
        print(f"mcp={r.get('mcp','')}")
        print(f"educate={r.get('educate','guided')}")
    marker = _marker(ROOT)
    should_rebuild = session_start or force_open
    if should_rebuild:
        rebuild_dashboard(ROOT)
        r = route()
    may_open = False
    if not no_open:
        may_open = claim_browser_open(force=force_open)
        if may_open:
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("opened\n", encoding="utf-8")
            except OSError:
                pass
    if may_open:
        open_dashboard(r.get("dashboard") or "", ROOT)
        print("opened=1")
    else:
        print("opened=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("dashboard=\nhost=unknown\nrules=AGENTS.md\nmemory=\nload=0\nokf=\ngraph_cli=\nmcp=\neducate=guided")
        raise SystemExit(0)
