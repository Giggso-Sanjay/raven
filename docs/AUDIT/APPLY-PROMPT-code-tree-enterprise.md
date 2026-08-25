# APPLY PROMPT — Raven Code Tree (Enterprise Edition)

> Hand this entire prompt to a Claude Code session inside the Raven Enterprise
> repo. It is self-contained: motivation, architecture, file-by-file spec,
> acceptance criteria, and guard rails. Designed 2026-08-14 in the Raven OSS
> repo (see `.raven/audit/2026-08-14.log`, feature `code-tree`).

---

## Context — why this exists

The current memory/graph pipeline is lossy and irrelevant:
conversation → LLM summary → markdown session note → wikilink scan →
force-directed graph. The result is a hairball of date-string nodes
(`2026-08-08-aryx`) orbiting one project hub, with boilerplate summaries not
tied to any commit or ask. Four lossy hops, zero navigable structure.

The replacement inverts it: **the codebase itself is the skeleton** — a
deterministic JSON tree built from AST + paths + docstrings + git — and all
memory (commit "whys", session touches, decisions) is **annotation pinned to
the exact tree node it describes**. No LLM in the pipeline. Sessions become
highlights on code nodes, not free-floating graph nodes.

Three properties are non-negotiable:
1. **Deterministic** — AST/paths/git only; same repo state → same tree.
2. **Delta-updated** — only changed files re-parsed; full rebuild is rare.
3. **Force-fed** — hook-injected context guarantees every session reads it;
   the model never gets to "choose" to consult memory.

---

## Deliverable 1 — `scripts/code-tree.py` (builder + delta updater)

Single script, three modes:

### `--build` (full scan)
- Walk the repo (respect `.gitignore`; skip `node_modules`, `__pycache__`,
  `.git`, binary files).
- For each Python file: parse with `ast` — module docstring → `purpose`
  (first line, ≤120 chars), top-level `functions`/`classes` (names only),
  `imports` (local modules only, resolved to node ids).
- For non-Python source (js/ts/sh/md/yaml): `purpose` from first comment/
  heading line; no function extraction in v1 (leave `functions: []`).
- Classify `role` from a mapping table (extend as needed):
  `*-guard.py → guard`, `*-router.py → router`, `hooks/ or settings.json
  hook entry → hook:<Event>`, `.claude/skills/**/SKILL.md → skill`,
  `scripts/ → script`, entry points from manifest → `entrypoint`.
  Read the hook table from `.claude/settings.json` — a file wired to a hook
  event gets `role: "hook:<EventName>"`.
- Git enrichment per file: last N=5 conventional commits touching it →
  `history: [{commit, kind, scope, why, date}]` parsed from
  `type(scope): subject`; non-conventional messages → `kind: "other"`,
  `why: subject verbatim`. Plus `churn_30d` (commit count, 30 days).
- Output `.raven/code-tree.json`:
  ```json
  {
    "version": 1,
    "generated_at": "<iso>",
    "repo": "<name>",
    "root": {
      "id": "<repo>", "type": "project", "children": [
        {"id": "scripts", "type": "module", "role": "engine", "children": [
          {"id": "scripts/code-tree.py", "type": "program",
           "role": "script", "purpose": "...", "functions": [...],
           "imports": [...], "history": [...], "churn_30d": 2,
           "sessions": ["2026-08-14-raven"]}
        ]}
      ]
    }
  }
  ```
- Node `id` = repo-relative path (stable key for delta patching).
- Cap `history` at 5 entries and `sessions` at 10 per node (older data lives
  in git — the tree is state, not archive; this keeps it constant-size).

### `--delta` (incremental, called from hooks)
- Inputs: `--files f1 f2 …` (or read changed files from
  `git diff --name-only HEAD~1` + `git status --short` if omitted), optional
  `--session YYYY-MM-DD-<project>`, optional `--commit <sha>`.
- Re-parse ONLY the named files; patch their nodes in place (create nodes for
  new files, tombstone `"deleted": true` for removed ones — prune on next
  full build). Append commit why + session id to touched nodes.
- Must complete <1s for typical deltas; fail-soft (any exception → exit 0
  with stderr note, never break a hook chain — match `obsidian-log.py`).

