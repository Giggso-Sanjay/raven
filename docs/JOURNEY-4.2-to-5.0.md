# The Road from v4.2 to v5.0 — What Actually Happened

**Commit range:** `21feff8` → `bb40ee0` (17 commits)
**Version travel:** 4.2.0 → **5.0.0**
**Size:** 106 files touched, +4,758 lines added, −7,495 lines deleted (net: the repo got *smaller*)

This document explains, in plain words, everything that was built in this stretch,
why it was built, and the process that was used.

---

## 1. The one-sentence summary

Raven started this stretch as a tool that **could not prove anything it claimed about itself** —
it reported wrong costs, ran hooks it said it ran but didn't, kept three copies of its own
engine that had silently drifted apart, and claimed four different version numbers at once.

It ended this stretch as a tool where **every claim is machine-checked in CI**, costs are
verified by two independent paths, and there is exactly one canonical copy of everything.

That's the whole story. The rest is detail.

---

## 2. The three phases

| Phase | Commits | What it was about |
|---|---|---|
| **A — Build the money layer** | `78fdfc4` … `964e017` (5) | Token metering, cost dashboard, model routing, code map |
| **B — The Discipline Fix Chain** | `4129672` … `4c3401e` (6) | A planned 6-prompt campaign to fix the repo's honesty problems, then release v5.0.0 |
| **C — Positioning + the Push Gate** | `23373d1` … `bb40ee0` (6) | README repositioning, then a briefing/approval workflow (built hard, then softened) |

---

## 3. Phase A — Building the money layer

### 3.1 `78fdfc4` — Token metering v4.3.0

**Simple version:** Raven learned to count how many tokens you burned and what it cost.

- A `Stop` hook (`token-meter-write.py`) writes per-session tokens and cost to a JSON file,
  rolls it up monthly, and logs it to the audit trail.
- The dashboard got a **tokenomics view** — Raven's own metered cost side-by-side with
  Claude's reported cost, so you can spot when they disagree.
- Added offline SVG icons for the knowledge graph (no CDN, works with no internet).
- New docs: `DASHBOARD.md`, `VIBE-CODER-MAP.md`.

### 3.2 `9de4131` — Stop trusting the current directory

**Simple version:** Scripts were looking for their config files "right here" instead of
"at the top of the repo", so wherever you happened to be standing changed where data landed.

Two bugs, same root cause:
- Three guard scripts wrote a **phantom `guard/guard/.raven/` folder** because they resolved
  `.raven/` as a plain relative path.
- A **stale `.model.env` copy** was routing every model tier to an Ollama *embedding* model —
  a model that can't chat at all.

Fix: all four scripts now walk up to the nearest `.git` folder to find the real repo root.

**Also closed a governance hole:** `session-start.py` was tagging `claude-opus-4-5` as the
auto-picked "high" tier. Setting an API key would have silently started spending Opus money
with nobody asking. Opus was removed from the auto tier table, and **Rule 8** was added to
CLAUDE.md: *never auto-select Opus or Fable — always ask the user first.*

### 3.3 `01d3c0f` — The honest answer about model routing

**Simple version:** Raven wanted to reroute cheap questions to a cheap model. It found out
that isn't possible, and said so instead of faking it.

Claude Code hooks **cannot swap the session model mid-conversation** — `/model` is fixed for
the session. So a real "send this one to Haiku" proxy is not buildable.

What was built instead: on SIMPLE-tier prompts, the router emits an **advisory directive**
suggesting Claude delegate self-contained questions to a Haiku *subagent* via the Agent tool.
Advisory, not enforced — no hook can force tool selection. The commit message says this
out loud rather than pretending otherwise.

### 3.4 `b37f2ba` — The $101,000 bug

**Simple version:** The token meter was adding up your *entire history* every single turn,
so the numbers exploded.

`Stop` fires at the end of **every turn**, not at session end. The meter re-read the whole
transcript each time and re-added the cumulative total. Over a session that compounds —
which is where the absurd **294M tokens / $101K** figures in old monthly rollups came from.

Three fixes in one commit:
- **Checkpoint file** — each run now counts only the *delta* since the last run. Sessions are
  deduplicated by `session_id` instead of incremented per hook call.
- **Schema clash** — `model-router.py` and `token-meter-write.py` were writing *incompatible*
  formats into the same file and clobbering each other every other call. Both now
  read-merge-write instead of overwrite.
