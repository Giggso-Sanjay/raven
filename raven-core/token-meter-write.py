#!/usr/bin/env python3
"""
token-meter-write.py — Raven Stop hook v1.0
Reads session transcript JSONL, extracts token usage, calculates costs.
Writes metrics to three files: session JSON, monthly rollup, audit log.
Non-blocking — logs errors but never crashes the session.
"""
import json
import sys
import os
import pathlib
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any

PRICING_FILE = pathlib.Path(__file__).parent / "model-pricing.json"
RAVEN_DIR = pathlib.Path.cwd() / ".raven"
VAULT_DIR = pathlib.Path.home() / "RavenVault"
AUDIT_DIR = RAVEN_DIR / "audit"
CHECKPOINT_FILE = RAVEN_DIR / ".token-meter-checkpoint.json"


def load_checkpoint() -> Dict[str, Any]:
    """Read the last-processed transcript position for this session.

    Stop fires on every turn, not once at true session end — this hook used
    to re-read the WHOLE transcript from line 1 every time and re-add that
    cumulative total into the monthly rollup, so a long session compounded
    its own totals turn after turn (this is what produced e.g. 23,527
    "sessions" and $3,727 in a single day in old rollups). Tracking how far
    we've already read lets each run count only its own NEW usage.
    """
    try:
        if CHECKPOINT_FILE.exists():
            return json.loads(CHECKPOINT_FILE.read_text())
    except Exception:
        pass
    return {"session_id": "", "last_line_index": 0}


def write_checkpoint(session_id: str, last_line_index: int) -> None:
    try:
        RAVEN_DIR.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(json.dumps({
            "session_id": session_id,
            "last_line_index": last_line_index,
            "last_processed_at": datetime.utcnow().isoformat() + "Z",
        }, indent=2))
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write checkpoint: {e}\n")


def load_pricing() -> Dict[str, Dict[str, float]]:
    """Load model pricing from config file."""
    try:
        if PRICING_FILE.exists():
            return json.loads(PRICING_FILE.read_text())["models"]
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to load pricing config: {e}\n")
    return {}


def get_cost(model: str, tokens_in: int, tokens_out: int, pricing: Dict) -> float:
    """Calculate cost in USD for a model + token counts."""
    model_price = pricing.get(model, pricing.get("gpt-4o", {}))
    if not model_price:
        model_price = pricing.get("default", {"input_per_1m": 1, "output_per_1m": 5})

    in_cost = (tokens_in / 1_000_000) * model_price.get("input_per_1m", 1)
    out_cost = (tokens_out / 1_000_000) * model_price.get("output_per_1m", 5)
    return round(in_cost + out_cost, 6)


def is_raven_code(tool_uses: list, skill_uses: list) -> bool:
    """Detect if a message is from Raven infrastructure vs user work."""
    # Check tool_uses for raven-related paths/commands
    for tool in tool_uses:
        if isinstance(tool, dict):
            # Check if bash command references raven
            if "bash" in str(tool).lower():
                cmd = tool.get("input", {}).get("command", "")
                if any(x in cmd for x in [".raven/", "raven-", ".claude/scripts/"]):
                    return True
            # Check file paths
            path = tool.get("input", {}).get("path", "")
            if any(x in path for x in [".raven/", ".claude/scripts/"]):
                return True

    # Check skill_uses for raven skills
    for skill in skill_uses:
        if isinstance(skill, dict):
            name = skill.get("name", "")
            if name.startswith("raven-") or "raven" in name.lower():
                return True

    return False


