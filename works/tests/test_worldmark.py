"""世界の解の行の住処（.shared/core/worldmark.py。計画 docs/plans/2026-10-09-world-solution.md の W4・5.3 節・5.7 節）。

行のファイル（JSON Lines）の読み・指示書の頭の節・答えの要る行・関所の軸・関所の行と、約束
（blk-world/world-row.schema.json）の欄と語が住処の定数と揃うことを見る。一時の置き場のファイルだけ（網・git・子のプロセスなし）。
"""
import inspect
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / ".shared" / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core"))

import worldmark  # noqa: E402

SCHEMA = ROOT / "blk-world" / "world-row.schema.json"


def row(**kw):
    base = {"finding": 1, "where": "src/red.py:12", "class_id": "w1", "problem": "テストを先に書く開発で、まだ無い機能を呼ぶテストをどう赤にするか",
            "activity": "テストを先に書く開発", "practice": "読み込みの失敗は赤に数えず、最小の仮の実装で走らせてから期待違いの失敗を赤とする",
            "sources": [{"id": "x1", "url": "https://example.org/tdd", "excerpt": "A compile error is not a red test."}],
            "applies": "赤の判定の直し全部", "not_applies": "",
            "versus": {"proposed": "生のログを読む役を足す", "verdict": "differs",
                       "challenge": "依頼は読む役を足す、定石は仮の実装で走らせる。読み込みの失敗が赤でない訳が無い限り定石を選ぶ"},
            "basis": "web", "cached": False}
    base.update(kw)
    return base


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rows):
        p = self.dir / worldmark.WORLD_FILE
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return p

    def test_rows_reads_lines(self):
        self.assertEqual(worldmark.rows(self.put([row(), row(finding=2)]))[1]["finding"], 2)

    def test_rows_refuses_broken_lines(self):
        p = self.dir / "w.jsonl"
        p.write_text("{]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            worldmark.rows(p)
        with self.assertRaises(ValueError):
            worldmark.rows(self.put([row(basis="rumor")]))
        with self.assertRaises(ValueError):
            worldmark.rows(self.put([row(versus={"proposed": "", "verdict": "maybe", "challenge": ""})]))
        with self.assertRaises(ValueError):
            worldmark.rows(self.dir / "missing.jsonl")

    def test_section_marks_knowledge_rows(self):
        p = self.put([row(), row(finding=2, class_id="w2", basis="knowledge", sources=[], practice="小さな定石")])
        got = worldmark.section(worldmark.rows(p))
        self.assertIn(worldmark.HEAD, got)
        self.assertIn("w1", got)
        self.assertIn("https://example.org/tdd", got)
        lines = [ln for ln in got.splitlines() if "小さな定石" in ln]
        self.assertTrue(lines and worldmark.NOT_WEB in lines[0], got)
        self.assertNotIn(worldmark.NOT_WEB, "\n".join(ln for ln in got.splitlines() if "最小の仮の実装" in ln))
        self.assertIn("依頼は読む役を足す", got)

    def test_readers_are_stage_rows_and_section(self):
        """住処の読み口は stage_rows（控えが指す行。無ければ None）と section(rows)（行の並びから頭の節）と報告の report_lines"""
        for name in ("board_rows", "board_section", "plan_section"):
            self.assertFalse(hasattr(worldmark, name), name)
        self.assertTrue(callable(worldmark.stage_rows))
        got = worldmark.section([row(), row(finding=2, class_id="w2")])
        self.assertIn(worldmark.HEAD, got)
        self.assertIn("w1", got)
        self.assertIn("w2", got)

    def test_section_empty_when_no_rows(self):
        self.assertEqual(list(inspect.signature(worldmark.section).parameters), ["rows"], "行の並びを取る（行のファイルの名は取らない）")
        self.assertEqual(worldmark.section([]), "")

    def test_read_state(self):
        self.assertIsNone(worldmark.read(self.dir))
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "ok", "reason": "", "world_file": "x"}), encoding="utf-8")
        self.assertEqual(worldmark.read(self.dir)["world_file"], "x")
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "odd"}), encoding="utf-8")
        self.assertIsNone(worldmark.read(self.dir))

    def test_write_then_read_and_stage_rows(self):
        """線の境が書く控え（write）を read が読み、stage_rows はその行を返す（控えが無い・落ちた・行が読めない周は None）"""
        self.assertIsNone(worldmark.stage_rows(self.dir))
        p = self.put([row()])
        worldmark.write(self.dir, status="ok", reason="", world_file=str(p), classes=1, dropped=3)
        got = worldmark.read(self.dir)
        self.assertEqual((got["status"], got["world_file"], got["classes"], got["dropped"]), ("ok", str(p), 1, 3))
        self.assertNotIn("cached", got)
        self.assertNotIn("skipped", got)
        self.assertEqual([r["class_id"] for r in worldmark.stage_rows(self.dir)], ["w1"])
        worldmark.write(self.dir, status="failed", reason="段が落ちた", world_file="", classes=0, dropped=0)
        self.assertIsNone(worldmark.stage_rows(self.dir))

    def test_report_lines(self):
        p = self.put([row(), row(finding=2, class_id="w2", basis="knowledge", sources=[])])
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps(
            {"status": "ok", "reason": "", "world_file": str(p), "classes": 2, "dropped": 4}),
            encoding="utf-8")
        got = "\n".join(worldmark.report_lines(self.dir))
        self.assertIn("w1", got)
        self.assertIn(worldmark.NOT_WEB, got)
        for n in ("類 2", "落とした抜き書き 4"):
            self.assertIn(n, got)
        self.assertEqual(worldmark.report_lines(self.dir / "none"), [])

    def test_report_lines_failed_state(self):
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "failed", "reason": "言い直す役が 3 回拒まれた",
                                                                 "world_file": ""}), encoding="utf-8")
        got = "\n".join(worldmark.report_lines(self.dir))
        self.assertIn("言い直す役が 3 回拒まれた", got)


