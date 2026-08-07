#!/usr/bin/env python3
"""
Model Router v1 — Dynamic Model Routing for Raven

Classifies user queries and context into tiers (SIMPLE, MEDIUM, COMPLEX, LOCAL_ONLY)
based on signal detection, and outputs routing decision to .raven/.model-session.json.

Usage:
  - Library: from model_router import classify
    tier, score, reasons, model = classify(prompt, context)

  - CLI: python3 model-router.py --prompt "..." [--context "{...}"]
"""

import argparse
import json
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict


# Signal definitions (keywords, weights)
SECURITY_KEYWORDS = {
    "vuln", "vulnerability", "cve", "exploit", "auth", "authentication",
    "token", "jwt", "oauth", "injection", "sql", "xss", "csrf", "credential",
    "secret", "password", "key", "cipher", "encrypt", "decrypt", "hash",
    "breach", "attack", "malicious", "threat", "vulnerability"
}

ARCHITECTURE_KEYWORDS = {
    "design", "schema", "database", "migrate", "migration", "refactor",
    "refactoring", "plan", "tradeoff", "architecture", "pattern",
    "structure", "class", "interface", "module", "component", "system",
    "api", "endpoint", "route", "handler", "service", "layer"
}

REASONING_KEYWORDS = {
    "compare", "which", "approach", "pros", "cons", "tradeoff", "should",
    "recommendation", "best", "optimal", "efficient", "trade-off",
    "advantage", "disadvantage", "alternative"
}


def _score_signal(prompt: str, context: str) -> Tuple[int, List[str]]:
    """
    Score the prompt and context on signal presence.

    Returns:
        (total_score, list_of_reasons)
    """
    score = 0
    reasons = []

    # Combine prompt and context for searching
    combined = f"{prompt} {context}".lower()

    # Security keywords (+3)
    for keyword in SECURITY_KEYWORDS:
        if keyword in combined:
            score += 3
            reasons.append(f"security_keyword:{keyword}")
            break  # Count once per category

    # Architecture keywords (+3)
    for keyword in ARCHITECTURE_KEYWORDS:
        if keyword in combined:
            score += 3
            reasons.append(f"architecture_keyword:{keyword}")
            break  # Count once per category

    # Reasoning keywords (+3)
    for keyword in REASONING_KEYWORDS:
        if keyword in combined:
            score += 3
            reasons.append(f"reasoning_keyword:{keyword}")
            break  # Count once per category

    # Multi-file scope (+2): references to multiple files
    file_count = len(re.findall(r'\b[a-z_]+\.(py|ts|js|go|java|rs|sql)\b', prompt))
    if file_count >= 3:
        score += 2
        reasons.append(f"multi_file_scope:{file_count}_files")
    elif "across the codebase" in prompt.lower() or "across" in prompt.lower():
        score += 2
        reasons.append("multi_file_scope:across_codebase")

    # Test/doc generation (+1)
    if any(x in prompt.lower() for x in ["write test", "write tests", "write unit test", "write unittest", "document", "docstring", "generate test"]):
        score += 1
        reasons.append("test_or_doc_generation")

    # Debugging with stack trace (+1)
    if "traceback" in combined or "error:" in combined or "failed" in combined:
        score += 1
        reasons.append("debugging_with_error")

    # Single-file bounded edit (-1): "fix typo", "rename variable", etc.
    if any(x in prompt.lower() for x in ["fix typo", "rename", "what does", "what is", "return"]):
        if not any(x in prompt.lower() for x in ["across", "multiple", "several"]):
            score = max(0, score - 1)
            reasons.append("single_file_bounded_edit")

    return score, reasons


def _detect_secrets(context: str) -> bool:
    """
    Detect if secrets or sensitive credentials are present in context.

    FORCE → LOCAL_ONLY if true.
    """
    # Check for common secret patterns
    secret_patterns = [
        r'manifest\.secrets',
        r'\.env',
        r'SECRET_KEY\s*=',
        r'API_KEY\s*=',
        r'password\s*=',
        r'token\s*=',
        r'private\s+key',
        r'-----BEGIN',
        r'-----END',
    ]

    context_lower = context.lower()
    for pattern in secret_patterns:
        if re.search(pattern, context_lower, re.IGNORECASE):
            return True

    # Check for credential markers in context
    if any(x in context for x in ['PRIVATE', 'SECRET', '-----BEGIN']):
        return True

    return False


