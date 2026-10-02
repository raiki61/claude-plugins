"""同じ run の中の案の直し（依頼 226）の締め: replan.close・close_at・settle。

待つ単位（裁定 fix_plan_item の行の状態 WAITING）を残したまま修正の段を抜けない。h-rejudge（settle）と報告の組み立て
（report.build の close_at）が、待つ行を諦めた行（GAVE_UP）にして ask_human の道に載せる。止まった盤面でも締める。
締めた後に待つ行が残れば BoardGap。持ち越し（次の run の修正案へ）の道は無い。
待つ単位が在る間、修正の受け付けは返答を盤面に渡さずに控え（conflict.HELD_REPLY。受けた時と同じ trace を書く）、settle が渡す
（replan.hand_held）。集める節と報告は返答を recount.fix_reply の 1 つの口で読む（盤面の p3.fix か控え）。
案の直しの役（blk-plan の replan の口。TestReplanRoles）: 待つ行を項目ごとに束ね（replan.material）、修正案の役には誤りと裁かれた
項目・申し出・裁定の文だけを渡し、返答を渡した項目に限って受け付け、事前審査の役には独立設計の節と前後の項目だけを渡す。
helper（fixed_item など・TripCase）は Task 7〜9 の試験も使う。
"""
import copy
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))

from test_blk_fix_conflict import (CLAMP, CLAMP_FIELDS, MEAN, PLAN_TEXT, ReplanCase, accept_module,  # noqa: E402,F401
                                   only_clamp_reply, split_plan_reply)
from test_blk_fix import PLAN_FIELDS, PLAN_REVIEW_OK, load  # noqa: E402

import board  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import planblk  # noqa: E402
import planmarks  # noqa: E402
import recount  # noqa: E402
import replan  # noqa: E402
import report  # noqa: E402


class TestSettle(ReplanCase):
    """settle と close_at が待つ行を締め、諦めた行は ask_human の道（human_lines・next_request）に裁定の文のまま載る"""

    def ruled(self):
        self.replanned()
        self.assertTrue(self.accept_script(only_clamp_reply(), pass_="ruled")["ok"])

    def test_settle_closes_waiting_rows(self):
        self.ruled()
        got = replan.settle(self.board, self.repo)
        self.assertEqual(len(got["closed"]), 1)
        self.assertTrue(got["handed"], "待つ間に控えた clamp の返答を渡す")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(conflict.waiting(b), [])
        row = conflict.items(b)[0]
        self.assertEqual((conflict.replan_state(row), row[conflict.REPLAN_WHY]), (conflict.GAVE_UP, replan.CLOSE_WHY))
        self.assertIn(PLAN_TEXT, conflict.human_lines(b)[0])

    def test_settle_twice_closes_once(self):
        self.ruled()
        first = replan.settle(self.board, self.repo)
        self.assertEqual(replan.settle(self.board, self.repo)["closed"], [])
        rows = [r for r in report.trace_rows(entry.open_board(self.board, allow_halted=True), conflict.REPLAN_OP)]
        self.assertEqual([r["id"] for r in rows], first["closed"])

    def test_close_without_waiting_rows_does_nothing(self):
        self.parked()
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(replan.close(b, replan.CLOSE_WHY), [])
        self.assertEqual(replan.settle(self.board, self.repo), {"closed": [], "handed": False})

    def test_unsettled_is_board_gap(self):
        self.replanned()
        with mock.patch.object(replan, "close", return_value=[]):
            with self.assertRaises(board.BoardGap) as cm:
                replan.settle(self.board, self.repo)
        self.assertIn("案の直しを待つ単位を残したまま", str(cm.exception))
        self.assertIn(self.items()[0]["id"], str(cm.exception))

    def test_closed_on_halted_board_names_the_stop(self):
        self.ruled()
        entry.open_board(self.board).stop("人が止めた一言", by="human:test")
        self.assertEqual(len(replan.close_at(self.board)), 1)
        row = self.items()[0]
        self.assertTrue(row[conflict.REPLAN_WHY].startswith("run が止まった（"), row)
        self.assertEqual(row[conflict.REPLAN_WHY], replan.HALTED_WHY.format(by="human:test", reason="人が止めた一言"))

    def test_report_build_closes_waiting_rows(self):
        """h-rejudge を通らずに（fixing が落ちた run）報告を組んでも、待つ行は諦めた行になり、次の run の依頼に裁定の文が届く"""
        self.ruled()
        report.build(self.board, judged=None, tests=None, start=None)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(conflict.waiting(b), [])
        self.assertEqual(conflict.replan_state(conflict.items(b)[0]), conflict.GAVE_UP)
        items = report.next_request(b)
        self.assertTrue(any(i["where"] == MEAN and PLAN_TEXT in i["text"] for i in items), items)

    def test_no_new_count_constant(self):
        self.assertFalse([n for n in dir(replan) if "LIMIT" in n or n == "GIVE_UP_AFTER"])