- **Dashboard crash** — a pre-existing `SyntaxError` (a backslash inside an f-string
  expression, illegal before Python 3.12) had silently broken the entire dashboard on
  Python 3.11. Fixed, plus `--if-stale MINUTES` so the ~3000-line HTML report isn't rebuilt
  every turn, and the Stop hook now auto-refreshes it so you never have to know the command.

The two corrupted monthly rollups were **archived, not deleted** — moved to
`*.json.corrupted` outside git.

### 3.5 `964e017` — Honest routing UX, Code Map, cost log

Three features in one commit:

**The router that never ran.** `model-router.py` was wired into `UserPromptSubmit` with no
arguments, but `--prompt` was required — argparse exited with code 2 every single turn, and a
trailing `|| true` swallowed the error. **The router had never actually executed from its
hook.** Now it reads the prompt from hook stdin. First prompt of each session discloses the
session model, router ON/OFF state, and the `/router` toggle. New `/router` skill for
on/off/status.

**`raven-xray.py` (new) — the Code Map.** A pure-stdlib code symbol map: parses Python with
`ast`, stores plain JSON (`.raven/xray.json` — *no SQLite*), and answers
callers / callees / impact questions from the CLI. Rebuilt by the Stop hook, throttled with
`--if-stale`. Limitations stated in the tool itself: **Python only, static imports only.**

**The Cost Log.** `.raven/cost-log.jsonl` — one row per model actually observed per turn
(primary and subagent separately), estimated vs computed cost kept apart, with running
session and month totals. Hook scripts make zero API calls and are never logged, so the old
phantom overhead figures stay dead.

---

## 4. Phase B — The Discipline Fix Chain

This is the interesting part, and it deserves an explanation of the **process**, not just
the features.

### 4.1 What the process was

Six numbered prompts, executed in order, each one:

1. Stating a **premise** (what was believed to be wrong)
2. **Investigating** the premise against reality — and *correcting the premise when it was wrong*
3. Making **one explicit decision per mismatch found** (no silent choices)
4. Adding a **CI check that fails the build** if the problem ever comes back
5. **Verifying the check works** by the same three-step ritual every time:
   **PASS clean → deliberately break it → confirm FAIL → restore → confirm PASS**

That last step is the thing that makes this a discipline chain rather than a cleanup.
A fix that isn't guarded by a test that has been *proven to fail* is just a hope.

Notice how often the premise turned out to be **partly wrong**, and was corrected rather
than forced to fit:

- Prompt 1 expected three full triplicate trees — found overlapping sets where only 2 files
  truly diverged.
- Prompt 2 expected a missing hook — found the code existed but the wiring didn't (half-true).
- Prompt 3 expected four config files — found **five**, and the extra one was the worst one.
- Prompt 4's premise named two skills (`andie-ww`, `anthropic-skills:andie`) that **don't
  exist in this repo** — noted and dismissed.
- Prompt 5's premise was **half-stale** — the on-disk symptom was already fixed by `9de4131`,
  but both root causes were still live in the code.

### 4.2 `4129672` — Prompt 1: One engine, not three

**Problem:** the same scripts existed in `scripts/`, `raven-core/`, and `.claude/scripts/`.
Only 2 shared files truly diverged — **but one of them mattered a lot**:
`raven-core/session-start.py` was missing the Rule-8 Opus gate from `9de4131`, meaning the
*distributed* copy of the engine would still auto-tier Opus.

**Resolution:**
- `scripts/` is now **canonical**.
- Every same-named file in the other two trees is a **relative symlink** to `scripts/`.
  (The 17 pre-existing symlinks were **absolute paths** — they broke on any other clone.
  Converted.)
- Files unique to a mirror (`server.py`, `pr-gate.py`, `version-check.py`) stay real —
  they aren't duplicates.
- **CI gate 1:** `check-engine-drift.py` fails on content drift, broken symlinks, or
  absolute symlinks.

### 4.3 `b272f2f` — Prompt 2: Make the docs true (Rule 5)

**Problem:** CLAUDE.md claimed a `PostToolUse` hook running secret-scan and db-guard on every
edit. `settings.json` never wired it. That is a violation of the repo's **own Rule 5**
("no documenting features that do not exist").

**Finding:** `db-guard.py` was *built* for PostToolUse — it reads hook stdin and extracts
`tool_input.file_path` — it was just never connected. The claim was half-true: code existed,
wiring didn't.

**Resolution (one decision per mismatch):**
- `PostToolUse` — **wired for real**: `db-guard.py` + `secret-scan.py --changed-files-only`,
  matcher `Write|Edit|MultiEdit`, async.
