"""Educated Push has two modes: advisory (default) and enforced, set by /educate.

Design points these tests exist to protect, each learned from a failure:

  * advisory is the DEFAULT, including when no mode file exists — a typo or an
    unreadable file must fail toward the less surprising behaviour.
  * the mode is PER PROJECT and survives SessionStart. The approval does not.
  * the advisory reminder fires once per TURN, not once per session and not once
    per file. A multi-file refactor gets one line.
  * only edit tools are gated. Bash left the matcher because bash_is_read_only()
    split on `|` and `>` without respecting quotes and DENIED a real read
    (`grep -oE "(allow|deny)" f`). A read cannot be wrongly blocked by a gate that
    never inspects reads.
  * enforced mode still cannot trap you — the c8c5c2e exemptions hold.
  * switching modes is verified END TO END (command -> flag -> gate behaviour).
    BUG-025 slipped through because the switch was tested only as a regex.
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
EDUCATE = _ROOT / "scripts" / "educate.py"

EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}


def _repo(tmp_path, name="proj"):
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    (d / ".raven").mkdir()
    return d


def _run(script, repo, payload=None, argv=(), io_encoding=None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env.pop("PYTHONUTF8", None)
    if io_encoding:
        env["PYTHONIOENCODING"] = io_encoding
    return subprocess.run(
        [sys.executable, str(script), *argv], cwd=str(repo), env=env,
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )


def _gate(repo, payload=EDIT):
    out = _run(GATE, repo, payload)
    s = out.stdout.strip()
    if not s:
        return "allow", False
    o = json.loads(s)
    return o["hookSpecificOutput"]["permissionDecision"], "systemMessage" in o


def _turn(repo, prompt="do something"):
    """Simulate a new user turn — this is what re-arms the advisory reminder."""
    return _run(APPROVE, repo, {"prompt": prompt, "session_id": "s1"})


# ── advisory is the default ───────────────────────────────────────────────────

def test_advisory_is_the_default_with_no_mode_file(tmp_path):
    repo = _repo(tmp_path)
    assert not (repo / ".raven" / ".push-mode").exists()
    decision, notice = _gate(repo)
    assert decision == "allow" and notice, "default should allow with a reminder"


def test_unrecognised_mode_value_falls_back_to_advisory(tmp_path):
    """A typo must not silently start blocking edits."""
    repo = _repo(tmp_path)
    (repo / ".raven" / ".push-mode").write_text("enforcd", encoding="utf-8")
    assert _gate(repo)[0] == "allow"


def test_advisory_reminder_is_once_per_turn(tmp_path):
    repo = _repo(tmp_path)
    assert _gate(repo) == ("allow", True), "first edit of the turn"
    assert _gate(repo) == ("allow", False), "second edit, same turn"
    assert _gate(repo) == ("allow", False), "third edit, same turn"
    _turn(repo)
    assert _gate(repo) == ("allow", True), "new turn re-arms the reminder"


def test_advisory_notice_names_the_way_to_enforce(tmp_path):
    repo = _repo(tmp_path)
    out = _run(GATE, repo, EDIT)
    assert "/educate enforced mode" in out.stdout, "advisory must advertise the exit"


# ── enforced ─────────────────────────────────────────────────────────────────

def test_enforced_denies_until_approved(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    assert _gate(repo)[0] == "deny"
    _turn(repo, "go ahead")
    assert _gate(repo)[0] == "allow"


def test_enforced_deny_names_the_way_back(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    reason = json.loads(_run(GATE, repo, EDIT).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "/educate advisory mode" in reason, "enforced must advertise the exit"
    assert "briefing" in reason


def test_approval_expires_in_enforced(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    _turn(repo, "go ahead")
    flag = repo / ".raven" / ".push-approved"
    old = time.time() - 7200
    os.utime(flag, (old, old))
    assert _gate(repo)[0] == "deny"


def test_non_approval_message_closes_the_gate(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    _turn(repo, "go ahead")
    assert _gate(repo)[0] == "allow"
    _turn(repo, "now add tests")
    assert _gate(repo)[0] == "deny"


def test_lucky_is_an_escape_hatch(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    _turn(repo, "Lucky")
    assert _gate(repo)[0] == "allow"


# ── switching, end to end ────────────────────────────────────────────────────

def test_mode_switch_changes_gate_behaviour(tmp_path):
    """BUG-025's lesson: test the switch end to end, not just its parsing."""
    repo = _repo(tmp_path)
    assert _gate(repo)[0] == "allow"

    _run(EDUCATE, repo, argv=("--enforced",))
    assert (repo / ".raven" / ".push-mode").read_text(encoding="utf-8").strip() == "enforced"
    assert _gate(repo)[0] == "deny"

    _run(EDUCATE, repo, argv=("--advisory",))
    assert (repo / ".raven" / ".push-mode").read_text(encoding="utf-8").strip() == "advisory"
    assert _gate(repo)[0] == "allow"


