# Grok + RavenVault playbook

> **Current:** Grok loads `AGENTS.md`, then `python3 scripts/memory/ide-boot.py`. If `load=1`, Read `.raven/memory/CARD.md` only. Do not paste a vault-load digest at boot.

Raven’s knowledge vault is host-agnostic: markdown under `~/RavenVault` plus local Python scripts.

## Session start

```bash
python3 scripts/memory/ide-boot.py
```

## Session end

```bash
python3 scripts/obsidian-log.py </dev/null
python3 scripts/knowledge-extract.py --quiet
python3 scripts/knowledge_graph.py
python3 scripts/dashboard.py --html
```

## Rules

1. Canonical vault is `~/RavenVault` only (not AndieVault).  
2. Do not load entire session dumps into the model.  
3. Prefer hub open questions + last decisions.  
4. Graph UI: open `~/RavenVault/dashboard.html` or `knowledge-graph.html`.
