#!/usr/bin/env python3
"""Memory card: schema, atomic write, no graph, rotation isolated."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "memory"))

import vault_common as vc  # noqa: E402


class TestMemoryCard(unittest.TestCase):
    def test_write_schema_and_no_graph(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".raven").mkdir()
            (root / ".raven" / "manifest.json").write_text(
                '{"project": "card-test"}', encoding="utf-8"
            )
            with mock.patch.object(vc, "PROJECTS", Path(td) / "hubs"):
                (vc.PROJECTS).mkdir()
                (vc.PROJECTS / "card-test.md").write_text(
                    "## Open questions\n- [ ] Should we ship the card?\n"
                    "## Key decisions\n- Use in-repo CARD.md\n"
                    "- ~~superseded old idea~~\n",
                    encoding="utf-8",
                )
                path = vc.write_memory_card(root, session_id="s1")
            text = path.read_text(encoding="utf-8")
            self.assertIn("schema: 1", text)
            self.assertIn("status: FRESH", text)
            self.assertIn("project: card-test", text)
            self.assertIn("Should we ship the card?", text)
            self.assertIn("Use in-repo CARD.md", text)
            self.assertNotIn("superseded", text)
            self.assertNotIn("knowledge-graph.json export", text)
            self.assertIn("Do not read ~/RavenVault or knowledge-graph.json unless asked.", text)
            self.assertTrue(path.exists())
            self.assertFalse(path.with_name("CARD.md.tmp").exists())

    def test_invalid_schema_rule_in_card(self):
        self.assertEqual(vc.CARD_SCHEMA, 1)

    def test_rotate_does_not_write_card(self):
        self.assertIsNone(vc.maybe_rotate_sessions())


if __name__ == "__main__":
    unittest.main()
