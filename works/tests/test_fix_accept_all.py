"""修正の受け付けが確かめを全部回して、誤りを 1 回の拒否に並べる（依頼 224）の検査。

- 盤面の乾いた照らし（Task 1）: DiskBoard.vet・entry.take と recount.accept_fix の commit=False が、受け付けと同じ検査を
  当てて盤面を書かず、拒否なら誤りを problems に並べる
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import hashlib
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import test_blk_fix  # noqa: E402  （core・blk-fix/lib を sys.path に足す）
import entry  # noqa: E402
import recount  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
