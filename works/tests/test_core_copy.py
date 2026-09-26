"""works/.shared/core/ の写しが graphloops の受け付けの核として動くかの骨組みの検査。

Task 1 の受け入れ試験: engine/rules の写しから `load_rules` が通ること・写した元の
commit が記録されていること・pack の manifest（archon-plugin.json）の形。
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"


class TestCoreCopy(unittest.TestCase):
    def test_rules_load_from_copy(self):
        sys.path.insert(0, str(CORE / "graphloops"))
        from engine.rules import load_rules
        gp = CORE / "graphloops" / "graphs" / "review-loop.json"
        rules = load_rules(gp, json.loads(gp.read_text()))
        for name in ("judge_output", "fix_plan_covers_units", "delta_review_output"):
            self.assertIn(name, rules.POST_CHECKS)
        self.assertTrue(hasattr(rules, "add"))

    def test_copied_from_names_commit(self):
        self.assertIn("fbd40e3", (CORE / "COPIED_FROM").read_text())

    def test_manifest(self):
        m = json.loads((ROOT / "archon-plugin.json").read_text())
        self.assertEqual(m["name"], "works")
        self.assertEqual(m["kind"], "workflow-pack")
        self.assertEqual(m["entrypoints"], {"darkfactory": "darkfactory/darkfactory.yaml"})
        self.assertEqual(m["compatibility"], {"archon": ">=0.11.1 <0.12.0"})


if __name__ == "__main__":
    unittest.main()