- `Stop` row — **doc corrected**: claimed 3 scripts, reality is **7**. Also corrected
  "fires when session ends" to "fires at the end of every turn", which is how Stop actually
  behaves.
- `SessionStart` / `UserPromptSubmit` — verified matching, left alone.
- **CI gate 2:** `check-docs-vs-reality.py` compares CLAUDE.md's Hook Reality table against
  `settings.json` per event and exits non-zero on mismatch.

### 4.4 `1b9df5a` — Prompt 3: One config, generated copies

**Problem:** **five** hook-config files, not the four predicted. The extra one was the worst:
`core/hooks/settings.json` is what the installer deploys into *user projects*, and it wired a
**completely different engine** (PreCompact / Notification / tool-guard / schema-guard, no
routers) than this repo actually runs. **Every downstream install was getting an unmaintained
config.**

**Resolution:**
- `.claude/settings.json` declared **canonical** — chosen empirically, because its hooks
  demonstrably fire every turn.
- The three distribution copies (`hooks/hooks.json`, `plugin/settings.json`,
  `core/hooks/settings.json`) are now **generated** by `scripts/export-hook-configs.py`,
  each stamped with a `_generated` notice. Never hand-edited again.
- One **declared** exception: `plugin/settings.json` keeps a `raven-skill-gate` PreToolUse
  entry (plugin-only). Explicit, documented, not drift.
- The git pre-commit hook is confirmed **intentionally external** (`~/.patronai`) and untouched.
- **CI gate 3:** `raven-config-canon-check` fails on any distribution copy drifting.

**Downstream effect:** user projects installed from this commit forward finally get the same
engine config this repo actually runs.

### 4.5 `79d5dca` — Prompt 4: A registry for 62 skills

**Problem:** 61 skills in `skills/`, 1 in `.claude/skills/`, and `core/skills/` turned out to
be a **35-skill distribution copy** with 4 silently diverged files — same modification times,
different content. Exactly the drift class Prompt 1 killed for scripts.

**Resolution:**
- `skills/MANIFEST.json` — a **generated registry** of all 62 skills (name, paths, owner,
  status, purpose), built by `scripts/build-skill-manifest.py`.
- **Overlaps resolved explicitly**, not quietly:
  - `oci-specialist` → **DEPRECATED**, superseded by `oracle-oci-specialist`. Marked, not deleted.
  - `andie` / `andie-jr` / `andie-guru` / `andie-frames` → **intentional layering**
    (orchestrator / debug arm / explainer / browser tests). Documented as hierarchy.
  - `db-router` → `db-specialist` → per-DB leaves → **intentional layering**, documented per skill.
- The 4 diverged `core/skills` files re-synced from canonical.
- **CI gate 4:** lint fails on unregistered skills, ghost entries, two ACTIVE same-domain
  skills with no layering note, or distribution drift.

### 4.6 `83131cf` — Prompt 5: No embedding models in the router; loud dry-run

**Problem (two latent root causes, even though the on-disk symptom was already fixed):**
- `discover_local()` had **no embedding-model filter**. `pick(free)` took whatever Ollama
  listed first — which is exactly how `nomic-embed-text` once became every tier's "chat" model.
- `notify.py` resolved its secrets path **relative to cwd**. Running from a subdirectory would
  silently fall into dry-run mode just by not finding the file. (Same bug class as `9de4131`.)

**Resolution:**
- Embedding and reranker models (`embed|minilm|bge-|e5-|reranker`) excluded from routing
  candidates entirely.
- `validate_routing()` prints **per-tier PASS/FAIL** at session start — FAILs on embedding
  models, missing models, and Rule-8 violations. Verified against a synthetic bad config
  that correctly failed all three ways.
- `notify.py` path root-anchored via `.git` walk.
- Dry-run is now **loud**: a `DEGRADED … NOTHING WAS ACTUALLY SENT` banner on every attempted
  send, a `--status` probe (PASS/DEGRADED, exit 0/1), and a persistent Notifications status
  line at session start.

Session start now shows **health**, not silence.

### 4.7 `da3caa4` — Prompt 6: Dual-path cost verification

This is the most important idea in the whole chain, so read it slowly.

`b37f2ba` fixed *one* cost bug. Prompt 6 adds the control that catches **the entire bug class**
from ever recurring silently.

- **Path A** (existing): per-turn checkpoint deltas accumulated into `cost-log.jsonl` — the
  aggregation layer, i.e. exactly where the bug lived.
