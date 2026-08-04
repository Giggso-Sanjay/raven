# RavenVault — Knowledge graph, dashboard & agent memory

**Audience:** Developers using Raven (Claude, Grok, Codex, Enterprise)  
**Vault root:** `~/RavenVault`  
**Build id (HTML):** `kg-v2-grounded+cite`  
**Related:** `docs/obsidian-knowledge-graph-plan.md`, `docs/grok-vault-playbook.md`

---

## 1. What problem this solves

Teams expected:

1. An **Obsidian knowledge graph** (projects, concepts, decisions, short sessions).  
2. Agents that **load memory at session start** (not blank chats).  
3. A **Raven HTML dashboard** that shows that graph **and** costs — with every number **cited**.

Previously: session notes were git dumps; project hubs were missing; dashboard was tokenomics-only; costs often showed `$0.00` while data existed; local clone paths were missing for nested repos.

---

## 2. Architecture (simple)

```
SessionStart                    During work                 Stop
─────────────                   ──────────                  ────
vault-load.py                   guards + routers            token-meter-write.py
  → digest into agent           edits / tools                 → ~/RavenVault/.metrics/
session-start.py                                              obsidian-log.py
  → brownfield + digest                                       → sessions/ + hub + index
                                                              knowledge-extract.py
                                                                → concepts/ decisions/
                                                              (optional) knowledge_graph.py
                                                                → graph/knowledge-graph.json

Human: python3 scripts/dashboard.py --html --open
  → ~/RavenVault/dashboard.html  (tokenomics + graph + citations + local/GitHub links)
```

| Path | Role |
|------|------|
| `~/RavenVault` | **Canonical** Obsidian vault + metrics + dashboard |
| `.raven/memory/` | Optional thin project-local cache only |
| `AndieVault` | **Deprecated** — do not use |

---

## 3. How agent memory works (new session)

### What the agent loads at SessionStart

1. **`session-start.py`** runs (brownfield/greenfield, models, banner).  
2. It shells **`vault-load.py`**, which builds a **capped digest** (≈ 2–4k chars), not the whole vault.  
3. Digest includes:
   - Project hub: **Current state**, **Open questions**  
   - Last **2** session summaries (AI bullets only)  
   - Last **3** decision one-liners  
   - Pointer to `graph/knowledge-graph.json` if present  

4. Plugin settings also run `vault-load.py --hook` for `additionalContext`.

### What is written at session end (Stop)

| Script | Writes | Content rules |
|--------|--------|----------------|
| `token-meter-write.py` | `.raven/.model-session.json`, `~/RavenVault/.metrics/YYYY-MM.json` | **Per-project** tokens/cost (`by_project`, day nest) |
| `obsidian-log.py` | `sessions/YYYY-MM-DD-{project}.md` | Hub-first, ≤ ~80 lines/entry, capped git status |
| `knowledge-extract.py` | `concepts/`, sometimes `decisions/` | Fail-soft path signals |
| Index | `index/README.md` | Rebuilt from `projects/*.md` (no garbage) |

### Why this is “memory”

- **Human memory:** Obsidian graph + dashboard briefings.  
- **Agent memory:** Same markdown, **curated at start**. Next session continues open questions and decisions instead of rediscovering context.  
- **Not memory:** Full git status dumps, multi‑MB transcripts, unscoped legacy cost rollups.

### How to verify memory is live

```bash
python3 scripts/vault-load.py
# Should print open questions / last sessions for current repo

# After a session ends (or dry-run):
echo '{}' | python3 scripts/obsidian-log.py
ls ~/RavenVault/sessions/ | tail
ls ~/RavenVault/projects/
```

---

## 4. Knowledge graph — how to use it

### Build / open

```bash
# From a Raven-enabled repo (or the raven product repo)
python3 scripts/dashboard.py --html --open

# Graph only
python3 scripts/dashboard.py --graph-only --open

# One project filter
python3 scripts/dashboard.py --html --project raven --open

# JSON only
python3 scripts/dashboard.py --graph-json
# → ~/RavenVault/graph/knowledge-graph.json
```

Also open vault in Obsidian: folder `~/RavenVault` → Graph view.

### On the HTML page

