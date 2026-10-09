"""承認済みの修正案を項目ごとの brief に切り出して凍結する口（blk-fix/lib/planbrief.py）の検査。
- 項目ごとの brief: 修正案の項目と盤面の控え（plan-fields.json）の欄と、判定の単位・目的の文・構造の目の行を 1 つのファイルに並べた文
- 凍結: 今の周に 1 度だけ書き、sha256 を控え（briefs.json）に残す。書き換えられたら控えの文で書き戻す
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import hashlib
import json
import os
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
           "refactor": {"declared": False, "why": ""}, "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}]


def count_ops(board, op) -> int:
    """盤面の trace.jsonl の、今の周の op の行の数"""
    rnd = entry.open_board(board).round
    rows = [json.loads(line) for line in (pathlib.Path(board) / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(1 for r in rows if r.get("op") == op and r.get("round") == rnd)


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
        args = (1, tbf.plan_reply()["plan"][0], FIELDS[0], {u["key"]: u for u in b.record["units"]}, "目的の文", "")
        self.assertEqual(planbrief.render(*args), planbrief.render(*args))

    def test_brief_carries_prescriptions_and_structure_answers(self):
        """修正役の brief に、判定の処方（盤面の記録は写さないので判定の返答から）と、修正案が構造の目の行・処方に答えた欄
        structure が載る（計画 2026-10-09-clean-whole の Task 2.4・利用者の声 D2）"""
        judge = tbf.load(tbf.JUDGE)
        judge["units"][0]["prescriptions"] = ["分母を len(xs) にする（既存の機構 1 つで済ませる）"]
        self.fix_ready(judge=judge)
        dev = {"row": tbf.MEAN, "deviation": "既存の呼び手が 3 つあり、今回は 1 か所に寄せると範囲が広がりすぎる"}
        planmarks.save(self.board, entry.open_board(self.board).round, [{**FIELDS[0], "structure": [dev]}])
        got = planbrief.cut(entry.open_board(self.board))
        text = pathlib.Path(got[0]["file"]).read_text(encoding="utf-8")
        self.assertIn("分母を len(xs) にする（既存の機構 1 つで済ませる）", text)
        self.assertIn("## 構造の目の行と処方への答え（structure）", text)
        self.assertIn(dev["deviation"], text)

    def test_render_shows_scope(self):
        """brief に書いてよいパス（allowed_paths）と触らない物（out_of_scope）の節が並ぶ。欄の無い行（217 番の形）は無し"""
        item1 = tbf.plan_reply()["plan"][0]
        f = {**FIELDS[0], "allowed_paths": ["stats.py"], "out_of_scope": [{"glob": "test_stats.py", "why": "既存の試験は触らない"}]}
        text = planbrief.render(1, item1, f, {}, "", "")
        for w in ("## 書いてよいパス（allowed_paths）", "- stats.py", "## 触らない物（out_of_scope）", "test_stats.py——既存の試験は触らない"):
            self.assertIn(w, text)
        old = {k: v for k, v in f.items() if k not in ("allowed_paths", "out_of_scope")}
        self.assertIn("## 書いてよいパス（allowed_paths）\n\n無し", planbrief.render(1, item1, old, {}, "", ""))
        text_old = planbrief.render(1, item1, old, {}, "", "")
        for h in ("## 書いてよいパス（allowed_paths）", "## 触らない物（out_of_scope）"):
            self.assertIn(f"{h}\n\n無し（この案は範囲を決めていない。範囲では縛らない）", text_old)
        self.assertIn("## 触らない物（out_of_scope）\n\n無し\n", planbrief.render(1, item1, {**f, "out_of_scope": []}, {}, "", ""))

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


    # ---------------------------------------------------------------- 凍結の破れ（LedgerBroken）と書き戻し
    def first_cut(self):
        """1 回目の cut の後の (盤面, 返り, 控えのパス)"""
        b = self.ready()
        rows = planbrief.cut(b)
        return b, rows, self.board / f"r{b.round}" / planbrief.LEDGER

    def edit_ledger(self, ledger, change):
        doc = json.loads(ledger.read_text(encoding="utf-8"))
        change(doc["briefs"][0])
        ledger.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def assert_broken(self, pattern):
        with self.assertRaisesRegex(planbrief.LedgerBroken, pattern):
            planbrief.cut(entry.open_board(self.board))

    def test_ledger_not_json_is_broken(self):
        _, _, ledger = self.first_cut()
        ledger.write_text("{壊れた", encoding="utf-8")
        self.assert_broken("読めない")

    def test_ledger_row_text_not_matching_sha_is_broken(self):
        _, _, ledger = self.first_cut()
        self.edit_ledger(ledger, lambda r: r.update(text=r["text"] + "足した"))
        self.assert_broken("sha256 が合わない")

    def test_ledger_row_file_with_path_is_broken(self):
        _, _, ledger = self.first_cut()
        self.edit_ledger(ledger, lambda r: r.update(file="../x"))
        self.assert_broken("形を成さない")

    def test_ledger_row_item_and_unit_keys_shape(self):
        _, _, ledger = self.first_cut()
        self.edit_ledger(ledger, lambda r: r.update(item="1"))
        self.assert_broken("形を成さない")
        self.edit_ledger(ledger, lambda r: r.update(item=1, unit_keys=[1]))
        self.assert_broken("形を成さない")

    def test_item_count_differs_from_fields_is_broken(self):
        self.fix_ready()
        planmarks.save(self.board, entry.open_board(self.board).round, FIELDS * 2)
        self.assert_broken("数")
        self.assertFalse(any(self.board.glob("r*/" + planbrief.LEDGER)))

    def test_ledger_deleted_after_first_cut_is_broken(self):
        b, _, ledger = self.first_cut()
        ledger.unlink()
        planmarks.save(self.board, b.round, [dict(FIELDS[0], route="direct", route_why="控えを消してから欄を書き換えた")])
        self.assert_broken("brief_cut")

    def test_ledger_rewritten_consistently_is_broken(self):
        _, _, ledger = self.first_cut()

        def forge(r):
            r["text"] = "役が書き換えた要求"
            r["sha256"] = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
        self.edit_ledger(ledger, forge)
        self.assert_broken("brief_cut")

    def test_first_cut_traces_ledger_sha(self):
        b, rows, ledger = self.first_cut()
        cuts = [json.loads(line) for line in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines()
                if '"brief_cut"' in line]
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0]["round"], b.round)
        self.assertEqual(cuts[0]["ledger_sha256"], hashlib.sha256(ledger.read_bytes()).hexdigest())
        self.assertEqual(cuts[0]["files"], [r["file"] for r in rows])
        planbrief.cut(entry.open_board(self.board))
        self.assertEqual((self.board / "trace.jsonl").read_text(encoding="utf-8").count('"brief_cut"'), 1)

    def test_deleted_brief_is_restored(self):
        _, first, _ = self.first_cut()
        pathlib.Path(first[0]["file"]).unlink()
        self.assertEqual(planbrief.cut(entry.open_board(self.board)), first)
        self.assertEqual(hashlib.sha256(pathlib.Path(first[0]["file"]).read_bytes()).hexdigest(), first[0]["sha256"])
        self.assertIn(planbrief.RESTORED_OP, (self.board / "trace.jsonl").read_text(encoding="utf-8"))

    def test_restore_does_not_write_through_symlink(self):
        _, first, _ = self.first_cut()
        outside = self.tmp / "outside.txt"
        outside.write_text("外のファイル", encoding="utf-8")
        brief = pathlib.Path(first[0]["file"])
        brief.unlink()
        os.symlink(outside, brief)
        planbrief.cut(entry.open_board(self.board))
        self.assertEqual(outside.read_text(encoding="utf-8"), "外のファイル")
        self.assertFalse(brief.is_symlink())
        self.assertEqual(hashlib.sha256(brief.read_bytes()).hexdigest(), first[0]["sha256"])

    def test_restore_over_directory_is_broken(self):
        _, first, _ = self.first_cut()
        brief = pathlib.Path(first[0]["file"])
        brief.unlink()
        brief.mkdir()
        self.assert_broken("ディレクトリ")


class BriefFreezeEdgeCase(tbf.BoardCase):
    """凍結の端: 欄の控え plan-fields.json の書き換え・cut の外で置いた控え・控えの一時ファイルのリンク"""
    ready = BriefCase.ready

    def test_fields_rewritten_before_first_cut_is_broken(self):
        """受け付けの後（1 回目の cut の前）に plan-fields.json を書き換えた盤面は brief を切らず LedgerBroken（控えを名指す）"""
        b = self.ready()
        p = self.board / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["route"] = "direct"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(planbrief.LedgerBroken, planmarks.FIELDS_FILE):
            planbrief.cut(entry.open_board(self.board))
        self.assertFalse((self.board / f"r{b.round}" / planbrief.LEDGER).exists())

    def test_unmarked_ledger_before_first_cut_is_broken(self):
        """1 回目の cut の前に置かれた控え（行の text と sha256 は揃っているが、切った印が無い）を正本にしない"""
        b = self.ready()
        text = "# 要求の正本: cut の外で書いた brief\n"
        ledger = self.board / f"r{b.round}" / planbrief.LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"briefs": [{"item": 1, "unit_keys": [tbf.MEAN], "file": "brief-1.md", "text": text,
                                                  "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}]},
                                     ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(planbrief.LedgerBroken, "印が無い"):
            planbrief.cut(entry.open_board(self.board))

    def test_ledger_tmp_symlink_is_not_written_through(self):
        """控えの一時ファイル（briefs.json.tmp）の置き場に先にリンクが在っても、リンクの先へ書かない"""
        b = self.ready()
        box = self.board / f"r{b.round}"
        box.mkdir(parents=True, exist_ok=True)
        outside = self.tmp / "outside.json"
        outside.write_text("外のファイル", encoding="utf-8")
        os.symlink(outside, box / (planbrief.LEDGER + ".tmp"))
        rows = planbrief.cut(entry.open_board(self.board))
        self.assertEqual(len(rows), 1)
        self.assertEqual(outside.read_text(encoding="utf-8"), "外のファイル")
        self.assertFalse((box / planbrief.LEDGER).is_symlink())


class TestRecutAfterAmend(tbf.BoardCase):
    """承認済みの項目の差し替え（planmarks.amend の AMEND_OP の印）の後の cut だけが、差し替えた項目の brief を切り直す"""
    ready = BriefCase.ready

    def amend_first(self, b):
        new = {k: v for k, v in planmarks.approved_items(b)[0].items() if k != "item"}
        new["tests"] = [{**new["tests"][0], "red_kind": "exception", "red_why": "今は ZeroDivisionError が出ない"}]
        planmarks.amend(b, {1: new}, self.repo)

    def test_recut_after_amend(self):
        b = self.ready()
        first = planbrief.cut(b)
        self.amend_first(b)
        again = planbrief.cut(entry.open_board(self.board))
        text = pathlib.Path(again[0]["file"]).read_text(encoding="utf-8")
        self.assertIn("exception", text)
        self.assertNotEqual(first[0]["sha256"], again[0]["sha256"])
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 1)
        self.assertEqual(count_ops(self.board, planbrief.CUT_OP), 2)
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), again[0]["sha256"])
        # 切り直した後は凍結に戻る（もう 1 度 cut しても切り直さない・控えは新しい CUT_OP の印と合う）
        self.assertEqual(planbrief.cut(entry.open_board(self.board)), again)
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 1)
        self.assertEqual(count_ops(self.board, planbrief.CUT_OP), 2)

    def test_no_recut_without_amend(self):
        b = self.ready()
        planbrief.cut(b); planbrief.cut(entry.open_board(self.board))
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 0)
        self.assertEqual(count_ops(self.board, planbrief.CUT_OP), 1)

    def test_tamper_after_recut_is_restored(self):
        b = self.ready()
        planbrief.cut(b)
        self.amend_first(b)
        again = planbrief.cut(entry.open_board(self.board))
        brief = pathlib.Path(again[0]["file"])
        brief.write_text("役が書き換えた", encoding="utf-8")
        self.assertEqual(planbrief.cut(entry.open_board(self.board)), again)
        self.assertEqual(hashlib.sha256(brief.read_bytes()).hexdigest(), again[0]["sha256"])
        self.assertIn("exception", brief.read_text(encoding="utf-8"))
        self.assertIn(planbrief.RESTORED_OP, (self.board / "trace.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(count_ops(self.board, planbrief.RECUT_OP), 1)


if __name__ == "__main__":
    unittest.main()
