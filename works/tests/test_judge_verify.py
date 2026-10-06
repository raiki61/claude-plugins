"""判定の根を開く（線の木の段 3。設計 docs/plans/2026-10-06-judge-verify.md）: 判定のブロックの裏取りの支度とまとめ
（blk-judge/lib/judgeverify.py）、修正案の役の指示書に貼る申し送りの節（planblk.verify_part）、報告の冒頭 1 の行（report.verify_lines）。
偽の盤面（SimpleNamespace に dir・scope・round・work・state・trace・stop）と一時の置き場で関数を直に呼ぶ（FAST。盤面・git・子の
プロセスなし。作業ツリーの姿は accept.tree_state・tree_moved を差し替える）"""
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
for p in (ROOT / ".shared" / "core", ROOT / "blk-judge" / "lib", ROOT / "blk-plan" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import accept  # noqa: E402
import judgeverify as jv  # noqa: E402
import planblk  # noqa: E402
import report  # noqa: E402

KEY1 = "stats.py+mean: 分母が len(xs) - 1 になっている"
KEY2 = "stats.py+clamp: 上限を超えた値に lo を返す"
KEY3 = "stats.py+fmt: 小数の桁が 2 でない"


def unit(key, label="block", disposition="do-now", reason="事実: stats.py の mean は sum(xs) / (len(xs) - 1) を返す"):
    return {"key": key, "label": label, "disposition": disposition, "reason": reason,
            "origin_analysis": "算術平均と不偏分散の分母の取り違え"}


def judgment(*units):
    return {"framing": "依頼の 2 件はどちらも stats.py の算術の取り違え", "one_shot": "分母と上限の枝を直す",
            "units": list(units), "questions": [], "precedents": []}


def good_answer(n, key, verdict="root", **extra):
    return {"unit": n, "verdict": verdict, "evidence_found": True,
            "evidence": f"stats.py:9 を読んだ。{key} の言う式がそのまま在る",
            "location_ok": True, "location": "stats.py:9", "why": "式を直せば試験の期待どおりの値になる", **extra}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.traces, self.stops = [], []
        self.b = self.board()
        snap = {"porcelain": "", "diff_sha256": "x", "ignored": [], "head": "h", "ref": "main"}
        for target, value in (("tree_state", snap), ("tree_moved", [])):
            patcher = mock.patch.object(accept, target, return_value=value)
            self.addCleanup(patcher.stop)
            setattr(self, target, patcher.start())

    def board(self, rnd=1, state=None):
        d = self.tmp / "art" / "board"
        d.mkdir(parents=True, exist_ok=True)

        def work(name):
            public = name == jv.VERIFY_FILE
            p = (d if public else d / "judging") / f"r{rnd}" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        return types.SimpleNamespace(dir=d, scope="judging", round=rnd, work=work, state=state or {},
                                     trace=lambda op, **kw: self.traces.append({"op": op, **kw}),
                                     stop=lambda reason, by: self.stops.append((reason, by)))

    def prep(self, doc):
        return jv.prep_on(self.b, doc, self.repo)

    def write_answer(self, n, body):
        p = jv.answer_file(self.b, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    def write_synergy(self, body):
        p = jv.synergy_file(self.b)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    def merged(self):
        return json.loads(self.b.work(jv.VERIFY_FILE).read_text(encoding="utf-8"))


class PrepCase(Base):
    def test_no_judgment_or_one_open_unit_does_not_go(self):
        """判定が無い・開いた単位が 2 つ未満（1 単位の時は裏取りも起こさない。設計の「1 単位の時は回さない」）は go 偽で、
        前の残りの申し送りを消す"""
        stale = self.b.work(jv.VERIFY_FILE)
        stale.write_text("{}", encoding="utf-8")
        self.assertEqual(self.prep(None), {"ok": True, "go": False, "prompt_file": ""})
        self.assertFalse(stale.exists())
        one = judgment(unit(KEY1), unit(KEY2, label="nit", disposition="defer"))   # 開いた単位は 1 つ
        self.assertIs(self.prep(one)["go"], False)
        self.assertFalse(self.b.work(jv.VERIFY_FILE).exists())

    def test_halted_board_does_not_go(self):
        self.b = self.board(state={"halted": {"reason": "止めた"}})
        self.assertIs(self.prep(judgment(unit(KEY1), unit(KEY2)))["go"], False)

    def test_two_open_units_write_briefs_and_prompt(self):
        got = self.prep(judgment(unit(KEY1), unit(KEY2), unit(KEY3, label="info", disposition="defer")))
        self.assertIs(got["go"], True)
        prompt = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        briefs = sorted(pathlib.Path(got["prompt_file"]).parent.glob("*.md"))
        self.assertEqual([p.name for p in briefs], ["prompt.md", "synergy.md", "unit-1.md", "unit-2.md"])
        for p in briefs:
            if p.name != "prompt.md":
                self.assertIn(str(p), prompt, "束ね役の指示書が下請けのファイルを全部名指す")
        self.assertIn(jv.SUBAGENT_TYPE, prompt)
        self.assertIn("1 つのメッセージ", prompt)
        self.assertIn('"summary"', prompt)
        one = (pathlib.Path(got["prompt_file"]).parent / "unit-1.md").read_text(encoding="utf-8")
        two = (pathlib.Path(got["prompt_file"]).parent / "unit-2.md").read_text(encoding="utf-8")
        self.assertIn(KEY1, one)
        self.assertNotIn(KEY2, one, "下請けのファイルは自分の単位だけを持つ")
        self.assertNotIn(KEY3, one + two, "開いていない単位は裏取りしない")
        head1, _, _ = one.partition(jv.UNIT_HEAD.format(n=1))
        head2, _, _ = two.partition(jv.UNIT_HEAD.format(n=2))
        self.assertTrue(head1)
        self.assertEqual(head1, head2, "共通の頭は全部の単位で同じバイト（プロンプトのキャッシュ）")
        ans = pathlib.Path(jv.answer_in(one))
        self.assertEqual(ans, jv.answer_file(self.b, 1))
        self.assertNotIn(str(self.b.dir), str(ans), "答えのファイルは盤面の外（盤面は役が書けない）")
        syn = (pathlib.Path(got["prompt_file"]).parent / "synergy.md").read_text(encoding="utf-8")
        for k in (KEY1, KEY2):
            self.assertIn(k, syn)
        self.assertEqual(pathlib.Path(jv.answer_in(syn)), jv.synergy_file(self.b))
        self.tree_state.assert_called_once()

    def test_prep_places_unverified_notes_first(self):
        """束ね役が落ちても修正案の役と報告に「確かめていない」が届くように、支度が初めの申し送りを置く"""
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        doc = self.merged()
        self.assertEqual([(u["n"], u["key"], u["state"]) for u in doc["units"]],
                         [(1, KEY1, jv.UNVERIFIED), (2, KEY2, jv.UNVERIFIED)])
        self.assertEqual(doc["synergy"]["state"], jv.UNVERIFIED)

    def test_prep_clears_old_answers(self):
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        self.write_answer(1, good_answer(1, KEY1))
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        self.assertFalse(jv.answer_file(self.b, 1).exists(), "前の起動の答えを今の判定の答えに数えない")


class MergeCase(Base):
    def setUp(self):
        super().setUp()
        self.prep(judgment(unit(KEY1), unit(KEY2)))

    def test_good_answers_and_synergy_are_merged_with_keys(self):
        self.write_answer(1, good_answer(1, KEY1))
        self.write_answer(2, good_answer(2, KEY2, verdict="not_root", real_root=f"単位 1（{KEY1}）の式の取り違えと同じ根"))
        self.write_synergy({"why": "2 つの単位は同じ関数の群の算術の取り違え",
                            "duplicates": [{"units": [1, 2], "why": "同じ取り違えの別の現れ"}], "relations": [],
                            "order": [{"first": 1, "then": 2, "why": "mean を先に直すと clamp の試験の前提が揃う"}]})
        got = jv.merge_on(self.b, self.repo)
        self.assertEqual(got, {"ok": True, "verify_file": str(self.b.work(jv.VERIFY_FILE)), "verified": 2, "unverified": 0})
        doc = self.merged()
        self.assertEqual([(u["key"], u["state"], u["verdict"]) for u in doc["units"]],
                         [(KEY1, jv.CHECKED, "root"), (KEY2, jv.CHECKED, "not_root")])
        self.assertIn("同じ根", doc["units"][1]["real_root"])
        syn = doc["synergy"]
        self.assertEqual(syn["state"], jv.CHECKED)
        self.assertEqual(syn["duplicates"], [{"units": [KEY1, KEY2], "why": "同じ取り違えの別の現れ"}])
        self.assertEqual(syn["order"], [{"first": KEY1, "then": KEY2, "why": "mean を先に直すと clamp の試験の前提が揃う"}])
        self.assertEqual(self.traces, [{"op": jv.TRACE_OP, "verified": 2, "unverified": 0, "synergy": True}])
        self.assertEqual(self.stops, [])

    def test_missing_or_bad_answers_are_named_unverified(self):
        """答えの無い単位・型に合わない答え・not_root で本当の根を書かない答えは「確かめられなかった」と誤りの行で控える
        （出し直しの輪は持たない。単位は消さない）"""
        self.write_answer(2, good_answer(2, KEY2, verdict="not_root"))
        self.write_synergy({"why": "短い"})
        got = jv.merge_on(self.b, self.repo)
        self.assertEqual((got["verified"], got["unverified"]), (0, 2))
        doc = self.merged()
        self.assertEqual([u["key"] for u in doc["units"]], [KEY1, KEY2], "単位は消さない")
        self.assertTrue(any("答えのファイルが無い" in e for e in doc["units"][0]["errors"]))
        self.assertTrue(any("real_root" in e for e in doc["units"][1]["errors"]))
        self.assertEqual(doc["synergy"]["state"], jv.UNVERIFIED)
        self.assertTrue(doc["synergy"]["errors"])

    def test_wrong_unit_number_and_out_of_range_synergy(self):
        self.write_answer(1, good_answer(2, KEY1))
        self.write_synergy({"why": "単位 3 と単位 1 が重なる", "duplicates": [{"units": [1, 3], "why": "同じ根の別の現れ"}],
                            "relations": [], "order": []})
        jv.merge_on(self.b, self.repo)
        doc = self.merged()
        self.assertEqual(doc["units"][0]["state"], jv.UNVERIFIED)
        self.assertTrue(any("unit" in e for e in doc["units"][0]["errors"]))
        self.assertEqual(doc["synergy"]["state"], jv.UNVERIFIED)
        self.assertTrue(any("3" in e for e in doc["synergy"]["errors"]))

    def test_tree_moved_stops_board(self):
        self.tree_moved.return_value = ["作業ツリーの差分が変わった"]
        self.write_answer(1, good_answer(1, KEY1))
        jv.merge_on(self.b, self.repo)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.stops[0][1], jv.STOP_BY)
        self.assertIn("作業ツリーの差分が変わった", self.stops[0][0])

    def test_merge_without_prep_record_is_empty(self):
        self.b = self.board(rnd=2)
        self.assertEqual(jv.merge_on(self.b, self.repo), {"ok": True, "verify_file": "", "verified": 0, "unverified": 0})


class PlanNotesCase(Base):
    """修正案の役の指示書に貼る申し送りの節（planblk.verify_part）。入力は形だけで受ける（出どころを名指さない）"""

    def notes(self):
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        self.write_answer(1, good_answer(1, KEY1))
        self.write_answer(2, good_answer(2, KEY2, verdict="not_root", location_ok=False, location="stats.py:20 の fmt",
                                         real_root="単位 1 と同じ取り違え"))
        self.write_synergy({"why": "2 つの単位は同じ群", "duplicates": [{"units": [1, 2], "why": "同じ取り違え"}],
                            "relations": [], "order": []})
        return jv.merge_on(self.b, self.repo)["verify_file"]

    def test_empty_inputs_give_no_section(self):
        for v in ("", "null", None):
            self.assertEqual(planblk.verify_part(v), "")

    def test_section_names_every_unit_and_keeps_obligation(self):
        text = planblk.verify_part(self.notes())
        self.assertTrue(text.startswith(planblk.VERIFY_HEAD))
        for needle in (KEY1, KEY2, "根本でない", "単位 1 と同じ取り違え", "stats.py:20 の fmt", "重複", "外せない"):
            self.assertIn(needle, text)

    def test_unverified_rows_are_said(self):
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        text = planblk.verify_part(str(self.b.work(jv.VERIFY_FILE)))
        self.assertIn("確かめられなかった", text)

    def test_unreadable_file_is_said(self):
        text = planblk.verify_part(str(self.tmp / "none.json"))
        self.assertIn("読めない", text)


class ReportLinesCase(Base):
    def test_lines_name_not_root_and_unverified(self):
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        self.write_answer(1, good_answer(1, KEY1, verdict="not_root", real_root="依頼の入力の形の取り違え"))
        jv.merge_on(self.b, self.repo)
        lines = report.verify_lines(types.SimpleNamespace(dir=self.b.dir))
        text = "\n".join(lines)
        self.assertIn(KEY1, text)
        self.assertIn("根本でない", text)
        self.assertIn(KEY2, text)
        self.assertIn("確かめられなかった", text)

    def test_all_root_is_one_line(self):
        self.prep(judgment(unit(KEY1), unit(KEY2)))
        self.write_answer(1, good_answer(1, KEY1))
        self.write_answer(2, good_answer(2, KEY2))
        self.write_synergy({"why": "2 つの単位は別の関数で重ならない", "duplicates": [], "relations": [], "order": []})
        jv.merge_on(self.b, self.repo)
        lines = report.verify_lines(types.SimpleNamespace(dir=self.b.dir))
        self.assertEqual(len(lines), 1)
        self.assertIn("2 単位", lines[0])

    def test_no_notes_no_lines(self):
        self.assertEqual(report.verify_lines(types.SimpleNamespace(dir=self.b.dir)), [])


if __name__ == "__main__":
    unittest.main()