def trace_ops(board_dir) -> list:
    """盤面の trace.jsonl の op の並び"""
    return [json.loads(x).get("op") for x in (pathlib.Path(board_dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]


class TestHold(ReplanCase):
    """待つ単位（fix_plan_item の WAITING）が在る間、受け付けは p3.fix を盤面に渡さずに控え、settle が渡す"""

    def held(self):
        self.replanned()
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertEqual((r["ok"], r.get("parked"), r["done"]), (True, True, True), r)
        return r

    def test_waiting_unit_holds_fix_reply(self):
        r = self.held()
        self.assertEqual([c["unit_key"] for c in r["changes"]], [CLAMP])
        self.assertEqual(sorted(r["changes"][0]), ["files", "unit_key", "what"])
        b = entry.open_board(self.board)
        self.assertNotIn("p3.fix", b.state["outputs"])                    # 盤面に渡していない
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file())
        got, path = recount.fix_reply(b)
        self.assertEqual(path, b.work(conflict.HELD_REPLY))
        self.assertEqual([c["unit_key"] for c in got["changes"]], [CLAMP])
        self.assertNotIn("bash_writes", got)

    def test_hold_keeps_declared_bash_writes(self):
        self.replanned()
        reply = only_clamp_reply()
        reply["bash_writes"] = [{"path": "stats.py", "why": "sed で上限の枝を直した"}]
        self.assertTrue(self.accept_script(reply, pass_="ruled")["parked"])
        b = entry.open_board(self.board)
        self.assertEqual(conflict.held_writes(b), reply["bash_writes"])
        self.assertNotIn("bash_writes", recount.fix_reply(b)[0])

    def test_collect_reads_held_reply(self):
        """集める節は控えを読む（fix_file は控えのパス）。受け付けた changes を changes.json に書く"""
        r = self.held()
        got = recount.collect(self.board, r, {"ok": True, "files": ["stats.py"]})
        b = entry.open_board(self.board)
        self.assertEqual(got["fix_file"], str(b.work(conflict.HELD_REPLY)))
        self.assertEqual(json.loads(pathlib.Path(got["changes_file"]).read_text(encoding="utf-8")), {"changes": r["changes"]})

    def test_hold_writes_accepted_traces(self):
        self.held()
        accept_mod = accept_module()
        ops = trace_ops(self.board)
        self.assertLessEqual({accept_mod.TESTS_OP, accept_mod.HELD_OP}, set(ops))
        self.assertEqual(ops.count(accept_mod.HELD_OP), 1)

    def test_settle_hands_held_reply(self):
        self.held()
        got = replan.settle(self.board, self.repo)
        self.assertTrue(got["handed"])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertEqual([c["unit_key"] for c in recount._fix_output(b)[0]["changes"]], [CLAMP])
        self.assertEqual(recount.fix_reply(b)[1], recount._fix_output(b)[1])

    def test_report_reads_held_reply_when_board_stopped(self):
        self.held()
        entry.open_board(self.board).stop("人が止めた一言", by="human:test")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.claimed_units(b), [CLAMP])
        self.assertFalse(report._no_fix(b, None))

    def test_settle_twice_hands_once(self):
        self.held()
        self.assertTrue(replan.settle(self.board, self.repo)["handed"])
        before = trace_ops(self.board)
        self.assertFalse(replan.settle(self.board, self.repo)["handed"])
        self.assertEqual(trace_ops(self.board), before)

    def test_hand_held_on_stopped_board_does_nothing(self):
        self.held()
        entry.open_board(self.board).stop("人が止めた一言", by="human:test")
        self.assertFalse(replan.hand_held(self.board, self.repo))
        self.assertNotIn("p3.fix", entry.open_board(self.board, allow_halted=True).state["outputs"])

    def test_board_refusing_held_reply_stops_the_board(self):
        self.held()
        with mock.patch.object(recount, "accept_fix", return_value={"ok": False, "reason": "数え直しが合わない", "changes": []}):
            self.assertFalse(replan.hand_held(self.board, self.repo))
        stop = entry.open_board(self.board, allow_halted=True).state["stop"]
        self.assertEqual(stop["by"], replan.STOP_BY)
        self.assertIn("数え直しが合わない", stop["reason"])

    def test_no_waiting_hands_as_before(self):
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "ask_human", "text": "方針の変更で、人が決める", "limits": [],
                           "request_searched": "依頼に分母と期待値のどちらを正とするかの答えを探したが無い"}])
        self.assertTrue(r["ok"], r)
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("parked", r)
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertFalse(b.work(conflict.HELD_REPLY).exists())
        self.assertEqual(recount.fix_reply(b)[1], recount._fix_output(b)[1])

    def test_fix_reply_without_either_is_unreadable(self):
        self.fix_ready()
        with self.assertRaises(recount.Unreadable):
            recount.fix_reply(entry.open_board(self.board))