def parse_transcript(transcript_path: str) -> Dict[str, Any]:
    """Parse JSONL transcript and extract metrics for lines NEW since the
    last checkpoint (delta), not the whole file every time.

    Returns metrics plus "_new_line_count" (total lines in the file right
    now) so the caller can persist the checkpoint after a successful write.
    """
    metrics = {
        "session_id": "",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": "unknown",
        "raven_code": {
            "tokens": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "cost_usd": 0.0,
            "calls": 0,
        },
        "user_work": {
            "tokens": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "cost_usd": 0.0,
            "calls": 0,
        },
        "by_model": {},  # model -> per-model delta usage, feeds the cost log
        "_new_line_count": 0,
    }
    pricing = load_pricing()
    total_in, total_out, total_cache_read, total_cache_creation = 0, 0, 0, 0

    try:
        with open(transcript_path, "r") as f:
            all_lines = f.readlines()

        metrics["_new_line_count"] = len(all_lines)

        # Peek the session_id from any line so we know whether the checkpoint
        # (keyed by session_id) applies to THIS transcript or a prior one.
        checkpoint = load_checkpoint()
        start_index = 0
        for line in all_lines:
            if not line.strip():
                continue
            try:
                peek = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = peek.get("session_id")
            if sid:
                metrics["session_id"] = sid
                if checkpoint.get("session_id") == sid:
                    start_index = min(checkpoint.get("last_line_index", 0), len(all_lines))
                break

        for line in all_lines[start_index:]:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                try:
                    # Extract usage from assistant messages
                    if msg.get("role") == "assistant":
                        usage = msg.get("message", {}).get("usage", {})
                        if not usage:
                            continue

                        model = msg.get("message", {}).get("model", "unknown")
                        metrics["model"] = model
                        if msg.get("session_id"):
                            metrics["session_id"] = msg["session_id"]

                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        cache_read = usage.get("cache_read_input_tokens", 0)
                        cache_creation = usage.get("cache_creation_input_tokens", 0)

                        # Categorize
                        is_raven = is_raven_code(
                            msg.get("message", {}).get("tool_uses", []),
                            msg.get("message", {}).get("skill_uses", []),
                        )
                        bucket = metrics["raven_code"] if is_raven else metrics["user_work"]

                        # Update totals
                        bucket["calls"] += 1
                        bucket["input"] += input_tokens
                        bucket["output"] += output_tokens
                        bucket["cache_read"] += cache_read
                        bucket["cache_creation"] += cache_creation
                        total_in += input_tokens
                        total_out += output_tokens
                        total_cache_read += cache_read
                        total_cache_creation += cache_creation

                        # Calculate cost (cache_read is 0.1x input, cache_creation is 1.25x input)
                        cost = get_cost(model, input_tokens, output_tokens, pricing)
                        cache_read_cost = (cache_read / 1_000_000) * (
                            pricing.get(model, {}).get("input_per_1m", 1) * 0.1
                        )
                        cache_creation_cost = (cache_creation / 1_000_000) * (
                            pricing.get(model, {}).get("input_per_1m", 1) * 1.25
                        )
                        msg_cost = cost + cache_read_cost + cache_creation_cost
                        bucket["cost_usd"] += msg_cost

                        # Per-model delta — one cost-log row per model per turn.
                        # Multiple models appear only when subagents with model
                        # overrides ran this turn; the transcript is the sole
                        # honest source of that signal.
                        pm = metrics["by_model"].setdefault(model, {
                            "tokens_in": 0, "tokens_out": 0,
                            "cache_read": 0, "cache_creation": 0,
                            "cost_usd": 0.0, "calls": 0,
                        })
                        pm["tokens_in"] += input_tokens
                        pm["tokens_out"] += output_tokens
                        pm["cache_read"] += cache_read
                        pm["cache_creation"] += cache_creation
                        pm["cost_usd"] += msg_cost
                        pm["calls"] += 1

                except Exception as e:
                    sys.stderr.write(f"Warning: Failed to parse message: {e}\n")
                    continue

        # Calculate totals
        metrics["tokens"] = total_in + total_out
        metrics["total"] = {
            "tokens": total_in + total_out,
            "input": total_in,
            "output": total_out,
            "cache_read": total_cache_read,
            "cache_creation": total_cache_creation,
            "cost_usd": metrics["raven_code"]["cost_usd"]
            + metrics["user_work"]["cost_usd"],
            "calls": metrics["raven_code"]["calls"] + metrics["user_work"]["calls"],
        }

    except Exception as e:
        sys.stderr.write(f"Warning: Failed to read transcript {transcript_path}: {e}\n")

    return metrics


