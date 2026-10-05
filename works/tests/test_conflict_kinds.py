"""食い違いの申し出の種類の欄 kind（conflict.DIV_KINDS の 6 つ）と、which_is_right との対の確かめ（依頼 211）。

- kind は申し出の必須の欄（conflict.FIELDS の末尾）。語の外の値は拒み、文に種類の名を並べる
- 対: kind query_hits_fixed ⇔ which_is_right query、kind needs_context なら which_is_right unknown。外れは両方の欄を名指して拒む
- 語の定数 conflict.WORD（216 の seams.json の words と同じ綴り）・TDD の輪の申し出の見本と決まりの節が種類を全部言う
- 控えの行と trace の行に kind が載り、種類の内訳（kind_counts）が数える。kind の無い前の形の行も読めて「無し」と出る
- brief_vs_judgment は、その単位の brief の行（planbrief.by_unit_at の形）を between に名指す時だけ通す。brief の無い run・
  ほかの項目の brief だけの名指しは拒む。brief の控えが壊れていれば brief は無い側（通さない側）に倒す
- 裁定 fix_plan_item（案の項目そのものの誤り）は直す裁定でなく、範囲 limits を持たず、grounds にその単位の brief の行を
  名指す時だけ通る（brief_vs_judgment と同じ 1 つの決まり）。役の返答の形・裁定役の決まりの節がこの語を持つ
- 直す義務から外す単位は「直す裁定でない裁定を受けた単位」の 1 つの決まりで、2 つ当たれば DECISIONS の順で先の理由
- fix_plan_item の行の案の直しの状態（waiting・amended・gave_up。依頼 226）: 裁定で waiting に置き、set_replan の 1 か所で
  amended か gave_up に移す。amended の単位は直す義務に戻り、gave_up の行は ask_human の行として字のまま並ぶ。欄の無い前の形の
  行は waiting と読む
- 1 回目に受け付けた返答の控え（fix-held-reply.json）: 今の周に p3.fix を受ける前だけ読み、その単位を直す義務から外し、
  2 回目の返答に単位ごとに合わせる。役が申告した bash_writes を残す
盤面・git・子のプロセスは使わない（関数を直に呼ぶ。一時の置き場に種のファイルと控えを書くだけ）。
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
BLK_FIX = BLK
BLK_REFIX = ROOT / "blk-refix"
BLK_DELTA = ROOT / "blk-delta"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))

import conflict  # noqa: E402
import fixrules  # noqa: E402
import gatemarks  # noqa: E402
import planbrief  # noqa: E402
import ruling  # noqa: E402
import tddloop  # noqa: E402

KEY = "stats.py clamp: 上限を超えた値に lo を返す"
ITEM = {"unit_key": KEY, "between": ["stats.py:3", "test_stats.py:2"],
        "why_both_cannot_hold": "テストは上限 hi を期待し、今のコードは lo を返す——両方は成り立たない",
        "which_is_right": "request", "kind": "unnamed_test_broke"}
OTHER = "stats.py mean: 分母が len - 1"
MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
BRIEFS: dict = {}   # BriefKindCase.setUp が一時の置き場の brief で埋める（planbrief.by_unit_at の形）


def seed(repo: pathlib.Path) -> None:
    """名指しの種（stats.py は 4 行・test_stats.py は 2 行）"""
    (repo / "stats.py").write_text("def clamp(x, lo, hi):\n    if x > hi:\n        return lo\n    return x\n",
                                   encoding="utf-8")
    (repo / "test_stats.py").write_text("def test_clamp():\n    assert clamp(11, 0, 10) == 10\n", encoding="utf-8")


class KindCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name)
        seed(self.repo)

    def errs(self, **over):
        return conflict.problems([{**ITEM, **over}], repo=self.repo, board_dir=self.repo, owed={KEY})

    def test_kind_is_a_required_field(self):
        self.assertEqual(conflict.FIELDS[-1], "kind")
        self.assertIn("kind", conflict.ITEM_SCHEMA["required"])
        item = dict(ITEM)
        item.pop("kind")
        got = conflict.problems([item], repo=self.repo, board_dir=self.repo, owed={KEY})
        self.assertTrue(any("kind" in e for e in got), got)

    def test_design_kinds_and_two_kept(self):
        self.assertEqual(conflict.DIV_KINDS, ("brief_vs_judgment", "unnamed_test_broke", "not_red", "scope_needed",
                                              "query_hits_fixed", "needs_context"))
        self.assertEqual(self.errs(), [])
        got = self.errs(kind="other")
        self.assertTrue(any("kind" in e and "needs_context" in e for e in got), got)

    def test_kind_and_which_must_pair(self):
        for over in ({"which_is_right": "query", "correct_lines": ["        return hi"]},   # kind が query_hits_fixed でない
                     {"kind": "query_hits_fixed"},                                          # which_is_right が query でない
                     {"kind": "needs_context", "which_is_right": "request"}):
            got = self.errs(**over)
            self.assertTrue(any("kind" in e and "which_is_right" in e for e in got), (over, got))
        self.assertEqual(self.errs(kind="needs_context", which_is_right="unknown"), [])

    def test_word_names_the_outlet(self):
        self.assertEqual(conflict.WORD, "divergence")

    def test_return_conflict_lists_every_kind(self):
        for k in conflict.DIV_KINDS:
            self.assertIn(k, tddloop.RETURN_CONFLICT)

    def test_rules_name_the_kinds(self):
        sec = fixrules.sections(fixrules.SHARED)["core-conflict"]
        for k in conflict.DIV_KINDS:
            self.assertIn(f"`{k}`", sec)
        self.assertIn('"kind"', fixrules.sections(fixrules.TDD)["tdd-remap"])


class FakeBoard:
    """盤面の代わり: work(name) は一時の置き場のファイル、round は 1、trace(op, **kw) は (op, kw) を traced に貯める。
    dir は盤面の根（scope の登録が無いので、include ごとに分かれた物を集める口 scopes.each は work の置き場に落ちる）"""

    def __init__(self, root: pathlib.Path):
        self.root = self.dir = root
        self.round = 1
        self.traced = []

    def work(self, name) -> pathlib.Path:
        return self.root / name

    def trace(self, op, **kw):
        self.traced.append((op, kw))


class KindRowsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.b = FakeBoard(pathlib.Path(tmp.name))

    def write_items(self, rows):
        self.b.work(conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False), encoding="utf-8")

    def test_park_keeps_kind_and_traces_it(self):
        conflict.park(self.b, [ITEM], source="fix")
        self.assertEqual(conflict.items(self.b)[0]["kind"], "unnamed_test_broke")
        self.assertEqual(self.b.traced[0][1]["kind"], "unnamed_test_broke")
        self.assertEqual(conflict.kind_counts(self.b)["unnamed_test_broke"], 1)

    def test_rows_without_kind_still_read(self):
        legacy = {k: ITEM[k] for k in ("unit_key", "between", "why_both_cannot_hold", "which_is_right")}
        self.write_items([{"id": "c1-1", "round": 1, "source": "fix", **legacy, "status": "ruled",
                           "ruling": {"decision": "ask_human", "text": "方針の変更で人が決める", "limits": [], "by": "x"}}])
        self.assertEqual(conflict.kind_counts(self.b)["unset"], 1)
        self.assertIn("種類 無し", conflict.human_lines(self.b)[0])
        self.assertIn("申し出の種類: （無し）", conflict.write_rulings(self.b).read_text(encoding="utf-8"))


class HeldByRulingsCase(KindRowsCase):
    """直す義務から外す単位の 1 つの決まり（直す裁定でない裁定を受けた単位）と、理由の文"""

    def test_one_rule_with_sorted_reasons(self):
        ruled = {"text": "裁きの文を十字以上で書く", "limits": [], "by": "x"}
        self.write_items([
            {"id": "c1-1", "unit_key": KEY, "ruling": {**ruled, "decision": "fix_plan_item", "plan_items": [2]}},
            {"id": "c1-2", "unit_key": OTHER, "ruling": {**ruled, "decision": "fix_plan_item", "plan_items": [1, 3]}},
            {"id": "c1-3", "unit_key": OTHER, "ruling": {**ruled, "decision": "ask_human"}},
            {"id": "c1-4", "unit_key": "u-code", "ruling": {**ruled, "decision": "fix_code_as"}},
            {"id": "c1-5", "unit_key": "u-open", "ruling": None}])
        self.assertEqual(conflict.held_by_rulings(self.b),
                         {KEY: "fix_plan_item の裁定 c1-1（案の項目 2）", OTHER: "ask_human の裁定 c1-3"})


class BriefKindCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name) / "repo"
        self.dir = pathlib.Path(tmp.name) / "board"
        self.repo.mkdir()
        self.dir.mkdir()
        seed(self.repo)
        self.brief1, self.brief2 = self.dir / "brief-1.md", self.dir / "brief-2.md"
        self.brief1.write_text("# brief 1\n上限を超えた値に hi を返す\n範囲は stats.py だけ\n", encoding="utf-8")
        self.brief2.write_text("# brief 2\n", encoding="utf-8")
        BRIEFS.clear()
        BRIEFS.update({KEY: [{"item": 1, "file": str(self.brief1)}], OTHER: [{"item": 2, "file": str(self.brief2)}]})

    def errs(self, item, briefs):
        return conflict.problems([item], repo=self.repo, board_dir=self.dir, owed={KEY}, briefs=briefs)

    def test_brief_kind_needs_the_units_brief(self):
        item = {**ITEM, "kind": "brief_vs_judgment", "between": [f"{self.brief1}:2", "stats.py:3"]}
        self.assertEqual(self.errs(item, briefs=BRIEFS), [])
        got = self.errs(item, briefs=None)
        self.assertTrue(any("brief_vs_judgment" in e and "brief が無い" in e for e in got), got)
        other = {**item, "between": [f"{self.brief2}:1", "stats.py:3"]}
        got = self.errs(other, briefs=BRIEFS)
        self.assertTrue(any("brief_vs_judgment" in e and str(self.brief1) in e for e in got), got)

    def test_other_kinds_ignore_briefs(self):
        self.assertEqual(self.errs(ITEM, briefs=None), [])

    def test_broken_ledger_gives_no_briefs(self):
        with mock.patch.object(planbrief, "_ledger", side_effect=planbrief.LedgerBroken("x")), \
             mock.patch.object(planbrief.entry, "open_board", return_value=object()):
            self.assertEqual(planbrief.by_unit_at(self.dir), {})
        self.assertEqual(planbrief.by_unit_at(self.dir / "no-board"), {})

    def test_brief_rules_name_the_kinds(self):
        # 節 brief-canon の申し出の道（範囲の外・query・brief の誤り・人が答えた条件）がそれぞれ種類の名を言う
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        for k in ("scope_needed", "query_hits_fixed", "brief_vs_judgment"):
            self.assertIn(f"`kind` は `{k}`", sec)



class RulingLimitsTextCase(KindRowsCase):
    """裁定の limits が広げるのは案の項目の範囲に足すパスだけ（planscope の継ぎ目の決まり）を、裁定役の決まり・裁定の文・
    修正役の brief の決まりが同じく言う"""

    def test_ruler_says_limits_only_add_paths(self):
        sec = fixrules.sections(fixrules.RULER)["ruler-reply"]
        for w in ("空なら足すパスは無い", "新しいファイル", "`out_of_scope`", "`tests`・`adds`・`removes`"):
            self.assertIn(w, sec)

    def test_rulings_file_says_only_ruled_paths_widen(self):
        rows = [{"id": f"c1-{i}", "round": 1, "source": "fix", **ITEM, "status": "ruled",
                 "ruling": {"decision": d, "text": "裁きの文を十字以上で書く", "limits": [], "by": "x"}}
                for i, d in enumerate(("fix_code_as", conflict.REPLACE), 1)]
        self.write_items(rows)
        text = conflict.write_rulings(self.b).read_text(encoding="utf-8")
        self.assertEqual(text.count("「範囲」に並べたパスだけ"), 2, text)

    def test_ruler_opens_brief_for_limits_too(self):
        # 範囲（limits）を書く時も fix_plan_item を考える時も、その単位の brief を開く
        self.assertIn("`limits` を書く時と `fix_plan_item` を考える時は", fixrules.sections(fixrules.RULER)["ruler-head"])

    def test_brief_rule_names_ruling_limits(self):
        self.assertIn("裁定の「範囲」", fixrules.sections(fixrules.BRIEF)["brief-canon"])


class FixPlanItemRulingCase(unittest.TestCase):
    """裁定 fix_plan_item の受け付けの確かめ（ruling.problems を直に呼ぶ。briefs は planbrief.by_unit_at の形）"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name)
        seed(self.repo)
        self.brief = self.repo / "brief-1.md"
        self.brief.write_text("# brief 1\n受け入れのテストは assertion で赤\n", encoding="utf-8")
        self.briefs = {KEY: [{"item": 1, "file": str(self.brief)}]}
        self.todo = {"c1-1": {"id": "c1-1", "unit_key": KEY, "which_is_right": "request", "kind": "not_red"}}

    def errs(self, briefs, **over):
        r = {"id": "c1-1", "decision": "fix_plan_item", "text": "受け入れのテストの赤の種類を exception に直す", "limits": [],
             "grounds": [f"{self.brief}:2"], **over}
        return ruling.problems({"rulings": [r]}, self.todo, self.repo, "", (), briefs=briefs)

    def test_fix_plan_item_needs_a_brief_and_no_limits(self):
        self.assertIn("fix_plan_item", conflict.DECISIONS)
        self.assertNotIn("fix_plan_item", conflict.FIX_DECISIONS)
        self.assertEqual(self.errs(self.briefs), [])
        self.assertTrue(any("brief" in e for e in self.errs({})))
        self.assertTrue(any("範囲" in e for e in self.errs(self.briefs, limits=["test_stats.py:2"])))

    def test_fix_plan_item_grounds_name_the_units_brief(self):
        # brief_vs_judgment と同じ決まり: grounds が無い・その単位の brief の外だけを名指す裁定は拒み、文に brief のファイルを名指す
        for grounds in ([], ["stats.py:3"]):
            got = self.errs(self.briefs, grounds=grounds)
            self.assertTrue(any("fix_plan_item" in e and "grounds" in e and str(self.brief) in e for e in got), (grounds, got))

    def test_rule_schema_and_yaml_carry_the_decision(self):
        enum = ruling.RULE_OUTPUT_FORMAT["properties"]["rulings"]["items"]["properties"]["decision"]["enum"]
        self.assertIn("fix_plan_item", enum)

    def test_ruler_rules_name_fix_plan_item(self):
        self.assertIn("`fix_plan_item`", fixrules.sections(fixrules.RULER)["ruler-reply"])
        self.assertIn("fix_plan_item", fixrules.sections(fixrules.PRINCIPLES)["principles"])
        self.assertIn("`kind`", fixrules.sections(fixrules.RULER)["ruler-head"])