class Notes(unittest.TestCase):
    """構造の目への単位の注記の道（unit_note・where_paths）は無い。世界の解は判定の単位の処方と先例を通って届く"""

    def test_no_unit_note_or_where_paths(self):
        for name in ("unit_note", "_overlap", "where_paths"):
            self.assertFalse(hasattr(worldmark, name), name)


class Answers(unittest.TestCase):
    def test_rows_are_not_bound_to_items_by_path(self):
        """行を項目に場所で結ぶ required は無い: どの項目も行に結ばれず、答えの無い行は欠けに残る"""
        self.assertFalse(hasattr(worldmark, "required"))
        rows = [row(), row(finding=2, class_id="w2", where="docs/guide.md"), row(finding=3, class_id="w3", applies="")]
        table = worldmark.need(rows)
        self.assertEqual(table.of({"allowed_paths": ["src/"]}), [])
        self.assertEqual(table.missing([{"allowed_paths": ["src/"]}]), ["w1", "w2"])

    def test_world_source_must_name_a_staged_row(self):
        """判定の返答の先例（precedents）の出どころ world:<類の id> は盤面の根の控えが指す行に在る id だけを通す。頭に字を添えても拾い、
        world: の無い出どころは見ない。出どころを返答から抜くのも worldmark（呼び手は返答をそのまま渡す）"""
        def refs(*sources):
            return {"precedents": [{"source": s, "why": "先例"} for s in sources]}
        self.assertTrue(hasattr(worldmark, "ref_problems"), "worldmark.ref_problems が無い")
        with tempfile.TemporaryDirectory() as tmp:
            board = pathlib.Path(tmp)
            world = board / worldmark.WORLD_FILE
            world.write_text(json.dumps(row(), ensure_ascii=False) + "\n", encoding="utf-8")
            (board / worldmark.STATE_FILE).write_text(json.dumps({"status": "ok", "reason": "", "world_file": str(world)}), encoding="utf-8")
            self.assertEqual(worldmark.ref_problems(refs("world:w1"), board), [])
            for src in ("world:w-none", "世界の解 world:w-none"):
                got = worldmark.ref_problems(refs(src), board)
                self.assertEqual(len(got), 1, got)
                self.assertIn("w-none", got[0])
            self.assertEqual(worldmark.ref_problems(refs("https://example.org/tdd", "docs/guide.md の 3 節"), board), [])
            self.assertEqual(len(worldmark.ref_problems(refs("world:w1", "world:w-none"), board)), 1)
        with tempfile.TemporaryDirectory() as bare:
            got = worldmark.ref_problems(refs("world:w1"), pathlib.Path(bare))
            self.assertEqual(len(got), 1, got)
            self.assertIn("w1", got[0])
            self.assertEqual(worldmark.ref_problems(refs("https://example.org/tdd"), pathlib.Path(bare)), [])

    def test_row_without_applies_needs_no_answer(self):
        self.assertEqual(worldmark.unanswered([row(applies="")], []), [])
        self.assertEqual(worldmark.need([row(applies="")]).missing([]), [])

    def test_unanswered_applies_row(self):
        rows = [row(), row(finding=2, class_id="w2", where="docs/guide.md"), row(finding=3, class_id="w3", applies="")]
        items = [{"structure": [{"world": "w1", "follows": True}]}]
        self.assertEqual(worldmark.unanswered(rows, items), ["w2"])
        self.assertEqual(worldmark.unanswered(rows, items + [{"structure": [{"world": "w2", "deviation": "訳"}]}]), [])

    def test_world_ok_follow(self):
        ok, why = worldmark.world_ok({"world": "w1", "follows": True}, row(), set(), lambda text: "")
        self.assertTrue(ok, why)

    def test_world_ok_without_answer_is_false(self):
        self.assertFalse(worldmark.world_ok(None, row(), set(), lambda text: "")[0])

    def test_world_ok_row_needing_no_answer(self):
        self.assertTrue(worldmark.world_ok(None, row(applies=""), set(), lambda text: "")[0])

    def test_world_ok_deviation_cited_to_request_is_false(self):
        ans = {"world": "w1", "deviation": "依頼が読む役を足せと言う", "decided_by": "/tmp/req.json:3"}
        ok, why = worldmark.world_ok(ans, row(), {"/tmp/req.json"}, lambda text: "")
        self.assertFalse(ok)
        self.assertIn("依頼", why)
        quoted = {"world": "w1", "deviation": "依頼の「読むだけの役を足す」に従う", "decided_by": "依頼の「読むだけの役を足す」"}
        self.assertFalse(worldmark.world_ok(quoted, row(), set(), lambda text: "")[0])

    def test_world_ok_deviation_cited_elsewhere_is_true(self):
        ans = {"world": "w1", "deviation": "人の前の決定が仮の実装を禁じる", "decided_by": "docs/decisions.md:40"}
        ok, why = worldmark.world_ok(ans, row(), {"/tmp/req.json"}, lambda text: "")
        self.assertTrue(ok, why)

    def test_world_ok_deviation_with_missing_source_is_false(self):
        ans = {"world": "w1", "deviation": "訳", "decided_by": "docs/none.md:40"}
        ok, why = worldmark.world_ok(ans, row(), set(), lambda text: "名指し docs/none.md:40 のファイルが無い")
        self.assertFalse(ok)
        self.assertIn("ファイルが無い", why)

    def test_world_ok_knowledge_deviation_goes_to_human(self):
        """web で確かめていない行からの外れは、依頼の外の出どころが在っても人に回る（計画の 5.5 節: 知識だけの定石に従うのは
        自明側、外れは人へ）。従う答えは web の行と同じに揃う"""
        ans = {"world": "w1", "deviation": "人の前の決定が仮の実装を禁じる", "decided_by": "docs/decisions.md:40"}
        ok, why = worldmark.world_ok(ans, row(basis="knowledge", sources=[]), set(), lambda text: "")
        self.assertFalse(ok)
        self.assertIn(worldmark.NOT_WEB, why)
        self.assertTrue(worldmark.world_ok({"world": "w1", "follows": True}, row(basis="knowledge", sources=[]), set(),
                                           lambda text: "")[0])

    def test_gate_line(self):
        follow = worldmark.gate_line(row(), {"world": "w1", "follows": True})
        self.assertIn("w1", follow)
        self.assertIn("従う", follow)
        dev = worldmark.gate_line(row(basis="knowledge", sources=[]), {"world": "w1", "deviation": "訳の文"})
        self.assertIn("訳の文", dev)
        self.assertIn(worldmark.NOT_WEB, dev)


class Contract(unittest.TestCase):
    def test_schema_fields_match_home(self):
        doc = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(set(doc["properties"]), set(worldmark.FIELDS))
        self.assertEqual(set(doc["required"]), set(worldmark.FIELDS))
        self.assertEqual(tuple(doc["properties"]["basis"]["enum"]), worldmark.BASES)
        self.assertEqual(tuple(doc["properties"]["versus"]["properties"]["verdict"]["enum"]), worldmark.VERDICTS)

    def test_constants(self):
        self.assertEqual(worldmark.WORLD_FILE, "world.jsonl")
        self.assertEqual(worldmark.STATE_FILE, "world-state.json")
        self.assertEqual(worldmark.VERDICTS, ("same", "differs", "none"))
        self.assertEqual(worldmark.BASES, ("web", "knowledge"))
        self.assertEqual(worldmark.NOT_WEB, "web で確かめていない")


if __name__ == "__main__":
    unittest.main()
