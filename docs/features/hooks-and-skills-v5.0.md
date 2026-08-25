# Hooks & Skills — v4.2.0 → v5.0.0

**Commit range:** `21feff8ade393d70d4581154f635f488ecea9672` → `bb40ee05bc5e7124adc44b82eeafed53ec07033c` (17 commits)
**Canonical config:** `.claude/settings.json` — distribution copies are generated, never hand-edited
**Written per** `CLAUDE.md` Rule A. Every claim below is sourced to a commit and verified against the config on disk.

---

## 1. What & why

This range turned Raven's hook layer from **claimed** into **wired**. At `21feff8` the routing
layer did not exist as a runnable hook at all, one hook had never once executed, and the
`PostToolUse` guards described in CLAUDE.md were never registered. By `bb40ee0` every hook in the
table below is registered, fires, and is machine-checked in CI.

Two events are **new** in this range (`PostToolUse`, `PreToolUse`). One skill is new (`/router`).
One registry file is new (`skills/MANIFEST.json` — a registry, not a skill).

---

## 2. Skills introduced

### 2.1 `/router` 

| | |
|---|---|
| **Path** | `skills/router/SKILL.md` (was `.claude/skills/` until BUG-030 — a project-local dir the plugin loader never reads, so no install could invoke `/router`) |
| **Introduced** | `964e017` — *feat(router,xray,costlog): honest model routing CX, Code Map, per-model cost log* |
| **Entry point** | Slash command `/router`, `/router off`, `/router status` |
| **Backing script** | `scripts/model-router.py --enable` / `--disable` / `--status` |
| **State** | `.raven/.router-state.json` — persists until toggled |

**What it's for.** Claude Code **cannot swap the session model mid-conversation** — `/model` is
fixed for the session, so a real "send this one to Haiku" proxy is not buildable. Rather than fake
it, the router emits an **advisory note** on prompts it classifies as SIMPLE, suggesting Claude
delegate fully self-contained questions to a Haiku subagent via the Agent tool. `/router` makes
that behaviour visible and user-switchable.

The skill's own instructions are explicit about the limit — *"The primary session model NEVER
changes… Never claim the router reroutes the main conversation."* That honesty is the feature; the
alternative was a routing claim the tool could not honour.

- **ON** — SIMPLE-tier prompts arrive with a delegation nudge. Advisory only: no hook can force
  tool selection.
- **OFF** (default) — no nudges. The secrets guard (`LOCAL_ONLY` warning) stays active either way.

### 2.2 `skills/MANIFEST.json` — the ownership registry

| | |
|---|---|
| **Path** | `skills/MANIFEST.json` (generated — never hand-edit) |
| **Generator** | `scripts/build-skill-manifest.py` |
| **Introduced** | `79d5dca` — *feat(skills): ownership registry, overlap resolutions, distribution-drift lint* |
| **Guarded by** | CI gate 4 — `raven-skill-manifest-check` |
| **Scanned dirs** | `skills/` (61) · `.claude/skills/` (1) · `core/skills/` (35, distribution mirror) |

#### What problem it solves

Before this, 62 skills existed with **no record of who owned them or how they related**. Two
concrete symptoms:

1. **`core/skills/` had silently diverged.** It's a 35-skill distribution copy, and 4 files had the
   *same modification times but different content* — the exact drift class `4129672` had just
   killed for scripts.
2. **Overlapping skills with no stated intent.** Nothing distinguished "these two overlap by
   accident" from "these two are a deliberate hierarchy". `oci-specialist` and
   `oracle-oci-specialist` were real duplication; `andie` and `andie-jr` were not — but the repo
   couldn't tell you which was which.

The registry makes every skill accountable: name, paths, owner, status, purpose, and — where skills
overlap — an **explicit resolution**.

#### Record shape

A plain entry:

```json
"raven-core": {
  "name": "raven-core",
  "paths": ["skills/raven-core"],
  "owner": "raven-core-team",
  "status": "active",
  "purpose": "Use when writing code, adding imports, creating files, committing,"
}
```

