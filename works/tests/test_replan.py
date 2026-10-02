"""同じ run の中の案の直し（依頼 226）の締め: replan.close・close_at・settle。

待つ単位（裁定 fix_plan_item の行の状態 WAITING）を残したまま修正の段を抜けない。h-rejudge（settle）と報告の組み立て
（report.build の close_at）が、待つ行を諦めた行（GAVE_UP）にして ask_human の道に載せる。止まった盤面でも締める。
締めた後に待つ行が残れば BoardGap。持ち越し（次の run の修正案へ）の道は無い。
待つ単位が在る間、修正の受け付けは返答を盤面に渡さずに控え（conflict.HELD_REPLY。受けた時と同じ trace を書く）、settle が渡す
（replan.hand_held）。集める節と報告は返答を recount.fix_reply の 1 つの口で読む（盤面の p3.fix か控え）。
"""
import json
import pathlib
import sys
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

from test_blk_fix_conflict import CLAMP, MEAN, PLAN_TEXT, ReplanCase, accept_module, only_clamp_reply  # noqa: E402,F401

import board  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
