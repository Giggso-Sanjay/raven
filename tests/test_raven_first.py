#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "ops" / "raven-first.py"
    spec = importlib.util.spec_from_file_location("raven_first", p)
    return spec.loader.load_module()


class TestRavenFirst(unittest.TestCase):
    def test_boot_copies_wrapper_and_router_into_empty_project(self):
        rf = _load()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        target = Path(td.name)
        with mock.patch.object(rf, "find_engine", return_value=ROOT):
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(target)}, clear=False):
                rc = rf.main(["--boot"])
        self.assertEqual(rc, 0)
        self.assertTrue((target / "scripts" / "raven-python.sh").is_file())
        self.assertTrue((target / "scripts" / "routing" / "model-router.py").is_file())
        self.assertTrue((target / "scripts" / "ops" / "raven-first.py").is_file())

    def test_find_engine_prefers_cwd_with_router(self):
        rf = _load()
        self.assertEqual(rf.find_engine(), ROOT.resolve())

    def test_subprocess_boot_via_plugin_path(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        target = Path(td.name)
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(target)
        env["RAVEN_ENGINE"] = str(ROOT)
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        script = ROOT / "scripts" / "ops" / "raven-first.py"
        r = subprocess.run(
            [sys.executable, str(script), "--boot"],
            cwd=str(target),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        self.assertTrue((target / "scripts" / "raven-python.sh").is_file())
        self.assertTrue((target / "scripts" / "routing" / "model-router.py").is_file())


if __name__ == "__main__":
    unittest.main()
