"""差分の審査の返答の works 側の 2 判定の欄（deltamarks）。役の型への重ね・欠けと誤りの行・欄を外す口・盤面の外の控えの
読み書きを、関数を直に呼んで見る（FAST。盤面・git・子のプロセスなし。控えは偽の b に一時の置き場を持たせる）"""
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import accept  # noqa: E402
import deltamarks  # noqa: E402
import refix  # noqa: E402

GRAPH = accept.GRAPH_PATH

FACE = {"key": "clamp の docstring が古いまま", "kind": "contract_drift", "where": "stats.py",
        "cite": "上限を超えたときに lo を返している", "why": "頭の docstring が直した後の振る舞いと食い違う（brief の項目 1 の約束）"}
PASS = {"verdict": "pass", "items": [], "read": "修正案の項目 1 と差分の stats.py・test_stats.py を読んだ"}
NA = {**PASS, "verdict": "not_applicable"}
GOOD_Q = {"verdict": "pass", "why": "足したテストは stats.mean を直に呼び、mock の値を断言していない"}
ITEMS = [{"item": 1, "unit_keys": ["k"]}]
MISS = {"item": 1, "kind": "missing", "face_key": FACE["key"], "why": "brief の adds の median が差分に無い（項目 1）"}
UNV = {"item": 1, "kind": "unverifiable", "face_key": "", "why": "受け入れのテストの赤は差分だけからは確かめられない"}


def reply(faces=(), compliance=PASS, quality=GOOD_Q):
    return {"faces": list(faces), "checks": [], "faces_none": "差分の stats.py を読み、穴は無いと確かめた",
            "compliance": compliance, "quality": quality}


class FakeBoard:
    """deltamarks が読む b の口だけ（work・trace・round）。trace は行を控える"""

    def __init__(self, d: pathlib.Path, rnd: int):
        self.dir, self.round, self.traced = d, rnd, []

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def trace(self, op, **kw):
        self.traced.append({"op": op, **kw})