A resolved-overlap entry — note `domain`, `superseded_by`, and a human `note`:

```json
"oci-specialist": {
  "name": "oci-specialist",
  "paths": ["skills/oci-specialist"],
  "owner": "raven-core-team",
  "status": "deprecated",
  "purpose": "Use for any OCI (Oracle Cloud) question. Assumes Larry Ellison persona...",
  "domain": "oci",
  "superseded_by": "oracle-oci-specialist",
  "note": "Generic OCI persona superseded by the Oracle-family suite."
}
```

Current state: **62 skills — 61 active, 1 deprecated, 13 carrying a `domain`.**

#### The `OVERRIDES` table — decisions, not observations

Overlap resolutions live in an `OVERRIDES` dict in the generator, so they are reviewed as code
rather than hand-typed into generated JSON. Every entry is a decision someone made:

| Cluster | Resolution |
|---|---|
| **OCI** | Genuine duplication → `oci-specialist` **deprecated**, `superseded_by: oracle-oci-specialist`. **Marked, not deleted** — history is not rewritten. |
| **Andie** | Intentional layering. `andie` = front-door orchestrator; `andie-jr` = brownfield debug arm, *"receives handoffs, never orchestrates"*; `andie-guru` = on-demand explainer, *"never auto-loaded"*; `andie-frames` = browser testing with andie packed inside. |
| **DB** | Intentional layering, three tiers. `db-router` = pure routing table, *"zero content"* → `db-specialist` = universal orchestrator → leaves (`postgres`, `oracle-db`, `graph-db`, `vector-db`, `redis`), each marked *"Leaf specialist under db-specialist routing."* |

#### The four lint rules (gate 4)

`--check` fails the build on any of:

| Rule | Failure message | Catches |
|---|---|---|
| 1 | `UNREGISTERED skill` | A skill dir exists with no manifest entry — someone added a skill without registering it |
| 2 | `GHOST manifest entry` | A manifest entry whose skill dir is gone — stale registry |
| 3 | `AMBIGUOUS OVERLAP in domain 'X'` | Two **active** skills share a `domain` and at least one lacks a `layering` note. Deprecate one or declare the hierarchy — silence is not an option |
| 4 | `DISTRIBUTION DRIFT` | `core/skills/<n>/SKILL.md` differs byte-for-byte from `skills/<n>/SKILL.md`, or has no canonical source |

Rule 3 is the interesting one: it does not forbid overlap, it forbids **unexplained** overlap. Two
skills in one domain are fine if you say why.

#### ⚠️ `--lint` is not a flag — use `--check`

The script parses arguments by bare membership test (`if "--check" in sys.argv`). Anything else
falls through to the **write** path and silently regenerates the manifest, exit 0:

```bash
python3 scripts/build-skill-manifest.py --lint    # was: silently REGENERATED the manifest
```

A "lint" invocation that writes can launder real drift into a green run. Fixed post-range —
unknown args now exit 2 with usage. See `bug-fix-log.md` **BUG-006**. The CI step is titled "Skill
manifest **lint**" while the flag is `--check`, which is exactly how the wrong guess happens.

#### How to verify

```bash
python3 scripts/build-skill-manifest.py --check
# → raven-skill-manifest-check: PASS — 62 skills registered, overlaps resolved, no distribution drift
```

#### Known limits

- **Registers the source tree, not the artifact.** Gate 4 validates `skills/` against
  `MANIFEST.json`; it says nothing about what the packaged plugin bundles.
- **`owner` is a constant** (`raven-core-team`) for every skill. The field exists and is enforced,
  but per-skill ownership is not yet real.
- **`purpose` is a truncated first line** from `SKILL.md`, so some entries end mid-sentence (see
  `raven-core` above).

