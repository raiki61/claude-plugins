"""修正の受け付けが確かめを全部回して、誤りを 1 回の拒否に並べる（依頼 224）の検査。

- 盤面の乾いた照らし（Task 1）: DiskBoard.vet・entry.take と recount.accept_fix の commit=False が、受け付けと同じ検査を
  当てて盤面を書かず、拒否なら誤りを problems に並べる
- 拒否の見出しと id の表・並べ方（Task 2）: accept.CHECKS・note・render_rejects・rejected が、確かめごとに見出しを立てて
  文を並べ、rejects に 1 行ずつ id を付ける
- 申し出より後の確かめを全部回す（Task 3）: accept_fix が確かめを返さずに積み、写しの照らしも乾いた形で当てて 1 回の拒否に
  並べる。最後の回は止めてよい確かめの行だけで単位を止める
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import hashlib
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import test_blk_fix  # noqa: E402  （core・blk-fix/lib を sys.path に足す）
import entry  # noqa: E402
import recount  # noqa: E402
import conflict  # noqa: E402
from test_blk_fix import CLAMP, FIXED, INVENTED, MEAN, extra_row, load  # noqa: E402


def accept_module(name):
    """blk-fix/scripts/accept.py を別名で読む（test_blk_fix.TestAccept.accept_module に任せる）"""
    return test_blk_fix.TestAccept.accept_module(None, name)


def sha(path) -> str:
    """ファイルの sha256"""
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class DryTakeCase(test_blk_fix.BoardCase):
    def two_copy_errors(self):
        reply = test_blk_fix.load("fix2_ok")
        reply["changes"][0]["bypass_tried"] = "なし"       # 写しの照らしの誤り 1（mean の行）
        reply["changes"][1]["breaks"]["result"] = "なし"   # 写しの照らしの誤り 2（clamp の行）
        return reply

    def test_dry_take_lists_copy_errors_and_writes_nothing(self):
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(self.two_copy_errors(), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"], got["changes"]), (False, True, []), got)
        self.assertEqual(len(got["problems"]), 2, got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_dry_take_of_clean_reply_leaves_board_waiting(self):
        # 乾いた照らしが通る返答は、後で commit しても同じく通る（当てる物が同じ）
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"]), (True, True), got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertIs(recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo)["ok"], True)
        self.assertNotEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_schema_errors_carry_one_problem_each(self):
        # 型の誤りの拒否は problems を持たない（commit の道の形を全部の節で今のまま保つ）ので、乾いた道は文を 1 要素で返す。
        # 欠けた 2 つの鍵は、その 1 つの文に並ぶ
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        reply = test_blk_fix.load("fix2_ok"); del reply["interactions"]; del reply["wrote_refs"]
        got = entry.take(self.board, "p3.fix", reply, self.repo, commit=False)
        self.assertIn("返答が型に合わない", got["reason"])
        self.assertEqual(got["problems"], [got["reason"]], got)
        self.assertIn("interactions", got["reason"])
        self.assertIn("wrote_refs", got["reason"])


class AllChecksCase(test_blk_fix.BoardCase):
    """受け付けの本体（accept_fix）を本物の盤面・作業ツリーの上で直に呼ぶ（最後の回の 2 つはスクリプトを子で起こす）"""

    acc = accept_module("blk_fix_accept_all")
    run_it = test_blk_fix.TestAccept.run_it
    scope_ready = test_blk_fix.TestAccept.scope_ready
    parked_units = test_blk_fix.ParkBoundBase.parked_units

    def env(self, iteration="1", pass_="first", state=""):
        """受け付けの入力の環境変数（実行器は無し）"""
        return mock.patch.dict(os.environ, {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": state, "INPUTS_PASS": pass_,
                                            "INPUTS_TDD_SUITE": ""})

    def accept_direct(self, reply, **env) -> dict:
        with self.env(**env):
            return self.acc.accept_fix(reply, self.board, "", self.repo)

    def test_duplicate_and_unopened_listed_together(self):
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"] += [reply["changes"][0], extra_row(INVENTED)]
        got = self.accept_direct(reply)          # iteration 1・first・state 空・suite 空
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertTrue({"duplicate", "not_opened"} <= set(checks), checks)
        self.assertIn(INVENTED, got["reason"])

    def test_scope_and_copy_listed_together(self):
        self.scope_ready(["docs/**"]); self.edit_tree(FIXED)
        reply = load("fix2_ok"); reply["changes"][1]["breaks"]["result"] = "なし"
        with mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc:
            got = self.accept_direct(reply)
        self.assertEqual([r["check"] for r in got["rejects"]][:1], ["scope"])
        self.assertIn("copy", [r["check"] for r in got["rejects"]])
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_tests_and_gates_run_with_form_errors(self):
        # 決め 2: 重なりの誤りが在っても、選んだ試験と事後の関門の束を 1 回ずつ回す
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"].append(reply["changes"][0])
        with mock.patch.object(self.acc, "check_tests", return_value=([], "")) as tests, \
                mock.patch.object(self.acc.fixgates, "problems", return_value=[]) as gates:
            got = self.accept_direct(reply)
        self.assertFalse(got["ok"])
        self.assertEqual((tests.call_count, gates.call_count), (1, 1))
        self.assertIn("duplicate", [r["check"] for r in got["rejects"]])

    def test_clean_reply_takes_once(self):
        self.fix_ready(); self.edit_tree(FIXED)
        with mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc:
            got = self.accept_direct(load("fix2_ok"))
        self.assertIs(got["ok"], True, got)
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], True)

    def test_last_round_parks_units_bound_by_two_checks(self):
        # 最後の回: mean の行は範囲の外の other.py（scope）、clamp の行は breaks.result「なし」（copy）。2 つの確かめの行が
        # それぞれ別の単位に結べるので、両方を止めて残りで通す（ParkBoundMultiLineCase と同じ盤面の形）
        self.scope_ready(["stats.py"]); self.edit_tree(FIXED)
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py"); reply["changes"][1]["breaks"]["result"] = "なし"
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3")[1])
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))

    def test_last_round_unbindable_line_rejects_whole(self):
        # 最後の回: 重なり（止めない確かめ）と clamp の写しの誤り（止めてよい確かめ）→ 何も止めず全体を拒み、両方を並べる
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"][1]["breaks"]["result"] = "なし"
        reply["changes"].append(reply["changes"][0])
        code, out, err = self.run_it(reply, INPUTS_ITERATION="3")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["done"]), (False, True), r)
        self.assertEqual(self.parked_units(), [])
        checks = [x["check"] for x in r["rejects"]]
        self.assertTrue({"duplicate", "copy"} <= set(checks), checks)
        self.assertEqual(list(self.board.rglob(conflict.FILE)), [])


class RenderCase(unittest.TestCase):
    acc = accept_module("blk_fix_accept_render")

    def test_groups_follow_table_order(self):
        found = []
        self.acc.note(found, "copy", ["c1"]); self.acc.note(found, "frozen", ["f1", ""]); self.acc.note(found, "copy", ["c2", "c1"])
        text = self.acc.render_rejects(found)
        self.assertTrue(text.startswith(self.acc.REJECT_HEAD))
        self.assertLess(text.index(self.acc.CHECKS["frozen"][0]), text.index(self.acc.CHECKS["copy"][0]))
        self.assertIn("（確かめ copy・2 件）", text)
        self.assertEqual([x for x in text.splitlines() if x.startswith("  - ")], ["  - f1", "  - c1", "  - c2"])

    def test_rejected_carries_one_check_per_line(self):
        found = []
        self.acc.note(found, "scope", ["s1"]); self.acc.note(found, "frozen", ["f1"])
        out = self.acc.rejected(found)
        self.assertEqual((out["ok"], out["changes"]), (False, []))
        self.assertEqual([r["check"] for r in out["rejects"]], ["frozen", "scope"])
        self.assertEqual([r["text"] for r in out["rejects"]], ["f1", "s1"])
        self.assertEqual(len(out["rejects"]), out["reason"].count("\n  - "))

    def test_multiline_text_is_indented(self):
        found = []
        self.acc.note(found, "copy", ["返答が型に合わない:\n  - a"])
        self.assertIn("  - 返答が型に合わない:\n      - a", self.acc.render_rejects(found))

    def test_unknown_check_is_value_error(self):
        with self.assertRaises(ValueError):
            self.acc.note([], "nope", ["x"])

    def test_table_values_are_the_ruled_ones(self):
        # 236 が role-rejects の行の確かめの id に引く表。id・並び（受け付けが回す順）・止めてよいかを固める
        self.assertEqual([(k, stop) for k, (_, stop) in self.acc.CHECKS.items()], [
            ("frozen", True), ("writes", True), ("conflict", False), ("pack", False), ("duplicate", False),
            ("not_opened", False), ("excused", False), ("scope", True), ("tests", True), ("gates", True), ("copy", True)])

    def test_yaml_names_rejects_on_both_accept_nodes(self):
        nodes = test_blk_fix.block()["nodes"]
        for nid in ("fix-accept", "fix-ruled-accept"):
            with self.subTest(nid=nid):
                fmt = test_blk_fix.find_node(nodes, nid)["output_format"]
                self.assertEqual(fmt["properties"].get("rejects"), {"type": "array"})
                self.assertNotIn("rejects", fmt["required"])


if __name__ == "__main__":
    unittest.main()
