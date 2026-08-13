"""Educated Push is advisory: it reminds once and NEVER denies.

Replaces test_push_gate_guided.py, deleted when the opt-in guided mode was removed
at the user's request (2026-08-13, bug-fix-log.md BUG-023). The tests kept here are
the ones that outlive that decision — most of the old file only exercised modes.

The no-deny assertion is the important one. c8c5c2e shipped a hard gate that blocked
its own diagnostics and the very Edit needed to fix it; bb40ee0 reverted it. If a
deny path ever reappears in push-gate.py, these fail.
"""
import json
import os
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).parent.parent
GATE = _ROOT / "scripts" / "push-gate.py"
APPROVE = _ROOT / "scripts" / "push-approve.py"

EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}, "session_id": "s1"}


def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".raven").mkdir()
    return tmp_path


def _run(repo, payload, script=None, io_encoding=None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env.pop("PYTHONUTF8", None)
    if io_encoding:
        env["PYTHONIOENCODING"] = io_encoding
    return subprocess.run(
        [sys.executable, str(script or GATE)], cwd=str(repo), env=env,
        input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=20,
    )


def _decision(out):
    s = out.stdout.strip()
    return json.loads(s)["hookSpecificOutput"]["permissionDecision"] if s else "silent"


def test_never_denies(tmp_path):
    """The whole contract: taught, not enforced."""
    repo = _repo(tmp_path)
    assert _decision(_run(repo, EDIT)) == "allow"


def test_a_stale_guided_flag_is_ignored(tmp_path):
    """Anyone who used the removed guided mode has a leftover .push-mode file.

    It must not resurrect the deny path — reset clears it, but a session that
    starts before the reset must still not be blocked.
    """
    repo = _repo(tmp_path)
    (repo / ".raven" / ".push-mode").write_text("guided", encoding="utf-8")
    assert _decision(_run(repo, EDIT)) == "allow"
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo x > out.txt"}}
    assert _decision(_run(repo, payload)) != "deny"


def test_reminder_fires_once_then_silent(tmp_path):
    repo = _repo(tmp_path)
    first = _run(repo, EDIT)
    assert "Educated Push" in first.stdout
    assert _run(repo, EDIT).stdout.strip() == "", "reminder repeated"
    assert (repo / ".raven" / ".push-notice-shown").is_file()


def test_read_only_bash_never_triggers_the_reminder(tmp_path):
    """`2>` / `2>>` are stderr silencing, not writes — the c8c5c2e regex said otherwise."""
    repo = _repo(tmp_path)
    for command in ("ls -la", "git status", "cat app.py 2>/dev/null",
                    "grep -rn foo . 2>>err.log"):
        out = _run(repo, {"tool_name": "Bash", "tool_input": {"command": command}})
        assert out.stdout.strip() == "", f"reminder fired on read-only: {command}"


def test_reset_re_arms_the_reminder(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, EDIT)
    env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = str(repo)
    subprocess.run([sys.executable, str(GATE), "--reset"], cwd=str(repo), env=env,
                   capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert not (repo / ".raven" / ".push-notice-shown").exists()
    assert "Educated Push" in _run(repo, EDIT).stdout


def test_approval_is_recorded_and_cleared(tmp_path):
    repo = _repo(tmp_path)
    flag = repo / ".raven" / ".push-approved"
    _run(repo, {"prompt": "go ahead", "session_id": "s1"}, script=APPROVE)
    assert flag.is_file(), "go-ahead not recorded"
    _run(repo, {"prompt": "now add tests", "session_id": "s1"}, script=APPROVE)
    assert not flag.exists(), "flag not cleared by a non-approval message"


def test_approval_confirmation_survives_a_legacy_console(tmp_path):
    """BUG-024: the message opens with an emoji; under cp1252 print() raised and the
    fail-soft wrapper swallowed it, so the flag was written and nothing was shown."""
    repo = _repo(tmp_path)
    out = _run(repo, {"prompt": "go ahead", "session_id": "s1"},
               script=APPROVE, io_encoding="cp1252")
    assert out.stdout.strip(), "no confirmation printed"
    assert "EDUCATED PUSH" in out.stdout


def test_mode_words_no_longer_do_anything(tmp_path):
    """`guided` / `auto` were removed — they must not write .push-mode any more."""
    repo = _repo(tmp_path)
    for word in ("guided", "auto", "turn on enforcement: guided"):
        _run(repo, {"prompt": word, "session_id": "s1"}, script=APPROVE)
    assert not (repo / ".raven" / ".push-mode").exists(), \
        ".push-mode written — a mode branch survived the removal"
