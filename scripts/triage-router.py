#!/usr/bin/env python3
"""
Raven — Triage Router (v4.2)

Deterministic routing: brownfield default = Andie-jr, greenfield default = Andie.

Precedence (mutually exclusive with architect-router — no double-fire):
  1. Force overrides: /andie, /andie-jr always win (T3.1)
  2. Data-only question (explicit keywords, no code change) → direct answer
  3. Architecture-class prompt (decision intent, no symptom) → SILENT here;
     architect-router owns it and routes to Andie
  4. Symptom language (broken/failing/error...) → Andie-jr
  5. Change-to-existing-code verb (fix/update/modify...) + brownfield → Andie-jr
  6. Everything else (plain prompt, no symptom) → Andie (ideation/planning)

Prompt intent is the signal for 4-6 — repo state only qualifies rule 5.
Mid-session escalation to Andie when a bug turns out architectural is
Andie-jr's skill-level handoff contract.

Local-only. No telemetry.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Raven output is emoji-forward and a console/pipe defaults to cp1252 on Windows, so
# print() raises UnicodeEncodeError and any fail-soft wrapper swallows it — the script
# appears to do nothing while having done its work. PYTHONUTF8=1 covers hook
# invocations; this covers being run by hand or by a skill via Bash. BUG-029.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

# Trivial bounded edits — no debug panel needed (matches docs/ROUTING.md
# "rename this variable → neither"). Symptom language still overrides.
_TRIVIAL = re.compile(
    r"^\s*(?:rename|fix\s+(?:a\s+)?typo|typo|reformat|re-?indent|sort\s+imports?|"
    r"bump\s+(?:the\s+)?version|add\s+a\s+comment)\b", re.IGNORECASE)

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from router_common import force_intent, semantic_fallback, log_overhead
except Exception:  # fail-soft: routing still works without the shared helper
    def force_intent(_p): return None
    def semantic_fallback(_p, _k): return False
    def log_overhead(_s, _t): return None


def is_brownfield() -> bool:
    """Return True if repo has git history (existing codebase)."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=".", capture_output=True, timeout=1, text=True
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return count > 1  # more than one commit = brownfield
    except Exception:
        pass
    return False


def is_data_question(prompt: str) -> bool:
    """Return True if this is a pure data/question (no code change expected).

    Keywords: read, explain, show, count, list, how does, what is, find, grep, etc.
    Must NOT mention: build, create, write, fix, change, refactor, implement, deploy.
    """
    if not prompt or len(prompt) < 10:
        return False

    data_keywords = {
        "read", "explain", "show", "count", "list", "what", "where", "when",
        "how does", "find", "grep", "search", "query", "describe", "summarize",
        "tell me", "give me", "what is", "why", "how do i", "can you", "help me understand"
    }
    change_keywords = {
        "build", "create", "write", "fix", "change", "refactor", "implement",
        "deploy", "add", "remove", "delete", "update", "modify", "rewrite"
    }

    prompt_lower = prompt.lower()
    has_data_keyword = any(kw in prompt_lower for kw in data_keywords)
    has_change_keyword = any(kw in prompt_lower for kw in change_keywords)

    return has_data_keyword and not has_change_keyword


_ARCHITECT_MOD = None


