"""Token metering must actually meter, and must not certify silence (BUG-027).

Live symptom: cost-log.jsonl absent, audit rows reading
{"session_id": "", "model": "unknown", "tokens": 0, "cost_usd": 0.0}, and
.cost-verify.json reporting {"path_a": 0.0, "path_b": 0.0, "verified": true} —
a green dashboard over a dead pipeline.

Four independent defects, each sufficient on its own to zero the output:
  a) open(transcript, "r") with no encoding — cp1252 raised on byte 0x81 and both
     paths bailed before parsing anything
  b) msg.get("role") == "assistant" — the transcript carries {"type": "assistant"}
     and no "role" key at all, so 141 usage records were skipped
  c) verification treated 0.0 == 0.0 as agreement
  d) bucket["tokens"] was never incremented while the rollup read it
"""
import importlib.util
import json
import pathlib

_ROOT = pathlib.Path(__file__).parent.parent


def _meter():
    spec = importlib.util.spec_from_file_location(
        "_token_meter", _ROOT / "scripts" / "token-meter-write.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _usage(inp, out, cache_read=0):
    return {"input_tokens": inp, "output_tokens": out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0}


def _transcript(tmp_path, lines, tail_bytes=b""):
    """Write a JSONL transcript as UTF-8, optionally with a non-cp1252 byte."""
    p = tmp_path / "t.jsonl"
    with p.open("wb") as fh:
        for obj in lines:
            fh.write((json.dumps(obj) + "\n").encode("utf-8"))
        if tail_bytes:
            fh.write(tail_bytes)
    return str(p)


CURRENT_SCHEMA = [
    {"type": "assistant", "session_id": "s-1",
     "message": {"model": "claude-sonnet-5", "usage": _usage(100, 50)}},
    {"type": "assistant", "session_id": "s-1",
     "message": {"model": "claude-sonnet-5", "usage": _usage(200, 25)}},
]
LEGACY_SCHEMA = [
    {"role": "assistant", "session_id": "s-2",
     "message": {"model": "claude-sonnet-5", "usage": _usage(100, 50)}},
]


def test_current_transcript_schema_is_parsed(tmp_path):
    """{"type": "assistant"} with no "role" key — the live format."""
    m = _meter()
    got = m.parse_transcript(_transcript(tmp_path, CURRENT_SCHEMA))
    assert got["model"] == "claude-sonnet-5", "model not extracted"
    assert got["session_id"] == "s-1"
    assert got["tokens"] == 375, got["tokens"]          # 100+50+200+25
    assert got["user_work"]["calls"] == 2


def test_legacy_role_schema_still_parsed(tmp_path):
    """The fix must be additive — older transcripts keep working."""
    m = _meter()
    got = m.parse_transcript(_transcript(tmp_path, LEGACY_SCHEMA))
    assert got["tokens"] == 150, got["tokens"]


def test_non_cp1252_bytes_do_not_abort_the_read(tmp_path):
    """0x81 is undefined in cp1252; an encoding-less open() raised and lost everything."""
    m = _meter()
    path = _transcript(tmp_path, CURRENT_SCHEMA, tail_bytes=b'{"note":"\xc2\x81"}\n')
    got = m.parse_transcript(path)
    assert got["tokens"] == 375, "usage lost to a decode error"
    assert m.full_transcript_totals(path) > 0, "path B aborted on the same byte"


def test_bucket_tokens_and_cost_agree(tmp_path):
    """bucket["tokens"] was never incremented while the rollup read it."""
    m = _meter()
    got = m.parse_transcript(_transcript(tmp_path, CURRENT_SCHEMA))
    bucket = got["user_work"]
    assert bucket["tokens"] == bucket["input"] + bucket["output"]
    assert bucket["tokens"] > 0 and bucket["cost_usd"] > 0, \
        "cost accrued with a zero token count — the live inconsistency"


def test_both_paths_agree_on_a_real_shaped_transcript(tmp_path):
    """Path A (deltas) and path B (full recompute) must land on the same number."""
    m = _meter()
    path = _transcript(tmp_path, CURRENT_SCHEMA)
    a = m.parse_transcript(path)["user_work"]["cost_usd"]
    b = m.full_transcript_totals(path)
    assert b > 0
    assert abs(a - b) / b * 100 <= 5.0, f"paths disagree: A={a} B={b}"


def test_verification_reports_unmeasured_not_verified():
    """BUG-027b: two zeros agree perfectly. That is not a pass.

    Mirrors the decision in cost_verify: measured = path_a > 0 or path_b > 0.
    """
    for path_a, path_b, expect in [
        (0.0, 0.0, "unmeasured"),
        (1.0, 1.0, "verified"),
        (1.0, 2.0, "divergent"),
    ]:
        measured = path_a > 0 or path_b > 0
        variance = abs(path_a - path_b) / path_b * 100 if path_b > 0 else (
            0.0 if path_a == 0 else 100.0)
        status = "unmeasured" if not measured else (
            "verified" if variance <= 5.0 else "divergent")
        assert status == expect, f"{path_a}/{path_b} -> {status}, expected {expect}"


NO_SID = [
    {"type": "assistant",
     "message": {"model": "claude-sonnet-5", "usage": _usage(100, 50)}},
]


def test_session_id_falls_back_to_the_hook_payload(tmp_path, monkeypatch):
    """BUG-028: a transcript with no session_id left it "", which zeroed path A.

    The hook payload always carries the real id; parse_transcript only learns one by
    peeking the transcript. Without the fallback an empty id also skipped the
    checkpoint write, making the next run re-read from line 0 — the b37f2ba
    compounding path.
    """
    import subprocess
    import sys as _sys
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".raven").mkdir()
    tpath = _transcript(repo, NO_SID)

    m = _meter()
    assert m.parse_transcript(tpath)["session_id"] == "", "fixture should lack a session_id"

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    subprocess.run(
        [_sys.executable, str(_ROOT / "scripts" / "token-meter-write.py")],
        cwd=str(repo), env=env,
        input=json.dumps({"session_id": "HOOK-SID", "transcript_path": tpath}),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    verdict = json.loads((repo / ".raven" / ".cost-verify.json").read_text(encoding="utf-8"))
    assert verdict["session_id"] == "HOOK-SID", "hook session_id not used as fallback"
    rows = [json.loads(l) for l in
            (repo / ".raven" / "cost-log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and all(r["session_id"] == "HOOK-SID" for r in rows)
    checkpoint = json.loads(
        (repo / ".raven" / ".token-meter-checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["session_id"] == "HOOK-SID", "checkpoint skipped — next run re-reads from 0"


def test_indeterminate_is_not_reported_as_divergent(tmp_path):
    """Path A with no basis must not assert a disagreement it never measured."""
    m = _meter()
    tpath = _transcript(tmp_path, CURRENT_SCHEMA)
    m.COST_LOG.parent.mkdir(parents=True, exist_ok=True)

    def verdict(session_id, rows):
        m.COST_LOG.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        m.write_cost_verify(session_id, tpath, "2026-08-12T00:00:00Z")
        return json.loads(m.COST_VERIFY.read_text(encoding="utf-8"))

    other = [{"session_id": "s1", "computed_cost_usd": 3.0}]
    assert verdict("", other)["status"] == "indeterminate", "empty session_id"
    assert verdict("s9", other)["status"] == "indeterminate", "no rows for this session"

    cost_b = m.full_transcript_totals(tpath)
    agree = verdict("s1", [{"session_id": "s1", "computed_cost_usd": cost_b}])
    assert agree["status"] == "verified" and agree["path_a_rows"] == 1
    disagree = verdict("s1", [{"session_id": "s1", "computed_cost_usd": cost_b * 3}])
    assert disagree["status"] == "divergent"


def test_indeterminate_writes_no_disagreement_audit_row(tmp_path):
    """The audit flag is gated on "divergent" — a false alarm trains people to ignore it."""
    m = _meter()
    tpath = _transcript(tmp_path, CURRENT_SCHEMA)
    m.COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    m.COST_LOG.write_text(json.dumps({"session_id": "s1", "computed_cost_usd": 3.0}) + "\n",
                          encoding="utf-8")
    before = list(m.AUDIT_DIR.glob("*.log")) if m.AUDIT_DIR.exists() else []
    sizes = {p: p.stat().st_size for p in before}
    m.write_cost_verify("", tpath, "2026-08-12T00:00:00Z")
    for p in (list(m.AUDIT_DIR.glob("*.log")) if m.AUDIT_DIR.exists() else []):
        text = p.read_text(encoding="utf-8", errors="replace")[sizes.get(p, 0):]
        assert "disagree" not in text, "indeterminate logged as a disagreement"


def test_cost_verify_source_encodes_the_precondition():
    """Guard the fix in the script itself, not just the logic mirrored above."""
    src = (_ROOT / "scripts" / "token-meter-write.py").read_text(encoding="utf-8")
    assert "path_a > 0 or path_b > 0" in src, "measured precondition missing"
    assert '"unmeasured"' in src, "unmeasured status missing"