# ---------------------------------------------------------------- 案の直しの役（226 Task 6）の helper（Task 7〜9 も使う）
def _item(n: int) -> dict:
    """承認済みの修正案の項目 n（ReplanCase の 2 項目の案: 1 は mean・2 は clamp）の核の欄と works の欄を合わせた写し"""
    fields = (PLAN_FIELDS[0], CLAMP_FIELDS)[n - 1]
    return copy.deepcopy({**split_plan_reply()["plan"][n - 1], **fields})


def fixed_item() -> dict:
    """前の項目 1 の写しで、手段の欄（approach）だけを直した物"""
    return {**_item(1), "approach": "mean の分母を len(xs) に直し、2 つの値の平均を受け入れのテストで縛る"}


def red_kind_fixed() -> dict:
    """受け入れのテストの red_kind を exception に、red_why を今のコードで赤になる理由に直した物（224b の型。手段の欄だけ）"""
    it = _item(1)
    it["tests"] = [{**it["tests"][0], "red_kind": "exception",
                    "red_why": "今の分母 len(xs) - 1 は 1 つの値の列で 0 になり ZeroDivisionError が出る"}]
    return it


def wider_paths() -> dict:
    """allowed_paths に 1 行を足した物（約束の欄が変わる。195b の型）"""
    it = _item(1)
    it["allowed_paths"] = [*it["allowed_paths"], "README.md"]
    return it


def clamp_item() -> dict:
    """項目 2（clamp）の写し"""
    return _item(2)


def no_faces() -> dict:
    """事前審査の空の返答（faces・shrink が空で、型の残りの欄を持つ）"""
    return copy.deepcopy(PLAN_REVIEW_OK)


def only_mean_reply() -> dict:
    """fix2_ok の mean の行だけ（only_clamp_reply の MEAN 版）"""
    reply = load("fix2_ok")
    reply["changes"] = [c for c in reply["changes"] if c["unit_key"] == MEAN]
    reply["interactions"] = []
    return reply


