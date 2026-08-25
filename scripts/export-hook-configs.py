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
                    "command": "python3 \"${CLAUDE_PROJECT_DIR:-.}/scripts/raven-skill-gate.py\" 2>/dev/null || true",
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
    """Rewrite the canonical dual-fallback command to plugin-root form."""
    scripts = re.findall(r"([a-z0-9_-]+\.py)((?:\s+--?[a-z0-9-]+(?:\s+\d+)?)*)", command)
    if not scripts:
        return command
    name, args = scripts[0]
    return f'python3 "${{CLAUDE_PLUGIN_ROOT}}/scripts/{name}"{args} 2>/dev/null || true'


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
