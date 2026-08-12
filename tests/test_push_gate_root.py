"""push-gate / push-approve must anchor to the repo root, not cwd (BUG-022).

Live failure this locks out: a session working in project B wrote
.push-notice-shown into project A's .raven/, because repo_root() fell back to
os.getcwd(). "Once per session" then tracked the wrong directory — the reminder
could re-fire forever in the real project, or never fire because an unrelated
project held the marker — and os.makedirs created a stray .raven/ tree.

Same bug class as 9de4131 (phantom guard/guard/.raven/), JOURNEY §8 lesson 1.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
GATE = _ROOT / "scripts" / "push-gate.py"
MARKER = ".push-notice-shown"


def _run(cwd, env_root=None, argv=(), payload=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_root:
        env["CLAUDE_PROJECT_DIR"] = str(env_root)
    return subprocess.run(
        [sys.executable, str(GATE), *argv], cwd=str(cwd), env=env,
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )


def _repo(tmp_path, name):
    """A directory that looks like a git repo."""
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    return d


EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "x.py"}, "session_id": "s1"}


def test_marker_lands_in_the_repo_containing_cwd(tmp_path):
    """Run from a SUBDIRECTORY with no env var — marker must go to the repo root."""
    repo = _repo(tmp_path, "proj")
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)

    assert _run(nested, payload=EDIT).returncode == 0
    assert (repo / ".raven" / MARKER).is_file(), "marker not at repo root"
    assert not (nested / ".raven").exists(), "stray .raven/ created in the subdirectory"


def test_marker_does_not_leak_into_a_sibling_repo(tmp_path):
    """The exact live failure: work in B, marker must not appear in A."""
    a = _repo(tmp_path, "project-a")
    b = _repo(tmp_path, "project-b")

    assert _run(b, payload=EDIT).returncode == 0
    assert (b / ".raven" / MARKER).is_file()
    assert not (a / ".raven" / MARKER).exists(), "marker leaked into the wrong project"


def test_env_var_wins_when_set(tmp_path):
    repo = _repo(tmp_path, "proj")
    other = _repo(tmp_path, "other")

    assert _run(other, env_root=repo, payload=EDIT).returncode == 0
    assert (repo / ".raven" / MARKER).is_file()
    assert not (other / ".raven" / MARKER).exists()


def test_reminder_fires_once_then_stays_silent(tmp_path):
    repo = _repo(tmp_path, "proj")

    first = _run(repo, payload=EDIT)
    assert "Educated Push" in first.stdout
    second = _run(repo, payload=EDIT)
    assert second.stdout.strip() == "", "reminder repeated — marker not honoured"


def test_reset_clears_using_the_same_resolver(tmp_path):
    """--reset must delete the marker repo_root() would have written."""
    repo = _repo(tmp_path, "proj")
    nested = repo / "src"
    nested.mkdir()

    _run(nested, payload=EDIT)
    assert (repo / ".raven" / MARKER).is_file()

    _run(nested, argv=("--reset",))
    assert not (repo / ".raven" / MARKER).exists(), "--reset missed the real marker"
    # and the reminder is available again next session
    assert "Educated Push" in _run(nested, payload=EDIT).stdout


def test_gate_never_denies(tmp_path):
    """Educated Push is advisory (bb40ee0) — no deny path may reappear."""
    repo = _repo(tmp_path, "proj")
    out = _run(repo, payload=EDIT).stdout
    assert "deny" not in out
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "allow"
