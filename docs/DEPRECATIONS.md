# Deprecations — tracked, not deleted

**Rule:** Do not remove these in this version. Revisit after the card + OKF path is the only boot/graph UX in all IDEs. Each row is a **candidate**, not a delete order.

Logged: 2026-08-22. Target window: later engine version (not unreleased card/OKF).

| Path | Status | Still used by (do not break) | Why candidate | Remove after |
|---|---|---|---|---|
| `scripts/code-tree.py` | shim | Anything still calling `code-tree.py` by old name | Renamed to `code-xray.py` | Zero grep hits except this doc + shim itself |
| `raven-core/raven-xray.py` | deprecated shim | Stop docs / old `raven-xray.py --build` | Code-XRay is `scripts/dashboard/xray.py` | CLAUDE.md Stop table no longer names `raven-xray.py`; hooks point at `code-xray.py` |
| `scripts/memory/vault-load.py` | **keep CLI**; not boot | Manual `python3 scripts/memory/vault-load.py`; `--hook` unused | Replaced at SessionStart by card + `ide-boot.py` | Product decision to drop manual digest; no `--hook` in any `settings.json` (already true) |
| `xray.py --digest` | keep flag; **not** SessionStart | On-demand only | Same class as vault-load inject | `.claude/settings.json` has no `--digest` (already true); then consider dropping the flag |
| `scripts/dashboard/graph.py` | live for vault export | `knowledge_graph.py`, `core.py` `--graph-json` / tests | Vault **note** map, not code OKF | Dashboard default HTML never calls it; Obsidian export has another owner |
| `scripts/dashboard/icons.py` | live for vault KG | `graph.py` `enrich_node` | Icons for wikilink graph only | Same as `graph.py` |
| `scripts/knowledge_graph.py` | shim → `graph.py` | CLI / Stop optional | Duplicate entrypoint | Callers use `dashboard/graph.py` only |
| `scripts/dashboard/core.py` vault KG HTML (`render_knowledge_graph_section`, ~line 3740) | still in file | `tests/test_knowledge_graph.py`; one remaining HTML template | Kitchen-sink dashboard | Tests rewritten to OKF HTML; default page has no vault canvas |
| `scripts/dashboard/__pycache__/render.cpython-*.pyc` | bytecode leftover | none | `render.py` already deleted | Safe to delete pyc anytime (not source) |
| `plugin/agents/claude-mem.md` + `core/agents/claude-mem.md` | duplicate of `agents/claude-mem.md` | plugin/core packs | Triple copy drifts | Single source + sync-manifest |
| `docs/APPLY-PROMPT-vault-graph-memory.md` | superseded | humans copying old port prompt | Tells forks to wire SessionStart vault-load | Leave with SUPERSEDED banner |
| `raven-dash-kg.md` | superseded snapshot | none in runtime | 2026-08-04 reverse-engineer | Archive or delete in docs sweep |
| `AndieVault` paths | deprecated name | none if grep is clean | Old vault root | Already unused |

## Still required (do not put on the delete list)

- `ide-boot.py`, `.raven/boot.json`, `CARD.md` writer, host one-liners  
- `scripts/dashboard/xray.py`, `scripts/code-xray.py`, OKF in `.raven/code-xray.json`  
- MCP graph tools on `mcp/server.py`  
- `obsidian-log.py`, token-meter, guards, routers, `session-start.py` (no vault-load)  
- `~/RavenVault` for humans  

## How to use this list later

1. `rg -n '<filename>'` — if only this doc + a shim, safe to propose delete.  
2. Run `tests/test_ide_boot.py`, `tests/test_okf.py`, `tests/test_memory_card.py`, `tests/test_knowledge_graph.py`.  
3. Commit with `[GUARD:ALLOW-DELETE]` if deleting source.  
4. Check every IDE one-liner still points at `ide-boot` + `code-xray` CLI, not the removed path.
