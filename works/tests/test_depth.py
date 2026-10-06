"""単位ごとの深さ（darkfactory/lib/depth.py。計画 docs/plans/2026-10-06-variable-depth.md）の検査。関数を直に呼び、一時の置き場に
控えを書くだけ（FAST。盤面・git・子のプロセスなし）。

語:
- 深さ: 単位の工程の厚さ。標準は今の振る舞いのすべて、軽量は測りで何も見つけなかった確かめ（レンズ・コメントの削除候補）を省く。
- 項目の欄: 修正案の項目ごとの works の欄（allowed_paths・tests・rewrite_tests・unit_keys）。
- 上げる信号: 修正の後に単位を標準へ上げる事実（食い違いの申し出・止めた単位・案の直し・再審・答えていない問い）。

見る物:
- 決め 3 の 5 つの条件を全部満たす単位だけが軽量で、1 つ外れれば標準と理由
- thickness の名指しで全部の単位を固定する（自動と空は機械が決める）
- 信号で上げる（単位に結べる物はその単位、結べない物は全部）・下げない
- run の深さは全部が軽量の時だけ軽量（単位が無ければ標準）
- 省く理由と報告の行（軽量で省いた物を名指す）
- 控えの書き読み
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import depth  # noqa: E402

U1, U2 = "u1: 一つ目の根本", "u2: 二つ目の根本"


def item(keys, paths=("a/b.py",), tests=1, rewrites=0):
    return {"unit_keys": list(keys), "allowed_paths": list(paths),
            "tests": [{"id": f"t.py::T::t{i}"} for i in range(tests)],
            "rewrite_tests": [{"id": f"r.py::R::r{i}"} for i in range(rewrites)]}


class UnitDepthCase(unittest.TestCase):
    def test_small_unit_with_checks_is_light(self):
        got, why = depth.unit_depth([item([U1], paths=("a.py", "b.py", "tests/t.py"), tests=1, rewrites=1)], U1, checked=True)
        self.assertEqual(got, depth.LIGHT)
        self.assertTrue(why)

    def test_each_condition_falls_to_standard_with_reason(self):
        cases = {
            "項目": ([item([U2])], True),
            "4 個": ([item([U1], paths=("a.py", "b.py", "c.py", "d.py"))], True),
            "glob": ([item([U1], paths=("tests/*.json",))], True),
            "3 本": ([item([U1], tests=2, rewrites=1)], True),
            "約束の形": ([item([U1], paths=("blk-x/schemas/a.schema.json",))], True),
            ".yaml": ([item([U1], paths=("darkfactory/darkfactory.yaml",))], True),
            "機械の確かめ": ([item([U1])], False),
        }
        for word, (items, checked) in cases.items():
            with self.subTest(word=word):
                got, why = depth.unit_depth(items, U1, checked=checked)
                self.assertEqual(got, depth.STANDARD)
                self.assertTrue(any(word in w for w in why), why)

    def test_no_items_is_standard(self):
        self.assertEqual(depth.unit_depth(None, U1, checked=True)[0], depth.STANDARD)


class DecideCase(unittest.TestCase):
    def test_auto_decides_per_unit(self):
        doc = depth.decide_doc([item([U1]), item([U2], paths=("a", "b", "c", "d"))], [U1, U2], forced="自動", checked=True)
        self.assertEqual({k: v["depth"] for k, v in doc["units"].items()}, {U1: depth.LIGHT, U2: depth.STANDARD})
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)

    def test_empty_forced_is_auto(self):
        doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
        self.assertEqual(doc["units"][U1]["depth"], depth.LIGHT)

    def test_forced_word_fixes_every_unit(self):
        big = item([U1], paths=("a", "b", "c", "d", "e"), tests=5)
        doc = depth.decide_doc([big], [U1], forced=depth.LIGHT, checked=False)
        self.assertEqual(doc["units"][U1]["depth"], depth.LIGHT)
        self.assertIn("名指し", " ".join(doc["units"][U1]["why"]))
        doc = depth.decide_doc([item([U1])], [U1], forced=depth.STANDARD, checked=True)
        self.assertEqual(doc["units"][U1]["depth"], depth.STANDARD)

    def test_no_units_is_standard_run(self):
        doc = depth.decide_doc(None, [], forced="", checked=True)
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
        self.assertEqual(depth.skip_reason(doc), "")


class RaiseCase(unittest.TestCase):
    def setUp(self):
        self.doc = depth.decide_doc([item([U1]), item([U2])], [U1, U2], forced="", checked=True)
        self.assertEqual(depth.run_depth(self.doc), depth.LIGHT)

    def test_unit_signal_raises_only_that_unit(self):
        got = depth.raise_doc(self.doc, units={U1: "食い違いの申し出"}, run=[])
        self.assertEqual(got["units"][U1]["depth"], depth.STANDARD)
        self.assertEqual(got["units"][U2]["depth"], depth.LIGHT)
        self.assertIn("食い違いの申し出", " ".join(got["units"][U1]["why"]))
        self.assertEqual(depth.run_depth(got), depth.STANDARD)

    def test_run_signal_raises_every_unit(self):
        got = depth.raise_doc(self.doc, units={}, run=["案の直しが走った"])
        self.assertEqual({v["depth"] for v in got["units"].values()}, {depth.STANDARD})
        self.assertIn("案の直しが走った", got["raised"])

    def test_signal_on_unknown_unit_is_kept_as_raised(self):
        got = depth.raise_doc(self.doc, units={"u9": "止めた"}, run=[])
        self.assertEqual(depth.run_depth(got), depth.LIGHT)
        self.assertTrue(any("u9" in r for r in got["raised"]))

    def test_no_signal_keeps_light(self):
        got = depth.raise_doc(self.doc, units={}, run=[])
        self.assertEqual(depth.run_depth(got), depth.LIGHT)


class LinesCase(unittest.TestCase):
    def test_light_run_names_what_it_skipped(self):
        doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
        reason = depth.skip_reason(doc)
        self.assertIn("軽量", reason)
        text = "\n".join(depth.lines(doc))
        self.assertIn("軽量で省いた: ", text)
        self.assertIn("レンズ", text)
        self.assertIn("r1.comment_candidates", text)

    def test_standard_run_skips_nothing(self):
        doc = depth.decide_doc([item([U1], tests=4)], [U1], forced="", checked=True)
        self.assertEqual(depth.skip_reason(doc), "")
        text = "\n".join(depth.lines(doc))
        self.assertNotIn("軽量で省いた", text)
        self.assertIn("標準", text)


class FileCase(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
            path = depth.write(pathlib.Path(d), doc)
            self.assertEqual(path.name, depth.FILE)
            self.assertEqual(depth.read(pathlib.Path(d)), doc)
            self.assertEqual(json.loads(depth.unit_map(doc)), {U1: depth.LIGHT})

    def test_read_missing_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(depth.read(pathlib.Path(d)))


if __name__ == "__main__":
    unittest.main()
