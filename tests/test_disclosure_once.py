"""Model disclosure fires once per session, keyed on a marker not session_id (BUG-021).

Observed live: the disclosure line appeared on every prompt. The old gate compared
the incoming session_id against a stored one, and two different ids were observed
minutes apart inside a single session — so "id differs" was true every turn. The
logic was correct; the key was not. Marker files are what SessionStart already
clears, so they mean once-per-session regardless of host id behaviour.
"""
import json
import os
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).parent.parent
ROUTER = _ROOT / "scripts" / "model-router.py"
GATE = _ROOT / "scripts" / "push-gate.py"
MARKER = ".model-disclosed"


def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".raven").mkdir()
    return tmp_path


def _hook(repo, prompt="what is 2+2", session_id="s1"):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(ROUTER), "--hook"], cwd=str(repo), env=env,
        input=json.dumps({"prompt": prompt, "session_id": session_id}),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    ).stdout


def _disclosed(out):
    return "model disclosure due" in (out or "")


def test_fires_once_then_silent_same_id(tmp_path):
    repo = _repo(tmp_path)
    assert _disclosed(_hook(repo)), "first prompt should disclose"
    assert not _disclosed(_hook(repo)), "second prompt must not disclose"
    assert (repo / ".raven" / MARKER).is_file()


def test_churning_session_id_does_not_re_disclose(tmp_path):
    """The actual live failure: a new id every turn must NOT re-trigger."""
    repo = _repo(tmp_path)
    assert _disclosed(_hook(repo, session_id="id-1"))
    for i in range(2, 6):
        assert not _disclosed(_hook(repo, session_id=f"id-{i}")), f"re-disclosed on id-{i}"


def test_reset_re_arms_the_disclosure(tmp_path):
    """SessionStart clears it, so the next real session discloses again."""
    repo = _repo(tmp_path)
    _hook(repo)
    assert (repo / ".raven" / MARKER).is_file()

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    subprocess.run([sys.executable, str(GATE), "--reset"], cwd=str(repo), env=env,
                   capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert not (repo / ".raven" / MARKER).exists(), "--reset must clear the marker"
    assert _disclosed(_hook(repo)), "next session should disclose again"


def test_router_never_blocks_the_prompt(tmp_path):
    """UserPromptSubmit must always exit 0 — e70c971's lockout lesson."""
    repo = _repo(tmp_path)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    for payload in ("", "{}", '{"prompt":""}', "not json at all"):
        proc = subprocess.run(
            [sys.executable, str(ROUTER), "--hook"], cwd=str(repo), env=env,
            input=payload, capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert proc.returncode == 0, f"non-zero exit on payload {payload!r}"
