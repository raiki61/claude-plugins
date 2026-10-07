"""修正の形（fix_shape）の読み口（.shared/core/fixshape.py）の検査。一時の置き場の JSON を読むだけ（FAST。git・子のプロセスなし）。

語:
- 形: 修正の工程の作り方の 4 つ（current・af・g3・g1）。入力が空なら既定の g3。
- 盤面の控え: 線の start が書く r1/start.json（鍵 fix_shape）と、後の振り分けが選んだ形の控え r1/fix-shape.json。

見る物:
- word は前後の空白を除き、空は既定、4 つの外は ValueError（4 つの語を名指す）
- shape_at は 振り分けの控え → start の控え → af（記録の無い前の版の盤面）の順に読み、壊れた控え・語の外は ValueError
- choose が書いた控えは start の控えより勝つ。語の外・空の by・why は ValueError
- START_REL は 1 周目の entry.START_FILE
- denied_tools は形と印の名から拒む道具を返す（g3 以外の座の節で Skill・g1 と g3 の外の修正役で Agent・g3 の外の輪の役で Agent。
  この順。依頼 243 の 2 で g3 の修正役も単位ごとの下請けを、g3 の輪の役も並べの周に単位の下請けを Agent で起こす）
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import entry  # noqa: E402
import fixshape  # noqa: E402


def put(path: pathlib.Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class FixShapeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_word_default_and_refuses_outside(self):
        self.assertEqual(fixshape.word(""), "g3")
        self.assertEqual(fixshape.word(" af "), "af")
        with self.assertRaises(ValueError) as cm:
            fixshape.word("g2")
        self.assertIn("current / af / g3 / g1", str(cm.exception))

    def test_shape_at_reads_start_record(self):
        self.assertEqual(fixshape.shape_at(self.tmp), "af")                       # start.json が無い（前の版の盤面）
        put(self.tmp / "r1" / "start.json", {"test_cmd": ""})
        self.assertEqual(fixshape.shape_at(self.tmp), "af")                       # 鍵が無い
        put(self.tmp / "r1" / "start.json", {"fix_shape": "g1"})
        self.assertEqual(fixshape.shape_at(self.tmp), "g1")
        self.assertFalse(fixshape.plain(self.tmp))
        for bad in ('{"fix_shape": "x"}', "{壊れた"):
            (self.tmp / "r1" / "start.json").write_text(bad, encoding="utf-8")
            with self.assertRaises(ValueError):
                fixshape.shape_at(self.tmp)

    def test_choice_wins_over_input(self):
        put(self.tmp / "r1" / "start.json", {"fix_shape": "g3"})
        fixshape.choose(self.tmp, "af", by="test", why="振り分けの継ぎ目の確かめ")
        self.assertEqual(fixshape.shape_at(self.tmp), "af")
        with self.assertRaises(ValueError):
            fixshape.choose(self.tmp, "x", by="test", why="知らない語")

    def test_start_rel_is_round_one_start_file(self):
        self.assertEqual(fixshape.START_REL, f"r1/{entry.START_FILE}")

    def test_plain_only_for_current(self):
        """平の run（current）だけが plain。choose の by・why が空なら ValueError（控えを書かない）"""
        put(self.tmp / "r1" / "start.json", {"fix_shape": "current"})
        self.assertTrue(fixshape.plain(self.tmp))
        for by, why in (("", "理由"), ("test", " ")):
            with self.subTest(by=by, why=why):
                with self.assertRaises(ValueError):
                    fixshape.choose(self.tmp, "af", by=by, why=why)
        self.assertFalse((self.tmp / fixshape.CHOICE_REL).exists())

    def test_broken_choice_is_refused(self):
        """振り分けの控えが壊れている・語の外なら、start の控えへ黙って逃げずに ValueError"""
        put(self.tmp / "r1" / "start.json", {"fix_shape": "g3"})
        for bad in ('{"shape": "x"}', "{壊れた"):
            with self.subTest(bad=bad):
                (self.tmp / fixshape.CHOICE_REL).write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    fixshape.shape_at(self.tmp)

    def test_denied_tools_table(self):
        # TDD の輪の役は Agent を持たない（並べは枝ごとの節。docs/plans/2026-10-07-lane-nodes.md）。座の Skill は g3 だけ
        rows = {("g3", "tdd"): (), ("af", "tdd"): ("Skill",), ("current", "tdd"): ("Skill",), ("g1", "tdd"): ("Skill",),
                ("g3", "tdd-rest"): (), ("af", "tdd-rest"): ("Skill",), ("g3", "tdd-lane-2"): (), ("af", "tdd-lane-1"): ("Skill",),
                ("g1", "fix"): (), ("g1", "fix-ruled"): (), ("g3", "fix"): (), ("g3", "fix-ruled"): (), ("af", "fix-ruled"): ("Agent",),
                ("af", "judge"): (), ("g3", "local-review"): (), ("g3", "refix"): (), ("af", "refix2"): ("Skill",),
                ("current", "refix"): ("Skill",), ("g3", "review"): ()}
        for (shape, node), want in rows.items():
            self.assertEqual(fixshape.denied_tools(shape, node), want, (shape, node))

    def test_recorded_tells_key_presence_and_fixture_mark(self):
        """recorded は start の控えの鍵の有無を隠さない（shape_at は無い時に af を返す。測る関数が記録の欠けを数える。
        preflight F6）。固定材料の印は fixture.adopted と同じ鍵を同じ 1 つの読み口から引く"""
        self.assertEqual(fixshape.recorded(self.tmp), {"shape": None, "fixture": None})       # 控えが無い
        put(self.tmp / "r1" / "start.json", {"test_cmd": ""})
        self.assertEqual(fixshape.recorded(self.tmp), {"shape": None, "fixture": None})       # 鍵が無い
        mark = {"source_run": "run-a", "manifest_sha256": "0" * 64, "at": "2026-10-02T00:00:00"}
        put(self.tmp / "r1" / "start.json", {"fix_shape": "g1", "fixture": mark})
        self.assertEqual(fixshape.recorded(self.tmp), {"shape": "g1", "fixture": mark})
        put(self.tmp / "r1" / "start.json", {"fix_shape": "af", "fixture": "壊れた印"})
        self.assertEqual(fixshape.recorded(self.tmp), {"shape": "af", "fixture": None})       # object でない印は無い物
        for bad in ("{壊れた", "[1]"):
            with self.subTest(bad=bad):
                (self.tmp / "r1" / "start.json").write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    fixshape.recorded(self.tmp)

    def test_fixture_key_is_the_fixture_module_key(self):
        import fixture
        self.assertEqual(fixshape.FIXTURE_KEY, fixture.KEY)

    def test_agent_nodes_are_the_fix_roles(self):
        """Agent を拒む節は修正役の 2 つ（Task 7 で YAML に Agent を足す節。先に拒む）と、修正役の並べの枝の役（審査の下請けを起こす。
        docs/plans/2026-10-07-fix-lane-nodes.md）"""
        self.assertEqual(fixshape.AGENT_NODES, frozenset({"fix", "fix-ruled", "fix-lane-1", "fix-lane-2", "fix-lane-3"}))
        self.assertEqual(fixshape.denied_tools("af", "fix-lane-1"), ("Agent",), "g1・g3 の外の形では拒む（枝は g3 だけで切る）")
        self.assertEqual(fixshape.denied_tools("g3", "fix-lane-2"), ())


if __name__ == "__main__":
    unittest.main()
