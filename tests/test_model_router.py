#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "routing" / "model-router.py"
    spec = importlib.util.spec_from_file_location("model_router", p)
    return spec.loader.load_module()


class TestBaseRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_default_state_is_router_on(self):
        with mock.patch.object(self.m, "_router_state_path", return_value=Path("/no/such/file.json")):
            st = self.m.load_router_state()
        self.assertEqual(st["mode"], "router")
        self.assertTrue(st.get("mandatory"))

    def test_arm_writes_router_on(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".router-state.json"
            with mock.patch.object(self.m, "_router_state_path", return_value=p):
                st = self.m.arm_base_router()
            self.assertEqual(st["mode"], "router")
            disk = json.loads(p.read_text())
            self.assertEqual(disk["mode"], "router")
            self.assertIn(disk.get("backend"), ("claude", "grok", "codex", "unknown", "cursor", "antigravity", "windsurf", "replit", "gemini"))

    def test_simple_hook_text_is_must_not_advisory(self):
        src = (ROOT / "scripts" / "routing" / "model-router.py").read_text()
        self.assertIn("applied=false", src)
        self.assertIn("--session-start", src)
        self.assertNotIn("delegation is advisory, not forced", src)

    def test_codex_host_not_claude_sonnet(self):
        env = {"CODEX_HOME": "/tmp/codex"}
        with mock.patch.object(self.m.os, "environ", env):
            host = self.m.detect_host(env)
            self.assertEqual(host, "codex")
            models = self.m._load_model_env("codex")
        self.assertNotIn("anthropic/claude-sonnet-5", models.get("MEDIUM", ""))
        self.assertEqual(models["MEDIUM"], "codex")

    def test_turn_toast_has_applied_false(self):
        line = self.m.format_turn_toast("MEDIUM", "grok-4.6", ["security_keyword:key"], host="grok")
        self.assertIn("host=grok", line)
        self.assertIn("MEDIUM", line)
        self.assertIn("grok-4.6", line)
        self.assertIn("applied=false", line)
        self.assertIn("why:", line)
        self.assertIn("total-cost=", line)

    def test_agents_dir_detects_antigravity_without_env(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".agents").mkdir()
            (root / ".agents" / "agents.md").write_text("x\n")
            (root / ".raven").mkdir()
            (root / ".raven" / "boot.json").write_text('{"hosts":{}}')
            with mock.patch.object(self.m, "_find_project_root", return_value=root):
                self.assertEqual(self.m.detect_host({}), "antigravity")

    def test_grok_host_uses_grok_models(self):
        env = {"GROK_SESSION_ID": "1"}
        self.assertEqual(self.m.detect_host(env), "grok")
        models = self.m._load_model_env("grok")
        self.assertEqual(models["SIMPLE"], "grok-4.5")
        self.assertEqual(models["MEDIUM"], "grok-4.6")


if __name__ == "__main__":
    unittest.main()
