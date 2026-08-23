> **SUPERSEDED boot path (2026-08-22):** `vault-load` is not SessionStart. Use `ide-boot.py` + CARD.md. This plan is historical.

# Raven — Obsidian vault + knowledge graph

**Status:** Implemented (P0–P2 in raven-core / plugin scripts)  
**Vault:** `~/RavenVault`  
**Dashboard:** `python3 scripts/dashboard.py --html` → `~/RavenVault/dashboard.html`

## Contract

| Path | Role |
|------|------|
| `~/RavenVault` | Canonical Obsidian vault (human + graph export) |
| `.raven/memory/` | Optional thin project-local cache only |
| `AndieVault` | Deprecated — use RavenVault |

### Note types

| Folder | Node type |
|--------|-----------|
| `projects/` | Project hub (always created before session links) |
| `concepts/` | Durable product facts |
| `decisions/` | ADRs |
| `sessions/` | Short summaries + wikilinks (≤ ~80 lines/entry) |
| `sessions/raw/` | Optional large git dumps (outside default graph) |
| `graph/knowledge-graph.json` | Nodes + edges export |
| `index/README.md` | Active projects = union of `projects/*.md` |

Tokenomics dashboard stays; knowledge graph is a **second** surface on the same HTML.

## Scripts

| Script | Role |
|--------|------|
| `vault_common.py` | Hub ensure, index rebuild, wikilink helpers |
| `obsidian-log.py` | Stop: hub-first, trimmed session, index, spawn extract |
| `vault-load.py` | SessionStart digest (≤ ~3.5k chars); `--hook` JSON |
| `knowledge-extract.py` | Fail-soft concepts/decisions from path signals |
| `knowledge_graph.py` | Scan vault → `graph/knowledge-graph.json` |
| `dashboard.py` | `--html` embeds graph; `--graph-only`, `--graph-json`, `--project` |

## Hooks (plugin `settings.json`)

**SessionStart:** `session-start.py` (embeds vault-load) + `vault-load.py --hook`  
**Stop:** `token-guard` + `obsidian-log` + `knowledge-extract` (async, fail-soft)

## CLI

```bash
python3 scripts/dashboard.py --html --open
python3 scripts/dashboard.py --graph-only --project raven
python3 scripts/dashboard.py --graph-json
python3 scripts/vault-load.py
python3 scripts/knowledge_graph.py --project raven
```

## Grok / other hosts

Run the same scripts:

```bash
python3 scripts/vault-load.py          # at session start
python3 scripts/obsidian-log.py        # at session end (stdin hook JSON optional)
```

Playbook: Read digest before coding; do not dump the full vault into context.

## Acceptance (smoke)

1. Session creates `projects/{name}.md` if missing.  
2. Session notes link `[[projects/{name}]]`.  
3. No multi-thousand-line git paste in session notes.  
4. Index Active Projects lists all hubs.  
5. `dashboard.py --html` contains `id="kg-canvas"` or sparse callout.  
6. `knowledge-graph.json` has nodes/edges matching wikilinks.

## Out of scope

Neo4j, auto-committing vault into app repos, replacing Obsidian as editor.

---

*Raven Obsidian + knowledge graph — tracking doc for GitHub.*
