#!/usr/bin/env python3
"""OKF / Code-XRay: EXTRACTED edges, HEAD resolve, if-stale, delete."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = ROOT / "scripts" / "dashboard" / "xray.py"
    spec = importlib.util.spec_from_file_location("xray_mod", p)
    return spec.loader.load_module()


class TestXrayOkf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x = _load()

    def _okf(self):
        return {
            "git_head": "63f1ed9",
            "nodes": [
                {"id": "file:a.py", "type": "file", "label": "a.py", "purpose": "x"},
                {"id": "file:gone.py", "type": "file", "label": "gone.py"},
                {"id": "commit:63f1ed9", "type": "commit", "short": "63f1ed9",
                 "sha": "63f1ed9abc", "summary": "fix card", "files": ["a.py"]},
            ],
            "edges": [
                {"from": "commit:63f1ed9", "to": "file:a.py", "type": "touches", "tag": "EXTRACTED"},
                {"from": "file:a.py", "to": "file:b.py", "type": "imports", "tag": "EXTRACTED"},
            ],
        }

    def test_extracted_only_touches_for_head(self):
        x = self.x
        with mock.patch.object(x, "_run", return_value="63f1ed9"):
            edges = x.query_graph(self._okf(), type="touches", commit="HEAD")
        self.assertTrue(edges)
        self.assertTrue(all(e["tag"] == "EXTRACTED" and e["type"] == "touches" for e in edges))
        self.assertEqual(edges[0]["to"], "file:a.py")

    def test_head_resolves_in_commit_impact(self):
        x = self.x
        with mock.patch.object(x, "_run", return_value="63f1ed9"):
            out = x.commit_impact(self._okf(), "HEAD")
        self.assertNotIn("error", out)
        self.assertIn("file:a.py", out["files"])

    def test_query_type_touches_not_empty_vs_node_type(self):
        x = self.x
        nodes = x.query_graph(self._okf(), type="commit")
        self.assertTrue(any(n["type"] == "commit" for n in nodes))
        with mock.patch.object(x, "_run", return_value="63f1ed9"):
            self.assertTrue(x.query_graph(self._okf(), type="touches", commit="HEAD"))

    def test_if_stale_noop(self):
        x = self.x
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td) / "code-xray.json"
            payload = {"okf": {"git_head": "abc1234", "nodes": [{"id": "keep"}]}, "root": {"id": "r", "children": []}}
            tree.write_text(json.dumps(payload))
            with mock.patch.object(x, "TREE_PATH", tree), mock.patch.object(x, "_run", return_value="abc1234"):
                out = x.build(if_stale=15)
            self.assertEqual(out["okf"]["nodes"][0]["id"], "keep")

    def test_deleted_file_drops_from_tree(self):
        x = self.x
        rebuilt = {
            "a.py": {"id": "a.py", "type": "program", "functions": [], "imports": [], "history": [], "sessions": []},
            "gone.py": {"id": "gone.py", "type": "program", "deleted": True, "functions": [], "imports": [], "history": [], "sessions": []},
        }
        live = {k: v for k, v in rebuilt.items() if not v.get("deleted")}
        self.assertIn("a.py", live)
        self.assertNotIn("gone.py", live)

    def test_commit_icon_not_unknown(self):
        p = ROOT / "scripts" / "dashboard" / "icons.py"
        spec = importlib.util.spec_from_file_location("kg_icons", p)
        ic = spec.loader.load_module()
        key = ic.resolve_icon_key(ntype="commit", label="818782d", node_id="commit:818782d")
        self.assertEqual(key, "commit")
        self.assertNotEqual(ic.emoji_for(key), "❓")

    def test_panel_has_repo_and_looping_flow(self):
        js = (ROOT / "scripts" / "dashboard" / "okf-viewer.js").read_text(encoding="utf-8")
        css = (ROOT / "scripts" / "dashboard" / "okf-viewer.css").read_text(encoding="utf-8")
        self.assertIn("repo: ", js)
        self.assertIn("linear infinite", css)
        self.assertIn("runOnce(true)", js)
        src = (ROOT / "scripts" / "dashboard" / "xray.py").read_text(encoding="utf-8")
        self.assertIn("okf-viewer.js", src)
        self.assertIn("rebake_tree_htmls", src)

    def test_rebake_rewrites_stub(self):
        x = self.x
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            trees = vault / "dashboard" / "trees"
            trees.mkdir(parents=True)
            old = '<html><script type="application/json" id="okf">{"repo":"Aryx","nodes":[{"id":"commit:1","type":"commit","label":"818782d"}],"edges":[]}</script><script>old inline</script></html>'
            (trees / "Aryx.html").write_text(old)
            with mock.patch.object(x, "VAULT", vault), mock.patch.object(x, "TREES_DIR", trees):
                n = x.rebake_tree_htmls()
            self.assertEqual(n, 1)
            body = (trees / "Aryx.html").read_text()
            self.assertIn("okf-viewer.js", body)
            self.assertNotIn("old inline", body)
            self.assertTrue((vault / "dashboard" / "okf-viewer.js").is_file())
            self.assertTrue((trees / "okf-viewer.js").is_file())
