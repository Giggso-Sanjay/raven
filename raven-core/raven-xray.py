#!/usr/bin/env python3
"""Deprecated — raven-xray was retired 2026-08-15; Code-XRay replaces it.

The file/why/session map: python3 scripts/code-xray.py --digest|--html
"""
import pathlib
import runpy
import sys

_pkg = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "dashboard"
sys.path.insert(0, str(_pkg))
sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "xray.py"), run_name="__main__")
