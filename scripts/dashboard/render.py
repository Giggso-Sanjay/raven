#!/usr/bin/env python3
"""Retired sidebar (treeSel / goTree / Aryx mind-maps).

TRACKED: docs/DEPRECATIONS.md
Landing page is core.render_index_shell → dashboard/index.html (this repo graph only).
"""
import pathlib
import runpy
import sys

print(
    "render.py is retired — writing index via dashboard/core.py",
    file=sys.stderr,
)
_pkg = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_pkg))
runpy.run_path(str(_pkg / "core.py"), run_name="__main__")
