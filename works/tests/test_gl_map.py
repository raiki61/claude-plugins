"""accept.py から本線の gl.py への対応表（works/.shared/core/gl_map.json）の検査。

Task 24（裁定 TA25）: 受け付けの口は本線の 3-8 まで accept.py のまま。載せ替えの日のために、
accept.py の公開の関数ごとに本線の相手と足りない物を表にしておく。accept.py に公開の関数を
足す・消すと、表に行が無い／余るのでここが赤になる（検査を足すなら、ブロックの受け付けの
スクリプトに置き、表に works-only の行で載せる）。
"""
import ast
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
MAP = CORE / "gl_map.json"
ACCEPT = CORE / "accept.py"
STATUSES = {"ready", "missing", "works-only"}


def public_functions(path: pathlib.Path) -> set:
    """ファイルの一番外の公開の関数（名前が _ で始まらない def）の名前。import はしない。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


def load_map() -> list:
    return json.loads(MAP.read_text(encoding="utf-8"))


def accept_rows(rows) -> list:
    """works の欄が accept.<関数> の行の関数名（重なりも残す）。"""
    return [r["works"][len("accept."):] for r in rows if r["works"].startswith("accept.")]


class TestGlMap(unittest.TestCase):
    def test_rows_have_the_four_fields(self):
        rows = load_map()
        self.assertIsInstance(rows, list)
        for r in rows:
            self.assertEqual(set(r), {"works", "gl", "status", "note"}, r)
            self.assertIn(r["status"], STATUSES, r)
            for k in ("works", "gl", "note"):
                self.assertIsInstance(r[k], str, r)
            self.assertTrue(r["works"] and r["note"], r)
        works = [r["works"] for r in rows]
        self.assertEqual(len(works), len(set(works)), "works の欄が重なる行")

    def test_every_accept_function_mapped(self):
        """accept.py の公開の関数の全部が、表の works に 1 度ずつ在る。"""
        names = accept_rows(load_map())
        for fn in sorted(public_functions(ACCEPT)):
            self.assertEqual(names.count(fn), 1, f"accept.{fn} の行が {names.count(fn)} 本")

    def test_missing_four_named(self):
        """本線の返答の足りない 4 つ: 依頼に依らない検査・注記を外す・判定の受け付け・差分を切る。"""
        by = {r["works"]: r for r in load_map()}
        for works, word in (("accept.check_request", "依頼"),
                            ("accept.role_schema", "注記"),
                            ("accept.check_judge", "判定"),
                            ("accept.cut_delta", "差分")):
            self.assertIn(works, by)
            self.assertEqual(by[works]["status"], "missing", works)
            self.assertIn(word, by[works]["note"], works)

    def test_works_only_checks_listed(self):
        """graphloops に無い works だけの検査は works-only。"""
        by = {r["works"]: r for r in load_map()}
        for works in ("accept.snapshot_tree", "accept.tree_state", "accept.tree_change", "accept.tree_moved",
                      "blk-premises/scripts/accept.py:check_claims",
                      "blk-pr/scripts/accept.py:check_no_post",
                      "blk-fix/scripts/accept.py:check_unique_units",
                      "blk-fix/scripts/accept.py:check_opened_units",
                      "leftovers.ignored_files",
                      "leftovers.record_ignored",
                      "leftovers.remove_new_ignored"):
            self.assertIn(works, by)
            self.assertEqual(by[works]["status"], "works-only", works)

    def test_leftovers_rows_name_core_functions(self):
        """後始末の 3 行は .shared/core/leftovers.py の公開の関数を指す（V13 で blk-fix/scripts から移した）"""
        rows = [r["works"] for r in load_map() if "leftovers" in r["works"]]
        self.assertEqual(sorted(rows), ["leftovers.ignored_files", "leftovers.record_ignored", "leftovers.remove_new_ignored"])
        have = public_functions(CORE / "leftovers.py")
        for w in rows:
            self.assertIn(w[len("leftovers."):], have, w)

    def test_no_branch_placeholder_rows(self):
        """合流を待つ枝の控えの行（works が <枝>:… の形）は残さない。入った関数は置き場の行に分ける。"""
        for r in load_map():
            self.assertFalse(r["works"].startswith("wip/"), r["works"])

    def test_ready_rows_name_a_gl_port(self):
        """ready の行は gl の口を名指す。note は読んだ本線の sha を持つ。"""
        rows = load_map()
        for r in rows:
            if r["status"] == "ready":
                self.assertTrue(r["gl"].startswith("gl "), r)
        by = {r["works"]: r for r in rows}
        self.assertEqual(by["accept.check_fix"]["gl"], "gl accept p3.fix")
        self.assertEqual(by["accept.check_delta"]["gl"], "gl accept p3.delta_review")
        self.assertTrue(any("d1b863f" in r["note"] for r in rows))

    def test_no_new_checks_in_accept(self):
        """accept.py の公開の関数の集合が、表の accept.* の控えと同じ（足しても消しても赤。TA25）。"""
        self.assertEqual(public_functions(ACCEPT), set(accept_rows(load_map())))


if __name__ == "__main__":
    unittest.main()
