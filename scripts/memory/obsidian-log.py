#!/usr/bin/env python3
"""
obsidian-log.py v3 — Raven Stop hook
Trimmed session log + project hub ensure + index hygiene.

Writes ~/RavenVault/sessions/YYYY-MM-DD-<project>.md (short entries).
Optional raw git dump → sessions/raw/ (outside default graph).
Never reads secrets. Local file write only.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys
from collections import Counter

# Allow import when run from .claude/scripts or plugin path
_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_HERE = __import__('pathlib').Path(__file__).resolve().parent
for _d in (_HERE, _HERE.parent / 'memory', _HERE.parent / 'routing'):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
from vault_common import (  # noqa: E402
    SESSIONS,
    ensure_project_hub,
    get_project,
    rebuild_index,
    update_hub_recent_session,
    RAW_SESSIONS,
    run,
    ensure_dirs,
)

MAX_ENTRY_LINES = 80
TOP_FILES = 10


def clean_files(lst):
    return [
        f
        for f in lst
        if f and not any(x in f for x in [".git/", "/tmp/", "__pycache__", "node_modules"])
    ]


def parse_transcript(transcript_path: str):
    files_written, files_read, bash_cmds = [], [], []
    tool_counts = Counter()
    skills_used = []
    if not transcript_path or not pathlib.Path(transcript_path).exists():
        return files_written, files_read, bash_cmds, tool_counts, skills_used
    try:
        with open(transcript_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if not isinstance(msg, dict) or msg.get("role") != "assistant":
                        continue
                    for block in msg.get("content") or []:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        tool_counts[name] += 1
                        if name in ("Write", "Edit", "MultiEdit"):
                            fp = inp.get("file_path", "")
                            if fp and fp not in files_written:
                                files_written.append(fp)
                        elif name == "Read":
                            fp = inp.get("file_path", "")
                            if fp and fp not in files_read:
                                files_read.append(fp)
                        elif name == "Bash":
                            cmd = (inp.get("command") or "")[:80]
                            if cmd:
                                bash_cmds.append(cmd)
                        elif name == "Skill":
                            sk = inp.get("skill", "")
                            if sk and sk not in skills_used:
                                skills_used.append(sk)
                except Exception:
                    pass
    except Exception:
        pass
    return files_written, files_read, bash_cmds, tool_counts, skills_used


def ai_summary(project, branch, files_written, tool_counts, skills_used, git_tip) -> str:
    context = f"""Project: {project}
Branch: {branch}
Commit tip: {git_tip or '(none)'}
Files: {', '.join(files_written[:TOP_FILES]) or '(none)'}
Tools: {', '.join(f'{k}:{v}' for k,v in tool_counts.most_common(6))}
Skills: {', '.join(skills_used) or '(none)'}
"""
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "In 3-5 crisp bullets (≤15 words each), summarise this coding session. "
                "No preamble. Bullets starting with •.\n\n" + context,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def main() -> None:
    ensure_dirs()
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        hook_input = {}

    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path and session_id:
        for p in pathlib.Path.home().glob(f".claude/projects/**/{session_id}.jsonl"):
            transcript_path = str(p)
            break

    files_written, files_read, _bash, tool_counts, skills_used = parse_transcript(
        transcript_path
    )
    files_written = clean_files(files_written)[:TOP_FILES]
    files_read = clean_files(files_read)[:5]

    project = get_project()
    ensure_project_hub(project)

    git_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    git_tip = run(["git", "log", "--oneline", "-1"])
    git_status = run(["git", "status", "--short"])
    # Cap status for raw archive only
    if git_status and len(git_status.splitlines()) > 40:
        raw_name = f"{datetime.date.today().isoformat()}-{project}-status.txt"
        try:
            (RAW_SESSIONS / raw_name).write_text(git_status[:50000])
        except OSError:
            pass
        git_status_lines = git_status.splitlines()[:15]
        git_status_short = "\n".join(git_status_lines) + "\n… (truncated; full in sessions/raw/)"
    else:
        git_status_short = "\n".join((git_status or "").splitlines()[:15])

    summary = ai_summary(
        project, git_branch, files_written, tool_counts, skills_used, git_tip
    )

    date = datetime.date.today().isoformat()
    timestamp = datetime.datetime.now().strftime("%H:%M")
    note_path = SESSIONS / f"{date}-{project}.md"
    total_tools = sum(tool_counts.values())
    top_tools = ", ".join(f"{k}×{v}" for k, v in tool_counts.most_common(5))

    parts = [
        f"\n---\n## Session Entry — {timestamp}",
        f"**Project:** [[{'projects/' + project}]]  ",
        f"**Branch:** {git_branch or 'unknown'}  ",
        f"**Tools:** {total_tools} ({top_tools})",
        "",
    ]
    if summary:
        parts += ["### AI Summary", summary, ""]
    if files_written:
        parts.append("### Top files")
        for f in files_written:
            parts.append(f"- `{f}`")
        parts.append("")
    if skills_used:
        parts.append("### Skills")
        parts.append(", ".join(f"`{s}`" for s in skills_used[:12]))
        parts.append("")
    if git_tip:
        parts += ["### Commit tip", f"- `{git_tip}`", ""]
    if git_status_short.strip():
        parts += ["### Uncommitted (capped)", f"```\n{git_status_short}\n```", ""]

    entry = "\n".join(parts) + "\n"
    # Enforce ~80 lines per entry
    elines = entry.splitlines()
    if len(elines) > MAX_ENTRY_LINES:
        entry = "\n".join(elines[:MAX_ENTRY_LINES]) + "\n… (trimmed)\n"

    if not note_path.exists():
        note_path.write_text(
            f"""---
type: session
project: {project}
date: {date}
tags: [session, raven]
---
# Session — {date} — {project}

[[projects/{project}]]

"""
        )

    with open(note_path, "a") as f:
        f.write(entry)

    update_hub_recent_session(project, f"sessions/{date}-{project}", timestamp)
    rebuild_index(last_session=f"{date}-{project}", timestamp=timestamp)

    # Fail-soft knowledge extract
    extract = _SCRIPT_DIR / "knowledge-extract.py"
    if extract.exists():
        try:
            subprocess.Popen(
                [sys.executable, str(extract), "--project", project, "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass

    print(f"✅ Session logged → RavenVault/sessions/{date}-{project}.md")
    print(f"   Hub: projects/{project}.md · index rebuilt")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"obsidian-log fail-soft: {e}", file=sys.stderr)
        sys.exit(0)
