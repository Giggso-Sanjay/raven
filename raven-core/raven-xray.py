#!/usr/bin/env python3
"""Deprecated — raven-xray was retired 2026-08-15; Code-XRay replaces it.
TRACKED FOR LATER REMOVAL: docs/DEPRECATIONS.md — do not delete this version.

The file/why/session map: python3 scripts/code-xray.py --html (not --digest at boot)
"""
import pathlib
import runpy
import sys

_pkg = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "dashboard"
sys.path.insert(0, str(_pkg))
sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "xray.py"), run_name="__main__")
