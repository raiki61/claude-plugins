"""同じ run の中の案の直し（依頼 226）の締め: replan.close・close_at・settle。

待つ単位（裁定 fix_plan_item の行の状態 WAITING）を残したまま修正の段を抜けない。h-rejudge（settle）と報告の組み立て
（report.build の close_at）が、待つ行を諦めた行（GAVE_UP）にして ask_human の道に載せる。止まった盤面でも締める。
締めた後に待つ行が残れば BoardGap。持ち越し（次の run の修正案へ）の道は無い。
"""
import pathlib
import sys
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

from test_blk_fix_conflict import CLAMP, MEAN, PLAN_TEXT, ReplanCase, only_clamp_reply  # noqa: E402,F401

import board  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
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
        self.assertFalse(got["handed"])
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


if __name__ == "__main__":
    unittest.main()
