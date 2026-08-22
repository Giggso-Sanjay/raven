#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_xray():
    p = ROOT / "scripts" / "dashboard" / "xray.py"
    spec = importlib.util.spec_from_file_location("xray", p)
    mod = spec.loader.load_module()
    return mod


class TestOkf(unittest.TestCase):
    def test_query_helpers(self):
        x = _load_xray()
        okf = {
            "nodes": [
                {"id": "file:a.py", "type": "file", "label": "a.py", "purpose": "x"},
                {"id": "commit:abc", "type": "commit", "short": "abc", "summary": "hi", "files": ["a.py"]},
            ],
            "edges": [
                {"from": "commit:abc", "to": "file:a.py", "type": "touches", "tag": "EXTRACTED"},
            ],
        }
        self.assertEqual(x.get_node(okf, "a.py")["id"], "file:a.py")
        self.assertTrue(x.get_neighbors(okf, "commit:abc"))
        impact = x.commit_impact(okf, "abc")
        self.assertIn("file:a.py", impact["files"])


if __name__ == "__main__":
    unittest.main()
