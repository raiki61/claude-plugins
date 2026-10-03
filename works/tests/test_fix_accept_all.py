"""修正の受け付けが確かめを全部回して、誤りを 1 回の拒否に並べる（依頼 224）の検査。

- 盤面の乾いた照らし（Task 1）: DiskBoard.vet・entry.take と recount.accept_fix の commit=False が、受け付けと同じ検査を
  当てて盤面を書かず、拒否なら誤りを problems に並べる
- 拒否の見出しと id の表・並べ方（Task 2）: accept.CHECKS・note・render_rejects・rejected が、確かめごとに見出しを立てて
  文を並べ、rejects に 1 行ずつ id を付ける
- 申し出より後の確かめを全部回す（Task 3）: accept_fix が確かめを返さずに積み、写しの照らしも乾いた形で当てて 1 回の拒否に
  並べる。最後の回は止めてよい確かめの行だけで単位を止める
- 凍結と書き込みの出どころも積む（Task 4）: 凍ったテストのファイル・書き込みの出どころの誤りも積んで先へ進み、食い違いの申し出は
  積んだ誤りに依らず裁定へ渡す（run 222f の 3 回の拒否を 1 回に並べる）
- 待つ単位の控え（Task 5。226 との継ぎ目）: 案の直しを待つ単位が在る盤面で、控える（hold_fix）のは積んだ行が無く写しの照らしも
  乾いた形で通る返答だけ。誤りが在れば控えずに並べて拒む（控えた返答を hand_held が渡して拒まれ盤面が止まる前に役へ返す）
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
from test_blk_fix_conflict import ReplanCase, conflict_on_mean, only_clamp_reply  # noqa: E402

FROZEN_LINE = "TDD の輪で凍ったテストのファイルを書き換えた: ['test_stats.py']（輪で直した単位のテストは変えない）"
WRITES_LINE = "書き込みの出どころの記録が無い変更: stats.py"


def accept_module(name):
    """blk-fix/scripts/accept.py を別名で読む（test_blk_fix.TestAccept.accept_module に任せる）"""
    return test_blk_fix.TestAccept.accept_module(None, name)


def sha(path) -> str:
    """ファイルの sha256"""
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def conflict_items(board) -> list:
    """盤面の今の周の食い違いの控え（conflict.FILE）の items"""
    return conflict.items(entry.open_board(board, allow_halted=True))


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


class SeamCase(test_blk_fix.BoardCase):
    """凍結と書き込みの出どころも積み、食い違いの申し出は積んだ誤りに依らず裁定へ渡す（Task 4。run 222f の型）"""

    acc = AllChecksCase.acc
    env = AllChecksCase.env
    accept_direct = AllChecksCase.accept_direct
    tdd_frozen = test_blk_fix.TestAccept.tdd_frozen
    scope_ready = test_blk_fix.TestAccept.scope_ready

    def test_222f_three_classes_in_one_rejection(self):
        # run 222f の 3 回の拒否（凍ったテストのファイル・修正案の範囲・写しの照らし）を、1 回の拒否に並べる
        state = self.tdd_frozen()                                            # test_stats.py を凍らせ、FIXED を当てた木
        (self.repo / "test_stats.py").write_text((self.repo / "test_stats.py").read_text(encoding="utf-8") + "\n# 凍った後の書き換え\n",
                                                 encoding="utf-8")         # 1 回目の型
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")     # 2 回目の型（allowed_paths は stats.py だけ）
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py")
        reply["changes"][1]["breaks"]["result"] = "なし"                     # 3 回目の型（写しの fix_covers_open_units）
        before = sha(self.board / "state.json")
        with mock.patch.object(self.acc, "check_tests", return_value=([], "")), self.env(state=state):
            got = self.acc.accept_fix(reply, self.board, "", self.repo)
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertEqual([c for c in self.acc.CHECKS if c in {"frozen", "scope", "copy"}],
                         [c for c in dict.fromkeys(checks) if c in {"frozen", "scope", "copy"}], checks)
        self.assertTrue(any("test_stats.py" in r["text"] for r in got["rejects"] if r["check"] == "frozen"))
        self.assertTrue(any("other.py" in r["text"] for r in got["rejects"] if r["check"] == "scope"))
        self.assertTrue(any(r["text"].startswith(CLAMP[:60]) for r in got["rejects"] if r["check"] == "copy"))
        self.assertEqual(sha(self.board / "state.json"), before)

    def test_frozen_error_does_not_stop_ruled_revert(self):
        # 決め 5: ruled で凍結の誤りが在っても revert_ruled_units は今の位置で呼ばれる（224e の事前審査の穴 3）
        self.fix_ready(); self.edit_tree(FIXED)
        with mock.patch.object(self.acc, "check_frozen", return_value=[FROZEN_LINE]), \
                mock.patch.object(self.acc, "revert_ruled_units", return_value=None) as revert:
            got = self.accept_direct(load("fix2_ok"), pass_="ruled")
        self.assertFalse(got["ok"])
        revert.assert_called_once()
        self.assertIn("frozen", [r["check"] for r in got["rejects"]])

    def first_pass_conflict(self) -> dict:
        """凍結の誤りが在る 1 回目に、名指しの在る食い違いの申し出（mean）を出す"""
        with mock.patch.object(self.acc, "check_frozen", return_value=[FROZEN_LINE]), self.env():
            return self.acc.accept_fix(only_clamp_reply([conflict_on_mean()]), self.board, "", self.repo)

    def test_first_pass_conflict_reaches_ruling_with_frozen_error(self):
        self.fix_ready(); self.edit_tree(FIXED)
        got = self.first_pass_conflict()
        self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.assertEqual([(i["unit_key"], i["status"]) for i in conflict_items(self.board)], [(MEAN, "parked")])

    def test_same_conflict_twice_parks_once(self):
        self.fix_ready(); self.edit_tree(FIXED)
        for _ in range(2):
            got = self.first_pass_conflict()
            self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.assertEqual(len(conflict_items(self.board)), 1)

    def test_ruled_pass_conflict_parked_despite_writes_error(self):
        # ruled で書き込みの出どころの誤り（check_writes を mock で 1 行に）と新しい申し出 → 拒否に writes が載り、申し出は
        # ask_human の裁定つきで積まれたまま残る（拒否で巻き戻さない。224e の R2）。同じ返答をもう一度出しても行は 1 つ
        self.fix_ready(); self.edit_tree(FIXED)

        def wrote(reply, *a, **k):
            return {"reply": {f: v for f, v in reply.items() if f != "bash_writes"}, "problems": [WRITES_LINE], "note": "",
                    "left": []}
        for _ in range(2):
            with mock.patch.object(self.acc, "check_writes", side_effect=wrote):
                got = self.accept_direct(only_clamp_reply([conflict_on_mean()]), pass_="ruled")
            self.assertFalse(got["ok"], got)
            self.assertIn(("writes", WRITES_LINE), [(r["check"], r["text"]) for r in got["rejects"]])
            self.assertEqual([(i["unit_key"], i["ruling"]["decision"]) for i in conflict_items(self.board)],
                             [(MEAN, conflict.ASK)])


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
            ("not_opened", False), ("accepted", False), ("excused", False), ("scope", True), ("tests", True), ("gates", True), ("copy", True)])

    def test_yaml_names_rejects_on_both_accept_nodes(self):
        nodes = test_blk_fix.block()["nodes"]
        for nid in ("fix-accept", "fix-ruled-accept"):
            with self.subTest(nid=nid):
                fmt = test_blk_fix.find_node(nodes, nid)["output_format"]
                self.assertEqual(fmt["properties"].get("rejects"), {"type": "array"})
                self.assertNotIn("rejects", fmt["required"])


class HoldCase(ReplanCase):
    """案の直しを待つ単位（mean を fix_plan_item に裁いた盤面）が在る間の受け付け（2 回目の受け付け ruled）"""

    acc = AllChecksCase.acc
    env = AllChecksCase.env

    def accept_held(self, reply):
        """受け付けの本体を ruled で直に呼ぶ。返り (結果, hold_fix の mock, recount.accept_fix の mock)"""
        self.replanned()
        self.assertTrue(conflict.waiting(entry.open_board(self.board)))
        with mock.patch.object(self.acc, "hold_fix", wraps=self.acc.hold_fix) as hold, \
                mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc, \
                self.env(pass_="ruled"):
            got = self.acc.accept_fix(reply, self.board, "", self.repo)
        return got, hold, rc

    def assert_not_held(self, got, hold, rc):
        self.assertIs(got["ok"], False, got)
        hold.assert_not_called()
        self.assertFalse(entry.open_board(self.board).work(conflict.HELD_REPLY).exists())
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_waiting_board_rejects_instead_of_holding(self):
        reply = only_clamp_reply()
        reply["changes"].append(reply["changes"][0])          # 重なりの誤り
        got, hold, rc = self.accept_held(reply)
        self.assert_not_held(got, hold, rc)
        self.assertIn("duplicate", [r["check"] for r in got["rejects"]])

    def test_waiting_board_rejects_copy_error_before_holding(self):
        # 積んだ行が無くても、写しの照らしの誤りが在れば控えない（乾いた照らしで役へ返す。裁定 F6）
        reply = only_clamp_reply()
        reply["changes"][0]["breaks"]["result"] = "なし"
        got, hold, rc = self.accept_held(reply)
        self.assert_not_held(got, hold, rc)
        self.assertEqual({r["check"] for r in got["rejects"]}, {"copy"}, got["rejects"])

    def test_waiting_board_holds_clean_reply(self):
        got, hold, rc = self.accept_held(only_clamp_reply())
        self.assertEqual((got["ok"], got.get("parked"), got["done"]), (True, True, True), got)
        hold.assert_called_once()
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)   # 乾いた照らしだけで、盤面には渡さない
        b = entry.open_board(self.board)
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file())
        self.assertNotIn("p3.fix", b.state["outputs"])


if __name__ == "__main__":
    unittest.main()