class TripCase(ReplanCase):
    """mean を fix_plan_item に裁き、1 回目の受け付けが clamp の返答を控え、replan.material が束ねた盤面"""

    def setUp(self):
        super().setUp()
        self.replanned()
        self.assertTrue(self.accept_script(only_clamp_reply(), pass_="ruled")["ok"])
        self.assertTrue(replan.material(entry.open_board(self.board))["go"])

    def play_role(self, role, reply):
        """1 つの役の輪の前の写し（planblk.snap の replan の口）・支度（planblk.prep）と受け付け。返りは accept_reply の返り"""
        self.assertTrue(planblk.snap(self.board, role, self.repo, replan="true")["go"])
        planblk.prep(self.board, role, self.repo, replan="true")
        return replan.accept_reply(self.board, role, json.dumps(reply, ensure_ascii=False), self.repo)

    def trip(self, *, new, review):
        """修正案の役が new を返し、事前審査の役が review を返す（どちらも受け付けを通る）"""
        got = self.play_role("plan", {"plan": [new]})
        self.assertTrue(got["ok"], got)
        got = self.play_role("plan-review", review)
        self.assertTrue(got["ok"], got)

    def approve(self, new):
        """trip に関所（replan.gate）と答えの無い受け（replan.answer。Task 7）を足す"""
        self.trip(new=new, review=no_faces())
        replan.gate(entry.open_board(self.board), run_id="r")
        return replan.answer(self.board, self.repo, None)

    def trip_doc(self):
        return json.loads(entry.open_board(self.board, allow_halted=True).work(replan.TRIP_FILE).read_text(encoding="utf-8"))