| UI | Action |
|----|--------|
| **◎ Center overview** | Portfolio briefing (all graph projects) |
| **Node click** (canvas or list) | Summary (Andie–Guru) · last update · cost/CVE · links |
| **Empty canvas** | Same as Center |
| **Project chips** | Briefing · **GitHub ↗** · **Local 📁** |
| **Per-repo table** | Sessions / tokens / cost + links |
| **Blue [C#]** | Jump to **Citations** bibliography |
| **Open local repo** | `file://` path to clone |
| **Vault note** | Hub markdown under RavenVault |

### Local path discovery

If hub has no `Local:` line, dashboard **searches** (depth ≤ 5) under:

- `~/AntiGravity_Projects` (includes nested e.g. `Proj1/fin-processor`)  
- `~/Projects`, `~/Developer`, `~/src`, `~/code`  

Prefers `.git` roots; rejects weak `docs/…` matches. On success, **writes** `Local:` into `projects/{name}.md` (creates hub if missing).

Hub format:

```markdown
## Repo
- GitHub: https://github.com/giggsoinc/fin-processor
- Local: /Users/you/AntiGravity_Projects/Proj1/fin-processor
```

### Costs — what is grounded

| Card | Source citation |
|------|-----------------|
| All repos | **[C1]** `~/RavenVault/.metrics/*.json` project-tagged rows |
| This repo | **[C2]** same, filtered by project |
| Live session | **[C3]** `.raven/.model-session.json` |
| Graph size | **[C4]** `graph/knowledge-graph.json` |
| Notes / hubs | **[C5]** vault markdown |
| Guards | **[C6]** `.raven/audit/*.log` |

**Not in headlines:** unscoped legacy `by_day` (no project; historically inflated).  
**Small $ amounts are real** when only router overhead was metered — shown as `$0.000212`, never `$0.00`.

---

## 5. Scripts (source of truth)

| File | Purpose |
|------|---------|
| `scripts/vault_common.py` | Hub ensure, index rebuild, wikilinks, paths |
| `scripts/vault-load.py` | SessionStart digest |
| `scripts/obsidian-log.py` | Stop: trimmed session + hub + index |
| `scripts/knowledge-extract.py` | Concepts/decisions (fail-soft) |
| `scripts/knowledge_graph.py` | Vault → JSON graph |
| `scripts/dashboard.py` | HTML: graph, costs, citations, local discovery |
| `scripts/token-meter-write.py` | Per-project metrics rollup |
| `scripts/session-start.py` | Embeds vault-load |
| `agents/claude-mem.md` | RavenVault-only mem agent |
| `plugin/settings.json` | SessionStart + Stop hooks |
| `tests/test_knowledge_graph.py` | Parse + graph + HTML markers |

Copy the same set into `raven-core/` and `plugin/scripts/` when releasing.

---

## 6. Packaging as a new Raven version (recommended **4.2.0**)

### Why 4.2.0

Feature release: agent vault load, knowledge graph export, dashboard graph + citations, local path discovery, per-project metrics. Not a patch on 4.1.0 docs-only.

### Release checklist

1. **Bump versions**
   - `.claude-plugin/plugin.json` → `"version": "4.2.0"`
   - `plugin/make-plugin.sh` → `VERSION="4.2.0"`
   - `raven-core/VERSION` → `4.2.0`
   - `.raven/manifest.json` `version` if product repo tracks engine
   - `scripts/dashboard.py` `PLUGIN_VERSION` if still hard-coded
   - Extend `version-check.py` `RAVEN_RELEASES` with `"4.1.0", "4.2.0"`

2. **Sync scripts**
   ```bash
   for f in vault_common.py vault-load.py knowledge-extract.py knowledge_graph.py \
            obsidian-log.py session-start.py token-meter-write.py dashboard.py; do
     cp -f scripts/$f raven-core/$f
     cp -f scripts/$f plugin/scripts/$f
   done
   cp -f agents/claude-mem.md plugin/agents/ core/agents/
   # settings already wired in plugin/settings.json + core/hooks/settings.json
   ```

3. **Tests**
   ```bash
   python3 -m unittest tests.test_knowledge_graph -v
   python3 scripts/dashboard.py --html
   test -f ~/RavenVault/dashboard.html
   grep -q 'kg-v2-grounded' ~/RavenVault/dashboard.html
   ```

4. **Plugin zip**
   ```bash
   bash plugin/make-plugin.sh
   # Ensure make-plugin.sh lists: vault_common, vault-load, knowledge-extract,
   # knowledge_graph, dashboard, obsidian-log, token-meter-write
   ```

5. **Docs in tag**
   - This file  
   - `docs/obsidian-knowledge-graph-plan.md`  
   - `docs/grok-vault-playbook.md`  
   - Changelog entry (see below)

6. **Git**
   ```bash
   git add -A  # exclude .raven/.cache, .model-session, secrets
   git commit -m "feat(vault): knowledge graph, agent digest, cited dashboard (v4.2.0)"
   git tag v4.2.0
   git push origin main --tags
   gh release create v4.2.0 --title "Raven v4.2.0 — RavenVault graph & agent memory" \
     --notes-file docs/CHANGELOG-4.2.0-vault-graph.md
   ```

### Suggested changelog blurb

```markdown
## v4.2.0 — RavenVault knowledge graph & agent memory
- SessionStart vault-load digest (hub + open questions + recent sessions/decisions)
- Trimmed obsidian-log + project hub auto-create + index hygiene
- knowledge-extract + knowledge-graph.json export
- dashboard.py: interactive graph, dual cost headlines, on-page citations,
  nested local-path discovery, GitHub + Local links
- token-meter per-project by_project rollups
- claude-mem RavenVault-only; Grok playbook
```

---

## 7. Apply to raven-codex / raven-enterprise

Use the **portable apply prompt** in:

`docs/APPLY-PROMPT-vault-graph-memory.md`

Paste that entire prompt into a session on those repos (or run from monorepo copy). Do not invent Hub-only behavior for OSS paths; Enterprise may add Hub later without changing vault file layout.

---

## 8. Day-to-day developer workflow

1. Work in a repo with Raven hooks.  
2. **Start session** → agent gets vault digest automatically.  
3. **Code** → guards fire as usual.  
4. **End session** → metrics + session note + hub update.  
5. **Review**  
   ```bash
   python3 scripts/dashboard.py --html --open
   ```  
6. Click project → Summary / costs / **Local 📁** / GitHub.  
7. Optional: open `~/RavenVault` in Obsidian for full graph editing.

---

*RavenVault graph + memory user guide — pairs with implementation plan and apply prompt.*
