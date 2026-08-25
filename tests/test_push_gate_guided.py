"""Guided mode denies until approval; advisory stays the default (BUG-023).

The hard-enforced gate (c8c5c2e) was reverted one commit later because it blocked
its own diagnostics, counted `2>/dev/null` as a write, and blocked the very Edit
needed to fix it. Those were allowlist bugs, not a flaw in enforcement — so guided
mode is opt-in and carries a self-exemption. These tests pin both halves: that
enforcement works when asked for, and that it can never trap the user.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).parent.parent
GATE = _ROOT / "scripts" / "push-gate.py"

EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}, "session_id": "s1"}


def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".raven").mkdir()
    return tmp_path


def _run(repo, payload):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(GATE)], cwd=str(repo), env=env,
        input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", timeout=20,
    )
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def _decision(out):
    return out["hookSpecificOutput"]["permissionDecision"] if out else "silent"


def _mode(repo, value):
    (repo / ".raven" / ".push-mode").write_text(value, encoding="utf-8")


def test_default_is_advisory_never_denies(tmp_path):
    """No .push-mode file — the bb40ee0 default must be untouched."""
    repo = _repo(tmp_path)
    assert _decision(_run(repo, EDIT)) == "allow"


def test_auto_mode_never_denies(tmp_path):
    repo = _repo(tmp_path)
    _mode(repo, "auto")
    assert _decision(_run(repo, EDIT)) == "allow"


def test_guided_denies_without_approval(tmp_path):
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    out = _run(repo, EDIT)
    assert _decision(out) == "deny"
    assert "briefing" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guided_allows_with_fresh_approval(tmp_path):
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    (repo / ".raven" / ".push-approved").write_text("go ahead", encoding="utf-8")
    assert _decision(_run(repo, EDIT)) != "deny"


def test_guided_denies_when_approval_expired(tmp_path):
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    stale = repo / ".raven" / ".push-approved"
    stale.write_text("go ahead", encoding="utf-8")
    old = time.time() - 7200  # 2h > 1h TTL
    os.utime(stale, (old, old))
    assert _decision(_run(repo, EDIT)) == "deny"


def test_read_only_bash_passes_in_guided(tmp_path):
    """The c8c5c2e bug: `2>/dev/null` is stderr silencing, not a write."""
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    for command in ("ls -la", "git status", "cat app.py 2>/dev/null",
                    "grep -rn foo . 2>>err.log"):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert _decision(_run(repo, payload)) != "deny", command


def test_writing_bash_is_denied_in_guided(tmp_path):
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo x > out.txt"}}
    assert _decision(_run(repo, payload)) == "deny"


def test_gate_can_always_be_repaired(tmp_path):
    """Self-exemption: guided mode must never block fixing or disabling itself."""
    repo = _repo(tmp_path)
    _mode(repo, "guided")
    exempt = [
        {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "scripts" / "push-gate.py")}},
        {"tool_name": "Write", "tool_input": {"file_path": str(repo / ".raven" / ".push-mode")}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 scripts/push-gate.py --reset"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 scripts/notify.py --status"}},
    ]
    for payload in exempt:
        assert _decision(_run(repo, payload)) != "deny", payload