### `--digest` (context payload)
- Print a ≤1,500-token markdown digest to stdout:
  - one-line repo shape (top modules + roles + counts),
  - top 10 nodes by `churn_30d` with their latest `why` line,
  - nodes with empty `purpose` (discipline signal — "no purpose statement"),
  - footer: `Full tree: .raven/code-tree.json — read the relevant subtree
    before editing a file.`
- Add `--for-prompt "<user prompt text>"`: additionally print the full JSON
  of any node whose id/basename appears in the prompt (per-turn relevance
  injection; cap 3 nodes / ~900 tokens).

## Deliverable 2 — Hook wiring (the ALWAYS mechanism)

- **SessionStart**: append `python3 scripts/code-tree.py --digest` to the
  existing session-start chain. Its stdout is force-injected into context —
  this is the guarantee; no model compliance involved.
- **UserPromptSubmit**: after the router chain, run
  `code-tree.py --digest --for-prompt "$PROMPT" --nodes-only` so prompts
  naming a file get that node's memory injected that turn.
- **Stop**: before `obsidian-log.py`, run `code-tree.py --delta --session
  <today>-<project>` (async, fail-soft, like the rest of the Stop chain).
- **git post-commit** (or extend the existing pre-commit wrapper's success
  path): `code-tree.py --delta --commit HEAD` so the why lands at commit
  time even without a Claude session.
- Closed loop: session end writes the tree → next session start is forced to
  read it. Constant-size digest keeps the injected prefix stable → prompt
  caching keeps recurring cost near zero.

## Deliverable 3 — Dashboard visualization

Replace the force-directed graph panel in `dashboard.py --html` with a tree
view rendered from `.raven/code-tree.json` (keep the old graph behind a
toggle for one release, then remove):

- Collapsible tree (nested `<details>` is fine in v1 — no d3/physics):
  indentation = containment, color chip = role (guard red, hook blue,
  router amber, skill violet, script gray), badge = `churn_30d`,
  `purpose` as the subtitle line, latest `why` beneath it.
- Click node → side panel: purpose, full `history`, `sessions`, imports.
- Session timeline scrubber: selecting a session id highlights the nodes
  whose `sessions` contain it (sessions are overlays, never nodes).
- Empty-purpose nodes get a visible ⚠ "no purpose statement" marker.
- Self-contained HTML, no CDN (Enterprise runs air-gapped), light/dark safe.

## Deliverable 4 — Enterprise integration

- **Hub telemetry**: on `--delta`, queue a signal (existing Hub signal path)
  with `{repo, nodes_changed, commits, session}` — fleet-level "which
  components are hot this week" rollups come from these.
- **CLAUDE.md contract rule** (append, don't rewrite): "Before editing any
  file, consult its node in `.raven/code-tree.json` (digest injected at
  session start). After structural changes, the Stop hook updates the tree —
  never hand-edit `code-tree.json`."
- **Guard rails**: tree writer must never read `.env` /
  `manifest.secrets.json`; purpose/why fields are pulled from code and
  commits only — run the secret-scan patterns over the digest output as a
  belt-and-braces check before printing.
- **Rule 8 compliance**: no LLM calls anywhere in this pipeline — so no
  model-selection surface at all. Keep it that way; an optional LLM backfill
  for missing purposes must be a separate, explicitly user-invoked command
  (`code-tree.py --backfill-purposes`, asks before running).

## Acceptance criteria

1. `--build` on the Raven repo completes <10s, produces valid JSON, every
   `scripts/*.py` node has non-empty `purpose` (they all have docstrings).
2. `--delta --files scripts/dashboard.py` completes <1s and changes only
   that node (diff the JSON to prove it).
3. `--digest` output ≤1,500 tokens (measure with any tokenizer; chars/4 ok).
4. New session shows the digest in injected context; a prompt naming
   `model-router.py` gets that node injected on that turn.
5. Dashboard tree renders, collapses, highlights a selected session's nodes.
6. Kill -9 during `--delta` leaves the previous JSON intact (write to temp
   file + atomic rename — required).
7. All scripts fail-soft: no hook chain ever breaks because of the tree.

## Out of scope (v1)

- Cross-language call graphs; non-Python function extraction.
- LLM narrative extraction (session stories stay in RavenVault notes, linked
  from node side panels by session id).
- Multi-repo federation (Hub rollup signal is the seam for it later).