def write_session_json(metrics: Dict[str, Any]) -> bool:
    """Merge transcript-derived metrics into .raven/.model-session.json.

    model-router.py (UserPromptSubmit hook) also writes this file, using a
    raven_overhead/user_work schema. Overwriting the file wholesale here wiped
    out that data (and vice versa) every other hook call, which is why
    user_work tokens/cost_usd always read back as 0 — the two writers never
    agreed on a shared shape. Read-merge-write instead of replace.
    """
    try:
        RAVEN_DIR.mkdir(parents=True, exist_ok=True)
        session_file = RAVEN_DIR / ".model-session.json"

        try:
            existing = json.loads(session_file.read_text()) if session_file.exists() else {}
        except Exception:
            existing = {}

        overhead = existing.get("raven_overhead", {"tokens": 0, "cost_usd": 0.0, "calls": 0, "by_source": {}})
        user_work = existing.get("user_work", {
            "tokens": 0, "cost_usd": 0.0, "calls": 0,
            "tier_counts": {"SIMPLE": 0, "MEDIUM": 0, "COMPLEX": 0, "LOCAL_ONLY": 0},
            "last_classification": None,
        })

        # Fold this transcript pass's raven_code totals into raven_overhead
        # (transcript-detected Raven-infra calls are overhead too).
        rc = metrics["raven_code"]
        overhead["tokens"] = overhead.get("tokens", 0) + rc["tokens"]
        overhead["cost_usd"] = overhead.get("cost_usd", 0.0) + rc["cost_usd"]
        overhead["calls"] = overhead.get("calls", 0) + rc["calls"]
        overhead.setdefault("by_source", {})

        # Accumulate real transcript-derived usage into user_work — additive,
        # never replaced, so model-router.py's tier_counts/last_classification
        # (written on the next UserPromptSubmit) survive alongside it.
        uw = metrics["user_work"]
        user_work["tokens"] = user_work.get("tokens", 0) + uw["tokens"]
        user_work["cost_usd"] = user_work.get("cost_usd", 0.0) + uw["cost_usd"]
        user_work["calls"] = user_work.get("calls", 0) + uw["calls"]
        user_work.setdefault("tier_counts", {"SIMPLE": 0, "MEDIUM": 0, "COMPLEX": 0, "LOCAL_ONLY": 0})
        user_work.setdefault("last_classification", None)

        merged = {
            "session_started_at": existing.get("session_started_at") or metrics["timestamp"],
            "raven_overhead": overhead,
            "user_work": user_work,
            "providers": existing.get("providers", {}),
            "last_transcript_model": metrics.get("model", "unknown"),
            "last_transcript_write": metrics["timestamp"],
        }

        session_file.write_text(json.dumps(merged, indent=2))
        return True
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write session JSON: {e}\n")
        return False


def _resolve_project_name() -> str:
    """Best-effort project name for per-repo metrics."""
    try:
        man = RAVEN_DIR / "manifest.json"
        if man.exists():
            name = json.loads(man.read_text()).get("project")
            if name:
                return str(name)
    except Exception:
        pass
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if remote:
            return remote.rstrip("/").split("/")[-1].replace(".git", "")
    except Exception:
        pass
    return pathlib.Path.cwd().name


def _bump_sessions(container: Dict[str, Any], session_id: str) -> None:
    """Increment container['sessions'] at most once per distinct session_id.

    Stop fires every turn, so without this a single session's sessions count
    would grow by 1 per turn instead of by 1 total (this is why old rollups
    showed things like 23,527 "sessions" in a single day). Falls back to a
    plain increment only when session_id is unknown/empty.
    """
    if not session_id:
        container["sessions"] = int(container.get("sessions") or 0) + 1
        return
    seen = container.setdefault("_session_ids", [])
    if session_id not in seen:
        seen.append(session_id)
        container["sessions"] = int(container.get("sessions") or 0) + 1


