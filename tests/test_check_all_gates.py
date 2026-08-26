"""check-all-gates.py must read each subprocess's own exit code, never through a
pipe. `cmd 2>&1 | tail` reports tail's exit code, not the command's — that mistake
already produced one false "all green" in this repo (see CLAUDE.md Rule C).
"""
import subprocess
import sys
import pathlib

_ROOT = pathlib.Path(__file__).parent.parent
RUNNER = _ROOT / "scripts" / "ops" / "check-all-gates.py"


def _run(argv=()):
    return subprocess.run([sys.executable, str(RUNNER), *argv], cwd=_ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def test_exits_nonzero_when_any_gate_fails():
    """docs-vs-reality is known to FAIL on main today — a real, not synthetic, case."""
    proc = _run()
    assert "docs-vs-reality" in proc.stdout
    if "[FAIL] docs-vs-reality" in proc.stdout:
        assert proc.returncode != 0, "a failing gate must not report success"


def test_runs_all_four_known_gates():
    proc = _run()
    for gate in ("engine-drift", "docs-vs-reality", "version-consistency", "counts"):
        assert gate in proc.stdout, f"{gate} did not run"


def test_tests_flag_selects_pytest_by_source_inspection():
    """--tests must run pytest, but this file's own subprocess call cannot invoke
    --tests for real: check-all-gates.py --tests runs pytest tests/, which would
    include THIS test, which would invoke --tests again, unboundedly (observed:
    a live recursive run here took 128s and still failed via subprocess timeout,
    not a clean assertion). Checking the source is the honest option, not a live
    self-referential run.
    """
    src = RUNNER.read_text(encoding="utf-8")
    assert '"--tests" in sys.argv' in src
    assert '"pytest", "tests/"' in src


def test_a_failing_subprocess_is_never_reported_as_pass():
    """The exit-code trap, directly: no gate line may say PASS when its own process
    returned nonzero."""
    proc = _run()
    lines = proc.stdout.splitlines()
    for i, line in enumerate(lines):
        if "[PASS]" in line:
            label = line.split("]")[1].split()[0]
            assert label not in ("docs-vs-reality",) or "raven-docs-reality-check: PASS" in line, \
                f"{label} reported PASS while known to fail"


def test_docs_vs_reality_never_crashes():
    """It may legitimately FAIL on real Rule 5 drift, but must never raise — a
    FileNotFoundError traceback and a structured Rule 5 report both exit 1, so exit
    code alone cannot distinguish a broken gate from a working one that found a
    real problem. The path bug (repo root one directory short after scripts/ ->
    scripts/ops/) produced exactly this: same exit code, wrong reason.
    """
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "ops" / "check-docs-vs-reality.py")],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "raven-docs-reality-check" in proc.stdout


def test_version_consistency_never_crashes():
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "ops" / "check-version-consistency.py")],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 0
    assert "raven-version-consistency-check: PASS" in proc.stdout