def _find_project_root() -> Path:
    """Walk up from cwd to the nearest .git directory. Falls back to cwd."""
    d = Path.cwd()
    for candidate in [d, *d.parents]:
        if (candidate / ".git").is_dir():
            return candidate
    return d


def _load_model_env() -> Dict[str, str]:
    """
    Load .model.env and extract tier → model mapping.

    Actual format (written by session-start.py):
        [routing]
        LOCAL_ONLY = ollama/dolphin-mistral:latest
        SIMPLE     = ollama/dolphin-mistral:latest
        MEDIUM     = anthropic/claude-sonnet-4-5
        COMPLEX    = anthropic/claude-opus-4-5

    Returns {tier: "provider/model"} dict
    """
    # Check project-local first (resolved via repo root, not cwd), then home.
    model_env_path = _find_project_root() / ".model.env"
    if not model_env_path.exists():
        model_env_path = Path.home() / ".model.env"

    # Opus and Fable are intentionally excluded from these defaults — the
    # router must never auto-select either; escalation requires an explicit
    # user ask regardless of tier or score.
    defaults = {
        "SIMPLE": "anthropic/claude-haiku-4-5",
        "MEDIUM": "anthropic/claude-sonnet-5",
        "COMPLEX": "anthropic/claude-sonnet-5-high",
        "LOCAL_ONLY": "ollama/dolphin-mistral",
    }

    if not model_env_path.exists():
        return defaults

    models = {}
    in_routing = False

    try:
        with open(model_env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue

                # Detect [routing] section
                if line == "[routing]":
                    in_routing = True
                    continue
                elif line.startswith("["):
                    in_routing = False
                    continue

                # Parse TIER = provider/model within [routing]
                if in_routing and "=" in line:
                    key, val = line.split("=", 1)
                    tier = key.strip()
                    model_str = val.strip()
                    if tier in ("LOCAL_ONLY", "SIMPLE", "MEDIUM", "COMPLEX"):
                        models[tier] = model_str
    except Exception as e:
        print(f"Warning: Failed to parse .model.env: {e}", file=sys.stderr)

    # Fill missing tiers with defaults
    for tier, default_model in defaults.items():
        if tier not in models:
            models[tier] = default_model

    return models


def classify(
    prompt: str,
    context: str = ""
) -> Tuple[str, int, List[str], str]:
    """
    Classify a query into tier: SIMPLE, MEDIUM, COMPLEX, LOCAL_ONLY.

    Args:
        prompt: User query text
        context: Additional context (e.g., previous messages, file content)

    Returns:
        (tier, score, reasons, model_string)
    """
    # Force LOCAL_ONLY if secrets detected
    if _detect_secrets(context):
        return "LOCAL_ONLY", 999, ["secrets_in_context"], "local_only"

    # Score the query
    score, reasons = _score_signal(prompt, context)

    # Assign tier based on score
    if score >= 6:
        tier = "COMPLEX"
    elif score >= 3:
        tier = "MEDIUM"
    else:
        tier = "SIMPLE"

    # Load model config and get model for this tier
    models = _load_model_env()
    model_string = models.get(tier, "anthropic/claude-sonnet-4-5")

    return tier, score, reasons, model_string


def write_session_json(tier: str, score: int, reasons: List[str], model: str, prompt: str, source: str = "user_work") -> Path:
    """
    Write classification result to .raven/.model-session.json.

    Two-bucket schema:
      - raven_overhead: tokens from Raven internals (hooks, skill loads, banners)
      - user_work: tokens from the user's actual prompt + Claude's response

    Default source = user_work (this is the typical case — Claude is responding
    to a user prompt). When called from a hook context that's purely overhead,
    pass --source raven_overhead.

    Returns:
        Path to written file
    """
    raven_dir = Path.cwd() / ".raven"
    raven_dir.mkdir(exist_ok=True)

    session_file = raven_dir / ".model-session.json"

    # Load existing or init two-bucket schema
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text())
        except Exception:
            data = {}
    else:
        data = {}

    # Backfill missing schema keys only — never reset keys that already hold
    # real data. token-meter-write.py (Stop hook) may have already populated
    # user_work.tokens/cost_usd from actual transcript usage; wiping the file
    # here on every UserPromptSubmit call would erase that real data (this was
    # the root cause of user_work always reading back as 0 tokens/$0).
    data.setdefault("session_started_at", datetime.utcnow().isoformat() + "Z")
    data.setdefault("raven_overhead", {"tokens": 0, "cost_usd": 0.0, "calls": 0, "by_source": {}})
    data.setdefault("user_work", {
        "tokens": 0,
        "cost_usd": 0.0,
        "calls": 0,
        "tier_counts": {"SIMPLE": 0, "MEDIUM": 0, "COMPLEX": 0, "LOCAL_ONLY": 0},
        "last_classification": None,
    })
    data["user_work"].setdefault("tier_counts", {"SIMPLE": 0, "MEDIUM": 0, "COMPLEX": 0, "LOCAL_ONLY": 0})
    data.setdefault("providers", {})

    # Update the appropriate bucket
    bucket = data[source] if source in ("user_work", "raven_overhead") else data["user_work"]
    bucket["calls"] += 1
    if source == "user_work":
        bucket["tier_counts"][tier] = bucket["tier_counts"].get(tier, 0) + 1
        bucket["last_classification"] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user_query_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "tier": tier,
            "score": score,
            "reasons": reasons,
            "model_for_tier": model,
            # prompt length feeds the cost-log's pre-turn estimate column
            # (est tokens ≈ chars/4) — the hash alone can't reconstruct size
            "prompt_chars": len(prompt),
        }

    # Write atomically
    try:
        session_file.write_text(json.dumps(data, indent=2))
        return session_file
    except Exception as e:
        print(f"Error writing {session_file}: {e}", file=sys.stderr)
        raise