class TestReplanRoles(ReplanCase):
    """案の直しの役の口: 束ね・指示書・返答を渡した項目に限る受け付け・事前審査の指示書・読んだ証拠の置き場"""

    def setUp(self):
        super().setUp()
        self.replanned(); self.accept_script(only_clamp_reply(), pass_="ruled")
        self.b = entry.open_board(self.board)

    def prep(self, role):
        """輪の前の写し（snap）と支度（prep）。輪の 2 回目以降の支度だけを回すなら planblk.prep を直に呼ぶ"""
        self.assertTrue(planblk.snap(self.board, role, self.repo, replan="true")["go"])
        return planblk.prep(self.board, role, self.repo, replan="true")

    def accept(self, role, reply):
        return replan.accept_reply(self.board, role, json.dumps(reply, ensure_ascii=False), self.repo)

    def trip(self):
        return json.loads(self.b.work(replan.TRIP_FILE).read_text(encoding="utf-8"))

    def test_material_groups_by_item(self):
        got = replan.material(self.b)
        self.assertEqual(got, {"go": True, "items": [1]})
        trip = self.trip()
        self.assertEqual(trip["items"][0]["units"], [MEAN])
        row = trip["items"][0]
        self.assertEqual(row["item"], 1)
        self.assertEqual(row["rows"], [self.items()[0]["id"]])
        self.assertEqual(row["old"], {k: v for k, v in planmarks.approved_items(self.b)[0].items() if k != "item"})
        self.assertEqual(row["brief"], str(self.b.work("brief-1.md")))
        self.assertIsNone(row["new"]); self.assertIsNone(row["review"])

    def test_material_keeps_trip_on_resume(self):
        replan.material(self.b)
        path = self.b.work(replan.TRIP_FILE)
        doc = self.trip(); doc["items"][0]["why"] = "再開の印"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(replan.material(self.b), {"go": True, "items": [1]})
        self.assertEqual(self.trip()["items"][0]["why"], "再開の印")

    def test_material_stops_when_fix_taken_or_board_stopped(self):
        replan.settle(self.board, self.repo)   # 待つ行を締めて控えを盤面に渡す（p3.fix を受けた）
        self.assertEqual(replan.material(entry.open_board(self.board, allow_halted=True)), {"go": False, "items": []})

    def test_brief_name_matches_planbrief(self):
        import planbrief
        self.assertEqual(replan.BRIEF_NAME, planbrief.NAME)

    def test_prompt_has_only_the_item_and_texts(self):
        replan.material(self.b)
        got = self.prep("plan")
        self.assertEqual(pathlib.Path(got["prompt_file"]).name, "prompt-replan.fix_plan.md")
        self.assertEqual(got["node"], replan.PLAN_NODE)
        p = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(PLAN_TEXT, p)                                  # 裁定の文（字のまま）
        self.assertIn(MEAN, p)
        self.assertNotIn(CLAMP, p)                                    # ほかの項目の単位を貼らない
        self.assertIn("一字も変えずに写せ", p)
        self.assertIn(replan.REPLAN_ASK, p)
        self.assertEqual(p.count(planmarks.HEAD), 1)                  # 欄の節を 2 度貼らない
        row = self.items()[0]
        for text in (row["why_both_cannot_hold"], row["kind"], *row["between"], str(self.b.work("brief-1.md"))):
            self.assertIn(text, p)

    def test_reply_limited_to_handed_items(self):
        replan.material(self.b); self.prep("plan")
        two = {"plan": [fixed_item(), clamp_item()]}                 # 項目を足した返答
        got = self.accept("plan", two)
        self.assertFalse(got["ok"]); self.assertIn("plan[] は 1 項目", got["reason"])
        renamed = {"plan": [{**fixed_item(), "unit_keys": [1]}]}    # 番号で書いた
        got = self.accept("plan", renamed)
        self.assertIn("一字も変えずに写す", got["reason"])
        self.assertTrue(got["reason"].startswith(replan.REPLAN_REJECT), got["reason"])

    def test_all_errors_in_one_rejection(self):
        replan.material(self.b); self.prep("plan")
        bad = {**fixed_item(), "unit_keys": [CLAMP], "route": "direct", "route_why": "",
               "narrows": [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま"}]}
        got = self.accept("plan", {"plan": [bad]})
        self.assertFalse(got["ok"])
        for word in ("plan[0].unit_keys が貼った", "plan[0].route_why", "plan[0].narrows[0]", "型"):
            self.assertIn(word, got["reason"])

    def test_same_test_id_left_in_tree_is_accepted(self):
        """作業ツリーに受け入れのテスト test_mean_of_two を書いておく（TDD の輪で止めた単位の残り）→ 同じ id で red_kind だけ
        直した返答が通る（既に在るかは修正の起点の版の木で見る）"""
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "    def test_clamp_within_range", "    def test_mean_of_two(self):\n        self.assertEqual(mean([1, 3]), 2)\n\n"
            "    def test_clamp_within_range"), encoding="utf-8")
        self.assertIsNotNone(planmarks.find_test(self.repo, red_kind_fixed()["tests"][0]["id"]))
        replan.material(self.b); self.prep("plan")
        got = self.accept("plan", {"plan": [red_kind_fixed()]})
        self.assertTrue(got["ok"], got)

    def test_test_in_start_tree_is_still_rejected(self):
        """修正の起点の版に在るテストを tests に名指せば、今どおり拒む"""
        replan.material(self.b); self.prep("plan")
        it = fixed_item()
        it["tests"] = [{**it["tests"][0], "id": "test_stats.py::TestStats::test_mean_of_three"}]
        got = self.accept("plan", {"plan": [it]})
        self.assertFalse(got["ok"]); self.assertIn("既に在るテスト", got["reason"])

    def test_good_reply_is_stored_not_swapped(self):
        """正しい返答 → TRIP_FILE の new に入り（narrows の決め手の欄は new_marks へ）、planmarks.approved_items はまだ前の項目"""
        replan.material(self.b); self.prep("plan")
        marks = {"decided_by": "依頼の 2 行目: 空の列は例外のままでよい",
                 "no_narrow": "空の列で例外を投げる今の動きを残すほかに形が無いので、狭めない案は無い"}
        new = {**fixed_item(), "narrows": [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま", **marks}]}
        got = self.accept("plan", {"plan": [new]})
        self.assertEqual((got["ok"], got["done"], got["give_up"], got["node"]), (True, True, False, replan.PLAN_NODE), got)
        row = self.trip()["items"][0]
        self.assertEqual(row["new"]["approach"], fixed_item()["approach"])
        self.assertEqual(row["new"]["narrows"], [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま"}])
        self.assertEqual(row["new_marks"], [marks])
        b = entry.open_board(self.board)
        self.assertEqual(planmarks.approved_items(b)[0]["approach"], _item(1)["approach"])

    def test_third_rejection_gives_up(self):
        replan.material(self.b); self.prep("plan")
        outs = [self.accept("plan", {"plan": [fixed_item(), clamp_item()]}) for _ in range(rolekit_give_up())]
        self.assertEqual([(o["done"], o["give_up"]) for o in outs], [(False, False), (False, False), (True, True)])

    def test_rejection_named_on_next_prompt(self):
        replan.material(self.b); self.prep("plan")
        self.accept("plan", {"plan": [fixed_item(), clamp_item()]})
        got = self.prep("plan")
        first = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("前の回の返答は受け付けで拒まれた", first)
        self.assertEqual(got["attempt"], 2)

    def test_tree_change_rejected(self):
        replan.material(self.b); self.prep("plan")
        (self.repo / "scratch.txt").write_text("役が書いた\n", encoding="utf-8")
        got = self.accept("plan", {"plan": [fixed_item()]})
        self.assertFalse(got["ok"]); self.assertIn(entry.READONLY_MOVED, got["reason"])

    def test_tree_change_left_by_rejected_attempt_is_still_rejected(self):
        """1 回目の返答の後に作業ツリーに残った変化は、2 回目の支度で写しの元にならない（写しは輪の前に 1 度だけ。planblk と同じ）"""
        replan.material(self.b); self.prep("plan")
        (self.repo / "scratch.txt").write_text("役が書いた\n", encoding="utf-8")
        self.assertFalse(self.accept("plan", {"plan": [fixed_item()]})["ok"])
        planblk.prep(self.board, "plan", self.repo, replan="true")          # 輪の 2 回目の支度（snap は輪の外で 1 回）
        got = self.accept("plan", {"plan": [fixed_item()]})
        self.assertFalse(got["ok"], got); self.assertIn(entry.READONLY_MOVED, got["reason"])

    def test_material_rejects_non_int_plan_items(self):
        path = self.b.work(conflict.FILE)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["items"][0]["ruling"][conflict.PLAN_ITEMS] = [1, "x"]
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(board.BoardGap):
            replan.material(entry.open_board(self.board))

    def test_review_role_sees_design_only_and_both_forms(self):
        """事前審査の指示書に独立設計の節と前後の項目、ほかの項目の欄（planmarks.REVIEW_HEAD の節）は無い"""
        replan.material(self.b); self.prep("plan")
        self.assertTrue(self.accept("plan", {"plan": [fixed_item()]})["ok"])
        self.assertTrue(replan.snap(self.board, "plan-review", self.repo)["go"])
        got = self.prep("plan-review")
        self.assertEqual(pathlib.Path(got["prompt_file"]).name, "prompt-replan.plan_review.md")
        p = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(planblk.DESIGN_HEAD, p)
        self.assertIn(replan.REVIEW_ASK_REPLAN, p)
        self.assertIn(planmarks.REVIEW_ASK, p)
        self.assertNotIn(planmarks.REVIEW_HEAD, p)
        self.assertIn(_item(1)["approach"], p)
        self.assertIn(fixed_item()["approach"], p)
        self.assertIn(PLAN_TEXT, p)
        self.assertNotIn(CLAMP, p)
        got = self.accept("plan-review", no_faces())
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.trip()["items"][0]["review"]["faces"], [])
        self.assertFalse(replan.snap(self.board, "plan-review", self.repo)["go"])

    def test_snap_go_follows_trip(self):
        self.assertTrue(replan.snap(self.board, "plan", self.repo)["go"])
        self.assertFalse(replan.snap(self.board, "plan-review", self.repo)["go"])
        self.prep("plan")
        self.assertTrue(self.accept("plan", {"plan": [fixed_item()]})["ok"])
        self.assertFalse(replan.snap(self.board, "plan", self.repo)["go"])

    def test_collect_keeps_exit_shape(self):
        replan.material(self.b)
        got = planblk.collect(self.board, replan="true")
        self.assertEqual(got, {"ok": True, "plan_file": "", "review_file": "", "asks_human": False, "gate_kinds": [],
                               "reads_file": "", "gave_up": False, "reason_file": ""})
        self.assertIsNone(entry.open_board(self.board).state.get("stop"))

    def test_replan_reads_do_not_overwrite_planning_reads(self):
        b = self.b
        before = {}
        for name in ("reads-plan.json", "reads-plan-review.json", planblk.READS_INDEX):
            b.work(name).write_text(f'{{"first": "{name}"}}\n', encoding="utf-8")
            before[name] = b.work(name).read_text(encoding="utf-8")
        replan.material(b); self.prep("plan")
        self.assertTrue(self.accept("plan", {"plan": [fixed_item()]})["ok"])
        self.prep("plan-review")
        got = planblk.collect_reads(self.board, self.repo, "", "replanning", replan="true")
        self.assertEqual(pathlib.Path(got["reads_file"]).name, "reads-replan-block.json")
        index = json.loads(pathlib.Path(got["reads_file"]).read_text(encoding="utf-8"))
        self.assertEqual({k: pathlib.Path(v).name for k, v in index.items()},
                         {"replan-plan": "reads-replan-plan.json", "replan-plan-review": "reads-replan-plan-review.json"})
        self.assertEqual({n: b.work(n).read_text(encoding="utf-8") for n in before}, before)
        self.assertEqual(planblk.collect(self.board, replan="true")["reads_file"], got["reads_file"])

    def test_scripts_route_to_replan(self):
        """blk-plan のスクリプトが INPUTS_REPLAN で replan の口へ回る（無い・空は今どおり）"""
        def run(script, **inputs):
            env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "WORKFLOW_ID"}
            env.update({"ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
            env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
            r = subprocess.run([sys.executable, str(ROOT / "blk-plan" / "scripts" / f"{script}.py")], cwd=str(self.repo),
                               env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertFalse(run("snap", role="plan")["go"])                       # 無い: 今どおり（p2.fix_plan は待っていない）
        self.assertFalse(run("snap", role="plan", replan="")["go"])            # 空: 今どおり
        self.assertTrue(run("snap", role="plan", replan="true")["go"])
        prep = run("prep", role="plan", excluded_file="", replan="true")
        self.assertEqual(prep["node"], replan.PLAN_NODE)
        got = run("accept", role="plan", reply=json.dumps({"plan": [fixed_item(), clamp_item()]}, ensure_ascii=False),
                  replan="true")
        self.assertFalse(got["ok"]); self.assertTrue(pathlib.Path(got["reason_file"]).is_file())
        got = run("accept", role="plan", reply=json.dumps({"plan": [fixed_item()]}, ensure_ascii=False), replan="true")
        self.assertEqual((got["ok"], got["done"], got["reason_file"]), (True, True, ""))
        self.assertEqual(run("collect", replan="true")["ok"], True)
        self.assertTrue(run("reads", include_id="replanning", replan="true")["ok"])


def rolekit_give_up() -> int:
    import rolekit
    return rolekit.GIVE_UP_AFTER


if __name__ == "__main__":
    unittest.main()
