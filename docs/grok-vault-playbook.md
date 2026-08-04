# Grok + RavenVault playbook

Raven’s knowledge vault is host-agnostic: markdown under `~/RavenVault` plus local Python scripts.

## Session start

```bash
python3 /path/to/raven/scripts/vault-load.py
# or, if cwd is the raven/product repo with scripts on path:
python3 scripts/vault-load.py --project "$(basename $(git remote get-url origin 2>/dev/null) .git)"
```

Paste or Read the digest into context. Cap is intentional (~2–4k tokens).

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
