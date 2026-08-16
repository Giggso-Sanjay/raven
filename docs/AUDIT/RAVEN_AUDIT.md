# Raven-Hub Audit — Skill-Miss Resolution & Version/Extension Awareness

Audit only. No fixes applied. Repo: `/Users/giggso/AntiGravity_Projects/SHAY-ROLLS/CLAUDE/RAVEN`

---

## PART 1 — Skill-Miss Resolution

### 1. Skill registry/loader — **PASS** (exists, but no manifest file — directory-based discovery)

Evidence: `skills/*/SKILL.md` (68 skill dirs, e.g. `skills/postgres-specialist/SKILL.md`), duplicated at `core/skills/*/SKILL.md` and a stale snapshot in `local/backups/plugin-skills-20260604T044330Z/`.

No JSON/YAML manifest enumerates all skills. Registry is implicit — Claude Code's native loader scans `skills/*/SKILL.md` YAML frontmatter (`name`, `description`, `allowed-tools`) and does description-based matching at runtime. `skills/db-router/SKILL.md:8-22` is the one explicit routing table, but covers only databases and routes by name string, not resolved file path. `falkordb` has no dedicated skill dir — it exists only as a sub-mode string inside `graph-db-specialist`'s description.

**Structural inconsistency:** `.claude/skills/` (the directory Claude Code conventionally scans first) contains only `router/SKILL.md`. The real ~68-skill set lives at repo-root `skills/`, duplicated under `core/skills/`.

### 2. Entry points that trigger skill selection — **PARTIAL** — scattered, not one resolve function

Evidence:
- `scripts/triage-router.py:1-19` — routes prompts to Andie vs Andie-jr via regex/symptom detection.
- `scripts/architect-router.py:27-52` — forces Andie load on "DECISION intent" prompts via regex.
- `.claude/scripts/model-router.py:26-79` — classifies prompts into model tiers (unrelated to skill selection).
- `skills/db-router/SKILL.md` — the only DB-specific routing table.
- Native Claude Code description-matching — implicit, not code in this repo.

No `resolve_skill(prompt) -> skill` function exists anywhere (`grep -rn "def resolve"` / `"skill_resolve"` = no hits). Four independent, non-integrated mechanisms decide different things (mode, model tier, DB specialist, everything else via LLM matching). Routing logic is duplicated, not funneled.

### 3. Skill NOT FOUND handling — **MISSING** — no detection/handling code exists

Evidence: no file performs an "does skill X exist" check with a fallback branch. `db-router`'s catch-all (`skills/db-router/SKILL.md:22`, `| anything else | dynamic-specialist |`) is content-routing, not a file-existence check.

Inferred behavior (not directly tested): a miss falls through silently to whatever skill is active, or no skill at all — the LLM answers from general knowledge with no specialist framing and no error surfaced. Silent skip, not a thrown error, not a fetch attempt.

### 4. Web/remote fetch fallback — **PARTIAL** — exists for discovering new skills, not wired to routing misses

Evidence:
- `.claude/scripts/skill-search.py:26-52` — searches `anthropics/skills` + general GitHub, fetches `SKILL.md` (`:54-63`), runs keyword security audit (`:65-84`), installs to `.claude/skills/<name>/SKILL.md` on explicit `yes` (`:86-99`, `:137-162`).
- `skills/raven-search/SKILL.md:1-42` — user-facing wrapper, requires architect approval before install.
- `skills/dynamic-specialist/SKILL.md:118-139` — spawns a search agent for best-practice *knowledge*, not for fetching a `SKILL.md`.

This is developer-invoked and gated by manual `yes/no` — not triggered automatically by a routing miss. Fetch capability exists; it's disconnected from miss-resolution.

### 5. Audit/event logging of skill loads — **MISSING** for skill loads specifically; PARTIAL for adjacent logging

Evidence:
- `.raven/audit/2026-08-15.log` — cost/token telemetry only (`session_id`, `model`, `tokens`, `cost_usd`, `raven_calls`, `user_calls`). No skill name, source, or hash field.
- `skills/task-observer/SKILL.md:1-9,17-31,37-45` — logs corrections/vulnerabilities/patterns to `docs/observations/security_log.md`; no trigger for "skill loaded" or "skill miss".
- `docs/observations/security_log.md` format (`task-observer/SKILL.md:52-63`) includes `Expert used:` / `Search used:` fields — closest thing to a load record, but scoped to `dynamic-specialist` only, and written by LLM discretion, not deterministic code.
- No `raven-log` skill/contract implementation exists anywhere in this repo (`grep -rl "raven-log\|raven_log("` = no hits), despite being listed as an available skill in the environment. Likely lives outside this repo as a plugin — flagged, not confirmed as a Rule-5 violation, since no internal doc in this repo claims it's implemented here.

No hash, source-URL, or fetch-provenance logging exists for skill loading anywhere.

### 6. Gap list for miss → web-fetch → validate → sandbox → load → ledger

