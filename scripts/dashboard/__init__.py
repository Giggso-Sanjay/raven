"""Raven dashboard package — metrics, render shell, knowledge graph, code tree.

Modules:
  core.py   — metrics aggregation, citations, legacy render modes, CLI
  render.py — the sidebar shell (Overview/Code Tree/Repos/Costs/Guards)
  graph.py  — vault knowledge-graph JSON builder
  icons.py  — knowledge-graph node icons
  tree.py   — deterministic per-repo code tree (build/delta/digest/html)

Entry points (back-compat shims call these):
  python3 scripts/dashboard.py …   → core.main()
  python3 scripts/code-tree.py …   → tree.main()
"""