def test_educate_prints_confirmation_on_a_legacy_console(tmp_path):
    """BUG-024: a swallowed confirmation makes a working switch look dead."""
    repo = _repo(tmp_path)
    for argv in (("--enforced",), ("--advisory",), ("--status",)):
        out = _run(EDUCATE, repo, argv=argv, io_encoding="cp1252")
        assert out.stdout.strip(), f"no output for {argv}"
        assert "EDUCATED PUSH" in out.stdout


def test_mode_persists_across_sessionstart(tmp_path):
    """Per project, by decision: --reset must NOT clear the mode, but must clear approval."""
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    _turn(repo, "go ahead")
    assert _gate(repo)[0] == "allow"

    _run(GATE, repo, argv=("--reset",))              # what SessionStart does
    assert (repo / ".raven" / ".push-mode").exists(), "mode was cleared — not per project"
    assert _gate(repo)[0] == "deny", "approval survived SessionStart"


def test_mode_does_not_leak_between_projects(tmp_path):
    repo_a = _repo(tmp_path, "a")
    repo_b = _repo(tmp_path, "b")
    _run(EDUCATE, repo_b, argv=("--enforced",))
    assert _gate(repo_b)[0] == "deny"
    assert _gate(repo_a)[0] == "allow", "enforced leaked into another project"


# ── scope: only edits are gated ──────────────────────────────────────────────

def test_bash_is_never_gated_in_either_mode(tmp_path):
    """Bash left the matcher; even if re-added, the script must not gate it.

    The deleted classifier denied `grep -oE "(allow|deny)" f` — a read — because it
    split on `|` inside quotes. That blocked real research.
    """
    repo = _repo(tmp_path)
    commands = ('ls -la', 'grep -oE "(allow|deny)" f', 'cat f 2>/dev/null',
                'echo x > out.txt', 'sed -i s/a/b/ f.py')
    for mode in ("--advisory", "--enforced"):
        _run(EDUCATE, repo, argv=(mode,))
        for command in commands:
            payload = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert _gate(repo, payload)[0] == "allow", f"{mode}: {command}"


def test_reads_are_never_gated(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    for tool in ("Read", "Grep", "Glob", "WebFetch", "Task"):
        assert _gate(repo, {"tool_name": tool,
                            "tool_input": {"file_path": "app.py"}})[0] == "allow", tool


def test_the_gate_can_always_be_repaired_in_enforced(tmp_path):
    """c8c5c2e blocked the Edit needed to fix itself. Still must not."""
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    for path in ("scripts/push-gate.py", "scripts/push-approve.py",
                 ".raven/.push-mode", str(repo / ".raven" / "x")):
        assert _gate(repo, {"tool_name": "Edit",
                            "tool_input": {"file_path": path}})[0] != "deny", path


def test_gate_fails_open_on_unparseable_input(tmp_path):
    repo = _repo(tmp_path)
    _run(EDUCATE, repo, argv=("--enforced",))
    for payload in ("", "not json", "{}"):
        env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = str(repo)
        proc = subprocess.run([sys.executable, str(GATE)], cwd=str(repo), env=env,
                              input=payload, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
        assert proc.returncode == 0 and "deny" not in proc.stdout, repr(payload)
