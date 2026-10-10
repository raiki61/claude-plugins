"""世界の解の行の住処（.shared/core/worldmark.py。計画 docs/plans/2026-10-09-world-solution.md の W4・5.3 節・5.7 節）。

行のファイル（JSON Lines）の読み・指示書の頭の節・単位の要点・答えの要る行・関所の軸・関所の行・報告の行と、約束
（blk-world/world-row.schema.json）の欄と語が住処の定数と揃うことを見る。一時の置き場のファイルだけ（網・git・子のプロセスなし）。
"""
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


def inside(path, item):
    """修正案の項目の範囲の当て方の代わり（試験の中だけ。字のまま同じパスか、/ で終わる前置き）"""
    return any(path == g or (g.endswith("/") and path.startswith(g)) for g in item.get("allowed_paths") or [])


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
        got = worldmark.section(str(p))
        self.assertIn(worldmark.HEAD, got)
        self.assertIn("w1", got)
        self.assertIn("https://example.org/tdd", got)
        lines = [ln for ln in got.splitlines() if "小さな定石" in ln]
        self.assertTrue(lines and worldmark.NOT_WEB in lines[0], got)
        self.assertNotIn(worldmark.NOT_WEB, "\n".join(ln for ln in got.splitlines() if "最小の仮の実装" in ln))
        self.assertIn("依頼は読む役を足す", got)

    def test_section_empty_when_no_rows(self):
        self.assertEqual(worldmark.section(""), "")
        self.assertEqual(worldmark.section(str(self.put([]))), "")

    def test_read_state(self):
        self.assertIsNone(worldmark.read(self.dir))
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "ok", "reason": "", "world_file": "x"}), encoding="utf-8")
        self.assertEqual(worldmark.read(self.dir)["world_file"], "x")
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "odd"}), encoding="utf-8")
        self.assertIsNone(worldmark.read(self.dir))

    def test_write_then_read_and_board_rows(self):
        """線の境が書く控え（write）を read が読み、board_rows はその行を返す（控えが無い・落ちた・行が読めない周は []）"""
        self.assertEqual(worldmark.board_rows(self.dir), [])
        p = self.put([row()])
        worldmark.write(self.dir, status="ok", reason="", world_file=str(p), classes=1, cached=0, skipped=2, dropped=3)
        got = worldmark.read(self.dir)
        self.assertEqual((got["status"], got["world_file"], got["skipped"], got["dropped"]), ("ok", str(p), 2, 3))
        self.assertEqual([r["class_id"] for r in worldmark.board_rows(self.dir)], ["w1"])
        worldmark.write(self.dir, status="failed", reason="段が落ちた", world_file="", classes=0, cached=0, skipped=0, dropped=0)
        self.assertEqual(worldmark.board_rows(self.dir), [])

    def test_report_lines(self):
        p = self.put([row(), row(finding=2, class_id="w2", basis="knowledge", sources=[], cached=False)])
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps(
            {"status": "ok", "reason": "", "world_file": str(p), "classes": 2, "cached": 1, "skipped": 3, "dropped": 4}),
            encoding="utf-8")
        got = "\n".join(worldmark.report_lines(self.dir))
        self.assertIn("w1", got)
        self.assertIn(worldmark.NOT_WEB, got)
        for n in ("控えから使った類 1", "飛ばした行 3", "落とした抜き書き 4"):
            self.assertIn(n, got)
        self.assertEqual(worldmark.report_lines(self.dir / "none"), [])

    def test_report_lines_name_cached_classes(self):
        """控えから使った類は行ごとに名指す（数の行だけでは、どの定石が前の run の物かが分からない）"""
        p = self.put([row(), row(finding=2, class_id="w2", cached=True, practice="前の定石")])
        worldmark.write(self.dir, status="ok", reason="", world_file=str(p), classes=2, cached=1, skipped=0, dropped=0)
        got = worldmark.report_lines(self.dir)
        cached = [ln for ln in got if "前の定石" in ln]
        fresh = [ln for ln in got if "最小の仮の実装" in ln]
        self.assertTrue(cached and "控えから使った" in cached[0], got)
        self.assertTrue(fresh and "控えから使った" not in fresh[0], got)

    def test_report_lines_failed_state(self):
        (self.dir / worldmark.STATE_FILE).write_text(json.dumps({"status": "failed", "reason": "言い直す役が 3 回拒まれた",
                                                                 "world_file": ""}), encoding="utf-8")
        got = "\n".join(worldmark.report_lines(self.dir))
        self.assertIn("言い直す役が 3 回拒まれた", got)


class Notes(unittest.TestCase):
    def test_unit_note_only_overlapping_rows(self):
        rows = [row(), row(finding=2, class_id="w2", where="docs/guide.md", practice="別の定石")]
        got = worldmark.unit_note(rows, ["src/red.py", "src/other.py"])
        self.assertIn("w1", got)
        self.assertNotIn("w2", got)
        self.assertEqual(worldmark.unit_note(rows, ["lib/x.py"]), "")

    def test_unit_note_names_knowledge_rows(self):
        self.assertIn(worldmark.NOT_WEB, worldmark.unit_note([row(basis="knowledge", sources=[])], ["src/red.py"]))

    def test_where_paths(self):
        self.assertEqual(worldmark.where_paths("src/red.py:12（赤の判定）と docs/a.md"), ["src/red.py", "docs/a.md"])
        self.assertEqual(worldmark.where_paths("全体"), [])


class Answers(unittest.TestCase):
    def test_required_by_path_overlap(self):
        rows = [row(), row(finding=2, class_id="w2", where="docs/guide.md"), row(finding=3, class_id="w3", applies="")]
        self.assertEqual(worldmark.required(rows, {"allowed_paths": ["src/"]}, inside), ["w1"])
        self.assertEqual(worldmark.required(rows, {"allowed_paths": ["lib/"]}, inside), [])

    def test_row_without_applies_needs_no_answer(self):
        self.assertEqual(worldmark.required([row(applies="")], {"allowed_paths": ["src/"]}, inside), [])

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
