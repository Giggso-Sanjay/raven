#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "ops" / "github-version.py"
    spec = importlib.util.spec_from_file_location("github_version", p)
    return spec.loader.load_module()


class TestGithubVersion(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_bullets_from_log(self):
        text = "## v9.9.9 — x\n\n- Alpha change\n- Beta change\n- Gamma\n\n---\n\n## v1.0.0\n- old\n"
        b = self.m._bullets_from_log(text, "9.9.9")
        self.assertEqual(b[0], "Alpha change")
        self.assertGreaterEqual(len(b), 3)

    def test_newer_banner_asks_upgrade(self):
        msg = self.m.format_banner("5.5.0", "5.5.4", ["one", "two", "three", "four", "five"])
        self.assertIn("available", msg)
        self.assertIn("upgrade", msg)
        self.assertIn("• one", msg)
        self.assertEqual(msg.count("•"), 5)

    def test_current_banner(self):
        msg = self.m.format_banner("5.5.4", "5.5.4", ["a"])
        self.assertIn("current", msg)
        self.assertNotIn("available", msg)

    def test_offline_banner(self):
        with mock.patch.object(self.m, "github_latest_tag", side_effect=OSError("net")):
            out = self.m.banner(ROOT)
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
