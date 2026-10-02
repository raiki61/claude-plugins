"""承認済みの修正案を項目ごとの brief に切り出して凍結する口（blk-fix/lib/planbrief.py）の検査。
- 項目ごとの brief: 修正案の項目と盤面の控え（plan-fields.json）の欄と、判定の単位・目的の文・構造の目の行を 1 つのファイルに並べた文
- 凍結: 今の周に 1 度だけ書き、sha256 を控え（briefs.json）に残す。書き換えられたら控えの文で書き戻す
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import hashlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import test_blk_fix as tbf  # noqa: E402
import entry  # noqa: E402
import planbrief  # noqa: E402
import planmarks  # noqa: E402

FIELDS = [{"route": "tdd", "route_why": "", "tests": [{"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "2 つの値の平均",
           "path": "stats.mean を直に呼ぶ", "red_kind": "assertion", "red_why": "今は len-1 で割る"}], "rewrite_tests": [],
           "refactor": {"declared": False, "why": ""}}]


class BriefCase(tbf.BoardCase):
    def ready(self):
        self.fix_ready()
        planmarks.save(self.board, entry.open_board(self.board).round, FIELDS)
        return entry.open_board(self.board)

    def test_render_is_deterministic_and_carries_item(self):
        b = self.ready()
        got = planbrief.cut(b)
        text = pathlib.Path(got[0]["file"]).read_text(encoding="utf-8")
        for w in ("要求の正本", "test_stats.py::TestStats::test_mean_of_two", tbf.plan_reply()["plan"][0]["approach"], tbf.MEAN, "背景"):
            self.assertIn(w, text)
        self.assertEqual(got[0]["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_cut_is_frozen_and_restores_edited_file(self):
        b = self.ready(); first = planbrief.cut(b)
        pathlib.Path(first[0]["file"]).write_text("書き換えた", encoding="utf-8")
        again = planbrief.cut(entry.open_board(self.board))
        self.assertEqual(again, first)
        self.assertEqual(hashlib.sha256(pathlib.Path(first[0]["file"]).read_bytes()).hexdigest(), first[0]["sha256"])
        self.assertIn(planbrief.RESTORED_OP, (self.board / "trace.jsonl").read_text(encoding="utf-8"))

    def test_cut_keeps_frozen_text_when_sources_change(self):
        b = self.ready(); first = planbrief.cut(b)
        before = pathlib.Path(first[0]["file"]).read_bytes()
        changed = [dict(FIELDS[0], route="direct", route_why="凍結の後に控えを書き換えた理由の文", tests=[])]
        planmarks.save(self.board, b.round, changed)
        again = planbrief.cut(entry.open_board(self.board))
        self.assertEqual(again, first)
        self.assertEqual(pathlib.Path(first[0]["file"]).read_bytes(), before)
        self.assertNotIn("凍結の後に控えを書き換えた理由の文", before.decode("utf-8"))

    def test_no_plan_or_no_fields_no_brief(self):
        self.fix_ready()
        b = entry.open_board(self.board)
        self.assertEqual(planbrief.cut(b), [])
        self.assertFalse((self.board / f"r{b.round}" / planbrief.LEDGER).exists())
        self.assertEqual(planbrief.cut_at(self.tmp / "no-board"), [])

    def test_for_units_picks_items_of_the_units(self):
        rows = [{"item": 1, "unit_keys": [tbf.MEAN, tbf.CLAMP], "file": "/b/brief-1.md", "sha256": "a" * 64},
                {"item": 2, "unit_keys": [tbf.MEAN], "file": "/b/brief-2.md", "sha256": "b" * 64}]
        self.assertEqual([r["item"] for r in planbrief.for_units(rows, [tbf.MEAN])], [1, 2])
        self.assertEqual([r["item"] for r in planbrief.for_units(rows, [tbf.CLAMP])], [1])
        self.assertEqual(planbrief.for_units(rows, ["判定に無い単位"]), [])

    def test_head_text(self):
        self.assertEqual(planbrief.head_text([]), "")
        rows = planbrief.cut(self.ready())
        head = planbrief.head_text(rows)
        for w in (planbrief.HEAD, rows[0]["file"], rows[0]["sha256"], "まず Read で全部読め"):
            self.assertIn(w, head)
        self.assertEqual(planbrief.files(entry.open_board(self.board)), [rows[0]["file"]])


if __name__ == "__main__":
    unittest.main()