def write_monthly_rollup(metrics: Dict[str, Any]) -> bool:
    """Append/merge into ~/RavenVault/.metrics/YYYY-MM.json (per-project).

    metrics["total"] is now a per-turn DELTA (see parse_transcript's
    checkpoint logic), so summing it across calls is correct — it used to be
    the transcript's cumulative total re-added every turn, which compounded.
    """
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        metrics_dir = VAULT_DIR / ".metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        # Extract YYYY-MM from timestamp
        ts = datetime.fromisoformat(metrics["timestamp"].replace("Z", "+00:00"))
        month_file = metrics_dir / f"{ts.strftime('%Y-%m')}.json"
        project = metrics.get("project") or _resolve_project_name()
        metrics["project"] = project

        # Load existing or init — preserve list-shaped sessions if present
        if month_file.exists():
            try:
                data = json.loads(month_file.read_text())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        data.setdefault("month", ts.strftime("%Y-%m"))
        data.setdefault("year_month", ts.strftime("%Y-%m"))
        data.setdefault("by_day", {})
        data.setdefault("by_project", {})
        data.setdefault("total", {})

        session_id = metrics.get("session_id", "")
        day_key = ts.strftime("%Y-%m-%d")
        tok = int(metrics.get("total", {}).get("tokens", 0) or 0)
        cost = float(metrics.get("total", {}).get("cost_usd", 0) or 0)

        # sessions counter may be int or list — keep both shapes safe
        if isinstance(data.get("sessions"), list):
            pass
        else:
            _bump_sessions(data, session_id)

        # Unscoped by_day (legacy) + nested by_project
        if day_key not in data["by_day"] or not isinstance(data["by_day"].get(day_key), dict):
            data["by_day"][day_key] = {
                "sessions": 0,
                "tokens": 0,
                "cost_usd": 0.0,
                "by_project": {},
            }
        day = data["by_day"][day_key]
        day.setdefault("by_project", {})
        _bump_sessions(day, session_id)
        day["tokens"] = int(day.get("tokens") or 0) + tok
        day["cost_usd"] = float(day.get("cost_usd") or 0) + cost
        pb = day["by_project"].setdefault(
            project, {"sessions": 0, "tokens": 0, "cost_usd": 0.0}
        )
        _bump_sessions(pb, session_id)
        pb["tokens"] += tok
        pb["cost_usd"] += cost

        # Top-level by_project with by_day
        prow = data["by_project"].setdefault(
            project,
            {"sessions": 0, "tokens": 0, "cost_usd": 0.0, "by_day": {}},
        )
        _bump_sessions(prow, session_id)
        prow["tokens"] = int(prow.get("tokens") or 0) + tok
        prow["cost_usd"] = float(prow.get("cost_usd") or 0) + cost
        prow.setdefault("by_day", {})
        pd = prow["by_day"].setdefault(
            day_key, {"sessions": 0, "tokens": 0, "cost_usd": 0.0}
        )
        _bump_sessions(pd, session_id)
        pd["tokens"] += tok
        pd["cost_usd"] += cost

        # Also append a project-tagged row into sessions list if list-shaped.
        # A delta row per turn is still meaningful here since tok/cost are
        # per-turn deltas, not cumulative totals — no double count.
        if isinstance(data.get("sessions"), list):
            data["sessions"].append(
                {
                    "date": day_key,
                    "started_at": metrics.get("timestamp"),
                    "session_id": session_id,
                    "project": project,
                    "sessions": 1,
                    "tokens": tok,
                    "cost_usd": cost,
                }
            )

        data["total"]["tokens"] = int(data["total"].get("tokens") or 0) + tok
        data["total"]["cost_usd"] = float(data["total"].get("cost_usd") or 0) + cost

        month_file.write_text(json.dumps(data, indent=2))
        return True
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write monthly rollup: {e}\n")
        return False


