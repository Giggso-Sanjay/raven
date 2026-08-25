#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "session" / "run_costs.py"
    spec = importlib.util.spec_from_file_location("run_costs", p)
    return spec.loader.load_module()


class TestRunCosts(unittest.TestCase):
    def test_disclaimer_and_local(self):
        rc = _load()
        self.assertIn("/run-costs", rc.DISCLAIMER)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(rc, "OUT", Path(td) / ".run-costs.json"):
                rec = rc.run()
        self.assertIn("local", rec)
        self.assertIn("kind", rec["local"])
        text = rc.format_text(rec)
        self.assertIn("Calculator is local", text)

    def test_skill_exists(self):
        self.assertTrue((ROOT / "skills" / "run-costs" / "SKILL.md").is_file())
        self.assertTrue((ROOT / "core" / "commands" / "run-costs.md").is_file())


if __name__ == "__main__":
    unittest.main()
