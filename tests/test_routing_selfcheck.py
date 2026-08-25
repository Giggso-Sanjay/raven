"""The routing self-check must never report PASS over a model it invented.

BUG-034: build_routing's fmt() ended with

    return f"{t[0]}/{t[1]}" if t else "anthropic/claude-sonnet-4-5"

so on a machine with no provider API keys — the normal Claude Code subscription
case — every pick was None, all four tiers received that hardcoded string, and
validate_routing printed "PASS" four times. Its own "FAIL — no model configured"
branch was unreachable: fmt() guaranteed a non-empty value.

A probe whose failure mode is PASS is not a probe. These tests pin the three
behaviours that matter: never invent, still fail loudly on a real misconfig, and
say "unconfigured" rather than four alarming FAILs when nothing is set up at all.
"""
import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location(
        "ss", _ROOT / "scripts" / "session" / "session-start.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ANTHROPIC = {"provider": "anthropic",
             "tiers": {"claude-haiku-4-5": "low", "claude-sonnet-4-5": "medium"}}


def test_no_providers_yields_no_invented_model():
    routing = _mod().build_routing([])
    assert set(routing.values()) == {""}, f"a model was invented: {routing}"
    assert "claude-sonnet-4-5" not in "".join(routing.values())


def test_no_providers_never_reports_pass():
    m = _mod()
    out = "\n".join(m.validate_routing(m.build_routing([])))
    assert "PASS" not in out, "self-check passed over an unconfigured table"
    assert "UNCONFIGURED" in out


def test_unconfigured_message_says_the_router_is_advisory():
    m = _mod()
    out = "\n".join(m.validate_routing(m.build_routing([])))
    assert "advisory" in out.lower()
    assert out.count("FAIL") == 0


def test_real_provider_still_passes_per_tier():
    m = _mod()
    routing = m.build_routing([ANTHROPIC])
    out = "\n".join(m.validate_routing(routing))
    assert "SIMPLE" in out and "PASS" in out
    assert routing["SIMPLE"] == "anthropic/claude-haiku-4-5"


def test_a_genuinely_missing_tier_still_fails():
    m = _mod()
    out = "\n".join(m.validate_routing(m.build_routing([ANTHROPIC])))
    assert "LOCAL_ONLY" in out and "FAIL" in out, "missing local tier was hidden"


def test_rule_8_guard_still_fires():
    m = _mod()
    out = "\n".join(m.validate_routing(
        {"LOCAL_ONLY": "", "SIMPLE": "anthropic/claude-opus-4-5",
         "MEDIUM": "", "COMPLEX": ""}))
    assert "Rule 8" in out and "PASS" not in out


def test_build_routing_never_returns_opus_or_fable():
    m = _mod()
    for provider in m.CLOUD_PROVIDERS.values():
        for model in provider.get("tiers", {}):
            assert "opus" not in model.lower(), model
            assert "fable" not in model.lower(), model
