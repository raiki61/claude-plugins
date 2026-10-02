"""修正の受け付けが確かめを全部回して、誤りを 1 回の拒否に並べる（依頼 224）の検査。

- 盤面の乾いた照らし（Task 1）: DiskBoard.vet・entry.take と recount.accept_fix の commit=False が、受け付けと同じ検査を
  当てて盤面を書かず、拒否なら誤りを problems に並べる
- 拒否の見出しと id の表・並べ方（Task 2）: accept.CHECKS・note・render_rejects・rejected が、確かめごとに見出しを立てて
  文を並べ、rejects に 1 行ずつ id を付ける
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