def fake_with_rows(rows):
    """偽の盤面（work は一時の置き場のファイル・round 1・state の outputs は空・trace は traced に貯める）に、申し出の行
    rows を置いた物。一時の置き場は模块の終わりに消す"""
    root = pathlib.Path(tempfile.mkdtemp())
    unittest.addModuleCleanup(shutil.rmtree, root, ignore_errors=True)
    traced = []
    b = types.SimpleNamespace(work=lambda name: root / name, trace=lambda op, **kw: traced.append((op, kw)),
                              round=1, state={"outputs": {}}, traced=traced, dir=root)
    b.work(conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False), encoding="utf-8")
    return b


def row(rid, key, decision, *, state=None, text="受け入れのテストの赤の種類を exception に直す", plan_units=()):
    """申し出の行 1 つ（decision が None なら裁いていない行。state は欄 replan の値で、None なら欄を置かない）"""
    out = {"id": rid, "round": 1, "source": "fix", "unit_key": key, "between": ["stats.py:3", "test_stats.py:2"],
           "why_both_cannot_hold": "テストは上限 hi を期待し、今のコードは lo を返す——両方は成り立たない",
           "which_is_right": "request", "kind": "brief_vs_judgment", "status": "ruled" if decision else "parked",
           "ruling": None if decision is None else
           {"decision": decision, "text": text, "limits": [], "by": "t",
            **({"plan_items": [1], "plan_units": list(plan_units)} if plan_units else {})}}
    if state is not None:
        out["replan"] = state
    return out


