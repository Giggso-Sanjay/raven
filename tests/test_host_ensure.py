#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "ops" / "host-ensure.py"
    spec = importlib.util.spec_from_file_location("host_ensure", p)
    return spec.loader.load_module()


class TestHostEnsure(unittest.TestCase):
    def test_writes_python_wrapper_and_agents(self):
        he = _load()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        target = Path(td.name)
        with mock.patch.object(he, "TARGET", target), mock.patch.object(he, "ENGINE", ROOT):
            done = he.ensure()
        self.assertTrue((target / "scripts" / "raven-python.sh").is_file())
        self.assertTrue((target / ".agents" / "agents.md").is_file())
        self.assertTrue(any("raven-python" in x for x in done))

    def test_skills_call_host_ensure(self):
        init = (ROOT / "skills" / "raven-init" / "SKILL.md").read_text()
        debug = (ROOT / "skills" / "raven-debug" / "SKILL.md").read_text()
        self.assertIn("host-ensure.py --open", init)
        self.assertIn("host-ensure.py --open", debug)


if __name__ == "__main__":
    unittest.main()