- **Path B** (new, deliberately independent): `full_transcript_totals()` — one dumb pass over
  the entire transcript. No checkpoint, no buckets, no aggregation layer to get wrong.
  **Crucially, it is not shared code called twice** — that would defeat the point.
- On every `Stop`, the two are compared. Variance over 5% writes `verified:false` to
  `.raven/.cost-verify.json` **and** a loud `cost-verify-flag … UNVERIFIED` line into the
  audit log.
- The dashboard shows the verdict: green *"VERIFIED — both paths agree within X%"* or red
  *"UNVERIFIED — paths disagree by X% — treat session figures as suspect."*

**Disagreement is flagged, never silently averaged or hidden.** Averaging two numbers that
disagree produces a third number that is confidently wrong — the design explicitly refuses to
do that.

**Proof it works:** backfilled against the `b37f2ba` scenario. Two correct turns verify at
0.0% variance. Delete the checkpoint (simulating the old compounding behavior) and you get
A = 2×B, 100% variance, `verified:false`, audit flag fired. **The dual-path check would have
caught the original bug on its very first turn.**

### 4.8 `4c3401e` — Release v5.0.0

**Problem:** the repo claimed **four different "current" versions simultaneously** — 4.3.0 in
VERSION/manifest/plugin.json, 4.1.0 in CLAUDE.md/README, 4.0.0 in footers, 3.0 in settings
descriptions.

**Resolution:**
- `raven-core/VERSION = 5.0.0` is the **single canonical version**.
- **`VERSIONLOG.md` (new)** — a roll-up update log with the v5.0.0 feature list and a
  summarized 4.x history. Historical changelogs in `docs/` were left untouched:
  **history is never rewritten.**
- Every current-version claim bumped recursively: CLAUDE.md (root + plugin), README (header,
  zip refs, footer), `plugin/README.md`, `make-plugin.sh`, both `plugin.json` files,
  `.raven/manifest.json`, `dashboard.py`, `raven-init.md`, and settings descriptions
  (regenerated via the Prompt 3 exporter).
- **CI gate 5:** `check-version-consistency.py` — any file claiming a current version that
  disagrees with `raven-core/VERSION` fails the build. Verified with the same
  PASS → planted stale claim → FAIL → PASS ritual.

---

## 5. The five discipline gates (the lasting result of Phase B)

All five run in `.github/workflows/raven-discipline.yml` and all five pass together.

| # | CI job | Fails the build when… |
|---|---|---|
| 1 | `raven-engine-drift-check` | Script trees diverge, symlinks break, or a symlink is absolute |
| 2 | `raven-docs-reality-check` | CLAUDE.md's hook table disagrees with `settings.json` |
| 3 | `raven-config-canon-check` | A distribution config drifts from canonical |
| 4 | `raven-skill-manifest-check` | Unregistered/ghost skills, unexplained overlap, skill drift |
| 5 | `raven-version-consistency-check` | Any file claims a version ≠ `raven-core/VERSION` |

**The pattern to take away:** every fix in this chain shipped with a machine check that was
*proven to fail* before it was trusted. A fix without a failing test is a hope, not a fix.

---

## 6. Phase C — Positioning, and the gate that had to be softened

### 6.1 `23373d1` + `f108d61` — README repositioning

Raven is now defined as the **AI Engineering Control Plane** — routing, guards, verified cost
metering, and persistent team memory in one governed local layer. The first paragraph names
the two problems it solves in plain words:

- **Discipline** — code shipping faster than the thinking behind it.
- **Comprehension debt** — nobody remembering what the AI wrote, or why.

The "Strategic Thinking · Scalable Structure · Security at Source" tagline moved to the
second line, unchanged.

### 6.2 `c8c5c2e` — The Educated Push Gate (hard-enforced version)

**The idea:** every change cycle follows a loop —

1. **Briefing** (≤200 words, bullets) — what will be done, how, what changes. Then stop.
2. **Go-ahead** — user says `go ahead` / `approved` / `GO` / `proceed`.
3. **Execute** — exactly what the briefing said. No scope creep.
4. **Confirmation** (≤150 words, bullets) — what was done, which files changed.
5. **Reset** — any non-approval message clears the flag; next change needs a fresh briefing.

Mechanically enforced by `push-gate.py` (PreToolUse) denying mutations without a fresh
`.raven/.push-approved` flag, and `push-approve.py` (UserPromptSubmit) parsing approvals.
Read-only commands always passed. 1-hour approval TTL. `Lucky` keyword opt-out preserved.