ROUTER_STATE_FILE = ".router-state.json"


def _router_state_path() -> Path:
    return _find_project_root() / ".raven" / ROUTER_STATE_FILE


def load_router_state() -> Dict:
    try:
        p = _router_state_path()
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return {"mode": "default", "session_id": "", "announced": False}


def save_router_state(state: Dict) -> None:
    try:
        p = _router_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"Warning: failed to write router state: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Classify query into model tier (SIMPLE/MEDIUM/COMPLEX/LOCAL_ONLY)"
    )
    parser.add_argument("--prompt", default=None, help="User query text (optional in --hook mode: read from stdin)")
    parser.add_argument("--context", default="", help="Additional context (JSON or text)")
    parser.add_argument("--write-json", action="store_true", help="Write result to .raven/.model-session.json")
    parser.add_argument("--hook", action="store_true",
                        help="UserPromptSubmit hook mode: emit hook JSON with a "
                             "user-visible systemMessage toaster instead of raw JSON")
    parser.add_argument("--source", default="user_work",
                        choices=["user_work", "raven_overhead"],
                        help="Attribution bucket: user_work (default) or raven_overhead")
    parser.add_argument("--enable", action="store_true", help="Turn router mode ON (delegation directives active)")
    parser.add_argument("--disable", action="store_true", help="Turn router mode OFF (session default model only)")
    parser.add_argument("--status", action="store_true", help="Show router mode and state")

    args = parser.parse_args()

    # Mode toggles — used by the /router skill, not the hook
    if args.enable or args.disable or args.status:
        state = load_router_state()
        if args.enable:
            state["mode"] = "router"
            save_router_state(state)
            print("🔀 Raven router: ON — SIMPLE prompts will carry a delegation "
                  "directive (Haiku subagent via Agent tool). The primary session "
                  "model is unchanged — Claude Code has no per-turn model swap.")
        elif args.disable:
            state["mode"] = "default"
            save_router_state(state)
            print("Raven router: OFF — all prompts run on the session's default model.")
        else:
            print(json.dumps(load_router_state(), indent=2))
        return 0

    # Hook mode gets prompt + session_id from stdin (Claude Code hook payload).
    # This was the fatal wiring bug: settings.json invokes this script with no
    # arguments, and --prompt used to be required=True — argparse exited 2 on
    # every single UserPromptSubmit and `|| true` swallowed it, so the router
    # never actually ran from the hook. stdin is the only channel the hook has.
    hook_session_id = ""
    if args.hook and args.prompt is None:
        try:
            payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
        except Exception:
            payload = {}
        args.prompt = payload.get("prompt", "") or ""
        hook_session_id = payload.get("session_id", "") or ""

    if args.prompt is None:
        parser.error("--prompt is required outside --hook mode")

    # Method B inference — if called from a hook context, override to overhead
    # CLAUDE_HOOK_EVENT is set by Claude Code when a hook fires
    if os.environ.get("CLAUDE_HOOK_EVENT") and args.source == "user_work":
        # Still default to user_work because the user prompt IS user work,
        # even though model-router runs from a hook. The hook FIRES it but
        # the work being classified IS the user's. Leave as user_work.
        pass

    # Classify
    tier, score, reasons, model = classify(args.prompt, args.context)

    # Persist the classification in hook mode too — the cost log's pre-turn
    # estimate column reads last_classification from .model-session.json, so
    # a hook run that classifies but never records would starve it.
    if args.write_json or args.hook:
        session_file = write_session_json(tier, score, reasons, model, args.prompt, source=args.source)
        if args.write_json:
            print(f"# Written to {session_file} (bucket: {args.source})", file=sys.stderr)

    if args.hook:
        # Hook mode: one-line toaster the user actually sees + context for the
        # model. Raven never routes silently.
        #
        # IMPORTANT PLATFORM CONSTRAINT: this hook cannot swap the primary
        # session model — Claude Code has no per-turn model override. SIMPLE
        # tier is instead surfaced as a DELEGATION directive: Claude should
        # consider answering via a Haiku subagent (Agent tool) rather than
        # inline, when the question is self-contained (no dependency on prior
        # conversation turns, no file reads/tool calls needed). This is
        # advisory, not enforced — Claude may still answer directly if
        # delegating would lose necessary context.
        state = load_router_state()
        router_on = state.get("mode") == "router"

        # First prompt of a NEW session: disclose the session model and offer
        # the router, instead of silently classifying. The hook cannot see
        # which model the session runs on (Claude Code doesn't expose it here)
        # — but Claude knows its own model, so the disclosure is delegated to
        # Claude via additionalContext.
        if hook_session_id and hook_session_id != state.get("session_id"):
            state["session_id"] = hook_session_id
            state["announced"] = True
            save_router_state(state)
            mode_word = "ON" if router_on else "OFF"
            print(json.dumps({
                "systemMessage": f"🪶 Raven · model disclosure due — router is {mode_word}",
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": (
                        "[RAVEN MODEL DISCLOSURE — first prompt of this session] "
                        "Before answering, tell the user in 2-3 sentences: "
                        "(1) which model this session is running on (state your own model name — the session default set via /model); "
                        f"(2) Raven's model router is currently {mode_word}. When ON, prompts classified as simple carry an advisory directive to delegate to a cheaper Haiku subagent via the Agent tool — the primary session model NEVER changes (Claude Code has no per-turn model swap; do not claim otherwise); "
                        "(3) they can say /router to enable it, /router off to disable, /router status to check. "
                        "Then answer their prompt normally."
                    ),
                },
            }))
            return 0

        # Router OFF (default): stay silent — no toast, no delegation nudges.
        # The one exception is the secrets guard: LOCAL_ONLY still warns,
        # because that's a security signal, not a routing preference.
        if not router_on and tier != "LOCAL_ONLY":
            return 0

        if tier == "LOCAL_ONLY":
            toast = "🔒 Raven router · secrets detected → LOCAL_ONLY · cloud subagents blocked, local model only"
        elif tier == "SIMPLE":
            toast = f"🔀 Raven router · SIMPLE → consider delegating to {model} (Agent tool) instead of answering inline"
        else:
            why = ", ".join(r.split(":", 1)[0] for r in reasons[:2]) or "no strong signals"
            toast = f"🔀 Raven router · {tier} → {model} · {why}"

        if tier == "SIMPLE":
            delegation_note = (
                f"RAVEN_MODEL_TIER=SIMPLE. This question scored as simple/factual. "
                f"Consider delegating it to a Haiku subagent via the Agent tool "
                f"(model: haiku) instead of answering inline, IF AND ONLY IF the "
                f"question is fully self-contained — no dependency on prior "
                f"conversation context, no file reads, no tool calls needed. "
                f"If it depends on this conversation's context or requires tools, "
                f"answer directly as normal; delegation is advisory, not forced."
            )
        else:
            delegation_note = (
                f"RAVEN_MODEL_TIER={tier}. Subagents spawned this turn should "
                f"use tier {tier} ({model}). "
                + ("SECRETS DETECTED: do NOT spawn cloud agents; local model only."
                   if tier == "LOCAL_ONLY" else
                   "Use this tier's model when spawning subagents.")
            )

        print(json.dumps({
            "systemMessage": toast,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    delegation_note
                ),
            },
        }))
        return 0

    print(json.dumps({
        "tier": tier,
        "score": score,
        "reasons": reasons,
        "model": model,
        "source": args.source,
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
