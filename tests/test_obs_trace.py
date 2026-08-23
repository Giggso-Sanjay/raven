#!/usr/bin/env python3
"""obs_trace writes vault jsonl, never the git repo."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TestObsTrace(unittest.TestCase):
    def test_emit_writes_jsonl(self):
        p = ROOT / "scripts" / "session" / "obs_trace.py"
        spec = importlib.util.spec_from_file_location("obs_trace", p)
        mod = spec.loader.load_module()
        td = tempfile.TemporaryDirectory()
        dest = Path(td.name) / "runs.jsonl"
        self.addCleanup(td.cleanup)
        with mock.patch.object(mod, "VAULT_OBS", dest):
            with mock.patch.dict("os.environ", {}, clear=False):
                mod.emit({"obs_run_id": "abc", "repo": "raven", "tier": "SIMPLE"})
        self.assertTrue(dest.is_file())
        self.assertIn("raven", dest.read_text())
        self.assertNotIn("prompt", dest.read_text())
