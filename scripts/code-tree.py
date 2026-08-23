#!/usr/bin/env python3
"""Transitional shim — renamed to code-xray.py (scripts/dashboard/xray.py).
TRACKED FOR LATER REMOVAL: docs/DEPRECATIONS.md — do not delete this version.
"""
import pathlib, runpy, sys
_pkg = pathlib.Path(__file__).resolve().parent / "dashboard"
sys.path.insert(0, str(_pkg)); sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "xray.py"), run_name="__main__")
