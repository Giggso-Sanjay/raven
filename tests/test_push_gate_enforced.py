"""Educated Push is ENFORCED: mutations are denied until the user approves.

Replaces test_push_gate_advisory.py. The gate has moved three times — hard
(c8c5c2e), advisory (bb40ee0), opt-in guided (BUG-023, removed), and now enforced
by default at the user's request after watching advisory mode be ignored on every
edit.

The half of this file that matters most is the self-exemption. c8c5c2e was
reverted one commit after shipping because it denied its own --status probes and
the very Edit needed to fix it. Every one of those failure modes has a test here,
so a future change cannot quietly reintroduce them.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

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
    return json.loads(s)["hookSpecificOutput"]["permissionDecision"] if s else "allow"


def _approve(repo, prompt="go ahead"):
    return _run(repo, {"prompt": prompt, "session_id": "s1"}, script=APPROVE)


# ── enforcement ──────────────────────────────────────────────────────────────

def test_mutations_denied_without_approval(tmp_path):
    repo = _repo(tmp_path)
    for payload in (
        {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}},
        {"tool_name": "Write", "tool_input": {"file_path": "new.py"}},
        {"tool_name": "MultiEdit", "tool_input": {"file_path": "app.py"}},
        {"tool_name": "NotebookEdit", "tool_input": {"file_path": "nb.ipynb"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo x > out.txt"}},
    ):
        assert _decision(_run(repo, payload)) == "deny", payload


def test_sed_i_is_treated_as_mutating(tmp_path):
    """c8c5c2e's allowlist permitted `sed -i` — an actual write — while denying probes."""
    repo = _repo(tmp_path)
    payload = {"tool_name": "Bash", "tool_input": {"command": "sed -i s/a/b/ f.py"}}
    assert _decision(_run(repo, payload)) == "deny"


def test_approval_opens_the_gate(tmp_path):
    repo = _repo(tmp_path)
    assert _decision(_run(repo, EDIT)) == "deny"
    _approve(repo)
    assert _decision(_run(repo, EDIT)) == "allow"


def test_non_approval_message_closes_it_again(tmp_path):
    repo = _repo(tmp_path)
    _approve(repo)
    assert _decision(_run(repo, EDIT)) == "allow"
    _approve(repo, "now add tests")          # not an approval word
    assert _decision(_run(repo, EDIT)) == "deny"


def test_approval_expires(tmp_path):
    repo = _repo(tmp_path)
    _approve(repo)
    flag = repo / ".raven" / ".push-approved"
    old = time.time() - 7200                  # 2h > 1h TTL
    os.utime(flag, (old, old))
    assert _decision(_run(repo, EDIT)) == "deny"


def test_lucky_is_an_escape_hatch(tmp_path):
    """Historical opt-out keyword — one message opens the gate for a turn."""
    repo = _repo(tmp_path)
    _approve(repo, "Lucky")
    assert _decision(_run(repo, EDIT)) == "allow"


def test_deny_reason_tells_the_user_what_to_do(tmp_path):
    repo = _repo(tmp_path)
    reason = json.loads(_run(repo, EDIT).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    for expected in ("briefing", "go ahead", "Read-only"):
        assert expected in reason, f"deny reason missing {expected!r}"


# ── the four failure modes that killed c8c5c2e ───────────────────────────────

def test_read_only_bash_is_never_denied(tmp_path):
    repo = _repo(tmp_path)
    for command in ("ls -la", "git status", "git log --oneline",
                    "cat app.py 2>/dev/null", "grep -rn foo . 2>>err.log",
                    "find . -name '*.py'", "wc -l app.py"):
        assert _decision(_run(repo, {"tool_name": "Bash",
                                     "tool_input": {"command": command}})) != "deny", command


def test_diagnostic_probes_are_never_denied(tmp_path):
    """c8c5c2e denied `--status` probes, which is how it hid its own breakage."""
    repo = _repo(tmp_path)
    for command in ("python3 scripts/notify.py --status",
                    "python3 scripts/push-gate.py --reset"):
        assert _decision(_run(repo, {"tool_name": "Bash",
                                     "tool_input": {"command": command}})) != "deny", command


def test_the_gate_can_always_be_repaired(tmp_path):
    """The decisive one: c8c5c2e blocked the Edit needed to fix itself."""
    repo = _repo(tmp_path)
    for path in ("scripts/push-gate.py", "scripts/push-approve.py",
                 ".raven/.push-approved", str(repo / ".raven" / "anything"),
                 "some/nested/push-gate.py"):
        assert _decision(_run(repo, {"tool_name": "Edit",
                                     "tool_input": {"file_path": path}})) != "deny", path


def test_reads_are_never_denied(tmp_path):
    repo = _repo(tmp_path)
    for tool in ("Read", "Grep", "Glob", "Task", "WebFetch"):
        assert _decision(_run(repo, {"tool_name": tool,
                                     "tool_input": {"file_path": "app.py"}})) != "deny", tool


# ── robustness ───────────────────────────────────────────────────────────────

def test_gate_fails_open_on_unparseable_input(tmp_path):
    """A broken gate must never brick a session — and it must fail OPEN, not shut.

    Scope matters: this covers input the gate cannot interpret. A payload that DOES
    name a mutating tool is a different case — see the next test. Fail-open applies
    to errors, not to valid-but-sparse payloads.
    """
    repo = _repo(tmp_path)
    for payload in ("", "not json", "{}", '{"tool_name":"Read"}'):
        env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = str(repo)
        proc = subprocess.run([sys.executable, str(GATE)], cwd=str(repo), env=env,
                              input=payload, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
        assert proc.returncode == 0, f"non-zero exit on {payload!r}"
        assert "deny" not in proc.stdout, f"failed CLOSED on {payload!r}"


def test_a_mutating_tool_with_no_tool_input_is_still_gated(tmp_path):
    """An Edit is a mutation whether or not the payload carries a file_path.

    Deliberately NOT treated as bad input: guessing "probably harmless" for a
    mutating tool would be a hole a malformed payload could walk through.
    """
    repo = _repo(tmp_path)
    assert _decision(_run(repo, {"tool_name": "Edit"})) == "deny"
    _approve(repo)
    assert _decision(_run(repo, {"tool_name": "Edit"})) == "allow"


def test_approval_confirmation_survives_a_legacy_console(tmp_path):
    """BUG-024: the message opens with an emoji; under cp1252 print() raised and the
    fail-soft wrapper swallowed it, so the flag was written and nothing was shown."""
    repo = _repo(tmp_path)
    out = _approve(repo)
    assert out.stdout.strip() and "EDUCATED PUSH" in out.stdout
    out = _run(repo, {"prompt": "go ahead", "session_id": "s1"},
               script=APPROVE, io_encoding="cp1252")
    assert out.stdout.strip(), "no confirmation printed under cp1252"


def test_reset_clears_the_approval(tmp_path):
    repo = _repo(tmp_path)
    _approve(repo)
    assert _decision(_run(repo, EDIT)) == "allow"
    env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = str(repo)
    subprocess.run([sys.executable, str(GATE), "--reset"], cwd=str(repo), env=env,
                   capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert _decision(_run(repo, EDIT)) == "deny", "approval survived SessionStart"
