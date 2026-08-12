#!/usr/bin/env python3
"""
export-hook-configs.py — raven-config-canon-check (generator + CI check).

.claude/settings.json is the single canonical hook config (empirically live).
Three distribution copies are GENERATED from it — never hand-edited:

  hooks/hooks.json          plugin-marketplace format (${CLAUDE_PLUGIN_ROOT} paths)
  plugin/settings.json      plugin zip payload (same shape as canonical
                            + declared plugin-only extras below)
  core/hooks/settings.json  what setup/sr-02-install-files.sh deploys into
                            user projects (same shape as canonical)

The git pre-commit hook (core/hooks/pre-commit → ~/.patronai) is intentionally
external to Claude hook config and NOT managed here.

Usage:
  python3 scripts/export-hook-configs.py            # regenerate all three
  python3 scripts/export-hook-configs.py --check    # CI: exit 1 if any drifted
"""
import json
import re
import sys
from pathlib import Path

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / ".claude" / "settings.json"

# Plugin-only hooks that do NOT exist in the canonical local config, kept by
# explicit decision (chain Prompt 3): the plugin ships skill-gating (see
# docs/SKILL-GATE.md); the local dev repo does not run it on itself.
PLUGIN_EXTRA_HOOKS = {
    "PreToolUse": [
        {
            "matcher": "Skill",
            "hooks": [
                {
                    "type": "command",
                    # PYTHONUTF8=1 for the same reason as every generated command
                    # (BUG-017) — and this script in particular is what BUG-014 was:
                    # it printed ⚠️ and exited 1 from its own allow paths.
                    "command": "PYTHONUTF8=1 python3 \"${CLAUDE_PROJECT_DIR:-.}/scripts/raven-skill-gate.py\" 2>/dev/null || true",
                }
            ],
        }
    ]
}

GEN_NOTE = (
    "GENERATED from .claude/settings.json by scripts/export-hook-configs.py — "
    "do not hand-edit; run the exporter after changing the canonical file."
)


def _merge_extra_hooks(base: dict, extra: dict) -> dict:
    """Append plugin-only matcher groups to the canonical ones for the same event.

    A plain {**base, **extra} merge REPLACES the event's whole group list, which
    silently dropped canonical's PreToolUse (push-gate.py) once that event existed.
    Extras are additive by definition — concatenate, never overwrite.
    """
    merged = {event: list(groups) for event, groups in base.items()}
    for event, groups in extra.items():
        merged.setdefault(event, [])
        merged[event] = merged[event] + list(groups)
    return merged


def _plugin_root_command(command: str) -> str:
    """Rewrite the canonical dual-fallback command to plugin-root form.

    Canonical shape:
      python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/X.py" ARGS 2>/dev/null || <fallback>

    ARGS must survive verbatim. The previous regex expected flags to follow the script
    name directly, but a closing double-quote sits between them, so the args group always
    matched empty and EVERY flag was silently dropped from the distributed config:
    --build (code map never built at all), --if-stale (3000-line report rebuilt every
    turn), --changed-files-only (whole tree rescanned per edit), --hook (prompt never
    read from stdin). Match the name, skip the optional quote, keep the rest.
    """
    first = command.split("||")[0]
    m = re.search(r'([a-z0-9_-]+\.py)"?(.*)$', first)
    if not m:
        return command  # e.g. the SessionStart `rm -f` flag reset — no script to rewrite
    name = m.group(1)
    args = m.group(2).replace("2>/dev/null", "").strip()
    args = f" {args}" if args else ""
    # PYTHONUTF8=1 must survive the rewrite (BUG-017). Raven's output is emoji-forward,
    # and on Windows a hook's stdout defaults to cp1252 — print() then raises and the
    # fail-soft wrapper swallows it, so the hook silently does nothing. It fixes the
    # decode side too (transcripts are UTF-8). Verified in a real shell: without it
    # stdout is cp1252 and 🎓 raises; with it stdout is utf-8 and prints.
    # Caveat: PYTHONUTF8 does NOT override an explicit PYTHONIOENCODING — if anything
    # ever sets that to a legacy codepage, the in-script reconfigure guards are the
    # remaining defence, which is why those stay.
    prefix = "PYTHONUTF8=1 " if "PYTHONUTF8=1" in command else ""
    return (f'{prefix}python3 "${{CLAUDE_PLUGIN_ROOT}}/scripts/{name}"{args} '
            f'2>/dev/null || true')


def build_outputs(canonical: dict) -> dict:
    hooks = canonical["hooks"]

    marketplace = {"hooks": {}}
    for event, groups in hooks.items():
        marketplace["hooks"][event] = [
            {
                "matcher": g.get("matcher", "*"),
                "hooks": [
                    {**{k: v for k, v in h.items() if k != "command"},
                     "command": _plugin_root_command(h["command"])}
                    for h in g["hooks"]
                ],
            }
            for g in groups
        ]

    plugin_settings = {
        "_generated": GEN_NOTE,
        "version": canonical.get("version", "1.0"),
        "description": canonical.get("description", ""),
        "hooks": _merge_extra_hooks(hooks, PLUGIN_EXTRA_HOOKS),
        "permissions": canonical.get("permissions", {}),
        "governance": canonical.get("governance", {}),
    }

    core_settings = {
        "_generated": GEN_NOTE,
        "version": canonical.get("version", "1.0"),
        "description": canonical.get("description", ""),
        "hooks": hooks,
        "permissions": canonical.get("permissions", {}),
        "governance": canonical.get("governance", {}),
    }

    marketplace["_generated"] = GEN_NOTE

    return {
        REPO / "hooks" / "hooks.json": marketplace,
        REPO / "plugin" / "settings.json": plugin_settings,
        REPO / "core" / "hooks" / "settings.json": core_settings,
    }


def main() -> int:
    check = "--check" in sys.argv
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
    outputs = build_outputs(canonical)

    failures = []
    for path, data in outputs.items():
        rendered = json.dumps(data, indent=2) + "\n"
        if check:
            on_disk = path.read_text(encoding="utf-8") if path.exists() else ""
            if on_disk != rendered:
                failures.append(f"DRIFTED from canonical: {path.relative_to(REPO)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered)
            print(f"generated: {path.relative_to(REPO)}")

    if check:
        if failures:
            print("raven-config-canon-check: FAIL")
            for f in failures:
                print(f"  {f}")
            print("  Fix: python3 scripts/export-hook-configs.py  (then commit)")
            return 1
        print("raven-config-canon-check: PASS — all distribution configs match canonical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
