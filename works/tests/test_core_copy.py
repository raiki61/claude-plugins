"""works/.shared/core/ の写しが graphloops の受け付けの核として動くかの骨組みの検査。

Task 1 の受け入れ試験: engine/rules の写しから `load_rules` が通ること・写した元の
commit が記録されていること・pack の manifest（archon-plugin.json）の形。
Task 9: works のスキル（SKILL.md の frontmatter と本文の起動名）と Claude Code の plugin.json の形。
"""
import json
import pathlib
import subprocess
import sys
import unittest

import yaml

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
        lines = (CORE / "COPIED_FROM").read_text().splitlines()
        self.assertEqual(lines[0].split()[0], "a1202d0")   # graphloops 0.21.0

    def test_copied_from_lists_existing_files(self):
        """COPIED_FROM の 2 行目以降に並ぶ写した物が、全部 core の下に在る（0.21.0 で足した 4 本を含む）"""
        listed = [ln.split()[0] for ln in (CORE / "COPIED_FROM").read_text().splitlines()[1:] if ln.strip() and not ln.startswith("#")]
        for rel in ("graphloops/engine/declared.py", "graphloops/engine/intake.py", "graphloops/engine/pointers.py",
                    "graphloops/rules/policy_input.py"):
            self.assertIn(rel, listed)
        for rel in listed:
            self.assertTrue((CORE / rel).is_file(), rel)
        # 検証器が読む物（盤面の層の scalars の段が要る。0.21.0 の写しで足した）
        for rel in ("scripts/comment-ratio.sh", "REVIEW.md"):
            self.assertIn(rel, listed)

    def test_copies_are_byte_identical_to_the_commit(self):
        """COPIED_FROM に並ぶ写しは、1 行目の commit の同じパスの中身とバイト単位で同じ（写しは直さない）"""
        lines = (CORE / "COPIED_FROM").read_text().splitlines()
        commit = lines[0].split()[0]
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((CORE / rel).read_bytes(), src)

    def test_manifest(self):
        m = json.loads((ROOT / "archon-plugin.json").read_text())
        self.assertEqual(m["name"], "works")
        self.assertEqual(m["kind"], "workflow-pack")
        self.assertEqual(m["entrypoints"], {"darkfactory": "darkfactory/darkfactory.yaml"})
        self.assertEqual(m["compatibility"], {"archon": ">=0.11.1 <0.12.0"})

    def test_skill_frontmatter(self):
        text = (ROOT / "skills" / "works" / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm)
        self.assertEqual(meta["name"], "works")
        self.assertTrue(meta.get("description"))
        self.assertIn("raiki61/works:darkfactory", body)
        p = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(p["name"], "works")
        self.assertEqual(p["version"], "0.1.0")
        self.assertTrue(p.get("description"))


if __name__ == "__main__":
    unittest.main()
