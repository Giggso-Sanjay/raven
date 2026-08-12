"""Tests for SYMPTOM_NEGATE's HTTP-status coverage (BUG-020).

A precisely-worded bug report often contains no symptom *word*:
"/api/azure-chat returns 500 ... instead of a clean 4xx" has no
fail/crash/broken/error, so it slipped past both routers in a live session and
Claude had to self-route. Status codes are symptom language for an HTTP service.

The false-positive cases matter as much as the positives: a status code in a
feature request ("returns 200") or a capacity figure ("500 users") must NOT be
read as a symptom, or every design prompt gets dragged to andie-jr.
"""
import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).parent.parent


def _architect():
    spec = importlib.util.spec_from_file_location(
        "_architect_router", _ROOT / "scripts" / "architect-router.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SYMPTOMS = [
    "/api/azure-chat returns 500 when AZURE_OPENAI_KEY is unset instead of a clean 4xx",
    "the endpoint gives a 502 on cold start",
    "the api responds with 401 for valid tokens",
    "handler throws 503 under load",
    "we get a 4xx on every retry",
]

NOT_SYMPTOMS = [
    "add a health check that returns 200",
    "we serve 500 users per day",
    "design a caching layer",
    "should the four endpoints share one rate limiter or one per route?",
    "return 201 on successful creation",
]


def test_http_status_reports_are_symptoms():
    negate = _architect().SYMPTOM_NEGATE
    for prompt in SYMPTOMS:
        assert negate.search(prompt), f"should be symptom: {prompt!r}"


def test_status_codes_in_non_symptom_context_are_ignored():
    negate = _architect().SYMPTOM_NEGATE
    for prompt in NOT_SYMPTOMS:
        assert not negate.search(prompt), f"false positive: {prompt!r}"


def test_word_based_symptoms_still_match():
    """Guard the pre-existing patterns — the BUG-020 fix must be additive."""
    negate = _architect().SYMPTOM_NEGATE
    for prompt in ("login is broken", "it keeps timing out", "throws a TypeError",
                   "the worker crashed", "why is the build failing"):
        assert negate.search(prompt), f"regression: {prompt!r}"


if __name__ == "__main__":
    test_http_status_reports_are_symptoms()
    test_status_codes_in_non_symptom_context_are_ignored()
    test_word_based_symptoms_still_match()
    print("ok")