def mean_row():
    """MEAN の changes の 1 行"""
    return {"unit_key": MEAN, "what": "mean の分母を len(xs) に直した", "files": ["stats.py"]}


def clamp_row():
    """CLAMP の changes の 1 行（1 回目の控えに置く）"""
    return {"unit_key": CLAMP, "what": "clamp の上限の枝の戻り値を hi に直した", "files": ["stats.py"]}


def hold(b, doc):
    """1 回目に受け付けた返答の控えを盤面に置く"""
    b.work(conflict.HELD_REPLY).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class TestReplanState(unittest.TestCase):
    def test_ruling_starts_waiting_and_holds(self):
        b = fake_with_rows([row("c1-1", MEAN, None)])                # 裁いていない申し出の行
        conflict.apply_rulings(b, {"c1-1": {"decision": "fix_plan_item", "text": "x" * 20, "limits": [],
                                            "plan_items": [1], "plan_units": [MEAN, CLAMP]}}, by="t")
        self.assertEqual(conflict.items(b)[0]["replan"], "waiting")
        self.assertEqual([r["id"] for r in conflict.waiting(b)], ["c1-1"])
        self.assertEqual(set(conflict.held_by_rulings(b)), {MEAN, CLAMP})
        self.assertEqual(conflict.asked(b), [])

    def test_other_rulings_have_no_state(self):
        b = fake_with_rows([row("c1-1", MEAN, None), row("c1-2", CLAMP, None)])
        conflict.apply_rulings(b, {"c1-1": {"decision": "ask_human", "text": "x" * 20, "limits": []},
                                   "c1-2": {"decision": "fix_code_as", "text": "x" * 20, "limits": []}}, by="t")
        self.assertTrue(all("replan" not in r for r in conflict.items(b)))
        self.assertEqual([conflict.replan_state(r) for r in conflict.items(b)], [None, None])
        self.assertEqual(conflict.waiting(b), [])
        self.assertEqual([r["id"] for r in conflict.asked(b)], ["c1-1"])

    def test_amended_rows_return_units_to_duty(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting")])
        conflict.set_replan(b, ["c1-1"], conflict.AMENDED)
        self.assertEqual(conflict.held_by_rulings(b), {})
        self.assertEqual(conflict.amended_keys(b), {MEAN})
        self.assertEqual(conflict.waiting(b), [])
        self.assertEqual(conflict.asked(b), [])
        self.assertEqual(b.traced, [(conflict.REPLAN_OP, {"id": "c1-1", "unit_key": MEAN, "state": "amended", "why": ""})])

    def test_amended_keys_cover_the_items_units(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="amended", plan_units=[MEAN, CLAMP]),
                            row("c1-2", "u-wait", "fix_plan_item", state="waiting")])
        self.assertEqual(conflict.amended_keys(b), {MEAN, CLAMP})
        self.assertEqual(set(conflict.held_by_rulings(b)), {"u-wait"})

    def test_gave_up_rows_join_ask_human_verbatim(self):
        text = "受け入れのテストの id を\nクラス付きにする（test_tiers.py:136-143）"
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting", text=text),
                            row("c1-2", CLAMP, "ask_human")])
        conflict.set_replan(b, ["c1-1"], conflict.GAVE_UP, why="修正案の役の直しが 3 回とも拒まれた: 数が違う")
        line = conflict.human_lines(b)[0]
        self.assertIn(text, line)                                  # 字のまま（改行も）
        self.assertIn("案の直し: 修正案の役の直しが 3 回とも拒まれた: 数が違う", line)
        self.assertTrue(line.endswith(f"・案の直し: 修正案の役の直しが 3 回とも拒まれた: 数が違う・{conflict.HELD_WORK_KEPT}）"), line)
        self.assertNotIn("案の直し", conflict.human_lines(b)[1])
        self.assertEqual([r["id"] for r in conflict.asked(b)], ["c1-1", "c1-2"])
        self.assertIn(MEAN, conflict.held_by_rulings(b))           # 諦めた行の単位は直す義務の外のまま
        self.assertEqual(conflict.items(b)[0]["replan_why"], "修正案の役の直しが 3 回とも拒まれた: 数が違う")
        self.assertEqual(b.traced[-1][1]["state"], "gave_up")

    def test_bad_transition_is_board_gap(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="gave_up"),
                            row("c1-2", CLAMP, "fix_plan_item", state="waiting"),
                            row("c1-3", "u-ask", "ask_human")])
        before = b.work(conflict.FILE).read_text(encoding="utf-8")
        for ids, state, why in ((["c1-1"], conflict.AMENDED, ""),       # 諦めた行は戻さない
                                (["c1-2"], conflict.GAVE_UP, ""),       # why の無い諦め
                                (["c1-2"], conflict.GAVE_UP, "  "),
                                (["c1-2"], conflict.WAITING, ""),       # waiting へは移さない
                                (["c1-3"], conflict.AMENDED, ""),       # fix_plan_item でない行
                                (["c9-9"], conflict.AMENDED, ""),       # 知らない id
                                (["c1-2", "c1-1"], conflict.AMENDED, "")):   # 1 つでも外れれば何も移さない
            with self.subTest(ids=ids, state=state, why=why), self.assertRaises(conflict._board.BoardGap):
                conflict.set_replan(b, ids, state, why=why)
        self.assertEqual(b.work(conflict.FILE).read_text(encoding="utf-8"), before)
        self.assertEqual(b.traced, [])

    def test_same_state_is_a_no_op(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="amended"),
                            row("c1-2", CLAMP, "fix_plan_item", state="gave_up")])
        conflict.set_replan(b, ["c1-1"], conflict.AMENDED)               # 再開で同じ移りが 2 度来る
        conflict.set_replan(b, ["c1-2"], conflict.GAVE_UP, why="別の理由")
        self.assertEqual(b.traced, [])
        self.assertNotIn("replan_why", conflict.items(b)[1])

    def test_row_without_state_reads_as_waiting(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item")])    # この版の前の盤面の行（欄 replan が無い）
        self.assertEqual(conflict.replan_state(conflict.items(b)[0]), "waiting")
        self.assertEqual([r["id"] for r in conflict.waiting(b)], ["c1-1"])
        self.assertEqual(conflict.asked(b), [])
        self.assertIn(MEAN, conflict.held_by_rulings(b))
        conflict.set_replan(b, ["c1-1"], conflict.AMENDED)
        self.assertEqual(conflict.amended_keys(b), {MEAN})


class TestHeldReply(unittest.TestCase):
    def test_accepted_units_leave_duty_but_not_board_owed(self):
        b = fake_with_rows([])
        hold(b, {"changes": [clamp_row()], "not_done": []})
        with mock.patch.object(conflict, "owed_units_but_asked", return_value={MEAN, CLAMP}), \
             mock.patch.object(gatemarks, "withheld_by", return_value={}):
            owed, excused = conflict.fix_duty(b)
        self.assertEqual(owed, {MEAN})
        self.assertIn("1 回目の修正の段で受け付けた", excused[CLAMP])
        self.assertIn(str(b.work(conflict.HELD_REPLY)), excused[CLAMP])
        self.assertEqual(set(excused), {CLAMP})

    def test_no_held_reply_leaves_duty_as_is(self):
        b = fake_with_rows([])
        with mock.patch.object(conflict, "owed_units_but_asked", return_value={MEAN, CLAMP}), \
             mock.patch.object(gatemarks, "withheld_by", return_value={}):
            self.assertEqual(conflict.fix_duty(b), ({MEAN, CLAMP}, {}))
        self.assertEqual(conflict.held_reply(b), (None, b.work(conflict.HELD_REPLY)))
        self.assertEqual(conflict.accepted_units(b), set())
        self.assertEqual(conflict.held_writes(b), [])

    def test_accepted_units_read_changes_and_not_done(self):
        b = fake_with_rows([])
        hold(b, {"changes": [clamp_row()], "not_done": [{"unit_key": "u-left", "why": "範囲外"}]})
        self.assertEqual(conflict.accepted_units(b), {CLAMP, "u-left"})

    def test_with_held_merges_rows_by_unit(self):
        b = fake_with_rows([])
        hold(b, {"changes": [clamp_row(), {**mean_row(), "what": "1 回目の古い行"}], "not_done": [],
                 "fix_closure": {"status": "open"}, "bash_writes": [{"path": "x.bin", "why": "バイナリ"}]})
        reply = {"changes": [mean_row()], "not_done": [], "fix_closure": {"status": "clean"}}
        merged = conflict.with_held(b, reply)
        self.assertEqual([c["unit_key"] for c in merged["changes"]], [CLAMP, MEAN])
        self.assertEqual(merged["changes"][1], mean_row())                # 同じ単位は返答の行
        self.assertEqual(merged["fix_closure"], {"status": "clean"})
        self.assertNotIn("bash_writes", merged)
        self.assertEqual(reply["changes"], [mean_row()])                  # 返答そのものは変えない（写し）

    def test_with_held_without_held_is_the_reply(self):
        b = fake_with_rows([])
        reply = {"changes": [mean_row()], "not_done": []}
        self.assertIs(conflict.with_held(b, reply), reply)

    def test_held_writes_are_kept(self):
        b = fake_with_rows([])
        writes = [{"path": "tools/run.sh", "why": "実行の権限を付けた"}]
        hold(b, {"changes": [clamp_row()], "not_done": [], "bash_writes": writes})
        self.assertEqual(conflict.held_writes(b), writes)

    def test_held_reply_ignored_after_board_took_fix(self):
        b = fake_with_rows([])
        hold(b, {"changes": [clamp_row()], "not_done": []})
        b.state["outputs"]["p3.fix"] = {"file": "outputs/p3.fix.json", "round": 0, "instance": "p3.fix"}   # 前の周
        self.assertEqual(conflict.held_reply(b)[0]["changes"], [clamp_row()])
        b.state["outputs"]["p3.fix"] = {"file": "outputs/p3.fix.json", "round": 1, "instance": "p3.fix"}   # 今の周
        self.assertEqual(conflict.held_reply(b), (None, b.work(conflict.HELD_REPLY)))
        self.assertEqual(conflict.accepted_units(b), set())

    def test_fix_node_matches_recount(self):
        """conflict は recount を読まずに修正の段の節の名を字で持つ（held_reply が盤面の受けを見る）。字は recount の物と同じ"""
        import recount
        self.assertEqual(conflict.FIX_NODE, recount.FIX_NODE)

    def test_broken_held_reply_is_board_gap(self):
        b = fake_with_rows([])
        for text in ("{", "[]", '{"changes": {}}', '{"changes": [{"what": "x"}]}', '{"not_done": ["x"]}',
                     '{"bash_writes": {}}'):
            with self.subTest(text=text):
                b.work(conflict.HELD_REPLY).write_text(text, encoding="utf-8")
                with self.assertRaises(conflict._board.BoardGap):
                    conflict.held_reply(b)


class TestReplanWords(unittest.TestCase):
    """fix_plan_item の意味は「同じ run の中で案を直す」（依頼 226）。持ち越しの語が残らず、裁定の文の約束が状態ごとに正しい"""

    @staticmethod
    def flat(p):
        return re.sub(r'[\s"]', "", p.read_text(encoding="utf-8"))

    def test_no_carry_over_words_left(self):
        for p in (CORE / "conflict.py", CORE / "entry.py", CORE / "deltamarks.py", BLK_FIX / "rules" / "principles.md",
                  BLK_FIX / "rules" / "ruler.md", BLK_FIX / "blk-fix.yaml", BLK_REFIX / "rules" / "refix.md",
                  BLK_DELTA / "commands" / "delta-review.md"):
            with self.subTest(p.name):
                self.assertNotIn("次のrunの修正案", self.flat(p))

    def test_ruler_says_same_run(self):
        self.assertIn("同じ run の中で修正案の役", fixrules.sections(fixrules.RULER)["ruler-reply"])

    def test_replan_promise_says_same_run(self):
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting", plan_units=[MEAN, CLAMP])])
        text = conflict.write_rulings(b).read_text(encoding="utf-8")
        self.assertIn("この run の中で修正案の役がこの項目だけを直し、事前審査と人の関所の決まりを通ってから、2 回目の修正の段で直す",
                      text)

    def test_gave_up_rows_promise_the_last_gate(self):
        """諦めた行（gave_up）は案の直しを約束しない。ask_human と同じく最後の人の関所で人が決め、諦めた理由を添える"""
        b = fake_with_rows([row("c1-1", MEAN, "fix_plan_item", state="waiting", plan_units=[MEAN, CLAMP])])
        conflict.set_replan(b, ["c1-1"], conflict.GAVE_UP, why="修正案の役の直しが 3 回とも拒まれた: 数が違う")
        text = conflict.write_rulings(b).read_text(encoding="utf-8")
        self.assertNotIn("2 回目の修正の段で直す", text)
        self.assertIn("最後の人の関所で人が決める", text)
        self.assertIn("修正案の役の直しが 3 回とも拒まれた: 数が違う", text)

    def test_parked_note_excludes_every_unit_outside_duty(self):
        """申し出の回の返答を出し直す注記は、直す義務の外の単位すべて（ask_human・fix_plan_item のどの状態も・1 回目に
        受け付けた単位）を除くと言う"""
        b = fake_with_rows([row("c1-1", MEAN, "ask_human")])
        b.work(conflict.PARKED_REPLY).write_text("{}", encoding="utf-8")
        text = conflict.write_rulings(b).read_text(encoding="utf-8")
        self.assertIn("直す義務の外の単位はすべて除く", text)
        self.assertIn("1 回目の修正の段で受け付けた単位", text)

    @staticmethod
    def section(text, rid):
        return text.split(f"## {rid}:", 1)[1].split("\n## ", 1)[0]

    def test_accepted_unit_rows_say_do_not_write(self):
        """1 回目に受け付けた控えの単位の裁定の行（直す裁定でも）は「changes に 1 行を書け」と言わず、受け付けが拒む
        （accept.ACCEPTED_ROWS）のと同じく、書くな・行は機械が足すと言う（fix_duty の ACCEPTED_WHY と同じ扱い）"""
        b = fake_with_rows([row("c1-1", CLAMP, "fix_code_as"), row("c1-2", MEAN, "fix_code_as")])
        hold(b, {"changes": [clamp_row()], "not_done": []})
        text = conflict.write_rulings(b).read_text(encoding="utf-8")
        mine = self.section(text, "c1-1")
        self.assertNotIn("changes に 1 行を書け", mine)
        self.assertIn(conflict.ACCEPTED_PROMISE.format(path=b.work(conflict.HELD_REPLY)), mine)
        self.assertIn("changes に 1 行を書け", self.section(text, "c1-2"), "控えに無い単位は今どおり")

    def test_second_pass_new_replan_rows_promise_the_last_gate(self):
        """2 回目の修正の段（案を直した行が在る。conflict.second_pass）で新しく fix_plan_item と裁いた行（待つ行）は、無い 3 回目の
        修正の段を約束せず、修正の段を抜ける時に諦めた行になり最後の人の関所へ行くと言う（replan.settle が締める）"""
        waiting = row("c2-1", MEAN, "fix_plan_item", state="waiting", plan_units=[MEAN])
        b = fake_with_rows([row("c1-1", CLAMP, "fix_plan_item", state="amended", plan_units=[CLAMP]), waiting])
        mine = self.section(conflict.write_rulings(b).read_text(encoding="utf-8"), "c2-1")
        self.assertNotIn("2 回目の修正の段で直す", mine)
        self.assertIn(conflict.LATE_REPLAN_PROMISE, mine)
        self.assertIn("最後の人の関所で人が決める", mine)
        first = self.section(conflict.write_rulings(fake_with_rows([waiting])).read_text(encoding="utf-8"), "c2-1")
        self.assertIn("2 回目の修正の段で直す", first, "1 回目の段の待つ行は今どおり")

    def test_ask_human_promise_keeps_held_work_conditionally(self):
        """ask_human の約束は、直しが作業ツリーに在ればそのまま残す（戻すな・触るな。機械が戻した時は控えの patch を当て直すな）と
        条件の形で言い、changes に書くなも残す。約束は decision だけで選ぶので、機械が戻した行（by=works:fix-accept）にも同じ文が
        届く——だから直しを残したと過去の事実を言い切る HELD_WORK_KEPT は使わない"""
        b = fake_with_rows([row("c1-1", MEAN, "ask_human")])
        mine = self.section(conflict.write_rulings(b).read_text(encoding="utf-8"), "c1-1")
        self.assertIn("この単位の直しが作業ツリーに在れば、そのまま残す（戻すな・触るな", mine)
        self.assertIn("当て直すな", mine)
        self.assertIn("changes に書くな", mine)
        self.assertNotIn(conflict.HELD_WORK_KEPT, mine)

    def test_held_ask_points_at_the_owed_keys_above(self):
        """控えの節の『直す義務』の名指しは、指示書でその節より前（上）に在る読む物の行を指す"""
        self.assertNotIn("下の『直す義務の単位』", fixrules.HELD_ASK)
        self.assertIn("上の「読む物」の「直す義務の単位の key」", fixrules.HELD_ASK)
        parts = [i for i, _, _ in fixrules.fix_parts({k: "" for k in fixrules.FIX_VALUES}, held="x")]
        self.assertLess(parts.index("fix-head"), parts.index("held"))
        self.assertIn("直す義務の単位の key", fixrules.sections(fixrules.DIRECT)["fix-head"])


if __name__ == "__main__":
    unittest.main()
