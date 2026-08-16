# Raven v4.2.0 — RavenVault knowledge graph & agent memory

## Summary

Raven now maintains a real **knowledge graph** in `~/RavenVault`, loads a **curated memory digest** into agents at session start, and shows **tokenomics + graph** in `dashboard.html` with **cited numbers** and **GitHub + local clone links** (including nested paths under `~/AntiGravity_Projects`).

## Features

### Agent memory
- `vault-load.py` — SessionStart digest (hub state, open questions, last sessions, decisions)
- `session-start.py` embeds vault-load
- Plugin Stop: `token-meter-write` → `obsidian-log` → `knowledge-extract`
- `claude-mem` agent: RavenVault-only (AndieVault deprecated)

### Vault writers
- `obsidian-log.py` v3 — hub-first, trimmed sessions (≤~80 lines), index rebuild, raw git to `sessions/raw/`
- `vault_common.py` — shared hub/index helpers
- `knowledge-extract.py` — fail-soft concepts/decisions
- `knowledge_graph.py` — `graph/knowledge-graph.json`

### Dashboard
- Interactive knowledge graph (vis-network + offline node list)
- Node panel: Summary (Andie–Guru) · last update · cost/CVE · GitHub · **Local** · vault note · drill-down links
- Dual headlines: portfolio / this repo / live session
- Every major number has **[C#]** citation → bibliography
- Nested **local path discovery** + hub backfill (`Local:`)
- Per-project metrics from token-meter

### Docs / tests
- `docs/RAVENVAULT-GRAPH-AND-MEMORY.md`
- `docs/obsidian-knowledge-graph-plan.md`
- `docs/grok-vault-playbook.md`
- `docs/APPLY-PROMPT-vault-graph-memory.md`
- `tests/test_knowledge_graph.py`

## Breaking / behavior notes

- Unscoped legacy `by_day` metrics **excluded** from cost headlines (were inflated).
- Sub-cent costs no longer display as `$0.00`.
- Session notes no longer paste unlimited git status into Obsidian graph path.

## Upgrade

1. Pull/tag `v4.2.0` or reinstall plugin zip.  
2. Ensure hooks include `vault-load`, `obsidian-log`, `knowledge-extract`, `token-meter-write`.  
3. Run `python3 scripts/dashboard.py --html --open`.  
4. Confirm banner `kg-v2-grounded` and citations section.
