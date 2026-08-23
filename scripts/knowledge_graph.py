#!/usr/bin/env python3
"""Back-compat shim — knowledge graph lives in scripts/dashboard/graph.py.
TRACKED FOR LATER REMOVAL: docs/DEPRECATIONS.md — do not delete this version.
"""
import pathlib
import sys

_pkg = pathlib.Path(__file__).resolve().parent / "dashboard"
for _d in (str(_pkg), str(_pkg.parent)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
from graph import *  # noqa: F401,F403
from graph import build_graph, write_graph  # noqa: F401

if __name__ == "__main__":
    import runpy
    runpy.run_path(str(_pkg / "graph.py"), run_name="__main__")