| Stage | Current state | Needed | Est. files |
|---|---|---|---|
| Miss detection | None — silent fallthrough | Deterministic resolver (`scripts/skill-resolve.py`) comparing requested keyword vs. `skills/*/SKILL.md` frontmatter | 1 new + 3 wiring edits (CLAUDE.md, db-router, dynamic-specialist) |
| Web fetch | Manual only (`skill-search.py`) | Auto-trigger mode reusing existing `search()`/`fetch_skill_md()` | 1 edit |
| Validate | Keyword-only audit (`skill-search.py:65-84`) | Schema check, allowed-tools allowlist, checksum pinning | 1 new module |
| Sandbox | None | Isolated dry-run before trust (today: direct install to `.claude/skills/`) | 1 new — largest task |
| Load | Native directory scan (implicit) | No change needed if install path is correct | 0 |
| Ledger | Cost-only log; security_log.md is prose | Structured ledger (skill name, source, hash, fetched-by, approved-by, timestamp) | 1 new + 1 edit |

**Total estimate: ~7-9 files**, plus edits to `skills/db-router/SKILL.md` and `skills/dynamic-specialist/SKILL.md` to call the new resolver instead of falling through silently.

---

## PART 2 — Version/Extension Awareness

### 7. postgres-specialist / oracle-db-specialist version handling — **PARTIAL**, asymmetric

**postgres-specialist — MISSING.** `skills/postgres-specialist/SKILL.md` (71 lines). No `SELECT version()`, no `pg_available_extensions`, no runtime probing. Only a fabrication-avoidance disclaimer:
```
67:If a specific version, feature, or edge case is outside built-in knowledge:
68:→ State: "Verifying against latest docs recommended for: [specific item]"
69:→ Never fabricate version-specific behavior
```

**oracle-db-specialist — hardcoded matrix, still no runtime probing.** `skills/oracle-db-specialist/SKILL.md:36-61` has an explicit 19c/21c/23ai capability matrix, e.g.:
```
46:| Property Graph | Basic (PGX) | Basic (PGX) | ✅ SQL/PGQ | 23ai: graph queries in standard SQL |
```
Plus discipline rules:
```
38: Ask the customer's Oracle version FIRST. Features vary significantly across versions.
57: Never recommend 23ai features to a 19c customer without flagging the version gap
58: Always ask: "Which Oracle version and edition (SE2/EE)?" before architecture advice
```
Static hardcoded knowledge + "ask the user" discipline — not runtime probing (no instruction to actually query the target DB).

### 8. Fragment/overlay mechanism — **MISSING**

`find skills/postgres-specialist skills/oracle-db-specialist skills/graph-db-specialist -type f` → one `SKILL.md` each, no subfolders. Oracle's version differences are baked into one flat table; Postgres has no mechanism at all.

**Proposed layout (not implemented):**
```
skills/postgres-specialist/
  SKILL.md                # base, version-agnostic core
  overlays/pg16.md         # PG16-specific syntax
  overlays/pg19-graph.md   # GRAPH_TABLE / SQL:2023 additions
  overlays/README.md       # load rule: match runtime version to overlay file
```
Load rule: base always loads; specialist reads detected/asked version, then optionally reads the matching overlay fragment.

### 9. Runtime capability manifest / context-passing — **PARTIAL** — file-read convention, not structured injection

Evidence:
- `.raven/manifest.json:1-60` — the actual config card: `stack.language`, `stack.db`, `stack.libraries`, `guard.*`. No runtime capability data (no DB version, no extension list).
- `CLAUDE.md:238-249` — boot sequence prose instructs the model to read `manifest.json` if present.
- `README.md:46` — "`.raven/manifest.json` — your project's config card... Andie and the guards read this before doing anything."

The mechanism is the model reading a static JSON file via the Read tool, on the instruction of CLAUDE.md prose — not a hook-injected structured context block, not an env var, not a programmatic manifest passed as tool input. No enforced injection; relies on model compliance with markdown instructions. No field carries runtime capability (DB version/extensions) data.

---

## Rule 5 flags (no undocumented/fictional features)

Per `CLAUDE.md:94`, Rule 5 exists because v4.0.0 documented `RAVEN_DISABLED` and email notifications that weren't implemented.

1. **`raven-log`** — listed as an available skill in the environment's catalog but has zero implementation files inside this repo. Unverifiable from this repo alone whether it's claimed as implemented here (no internal doc found claiming so) — flagged, not confirmed.
2. **Skill-miss auto-fetch pipeline** — not documented as existing, and indeed doesn't exist. Consistent, no violation.
3. **`.claude/skills/` vs `skills/`** — if any doc claims a single canonical skill directory, that claim would be inaccurate given the actual split. Not exhaustively checked against every doc — flagged as speculative, worth a follow-up doc pass.

---

## Summary table

| # | Item | Verdict |
|---|---|---|
| 1 | Skill registry/loader | PASS (implicit, directory-based) |
| 2 | Single resolve funnel | PARTIAL — scattered across 4 mechanisms |
| 3 | Skill-not-found handling | MISSING |
| 4 | Web/remote fetch fallback | PARTIAL — exists, not auto-wired |
| 5 | Skill-load audit logging | MISSING |
| 6 | Gap list for full pipeline | ~7-9 files (see table) |
| 7 | Version/capability probing (PG/Oracle) | PARTIAL — Oracle has static matrix, PG has nothing |
| 8 | Fragment/overlay mechanism | MISSING |
| 9 | Runtime capability manifest passing | PARTIAL — prose convention only |
