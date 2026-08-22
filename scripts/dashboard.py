#!/usr/bin/env python3
"""Back-compat shim — dashboard lives in scripts/dashboard/core.py."""
import pathlib
import runpy
import sys

_pkg = pathlib.Path(__file__).resolve().parent / "dashboard"
sys.path.insert(0, str(_pkg))
sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "core.py"), run_name="__main__")
