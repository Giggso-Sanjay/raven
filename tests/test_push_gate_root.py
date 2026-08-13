"""Approval state must anchor to the repo root, not cwd (BUG-022).

Originally written around .push-notice-shown, the advisory-era reminder marker.
That marker is gone — enforcement replaced it — but the property it guarded is now
more important, not less: `.push-approved` decides whether mutations are allowed,
so if it lands in the wrong directory an approval given in project A can open the
gate in project B, or a real approval can be invisible to the gate that needs it.

Original defect: `os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()`, with no
`.git` walk — the cwd bug class of 9de4131 (the phantom guard/guard/.raven/).
"""
import json
import os
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).parent.parent
GATE = _ROOT / "scripts" / "push-gate.py"
APPROVE = _ROOT / "scripts" / "push-approve.py"
EDUCATE = _ROOT / "scripts" / "educate.py"
FLAG = ".push-approved"

EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "x.py"}, "session_id": "s1"}


def _repo(tmp_path, name, enforced=False):
    """Advisory is the default, so allow-vs-deny is only observable in enforced mode.

    These tests are about WHERE the approval flag lands, and the deny/allow answer is
    how we observe it — hence enforced mode as the instrument, not the subject.
    """
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    (d / ".raven").mkdir(exist_ok=True)
    if enforced:
        _run(EDUCATE, d, argv=("--enforced",))
    return d


def _run(script, cwd, payload=None, env_root=None, argv=()):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_root:
        env["CLAUDE_PROJECT_DIR"] = str(env_root)
    return subprocess.run(
        [sys.executable, str(script), *argv], cwd=str(cwd), env=env,
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )


def _decision(out):
    s = out.stdout.strip()
    return json.loads(s)["hookSpecificOutput"]["permissionDecision"] if s else "allow"


def test_approval_lands_at_the_repo_root_from_a_subdirectory(tmp_path):
    """Run from repo/src/deep with no env var — the flag must go to the repo root."""
    repo = _repo(tmp_path, "proj")
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)

    _run(APPROVE, nested, {"prompt": "go ahead", "session_id": "s1"})
    assert (repo / ".raven" / FLAG).is_file(), "approval not at repo root"
    assert not (nested / ".raven").exists(), "stray .raven/ created in the subdirectory"


def test_the_gate_reads_the_same_root_it_was_written_to(tmp_path):
    """Write from a subdirectory, read from another — the gate must still see it.

    This is the failure that matters: a mismatch here means a real approval is
    invisible and every mutation stays denied.
    """
    repo = _repo(tmp_path, "proj", enforced=True)
    a = repo / "src"; a.mkdir()
    b = repo / "tests"; b.mkdir()

    assert _decision(_run(GATE, a, EDIT)) == "deny"
    _run(APPROVE, a, {"prompt": "go ahead", "session_id": "s1"})
    assert _decision(_run(GATE, b, EDIT)) == "allow", "approval written and read from different roots"


def test_approval_does_not_leak_into_a_sibling_repo(tmp_path):
    """Approving in B must not open the gate in A."""
    a = _repo(tmp_path, "project-a", enforced=True)
    b = _repo(tmp_path, "project-b", enforced=True)

    _run(APPROVE, b, {"prompt": "go ahead", "session_id": "s1"})
    assert (b / ".raven" / FLAG).is_file()
    assert not (a / ".raven" / FLAG).exists(), "approval leaked into the wrong project"
    assert _decision(_run(GATE, a, EDIT)) == "deny", "gate opened in an unapproved project"


def test_env_var_wins_when_set(tmp_path):
    repo = _repo(tmp_path, "proj")
    other = _repo(tmp_path, "other")

    _run(APPROVE, other, {"prompt": "go ahead", "session_id": "s1"}, env_root=repo)
    assert (repo / ".raven" / FLAG).is_file()
    assert not (other / ".raven" / FLAG).exists()


def test_reset_clears_using_the_same_resolver(tmp_path):
    """--reset from a subdirectory must delete the flag repo_root() would have written."""
    repo = _repo(tmp_path, "proj", enforced=True)
    nested = repo / "src"; nested.mkdir()

    _run(APPROVE, nested, {"prompt": "go ahead", "session_id": "s1"})
    assert (repo / ".raven" / FLAG).is_file()

    _run(GATE, nested, argv=("--reset",))
    assert not (repo / ".raven" / FLAG).exists(), "--reset missed the real flag"
    assert _decision(_run(GATE, nested, EDIT)) == "deny", "gate still open after reset"
