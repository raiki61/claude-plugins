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

# 写しの works の手直し（COPIED_FROM の行の注記に同じ物を書く）。{写しのパス: [(元のバイト, 写しのバイト)]}。
# 元の commit の中身に、元のバイトがちょうど 1 度だけ在り、それを写しのバイトに替えた物が写しとバイト単位で同じ。
# ここに無い写しは 1 バイトも変えない。test_core_verbatim も同じ表を読む
DEVIATIONS = {
    # 一式 1 回の上限 1800 秒 → 20 日（works の期限は 20 日だけ。裁定 R4）
    "graphloops/rules/review-loop-tdd.py": [(b"SUITE_TIMEOUT = 1800        #", b"SUITE_TIMEOUT = 1728000     #")],
}
# 修正の段の TDD（仕様 tdd-spec 1.2 節）で足した写し
TDD_COPIES = ("graphloops/graphs/review-loop-tdd.json", "graphloops/rules/review-loop-tdd.py",
              "graphloops/prompts/review-loop/tdd/p3.delta_review.md", "graphloops/prompts/review-loop/tdd/p3.fix.md",
              "graphloops/prompts/review-loop/tdd/p3.tdd_tests.md")


def expected_copy(rel: str, src: bytes) -> bytes:
    """元の commit の中身 src に DEVIATIONS の手直しを当てた、写しが持つべきバイト（元のバイトが 1 度でなければ AssertionError）"""
    for old, new in DEVIATIONS.get(rel, ()):
        assert src.count(old) == 1, f"{rel}: 手直しの元 {old!r} が元の commit に {src.count(old)} 度在る（1 度だけのはず）"
        src = src.replace(old, new)
    return src


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
        for rel in ("scripts/comment-ratio.sh", "REVIEW.md", "graphloops/scripts/parallel-pr.py"):
            self.assertIn(rel, listed)
        for rel in TDD_COPIES:
            self.assertIn(rel, listed)

    def test_tdd_rules_load_from_copy(self):
        """写しの TDD 版の graph から load_rules が通り、TDD の機械の節・返答の検査が表に在る。一式の上限は 20 日"""
        sys.path.insert(0, str(CORE / "graphloops"))
        from engine.rules import load_rules
        from engine.schema import load_graph
        gp = CORE / "graphloops" / "graphs" / "review-loop-tdd.json"
        g, why = load_graph(str(gp))
        self.assertFalse(why)
        rules = load_rules(str(gp), g)
        for name in ("tdd_start", "tdd_red", "tdd_green"):
            self.assertIn(name, rules.BUILTINS)
        self.assertIn("tdd_tests_output", rules.POST_CHECKS)
        self.assertEqual(rules.SUITE_TIMEOUT, 1728000)
        # TDD 版の指示書（tdd/ の下。graph の置き場からの相対）は写しの中に在る。元の版の指示書（p3.fix.md など）は写さない
        # （works の役は各ブロックの commands/ の指示書で起こす）
        refs = {p for n in g["nodes"].values() for p in [n.get("prompt_file"), *(n.get("prompt_append") or [])]
                if p and "/tdd/" in p}
        self.assertEqual(len(refs), 3)
        for p in refs:
            self.assertTrue((gp.parent / p).resolve().is_file(), p)

    def test_deviations_are_recorded(self):
        """手直しの在る写しは COPIED_FROM の行の注記に『works の手直し』と書く。手直しの表の写しは COPIED_FROM に並ぶ"""
        rows = {ln.split()[0]: ln for ln in (CORE / "COPIED_FROM").read_text().splitlines()[1:]
                if ln.strip() and not ln.startswith("#")}
        for rel in DEVIATIONS:
            self.assertIn(rel, rows)
            self.assertIn("works の手直し", rows[rel])
        self.assertEqual([rel for rel, ln in rows.items() if "works の手直し" in ln], list(DEVIATIONS))

    def test_copies_are_byte_identical_to_the_commit(self):
        """COPIED_FROM に並ぶ写しは、1 行目の commit の同じパスの中身とバイト単位で同じ（写しは直さない。DEVIATIONS の手直しだけを除く）"""
        lines = (CORE / "COPIED_FROM").read_text().splitlines()
        commit = lines[0].split()[0]
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((CORE / rel).read_bytes(), expected_copy(rel, src))

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