> **Note on skill counts.** `claude plugin details` reports **73** skills for the packaged plugin.
> That is `61 skills/ + 12 commands/` rendered under a single heading — the 12 `commands/*.md` are
> slash-command wrappers that pair 1:1 with a skill of the same name. It is a display artifact, not
> duplicate registration; `core/skills/` is packaged but never registered. See `bug-fix-log.md`
> **BUG-008** (logged, then reclassified NOT-A-BUG).

---

## 2A. Educated Push — the discipline loop

The flagship feature of this range, and the one most often misunderstood, because it was built
hard-enforced and then deliberately softened one commit later.

| | |
|---|---|
| **Scripts** | `.claude/scripts/push-gate.py` (PreToolUse) · `.claude/scripts/push-approve.py` (UserPromptSubmit) |
| **Introduced** | `c8c5c2e` — hard-enforced (PR #24) |
| **Softened** | `bb40ee0` — advisory, no deny path |
| **State files** | `.raven/.push-approved` · `.raven/.push-mode` · `.raven/.push-notice-shown` |

### What the name means

**"Push"** = pushing changes into your codebase. **"Educated"** = you are told what is coming, in
plain words, before it happens. The premise: AI writes code faster than a human can think about it,
so create a pause where Claude explains itself *before* touching anything and summarizes *after*.

### The loop it teaches

```
1. BRIEFING     WHAT will be done, HOW it works, WHAT changes
                (files, db, config).  ≤200 words, bullets.  Then STOP.
   ↓
2. GO-AHEAD     User replies "go ahead" / "approved" / "GO" / "proceed"
   ↓
3. EXECUTE      Exactly what the briefing said. No scope creep.
   ↓
4. CONFIRM      What was done + which files changed.  ≤150 words, bullets.
   ↓
5. RESET        Any later message that is not an approval clears the flag,
                so the next change needs a fresh briefing.
```

The word limits are the mechanism, not decoration — they force a summary that gets read instead of
a wall of text that gets skipped.

### What it actually does today

**Nothing blocking.** Since `bb40ee0` it emits **one** `systemMessage` reminder on the first
mutating action of a session, then stays silent, and allows everything:

```bash
$ grep -o '"permissionDecision": "[a-z]*"' .claude/scripts/push-gate.py | sort -u
"permissionDecision": "allow"      # the only value present — zero deny paths
```

It is a **teaching aid, not a guardrail**. Recorded decision (2026-08-07):
*"educated is educational — it should not block."* Per Rule 5, the CLAUDE.md section was retitled
**ADVISORY** — you do not document enforcement that no longer exists.

### Why the hard version lasted exactly one commit

`c8c5c2e` denied any mutation without a fresh `.raven/.push-approved` flag. It broke itself four
ways:

- `python3 … --status` diagnostic probes → **denied**
- Any command containing `2>/dev/null` → **denied**, because the `[><]` regex counted *silencing
  stderr* as a write
- **It blocked the very Edit needed to fix itself** — the decisive one
- Meanwhile its "read-only" allowlist still permitted `sed -i`, which is an actual write

A gate that denies your debugging tools while permitting a real file mutation is not strict, it is
miscalibrated. `bb40ee0` also stopped counting `2>` / `2>>` as mutation.

### ⚠️ The landmine: never clean the flag from a `Stop` hook

Cleanup of `.push-approved` lives **only** in `push-approve.py`. A `Stop`-hook `rm` was tried and
verified (2026-08-07) to **delete fresh approvals** — because `Stop` hooks execute at *next-prompt
submission*, so it raced the approval write and deadlocked the session.

```bash
# invariant: push-approved must never appear under Stop
python3 -c "import json;h=json.load(open('.claude/settings.json'))['hooks'];\
print(any('push-approved' in x.get('command','') for g in h['Stop'] for x in g.get('hooks',[])))"
# → False
```

`SessionStart` clearing it is correct. `Stop` is not. Never add one back.

### Failure history worth knowing

Three separate defects traced to this feature after the range closed:

- **It did not ship in the plugin.** `hooks/hooks.json` declared no `PreToolUse` at all, so every
  install lacked the feature the release is named for, while `push-gate.py` sat in the package
  unwired (`bug-fix-log.md` **BUG-004**).
- **A dict merge silently dropped it** from `plugin/settings.json` even after regeneration —
  `{**hooks, **PLUGIN_EXTRA_HOOKS}` *replaces* the shared `PreToolUse` key instead of appending
  (**BUG-013**). This is what CI gate 6 now guards.
- **The Enterprise port guide is stale.** Its Prompt 5 is pinned to `c8c5c2e` and instructs
  "wire PreToolUse **deny** logic / expect deny" — which cannot pass against current OSS `main`.

---

## 2B. `raven-xray.py` — the Code Map

| | |
|---|---|
| **Path** | `scripts/raven-xray.py` (321 lines, pure stdlib) |
| **Introduced** | `964e017` |
| **Storage** | `.raven/xray.json` (map) · `.raven/xray-stamp.json` (stats) — **plain JSON, no SQLite** |
| **Rebuilt by** | `Stop` hook, `--build --if-stale 15`, async |
| **Root anchoring** | `find_project_root()` walks up to `.git` — never `cwd` |

### What problem it solves

**Comprehension debt** — nobody remembering what the AI wrote, or why. When code arrives faster
than anyone reads it, the question that matters is not "what does this function do" but *"what
breaks if I change it."* The Code Map answers that from the CLI.

Deliberate non-choices, stated in the tool's own docstring: *"Not a port of any external tool… no
tree-sitter, no native binary, no database."* It parses Python with stdlib `ast` and stores plain
JSON — human-readable, diffable, grep-able, and consistent with every other Raven store.

### CLI surface

| Flag | Question it answers |
|---|---|
| `--build` | (Re)build the map |
| `--if-stale MINUTES` | Skip the build if the map is younger than N minutes (silent skip) |
| `--callers NAME` | Who calls this function/method? |
| `--callees NAME` | What does this function/method call? |
| `--impact NAME` | **Blast radius** — who is affected if this changes? |
| `--max-hops N` | Impact query depth (default 3) |
| `--status` | Map stats |

### Live output from this repo

```bash
$ python3 scripts/raven-xray.py --status
{
  "generated_at": "2026-08-12 11:42:23",
  "nodes": 565,
  "edges": 752,
  "files": 77,
  "scope": "python-only, static-import-resolution-only"
}

$ python3 scripts/raven-xray.py --callers build_graph
_load_or_build_graph  (scripts\dashboard.py:1442)
main                  (scripts\knowledge_graph.py:192)
test_golden_vault     (tests\test_knowledge_graph.py:35)

$ python3 scripts/raven-xray.py --impact find_project_root --max-hops 2
Impact of changing 'find_project_root' — 3 symbol(s) within 2 hop(s):
  main                (scripts\session-start.py:613)
  notify_status_line  (scripts\session-start.py:403)
  write_model_env     (scripts\session-start.py:412)
```

`--impact` is a breadth-first walk **over callers** — it answers "what breaks", which is the
opposite direction from `--callees`.

### Storage schema

Top-level keys: `generated_at` · `scope` · `nodes` · `edges` · `files` · `imports`.

```json
"nodes": {
  "agent\\scripts\\model-router-hook.py:_run_classifier:19": {
    "name": "_run_classifier", "type": "function",
    "file": "agent\\scripts\\model-router-hook.py", "line": 19
  }
},
"edges": [
  { "src": "...:_run_classifier:19", "dst": "...:run:26", "rel": "calls" }
]
```

Node IDs are `file:name:line`. Writes go to a `.json.tmp` then `replace()` — atomic, so a killed
`Stop` hook cannot leave a half-written map.

### ⚠️ Read the limits before trusting an answer

Stated up front in the docstring, and they are **not theoretical** — here is one visible in real
output from this repo:

```bash
$ python3 scripts/raven-xray.py --callees build_map
now                (raven-core\registry\raven-register.py:33)     ← WRONG
iter_python_files  (scripts\raven-xray.py:56)
parse_file         (scripts\raven-xray.py:128)
```

`build_map` calls a local `now()`, but call edges resolve on **unqualified name, first definition
wins**, so the resolver bound it to an unrelated `now()` in a different file. That is the documented
ambiguity, not a bug — and it means **cross-file edges can be false positives**.

| Limit | Consequence |
|---|---|
| **Python only** | No JS/TS/other languages. Frontend is invisible. |
| **Static imports only** | `importlib`, string dispatch, decorator-registered handlers are unresolved — `ast` alone cannot see them without executing the code |
| **Unqualified-name matching** | First definition wins; same-named functions in different files produce false edges (see above) |
| **One map per project root** | No cross-repo / monorepo support |
| **Excluded dirs** | `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`, `env`, `.raven`, `dist`, `build`, `.mypy_cache`, `.pytest_cache` |

Treat `--impact` as a **starting list to verify**, not a proof of completeness. It over-reports on
common names and under-reports on dynamic dispatch.

### How to verify

```bash
python3 scripts/raven-xray.py --build && python3 scripts/raven-xray.py --status
# expect a JSON stamp with non-zero nodes/edges/files
python3 scripts/raven-xray.py --callers <a function you know is called>
```

Unknown flags are **ignored with a warning** rather than fatal (`parse_known_args`) — a deliberate
fail-soft choice, because this runs from a hook where a non-zero exit is expensive.

---

## 3. Hooks — what is wired at `bb40ee0`

All five events, exactly as they exist in canonical `.claude/settings.json`. Every command uses a
dual-fallback form (`.claude/scripts/X || scripts/X || true`), which is why script names appear
twice in raw greps — that is one entry, not two.

### 3.1 `SessionStart` — a new session opens

| Script | Args | Timeout | Async |
|---|---|---|---|
| `session-start.py` | — | 10s | no |
| `vault-load.py` | `--hook` | 5s | no |
| *(flag reset)* | `rm -f .raven/.push-mode .raven/.push-approved .raven/.push-notice-shown` | 5s | no |

Brownfield/greenfield detection, model tiers, manifest check, vault digest. Synchronous on
purpose — the session banner depends on it. The `rm -f` entry (added `c8c5c2e`) resets Educated
Push state so the mode question and the one-time reminder happen once per session.

### 3.2 `UserPromptSubmit` — every user message

| Order | Script | Args | Timeout |
|---|---|---|---|
| 1 | `triage-router.py` | — | 10s |
| 2 | `architect-router.py` | — | 10s |
| 3 | `model-router.py` | `--hook` | 10s |
| 4 | `cve-prompt-guard.py` | — | 10s |
| 5 | `push-approve.py` | — | 5s |

Runs in order: symptom-class triage → architecture routing → model-tier advisory → prompt-time CVE
check → approval parsing. `push-approve.py` (added `c8c5c2e`) is the **sole cleaner** of
`.push-approved`.

> **This event is the most dangerous place in Raven.** A non-zero exit here can lock you out of
> your own tool — see §4.3 and §4.5. Every script on this event must fail soft.

### 3.3 `PreToolUse` — **new in `c8c5c2e`**

| Matcher | Script | Timeout |
|---|---|---|
| `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | `push-gate.py` | 5s |

Educated Push. **Advisory as of `bb40ee0`**: one `systemMessage` reminder on the first mutating
action of a session, silent thereafter, and it always returns `allow` — there is no deny path.
See §4.6 for why the hard version was reversed.

### 3.4 `PostToolUse` — **new in `b272f2f`**

| Matcher | Script | Args | Async |
|---|---|---|---|
| `Write\|Edit\|MultiEdit` | `db-guard.py` | — | yes |
| `Write\|Edit\|MultiEdit` | `secret-scan.py` | `--changed-files-only </dev/null` | yes |

DB discipline and secret scanning after every file write. Async — advisory, never blocks the edit.
Hard blocking remains at the git pre-commit gate.

### 3.5 `Stop` — end of **every turn**

| Script | Args |
|---|---|
| `token-meter-write.py` | — |
| `token-guard.py` | — |
| `dashboard.py` | `--html --current-project --if-stale 15` |
| `raven-xray.py` | `--build --if-stale 15` |
| `obsidian-log.py` | — |
| `knowledge-extract.py` | `--quiet` |
| `session-gate.py` | — |

All seven async. **`Stop` fires at the end of every turn, not at session end** — the single most
consequential misunderstanding in this range (§4.4). The `--if-stale 15` throttles exist because
rebuilding a ~3000-line HTML report every turn is waste.

### 3.6 Not a Claude Code hook

| Hook | Path | Action |
|---|---|---|
| `pre-commit` | `.git/hooks/pre-commit` → `~/.patronai/pre_commit_hook.sh` | Secrets + CVE + style gate + `notify.py` |

Intentionally **external** to this repo (`1b9df5a`) and untouched. There is no `PostEdit` and no
`PreCommit` event in Claude Code — those names in pre-v5.0 docs were aspirational fiction.

---

## 4. Hook evolution, commit by commit

Verified by reading `.claude/settings.json` at each commit.

| Commit | SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | Stop |
|---|---|---|---|---|---|
| `21feff8` (before) | vault-load | **raw string** | — | — | 4 scripts |
| `78fdfc4` | +session-start | **4 routers (real array)** | — | — | +session-gate |
| `964e017` | | | — | — | +dashboard, +raven-xray |
| `b272f2f` | | | — | **created** (2) | |
| `c8c5c2e` | +flag reset | +push-approve | **created** (1) | | |
| `bb40ee0` | | | *behaviour only* | | |

### 4.1 `78fdfc4` — the routing layer was not a hook

At `21feff8`, `UserPromptSubmit` was a bare string:

```json
"UserPromptSubmit": "andie --auto --mode=detect"
```

Claude Code expects an array of matcher groups. **A string is not a runnable hook** — the entire
Andie routing layer was inert config. `78fdfc4` replaced it with a real 4-script array and added
`session-start.py` (previously absent from `SessionStart` entirely) plus `session-gate.py` to
`Stop`.

### 4.2 `9de4131` — the `cwd` bug class, and Rule 8

Three guard scripts wrote a phantom `guard/guard/.raven/` folder because they resolved `.raven/`
as a plain relative path; a stale `.model.env` copy routed every tier to an Ollama **embedding**
model that cannot chat. Both are the same root cause: resolving from `cwd` instead of the repo
root. All four scripts now walk up to the nearest `.git`.

Also closed a governance hole: `session-start.py` tagged `claude-opus-4-5` as the auto-picked
"high" tier, so setting an API key would silently start spending Opus money. Opus was removed from
the auto table and **Rule 8** added: *never auto-select Opus or Fable — always ask first.*

### 4.3 `964e017` — the hook that had never run

`model-router.py` was wired into `UserPromptSubmit` **with no arguments**, but `--prompt` was
required. Argparse exited code 2 every single turn, and a trailing `|| true` swallowed it.

> **The router had never once executed from its hook.** It was wired, documented, and dead.

Fixed by reading the prompt from hook stdin (`--hook`). Also added the `/router` skill (§2.1),
`raven-xray.py` (Code Map: pure-stdlib `ast` parse, plain JSON, **Python only, static imports
only**), and `.raven/cost-log.jsonl`.

### 4.4 `b37f2ba` — `Stop` fires every turn

The token meter re-read the whole transcript each turn and re-added the cumulative total, because
`Stop` was assumed to mean "session end". Compounded over a session, that produced the
**294M tokens / $101K** figures in old rollups. Three fixes: a checkpoint file so each run counts
only its delta; a read-merge-write fix for two scripts writing incompatible schemas to one file;
and a pre-existing `SyntaxError` (backslash inside an f-string expression, illegal before Python
3.12) that had silently broken the entire dashboard on 3.11.

### 4.5 `b272f2f` — `PostToolUse` created (Rule 5)

CLAUDE.md claimed a `PostToolUse` hook running secret-scan and db-guard on every edit.
`settings.json` never wired it — a violation of the repo's **own Rule 5**. `db-guard.py` was
already *built* for the event (it reads hook stdin and extracts `tool_input.file_path`); only the
wiring was missing. The claim was half-true: code existed, wiring didn't.

Same commit corrected the `Stop` row from 3 scripts to the real **7**, and "fires when session
ends" to "fires at the end of every turn".

### 4.6 `c8c5c2e` → `bb40ee0` — `PreToolUse` created, then softened

`c8c5c2e` created the event with a **hard-enforced** gate: `push-gate.py` denied mutations without
a fresh `.raven/.push-approved` flag. `bb40ee0` reversed the enforcement because the gate blocked
its own diagnostics:

- `python3 … --status` probes were denied.
- Any command containing `2>/dev/null` was denied — the `[><]` regex counted **stderr silencing**
  as a write.
- **It blocked the very Edit needed to fix itself.**
- Its "read-only" allowlist still permitted `sed -i` — an actual write.

Per the user's decision — *"educated is educational — it should not block"* — the gate became
advisory. Marker `.raven/.push-notice-shown`, wiped at SessionStart. **No deny path remains.**

**One design note worth keeping:** flag cleanup lives **only** in `push-approve.py`. A Stop-hook
`rm` was tried and verified (2026-08-07) to **race the approval write and delete fresh
approvals** — because Stop hooks execute at next-prompt submission. Never add one back.

### 4.7 `e70c971` — the router that blocked every prompt

A miswired hook called `model-router.py --write-json` **without** `--prompt`. Argparse exited 2,
and because it ran on `UserPromptSubmit`, **Claude blocked every single prompt** — and since
stderr was redirected, the UI reported *"No stderr output."*

Fixed by reading the prompt from stdin for `--hook` / `--write-json` / `CLAUDE_HOOK_EVENT`,
accepting `userMessage` / `message` keys as well as `prompt`, and **failing soft with exit 0** on
empty payloads or unexpected errors.

> **Lesson:** a hook on `UserPromptSubmit` that can exit non-zero can lock you out of your own
> tool — and `|| true` or a stderr redirect will hide it from you completely. Fail soft.

---

## 5. Fixes introduced, by commit

| Commit | Type | Fix |
|---|---|---|
| `78fdfc4` | feat | Token metering v4.3.0; `UserPromptSubmit` becomes a real hook; tokenomics dashboard view; offline SVG graph icons |
| `9de4131` | fix | `.raven/` + `.model.env` anchored to repo root (`.git` walk); Opus/Fable removed from auto tiers (**Rule 8**) |
| `01d3c0f` | feat | SIMPLE-tier Haiku-subagent delegation directive — advisory, stated as such |
| `b37f2ba` | fix | Token-meter compounding ($101K bug); schema clash between two writers; dashboard f-string `SyntaxError`; `--if-stale` |
| `964e017` | feat | Router reads hook stdin (**had never run**); `/router` skill; `raven-xray.py` Code Map; per-model cost log |
| `4129672` | fix | `scripts/` canonical, mirrors become **relative** symlinks (17 were absolute, broken on any other clone) · **CI gate 1** |
| `b272f2f` | fix | `PostToolUse` wired for real; `Stop` docs corrected (3→7 scripts, per-turn) · **CI gate 2** |
| `1b9df5a` | fix | One canonical hook config; 3 distribution copies **generated**; the installer had been shipping a different engine · **CI gate 3** |
| `79d5dca` | feat | 62-skill ownership registry; overlaps resolved explicitly · **CI gate 4** |
| `83131cf` | fix | Embedding/reranker models blocked from routing; per-tier PASS/FAIL self-check at session start; `notify.py` root-anchored; loud dry-run banner |
| `da3caa4` | feat | Dual-path cost verification — two independent computations, divergence flagged, **never averaged** |
| `4c3401e` | release | v5.0.0; single canonical version (repo had claimed **four** at once) · **CI gate 5** |
| `23373d1`, `f108d61` | docs | Positioned as the AI Engineering Control Plane |
| `c8c5c2e` | feat | Educated Push Gate — `PreToolUse` created, hard-enforced |
| `e70c971` | fix | `model-router.py` never blocks `UserPromptSubmit`; fail soft with exit 0 |
| `bb40ee0` | fix | Educated Push becomes advisory — one-time reminder, no deny path |

### 5.1 The CI gates these fixes installed

| # | Job | Fails the build when… |
|---|---|---|
| 1 | `raven-engine-drift-check` | Script trees diverge, symlinks break, or a symlink is absolute |
| 2 | `raven-docs-reality-check` | CLAUDE.md's hook table disagrees with `settings.json` |
| 3 | `raven-config-canon-check` | A distribution config drifts from canonical |
| 4 | `raven-skill-manifest-check` | Unregistered/ghost skills, unexplained overlap, skill drift |
| 5 | `raven-version-consistency-check` | Any file claims a version ≠ `raven-core/VERSION` |

Every gate was verified by the same ritual: **PASS → break it deliberately → confirm FAIL →
restore → confirm PASS.** A fix without a check proven to fail is a hope, not a fix.

> A sixth gate, `raven-distribution-coverage-check`, was added **after** this range while auditing
> it. Gate 3 compares generated copies against what the exporter *would* generate, so it cannot
> catch a bug in the exporter itself. Gate 6 checks the same invariant by reading the JSON
> directly, sharing no code with the generator. See `bug-fix-log.md` BUG-011 and BUG-013.

---

## 6. Failure modes

| Condition | Behaviour |
|---|---|
| Hook script missing | `|| true` fallback — hook is a no-op, session continues |
| `UserPromptSubmit` script errors | **Must** exit 0. Non-zero blocks the prompt (§4.7) |
| `PreToolUse` `push-gate.py` | Always `allow`. No deny path since `bb40ee0` |
| `PostToolUse` guard fires | Async advisory; never blocks the edit |
| `Stop` script slow | Async; `--if-stale 15` throttles the expensive rebuilds |
| Secrets file missing | `notify.py` dry-run — logs intent, does not block the commit |
| Non-ASCII output on a legacy Windows console | `UnicodeEncodeError` can kill a hook. Scripts printing emoji must `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` — see `bug-fix-log.md` BUG-014 |

---

## 7. How to verify

```bash
# every gate plus the suite, one command (added post-range)
python3 scripts/check-all-gates.py --tests        # expect: PASS — all 7 checks green

# docs match wiring — the Rule 5 gate
python3 scripts/check-docs-vs-reality.py          # expect exit 0

# what is actually wired right now
python3 -c "import json;print(list(json.load(open('.claude/settings.json'))['hooks']))"
# expect: ['UserPromptSubmit', 'PreToolUse', 'SessionStart', 'PostToolUse', 'Stop']

# prove the push gate has no deny path
grep -n permissionDecision .claude/scripts/push-gate.py   # expect only "allow"

# prove no Stop-hook race on the approval flag
grep -c "push-approved" .claude/settings.json     # SessionStart only, never Stop
```

Measure exit codes with `echo $?` **immediately** after the command. `cmd 2>&1 | tail` reports
`tail`'s status and has already produced one false "all green" in this repo.

---

## 8. Known limits

- **`raven-xray.py`** — Python only, static imports only. Stated in the tool itself.
- **Model routing is advisory.** No hook can force tool selection, and the session model cannot be
  swapped mid-conversation. Any claim otherwise is false.
- **Educated Push does not enforce.** It teaches. By design, as of `bb40ee0`.
- **Gate 1 on Windows** — symlinks are not materialised when `core.symlinks=false`; the gate now
  verifies via the git index instead of comparing contents.
- **Gates run in CI and on demand only.** Nothing blocks a red commit; pre-commit wiring is still
  an open decision (`bug-fix-log.md` BUG-011).

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