def _architect_mod():
    """Load architect-router.py once so its decision/symptom regexes have ONE
    source of truth. Fail-soft: any load error → None (triage keeps its
    repo-state default; worst case is the pre-v4.2 double-fire, never a missed
    route)."""
    global _ARCHITECT_MOD
    if _ARCHITECT_MOD is None:
        try:
            import importlib.util
            path = Path(__file__).resolve().parent / "architect-router.py"
            spec = importlib.util.spec_from_file_location("_architect_router", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _ARCHITECT_MOD = mod
        except Exception:
            _ARCHITECT_MOD = False
    return _ARCHITECT_MOD or None


def is_symptom(prompt: str) -> bool:
    """True if the prompt carries symptom language (broken/failing/timeout...)."""
    mod = _architect_mod()
    return bool(mod and mod.SYMPTOM_NEGATE.search(prompt))


def is_architecture_class(prompt: str) -> bool:
    """True if architect-router would claim this prompt (decision intent, no
    symptom language)."""
    mod = _architect_mod()
    return bool(mod and mod.classify(prompt))


# Change-to-existing-code verbs — with git history present these mean
# "work on what exists", not ideation. Symptom language is the stronger
# andie-jr signal and is checked first.
# Explicit ideation language — always Andie territory, even when the prompt
# also contains question words that would otherwise read as data-only.
_IDEATION = re.compile(
    r"\b(?:brainstorm|idea(?:s|te|tion)?|what\s+if|imagine|"
    r"explore\s+(?:options|ideas|approaches)|concept|ideat\w*)\b",
    re.IGNORECASE)

_EXISTING_CODE_CHANGE = re.compile(
    r"\b(?:fix|debug|patch|update|modify|remove|delete|clean\s*up|"
    r"troubleshoot|investigate)\b", re.IGNORECASE)


def classify(prompt: str) -> Optional[str]:
    """Return 'andie-jr' for issue/existing-code prompts, 'andie' for
    ideation/planning prompts, None when triage should stay silent
    (data-only, trivial, or architect-router owns it)."""
    symptom = is_symptom(prompt)

    if not symptom and _TRIVIAL.match(prompt) and len(prompt.split()) <= 8:
        return None  # trivial bounded edit — no panel needed

    ideation = bool(_IDEATION.search(prompt))

    if is_data_question(prompt) and not symptom and not ideation:
        return None  # direct answer — but symptom/ideation language overrides

    if is_architecture_class(prompt):
        return None  # decision/architecture intent → architect-router routes to Andie

    if ideation and not symptom:
        return "andie"  # explicit ideation language wins over change verbs

    if symptom:
        return "andie-jr"  # issue/bug language = debug mode

    if is_brownfield() and _EXISTING_CODE_CHANGE.search(prompt):
        return "andie-jr"  # change to existing code = debug/fix mode

    return "andie"  # plain prompt, no symptom = ideation/planning mode


def main() -> None:
    """Route based on repo state (brownfield → Andie-jr, greenfield → Andie).

    Order: explicit force (T3.1) → repo state classify → opt-in semantic fallback (T3.2).
    """
    prompt = os.environ.get("PROMPT", "")
    if not prompt:
        try:
            prompt = sys.stdin.read()
        except Exception:
            return

    # T3.1: explicit force always wins
    forced = force_intent(prompt)
    if forced == "andie":
        return  # architect-router owns the andie force path
    if forced == "andie-jr":
        _emit_andie_jr(reason="forced via /andie-jr")
        return

    # Deterministic routing by repo state
    routed_to = classify(prompt)
    if routed_to == "andie-jr":
        _emit_andie_jr()
    elif routed_to == "andie":
        _emit_andie()
    # else: None → data question, or architect-router owns it (no emission)


def _emit_andie_jr(reason: str = "issue/existing-code prompt detected") -> None:
    """Emit [ANDIE-JR REQUIRED] injection + user-visible toaster."""
    emission = (
        "[ANDIE-JR REQUIRED] Issue or existing-code work detected. MANDATORY: invoke "
        "`andie-jr` skill BEFORE any diagnosis, file read, bash command, or "
        "response. Andie-jr structures the debug flow: problem → root cause → "
        "fix → why → audit note.\n"
    )
    _emit(emission, f"🪶 Raven → andie-jr · {reason} · debug flow: triage → root cause → fix")
    log_overhead("triage-router", emission)


def _emit_andie(reason: str = "ideation/planning prompt detected") -> None:
    """Emit [ANDIE REQUIRED] injection + user-visible toaster."""
    emission = (
        "[ANDIE REQUIRED] Ideation/planning prompt detected. MANDATORY: invoke "
        "`andie` skill BEFORE any coding. Andie structures planning: problem → "
        "angles → decisions → plan. Then /andie-jr for implementation.\n"
    )
    _emit(emission, f"🪶 Raven → andie · {reason} · planning flow: problem → angles → plan")
    log_overhead("triage-router", emission)


def _emit(context: str, toast: str) -> None:
    """Write hook JSON: additionalContext for the model + systemMessage toaster
    the user actually sees. The toaster is the visibility contract — Raven never
    routes silently."""
    sys.stdout.write(json.dumps({
        "systemMessage": toast,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        },
    }) + "\n")


if __name__ == "__main__":
    main()
