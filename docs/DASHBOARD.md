# Raven Dashboard

The Raven dashboard is a single local HTML file — **`~/RavenVault/dashboard.html`** —
that shows what Raven is doing across your projects: token spend, costs, session
history, and the knowledge graph. Everything is generated from local files; no
data leaves your machine, and the page works offline (`file://`, no CDN).

## Open it

```bash
python3 scripts/dashboard.py --html --open
```

The dashboard is rebuilt on **Stop** (`dashboard.py --if-stale 15`), not by injecting
the vault into the agent. Open `~/RavenVault/dashboard.html` in a browser. Agent boot
uses `ide-boot.py` + `.raven/memory/CARD.md`, which lists this dashboard path.

## What it shows

### 1. Tokenomics (session cost metering)

- **Per-session meters** — tokens, cost, and Raven-vs-user call counts for each
  session. Written by the `token-meter-write.py` Stop hook, which parses the
  session transcript JSONL after each session and records:
  - per-session JSON (`.raven/state/`)
  - a monthly rollup
  - an audit log entry
- **Cost comparison** — Raven-metered usage rendered side-by-side with
  Claude/Anthropic-reported usage. The dashboard writes an editable template file;
  paste in Claude's own reported numbers and the next rebuild shows both columns.
- The same numbers appear in-terminal at session end:
  `📊 Session meters: 324 tok · $0.000081 · 5 raven / 3 user calls`

### 2. Knowledge graph (picture map)

An icon-based map of your projects built from RavenVault memory (sessions,
projects, concepts, decisions). Nodes carry SVG icons inlined as data-URIs
(`assets/kg-icons/`, rendered by `kg_icons.py`) so the graph is readable by
non-programmers — see [VIBE-CODER-MAP.md](VIBE-CODER-MAP.md) for the zero-code
guide to reading it.

| Icon | Meaning |
|------|---------|
| 📦 project | Whole app / repo |
| 💡 concept | A system piece (login, DB…) |
| ✅ decision | A choice locked in |
| ⏱️ session | One day of work |
| 🔐 / 🛡️ | Auth / security guards |
| 🗄️ / 🔌 / 🖥️ | Database / API / UI |
| 💳 / ☁️ / 🔄 / 💻 | Payments / cloud / pipelines / code |

### 3. Session history & memory

Recent session notes, open questions, and decisions from `~/RavenVault/`
(the same digest that Raven loads at session start).

## Data sources

| Source | Path |
|--------|------|
| Session metrics | `.raven/state/` (per project) |
| Vault memory | `~/RavenVault/sessions|projects|concepts|decisions` |
| Graph export | `~/RavenVault/graph/knowledge-graph.json` |
| Dashboard output | `~/RavenVault/dashboard.html` |

## Related docs

- [TOKENOMICS.md](TOKENOMICS.md) — where Raven saves tokens
- [VIBE-CODER-MAP.md](VIBE-CODER-MAP.md) — reading the picture map without code
- [RAVENVAULT-GRAPH-AND-MEMORY.md](RAVENVAULT-GRAPH-AND-MEMORY.md) — how memory and the graph are built
