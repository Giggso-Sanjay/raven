#!/usr/bin/env python3
"""Back-compat shim — Code-XRay lives in scripts/dashboard/xray.py."""
import pathlib
import runpy
import sys

_pkg = pathlib.Path(__file__).resolve().parent / "dashboard"
sys.path.insert(0, str(_pkg))
sys.path.insert(1, str(_pkg.parent))
runpy.run_path(str(_pkg / "xray.py"), run_name="__main__")