def write_audit_log(metrics: Dict[str, Any]) -> bool:
    """Append to .raven/audit/YYYY-MM-DD.log."""
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)

        ts = datetime.fromisoformat(metrics["timestamp"].replace("Z", "+00:00"))
        log_file = AUDIT_DIR / f"{ts.strftime('%Y-%m-%d')}.log"

        entry = {
            "timestamp": metrics["timestamp"],
            "session_id": metrics.get("session_id", ""),
            "model": metrics.get("model", "unknown"),
            "tokens": metrics["total"].get("tokens", 0),
            "cost_usd": round(metrics["total"].get("cost_usd", 0), 4),
            "raven_calls": metrics["raven_code"].get("calls", 0),
            "user_calls": metrics["user_work"].get("calls", 0),
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return True
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write audit log: {e}\n")
        return False


COST_LOG = RAVEN_DIR / "cost-log.jsonl"


def _read_estimate() -> Optional[Dict[str, Any]]:
    """Pre-turn estimate from model-router's last classification, if any.

    est tokens ≈ prompt_chars/4 input + a nominal 500-token reply, priced at
    the tier model's rates. Clearly an estimate — never merged with computed.
    Returns None when no classification is available; the log row then shows
    est_cost_usd: null rather than a fabricated number.
    """
    try:
        session = json.loads((RAVEN_DIR / ".model-session.json").read_text())
        lc = (session.get("user_work") or {}).get("last_classification") or {}
        model_str = lc.get("model_for_tier", "")
        prompt_chars = lc.get("prompt_chars")
        if not model_str or prompt_chars is None:
            return None
        model = model_str.split("/", 1)[-1]
        pricing = load_pricing()
        est_in = prompt_chars / 4
        est_out = 500
        return {
            "tier": lc.get("tier"),
            "model": model_str,
            "est_cost_usd": get_cost(model, int(est_in), est_out, pricing),
        }
    except Exception:
        return None


def write_cost_log(metrics: Dict[str, Any]) -> bool:
    """Append one row per model actually observed this turn to cost-log.jsonl.

    Honest-accounting rules:
      - Rows exist ONLY for models seen in the transcript delta. Raven's hook
        scripts (triage/architect/model-router/cve-guard) make zero API calls
        and cost $0 — they never get rows. (The old by_source overhead numbers
        were fiction: nothing ever computed them.)
      - "primary" = the model with the most calls in this turn's delta;
        any other model means a subagent ran — tagged "subagent".
      - est_cost_usd is the router's pre-turn guess (may be null);
        computed_cost_usd is real token usage x pricing. Never merged.
      - cum_session_usd / cum_month_usd are running sums of computed cost,
        derived from this same log file — one source of truth.
    """
    by_model = metrics.get("by_model") or {}
    if not by_model:
        return True  # nothing ran this turn — no fake rows

    try:
        RAVEN_DIR.mkdir(parents=True, exist_ok=True)
        session_id = metrics.get("session_id", "")
        month_prefix = metrics["timestamp"][:7]  # YYYY-MM

        cum_session = 0.0
        cum_month = 0.0
        if COST_LOG.exists():
            for line in COST_LOG.read_text().splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                c = float(row.get("computed_cost_usd") or 0)
                if row.get("ts", "").startswith(month_prefix):
                    cum_month += c
                if session_id and row.get("session_id") == session_id:
                    cum_session += c

        estimate = _read_estimate()
        primary_model = max(by_model, key=lambda m: by_model[m]["calls"])

        rows = []
        for model, pm in by_model.items():
            cum_session += pm["cost_usd"]
            cum_month += pm["cost_usd"]
            rows.append({
                "ts": metrics["timestamp"],
                "session_id": session_id,
                "model": model,
                "source": "primary" if model == primary_model else "subagent",
                "tokens_in": pm["tokens_in"],
                "tokens_out": pm["tokens_out"],
                "cache_read": pm["cache_read"],
                "cache_creation": pm["cache_creation"],
                "est_cost_usd": (estimate or {}).get("est_cost_usd"),
                "est_tier": (estimate or {}).get("tier"),
                "computed_cost_usd": round(pm["cost_usd"], 6),
                "cum_session_usd": round(cum_session, 6),
                "cum_month_usd": round(cum_month, 6),
            })

        with open(COST_LOG, "a") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        return True
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write cost log: {e}\n")
        return False


def main() -> None:
    """Read Stop hook stdin, parse transcript, write metrics."""
    try:
        # Read hook input from stdin
        hook_input = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        hook_input = {}

    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path:
        sys.stderr.write("No transcript_path in hook input; skipping metrics\n")
        return

    # Parse transcript — only the delta since the last checkpoint
    metrics = parse_transcript(transcript_path)
    metrics["project"] = _resolve_project_name()
    new_line_count = metrics.pop("_new_line_count", 0)

    # Write all four atomically
    write_session_json(metrics)
    write_monthly_rollup(metrics)
    write_audit_log(metrics)
    write_cost_log(metrics)

    # Only advance the checkpoint after a successful parse, so a transient
    # read failure doesn't silently skip real usage on the next run.
    if metrics.get("session_id"):
        write_checkpoint(metrics["session_id"], new_line_count)

    # Silent on success (hook should be non-blocking)


if __name__ == "__main__":
    main()
