# GAP PROMPT — Skill-Routing Remaining Work (Enterprise Edition)

> Hand this entire prompt to a Claude Code session inside the Raven Enterprise
> repo. It is self-contained: context, what step 1 already shipped, and the
> remaining gaps from the OSS audit that step 1 deliberately left out of
> scope. Source audit: `RAVEN_AUDIT.md` (2026-08-15, OSS repo). Step 1 fix:
> `scripts/skill-resolve.py`, `skills/db-router/SKILL.md`,
> `skills/dynamic-specialist/SKILL.md`.

---

## Context — what already shipped (step 1)

The audit found skill routing scattered across 4 disconnected mechanisms
(`triage-router.py`, `architect-router.py`, `db-router` SKILL.md, implicit
LLM description-matching), with skill-not-found cases failing silently —
no error, no fetch, no log.

Step 1 closed the silent-failure hole only:
- `scripts/skill-resolve.py` — single resolve function against the existing
  `skills/MANIFEST.json`. Exact-name match, then substring match on
  name/purpose. Hit → returns `(name, path)`. Miss → logs a JSONL record to
  `.raven/audit/skill-misses.jsonl` (`ts`, `event`, `keyword`, `caller`).
  A missing manifest logs as its own `manifest_missing` event, distinct
  from a genuine unknown-keyword miss.
- `skills/db-router/SKILL.md` — catch-all row now calls the resolver before
  falling to `dynamic-specialist`.
- `skills/dynamic-specialist/SKILL.md` Step 1 — calls the resolver instead
  of `skill-search.py` for existence checks; `skill-search.py` remains a
  separate, manually-confirmed web-fetch path.

Explicitly **out of scope** for step 1, by design: no auto-fetch, no
validation/sandboxing of fetched skills, no ledger beyond the miss log, and
no fix to the underlying routing duplication across the 4 mechanisms (only
the miss/hit visibility problem was closed).

Two known minor gaps from step 1's own cross-check, already resolved before
this handoff: log schema normalized to `ts`/`event`/`keyword`/`caller`
(previously `timestamp`), and `manifest_missing` is now distinguishable from
`skill_miss`. Do not re-open those — verify they're present, don't redo them.

---

## Remaining gaps (this prompt's scope)

### Gap A — Routing is still scattered across 4 mechanisms, not funneled

`triage-router.py` (Andie vs Andie-jr), `architect-router.py` (decision-intent
detection), `db-router` SKILL.md (DB keyword table), and implicit LLM
description-matching (everything else) still make independent decisions with
no shared entry point. `skill-resolve.py` only sits inside the db-router /
dynamic-specialist path — it is not called by triage-router.py or
architect-router.py, and non-DB curated skills (postgres/redis/oracle aside,
think aws-specialist, k8s-specialist, etc.) never pass through it at all.

**Task:** Decide whether full funneling is worth the risk of breaking native
Claude Code skill-matching (which works via `description:` frontmatter, not
code) before doing anything. If yes: extend `skill-resolve.py`'s manifest
scan to be callable from `raven-core` (the always-active first-layer skill)
as an optional pre-check, logging non-DB misses too. If no: document why
funneling further is not worth it, and close this gap as "PASS — accepted
scope."

### Gap B — No fetch → validate → sandbox → load → ledger pipeline

Per the original audit's item 6 gap table: web fetch exists (`skill-search.py`)
but is manual-only; there is no validation beyond keyword-audit, no sandboxing
of a fetched `SKILL.md` before trust, and no structured ledger (only the miss
log from step 1).

**Task:** Build the pipeline described in `RAVEN_AUDIT.md` Part 1 item 6:
1. Auto-trigger mode for `skill-search.py` on a logged `skill_miss` event
   (read `.raven/audit/skill-misses.jsonl`, do not auto-fetch without a
   human `yes` — this is Enterprise, keep the approval gate from OSS).
2. Stronger validation: YAML frontmatter schema check, `allowed-tools`
   allowlist enforcement, checksum pinning on install.
3. A dry-run/sandbox step for a newly fetched `SKILL.md` before it's trusted
   and copied into `.claude/skills/` or `skills/`.
4. A structured ledger (skill name, source URL, hash, fetched-by,
   approved-by, timestamp) — extend `.raven/audit/` rather than inventing a
   new subsystem; keep the field-naming consistent with the `ts`/`event`
   convention step 1 already normalized to.

Estimate from the original audit: ~7-9 files. Confirm or revise that
estimate once you've read the current `skill-search.py` and `raven-search`
SKILL.md in the Enterprise repo (paths may differ from OSS).

### Gap C — Directory-structure inconsistency (`.claude/skills/` vs `skills/`)

`.claude/skills/` (the directory Claude Code conventionally scans first)
contains only `router/SKILL.md` in the OSS repo; the ~68 real specialists
live at repo-root `skills/`. Check whether Enterprise has the same split.
If any doc claims a single canonical skill directory, correct it (Rule 5 —
no documenting what isn't true). If the split is intentional (e.g. `skills/`
is the source, `.claude/skills/` is a build/symlink target), document that
explicitly instead of leaving it implicit.

### Gap D — `raven-log` skill referenced but not found in-repo

Flagged as unverifiable from the OSS repo alone. In Enterprise, check whether
`raven-log` has real implementation files. If yes, no action — the OSS repo
just doesn't carry it. If no, this may be a genuine Rule-5 violation
(`RAVEN_DISABLED` precedent) — flag to the user, do not silently document it
as working.

---

## Acceptance criteria

- Gap A: either extended funneling shipped with a live test (miss on a
  non-DB keyword now logs), or an explicit written decision to not extend
  further, with reasoning.
- Gap B: pipeline stages B1-B4 each land as a working, independently
  testable piece — do not ship a single monolithic script no one can review.
  Each stage gets a live test (a real fetch attempt, a real validation
  rejection, a real sandbox run, a real ledger entry).
- Gap C: directory-structure reality documented accurately wherever it's
  currently misrepresented, or confirmed already accurate.
- Gap D: verdict delivered — implemented or flagged, not left ambiguous.
- All new/changed files listed explicitly in the final confirmation, per the
  Educated Push contract (briefing → go-ahead → execute → confirmation).
