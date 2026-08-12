#!/usr/bin/env python3
"""
check-distribution-coverage.py — raven-distribution-coverage-check (CI + local).

Gate 6. Independent of the exporter, deliberately.

Gate 3 (export-hook-configs.py --check) asks "do the distribution copies match what
the exporter would generate?" That catches hand-edits, but it cannot catch a bug in
the exporter itself — generator and checker agree by construction. BUG-013 was exactly
that: a {**a, **b} merge silently dropped canonical's PreToolUse from
plugin/settings.json, and gate 3 reported PASS.

This gate asserts the SEMANTIC invariant instead, by reading the JSON directly and
sharing no code with export-hook-configs.py: every hook event canonical declares must
exist in every distribution copy, and every script canonical runs for that event must
be present there too. Extra entries are allowed — distribution copies may add
plugin-only hooks (declared exception: plugin/settings.json ships raven-skill-gate).

Two independent paths beat one careful path. If this gate and gate 3 ever disagree,
believe this one: it does not import the code it is checking.

Exit 0 = every distribution copy covers canonical. Exit 1 = something is missing.
"""
import json
import pathlib
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
DISTRIBUTION = [
    Path("hooks") / "hooks.json",
    Path("plugin") / "settings.json",
    Path("core") / "hooks" / "settings.json",
]

SCRIPT_RE = re.compile(r"([a-z0-9_-]+\.py)")


def scripts_by_event(path: Path) -> dict:
    """event -> {script name: normalised args}, read straight from the JSON.

    Args are captured too, not just names. Comparing names alone let BUG-015 through:
    the exporter stripped every flag from the distributed config and this gate still
    reported PASS, because the same seven scripts were present in both files. A hook
    wired without --build or --if-stale is a different hook.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    out = {}
    for event, groups in hooks.items():
        found = {}
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command", "")
                # Only the first fallback branch matters; the rest re-runs the same script.
                first = command.split("||")[0]
                m = re.search(r'([a-z0-9_-]+\.py)"?(.*)$', first)
                if m:
                    args = m.group(2).replace("2>/dev/null", "").strip()
                    found[m.group(1)] = args
                else:
                    for name in SCRIPT_RE.findall(command):
                        found.setdefault(name, "")
        out[event] = found
    return out


def missing_script_files(canon: dict) -> list:
    """Every hook-referenced script must EXIST where the plugin will look for it.

    hooks/hooks.json rewrites all commands to ${CLAUDE_PLUGIN_ROOT}/scripts/<name>, so a
    script that lives only in .claude/scripts/ resolves to nothing once packaged — and
    `|| true` swallows the error, leaving a silently dead hook. BUG-019: push-gate.py was
    wired, documented, flag-correct and present in the package, yet Educated Push never
    fired in any install because it sat in .claude/scripts/ and the plugin looked in
    scripts/. Name and arg checks both passed; nobody asked whether the file was there.
    """
    problems = []
    for event, entries in sorted(canon.items()):
        for name in sorted(entries):
            if not (REPO / "scripts" / name).is_file():
                problems.append(
                    f"{event}: {name} is wired but scripts/{name} does not exist — the "
                    f"plugin resolves ${{CLAUDE_PLUGIN_ROOT}}/scripts/{name} and will "
                    f"silently no-op (|| true)"
                )
    return problems


def unprefixed_python_commands() -> list:
    """Every hook command invoking python3 must carry PYTHONUTF8=1 (BUG-017).

    Raven's output is emoji-forward and a hook's stdout defaults to cp1252 on Windows,
    so print() raises and the `|| true` fail-soft swallows it — the hook silently does
    nothing. Six separate bugs came from this one class (BUG-007/014/016/024 and twice
    inside BUG-027), three of them failing silently. Checked in every config, canonical
    included, because a new hook added without the prefix is a hook that will one day
    do nothing on someone's machine.
    """
    problems = []
    for rel in [pathlib.Path(".claude") / "settings.json", *DISTRIBUTION]:
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # covered by other checks
        hooks = data.get("hooks", {})
        for event, groups in hooks.items():
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "")
                    for branch in command.split("||"):
                        if "python3" in branch and "PYTHONUTF8=1" not in branch:
                            script = SCRIPT_RE.search(branch)
                            problems.append(
                                f"{rel}: {event} runs {script.group(1) if script else 'python3'} "
                                f"without PYTHONUTF8=1 — its output will be silently dropped on a "
                                f"legacy Windows console"
                            )
    return problems


def main() -> int:
    if not CANONICAL.is_file():
        print(f"raven-distribution-coverage-check: FAIL — canonical missing: {CANONICAL}")
        return 1

    canon = scripts_by_event(CANONICAL)
    failures = missing_script_files(canon) + unprefixed_python_commands()

    for rel in DISTRIBUTION:
        path = REPO / rel
        if not path.is_file():
            failures.append(f"MISSING distribution config: {rel}")
            continue
        try:
            dist = scripts_by_event(path)
        except (json.JSONDecodeError, OSError) as e:
            failures.append(f"UNPARSEABLE {rel}: {e}")
            continue

        for event, expected in canon.items():
            if event not in dist:
                failures.append(
                    f"{rel}: canonical event {event} absent entirely "
                    f"(canonical runs {sorted(expected)})"
                )
                continue
            missing = sorted(set(expected) - set(dist[event]))
            if missing:
                failures.append(
                    f"{rel}: event {event} is missing canonical scripts {missing} "
                    f"(has {sorted(dist[event])})"
                )
            for name, want in sorted(expected.items()):
                if name in dist[event] and dist[event][name] != want:
                    failures.append(
                        f"{rel}: event {event} script {name} ARGS DIFFER — "
                        f"canonical {want!r}, distributed {dist[event][name]!r}"
                    )

    if failures:
        print("raven-distribution-coverage-check: FAIL (distribution lost canonical hooks)")
        for f in failures:
            print(f"  {f}")
        return 1

    events = len(canon)
    total = sum(len(v) for v in canon.values())
    print(
        f"raven-distribution-coverage-check: PASS — all {len(DISTRIBUTION)} distribution "
        f"configs cover canonical ({events} events, {total} script wirings, args included)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