class DeltaMarksCase(unittest.TestCase):
    def test_role_schema_carries_verdicts_on_first_review_only(self):
        self.assertTrue({"compliance", "quality"} <= set(accept.role_schema("p3.delta_review")["required"]))
        self.assertNotIn("compliance", json.dumps(accept.role_schema("p3.delta_review2")))
        copy = json.loads(GRAPH.read_text(encoding="utf-8"))["nodes"]["p3.delta_review"]["schema"]
        self.assertNotIn("compliance", json.dumps(copy))
        self.assertEqual(deltamarks.NODE, refix.passes()[1]["review"])

    def test_no_plan_needs_not_applicable(self):
        self.assertTrue(any(g.startswith("compliance.verdict") for g in deltamarks.gaps(reply(), None)))
        self.assertEqual(deltamarks.gaps(reply(compliance=NA), None), [])
        self.assertTrue(any(g.startswith("compliance.verdict") for g in deltamarks.gaps(reply(compliance=NA), ITEMS)))
        self.assertTrue(any(g.startswith("compliance.items") for g in deltamarks.gaps(reply(compliance={**NA, "items": [UNV]}), None)))

    def test_fail_row_needs_face_key_in_faces(self):
        bad = {**MISS, "face_key": "nope-nope"}
        got = deltamarks.gaps(reply(compliance={**PASS, "verdict": "fail", "items": [bad]}), ITEMS)
        self.assertTrue(any("face_key" in g and "nope-nope" in g for g in got), got)
        self.assertEqual(deltamarks.gaps(reply([FACE], {**PASS, "verdict": "fail", "items": [MISS]}), ITEMS), [])

    def test_verdict_must_match_rows(self):
        self.assertTrue(deltamarks.gaps(reply([FACE], {**PASS, "items": [MISS]}), ITEMS))          # pass なのに missing
        self.assertTrue(deltamarks.gaps(reply(compliance={**PASS, "verdict": "fail", "items": [UNV]}), ITEMS))
        self.assertEqual(deltamarks.gaps(reply(compliance={**PASS, "verdict": "unverifiable", "items": [UNV]}), ITEMS), [])

    def test_quality_fail_iff_untied_faces(self):
        self.assertTrue(deltamarks.gaps(reply([FACE]), ITEMS))                                     # 結ばれない穴で pass
        self.assertEqual(deltamarks.gaps(reply([FACE], quality={**GOOD_Q, "verdict": "fail"}), ITEMS), [])
        self.assertTrue(deltamarks.gaps(reply(quality={**GOOD_Q, "verdict": "fail"}), ITEMS))     # 穴が無いのに fail

    def test_unverifiable_row_cannot_bind_face(self):
        """face_key で穴に結ぶのは落ちた行だけ。unverifiable の行は face_key を空にし、穴を結べない（品質は fail のまま）"""
        tied = {**UNV, "face_key": FACE["key"]}
        got = deltamarks.gaps(reply([FACE], {**PASS, "verdict": "unverifiable", "items": [tied]}), ITEMS)
        self.assertTrue(any(g.startswith("compliance.items[0].face_key") for g in got), got)
        self.assertTrue(any(g.startswith("quality.verdict") for g in got), got)   # 結ばれない穴が在るので pass は誤り
        self.assertEqual(deltamarks.gaps(reply([FACE], {**PASS, "verdict": "unverifiable", "items": [UNV]},
                                               {**GOOD_Q, "verdict": "fail"}), ITEMS), [])

    def test_fail_row_on_held_item_rejected(self):
        """裁定で外れた項目（held）に missing・extra・misunderstood の行を書けば拒む（手直しの義務にしない）。unverifiable は通す"""
        held = [{"item": 1, "unit_keys": ["k"], "held": "fix_plan_item の裁定 c1-1（案の項目 1）"}]
        fail = {**PASS, "verdict": "fail", "items": [MISS]}
        got = deltamarks.gaps(reply([FACE], fail), held)
        self.assertTrue(any("compliance.items[0].item（1）" in g and "held" in g for g in got), got)
        self.assertEqual(deltamarks.gaps(reply([FACE], fail), ITEMS), [])
        unv = {**PASS, "verdict": "unverifiable", "items": [UNV]}
        self.assertEqual(deltamarks.gaps(reply(compliance=unv), held), [])

    def test_malformed_faces(self):
        """faces が key を持つ object の並びでない返答は、2 判定の欄を照らさない（写しの型が拒む）"""
        for faces in ("x", None, ["x"], [{"kind": "copy"}], [{"key": 1}]):
            with self.subTest(faces=faces):
                self.assertTrue(deltamarks.malformed({**reply(), "faces": faces}))
        self.assertTrue(deltamarks.malformed("x"))
        self.assertFalse(deltamarks.malformed(reply([FACE])))
        self.assertFalse(deltamarks.malformed(reply()))

    def test_item_number_in_range(self):
        far = {**UNV, "item": 2}
        got = deltamarks.gaps(reply(compliance={**PASS, "verdict": "unverifiable", "items": [far]}), ITEMS)
        self.assertTrue(any(g.startswith("compliance.items[0].item") for g in got), got)

    def test_malformed_does_not_raise(self):
        bad = reply(compliance="x")
        del bad["quality"]
        got = deltamarks.gaps(bad, ITEMS)
        self.assertTrue(any(g.startswith("compliance") for g in got), got)
        self.assertTrue(any(g.startswith("quality") for g in got), got)
        for broken in ("x", None, {"faces": "x", "compliance": {"verdict": "pass"}, "quality": []}):
            with self.subTest(broken=broken):
                self.assertTrue(deltamarks.gaps(broken, ITEMS))

    def test_split_save_read(self):
        full = reply([FACE], {**PASS, "verdict": "fail", "items": [MISS]})
        bare, verdicts = deltamarks.split(full)
        self.assertFalse({"compliance", "quality"} & set(bare))
        self.assertEqual(set(bare), {"faces", "checks", "faces_none"})
        self.assertEqual(verdicts, {"compliance": full["compliance"], "quality": full["quality"]})
        self.assertIn("compliance", full)   # 渡した返答は変えない（写しを返す）
        with tempfile.TemporaryDirectory() as d:
            b = FakeBoard(pathlib.Path(d), 2)
            self.assertIsNone(deltamarks.read(b))
            deltamarks.save(b, verdicts)
            self.assertEqual(deltamarks.read(b), {"round": 2, **verdicts})
            self.assertEqual(b.traced, [{"op": deltamarks.SAVED_OP, "compliance": "fail", "quality": "pass"}])
            self.assertEqual(deltamarks.fail_rows(deltamarks.read(b)), [MISS])
            self.assertEqual([p.name for p in b.work("x").parent.iterdir()], [deltamarks.VERDICTS_FILE])   # 一時のファイルは残らない
            doc = json.loads(b.work(deltamarks.VERDICTS_FILE).read_text(encoding="utf-8"))
            b.work(deltamarks.VERDICTS_FILE).write_text(json.dumps({**doc, "round": 1}), encoding="utf-8")
            self.assertIsNone(deltamarks.read(b))   # 周が違う
            b.work(deltamarks.VERDICTS_FILE).write_text("{", encoding="utf-8")
            self.assertIsNone(deltamarks.read(b))   # 読めない
        self.assertEqual(deltamarks.fail_rows(None), [])
        self.assertEqual(deltamarks.fail_rows({"compliance": {"items": [UNV]}}), [])


if __name__ == "__main__":
    unittest.main()
