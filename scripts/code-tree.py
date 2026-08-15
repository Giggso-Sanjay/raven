#!/usr/bin/env python3
"""Back-compat shim — code tree lives in scripts/dashboard/tree.py."""
import pathlib
import runpy
import sys

_pkg = pathlib.Path(__file__).resolve().parent / "dashboard"
sys.path.insert(0, str(_pkg))
sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "tree.py"), run_name="__main__")
