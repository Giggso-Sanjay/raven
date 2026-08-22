#!/usr/bin/env python3
"""Link audit for raven-dashboard.html — no legacy picker, iframe exists."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

VAULT = Path.home() / "RavenVault" / "dashboard"
PAGE = VAULT / "raven-dashboard.html"
LEGACY_MARKERS = ("treeSel", "goTree", "setTree", "trees/Aryx.html", "function goTree")


class TestRavenDashboard(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(PAGE.is_file(), f"missing {PAGE}")

    def test_no_legacy_markers(self):
        text = PAGE.read_text(errors="replace")
        for m in LEGACY_MARKERS:
            self.assertNotIn(m, text, f"legacy marker {m}")

    def test_iframe_okf_exists(self):
        text = PAGE.read_text(errors="replace")
        srcs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', text)
        self.assertTrue(srcs, "no src/href")
        base = PAGE.parent
        for rel in srcs:
            if rel.startswith(("http:", "https:", "data:", "javascript:")):
                continue
            target = (base / rel).resolve()
            self.assertTrue(target.is_file(), f"broken {rel} -> {target}")
            inner = target.read_text(errors="replace")
            self.assertTrue(
                'id="okf"' in inner or "EXTRACTED graph" in inner or 'id="canvas"' in inner,
                f"{rel} is not the OKF graph page",
            )
            self.assertNotIn("id=\"treeSel\"", inner)
            self.assertNotIn("function goTree", inner)

    def test_shared_viewer_exists(self):
        dash = PAGE.parent
        self.assertTrue((dash / "okf-viewer.js").is_file())
        self.assertTrue((dash / "okf-viewer.css").is_file())

    def test_logs_pane_in_writer(self):
        src = Path(__file__).resolve().parents[1] / "scripts" / "dashboard" / "core.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn('data-v="logs"', text)
        self.assertIn("turn-log.jsonl", text)
        self.assertIn("total-cost", text)
        self.assertIn("<th>IDE</th>", text)
        self.assertIn("Back to log tables", text)
        self.assertIn("<th>Repo</th>", text)
        self.assertIn("filterLogs", text)
        self.assertIn("_gather_repo_logs", text)
        self.assertIn("data-v=\"settings\"", text)
        self.assertIn("saveSettings", text)
        self.assertIn("airtaas", text.lower())

    def test_guards_have_meaning_column(self):
        src = Path(__file__).resolve().parents[1] / "scripts" / "dashboard" / "core.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("What it means", text)
        self.assertIn("GUARD_MEANING", text)
        self.assertIn("not a block", text)

    def test_no_looping_auto_refresh(self):
        text = PAGE.read_text(errors="replace")
        self.assertNotIn('content="30"', text)
        self.assertNotIn("setInterval(function(){ location.reload(); }", text)
        self.assertIn("Looking at:", text)


if __name__ == "__main__":
    unittest.main()