**One design note worth keeping:** flag cleanup lives **only** in `push-approve.py`. A Stop-hook
`rm` was tried and verified (2026-08-07) to **race the approval write and delete fresh
approvals** — Stop hooks execute at next-prompt submission. Never add one back.

### 6.3 `e70c971` — The router that blocked every prompt

A miswired hook called `model-router.py --write-json` **without** `--prompt`. Argparse exited
with code 2, and since it ran on `UserPromptSubmit`, **Claude blocked every single prompt** —
and because stderr was redirected, the UI helpfully reported *"No stderr output."*

Fixed by reading the prompt from hook stdin for `--hook`, `--write-json`, or
`CLAUDE_HOOK_EVENT`; accepting `userMessage`/`message` keys as well as `prompt`; and
**failing soft with exit 0** on empty payloads or unexpected errors. `model-router-hook.py`
hardened the same way.

**Lesson:** a hook on `UserPromptSubmit` that can exit non-zero can lock you out of your own
tool.

### 6.4 `bb40ee0` — Educated Push becomes advisory

The hard gate from `c8c5c2e` **blocked its own diagnostics**:

- `python3 … --status` probes were denied.
- Any command containing `2>/dev/null` was denied — the `[><]` regex counted **stderr
  silencing** as a write.
- **It blocked the very Edit needed to fix itself.**
- Meanwhile its "read-only" allowlist still happily permitted `sed -i` — an actual write.

Per the user's decision — *"educated is educational — it should not block"* — the gate became
advisory:

- The **first mutating action of each session** emits a one-time `systemMessage` reminder of
  the briefing loop, and **allows**. Every later call is silent. **No deny path remains.**
- Marker `.raven/.push-notice-shown`, wiped at SessionStart so the reminder shows once per session.
- `2>` / `2>>` no longer count as mutation.
- CLAUDE.md retitled the section **ADVISORY** — because per **Rule 5**, you do not document
  enforcement that no longer exists.

---

## 7. Everything new, in one table

| Thing | What it does |
|---|---|
| `scripts/raven-xray.py` | Python code symbol map — callers/callees/impact. Plain JSON, no SQLite |
| `scripts/check-engine-drift.py` | CI gate 1 — one canonical script tree |
| `scripts/check-docs-vs-reality.py` | CI gate 2 — docs must match wiring |
| `scripts/export-hook-configs.py` | Generates all distribution hook configs (CI gate 3) |
| `scripts/build-skill-manifest.py` | Generates `skills/MANIFEST.json` (CI gate 4) |
| `scripts/check-version-consistency.py` | CI gate 5 — one version number |
| `.github/workflows/raven-discipline.yml` | Runs all five gates |
| `skills/MANIFEST.json` | Registry of all 62 skills with ownership + overlap notes |
| `VERSIONLOG.md` | Roll-up version update log |
| `.claude/skills/router/` | `/router` on/off/status skill |
| `.claude/scripts/push-gate.py` | Educated Push advisory reminder (PreToolUse) |
| `.claude/scripts/push-approve.py` | Approval parsing (UserPromptSubmit) |
| `.raven/cost-log.jsonl` | Per-model, per-turn cost rows |
| `.raven/.cost-verify.json` | Dual-path cost verdict |
| `.raven/xray.json` | Code map storage |
| `assets/kg-icons/*.svg` | 15 offline knowledge-graph icons |
| `docs/DASHBOARD.md`, `docs/VIBE-CODER-MAP.md` | Dashboard + graph documentation |

---

## 8. The five lessons, if you only remember five things

1. **The `cwd` bug is a bug class, not a bug.** It appeared in guard scripts, `.model.env`,
   and `notify.py`. The fix is always the same: resolve from the repo root by walking to `.git`.
2. **A hook that exits non-zero on `UserPromptSubmit` locks you out of your own tool** —
   and `|| true` or a stderr redirect will hide it from you completely. Fail soft.
3. **Two independent paths beat one careful path.** Dual-path cost verification catches the
   whole bug class, not one instance — precisely *because* Path B shares no code with Path A.
4. **When two measurements disagree, flag it — never average it.** An average of two numbers
   that disagree is a third number that is confidently wrong.
5. **A fix without a check that has been proven to fail is a hope.** Every gate in the
   discipline chain was verified by the same ritual: PASS → break it deliberately → confirm
   FAIL → restore → confirm PASS.

And the meta-lesson running through all of it: **when the premise turns out to be wrong,
correct the premise.** Five of the six discipline prompts started from a belief that reality
partly contradicted. Every time, reality won and the plan was updated — which is why the
result holds.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
