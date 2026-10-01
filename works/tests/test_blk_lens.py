"""修正の後のレンズのブロック blk-lens（振り分け・レンズの節・集め役・境）と、その控え lens.json を読む 2 つの口（差分の審査の
支度 refix.cut の brief・機械の報告の「未確認のレンズ」）。

盤面は test_blk_refix.DeltaBoardCase の、修正を受けた盤面（今の周の修正の差分が在る）。レンズの定義は linekit.lens_plugin の
偽の置き場（PR_REVIEW_TOOLKIT_ROOT）から引く。スクリプトは子のプロセスで起こし、出口を YAML の output_format に当てる。
"""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLK = ROOT / "blk-lens"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import entry  # noqa: E402
import lens  # noqa: E402
import lenses  # noqa: E402
import linekit  # noqa: E402
import refix  # noqa: E402
import report  # noqa: E402
import test_blk_refix as RF  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

FINDING = {"where": "stats.py", "cite": "return hi", "why": "上限を超えた値を黙って hi に丸め、呼び元は丸めたことに気づけない"}


def flow() -> dict:
    return yaml.safe_load((BLK / "blk-lens.yaml").read_text(encoding="utf-8"))


def node(nid) -> dict:
    return next(n for n in flow()["nodes"] if n["id"] == nid)


class LensYamlCase(unittest.TestCase):
    def test_nodes_and_exit(self):
        """振り分け → レンズの節（when: で go を引く）→ 集め役（all_done）→ 境（all_done）。出口は境で ok を成否にする"""
        y = flow()
        self.assertEqual((y["returns"], y["outcome_field"]), ("lens-exit", "ok"))
        self.assertEqual([n["id"] for n in y["nodes"]],
                         ["lens-route", *[f"lens-{r['lens']}" for r in lenses.LENSES], "lens-collect", "lens-exit"])
        for row in lenses.LENSES:
            with self.subTest(row["lens"]):
                n = node(f"lens-{row['lens']}")
                self.assertEqual(n["when"], f"$lens-route.output.{lenses.key(row)}_go == true")
                self.assertIn(f"$lens-route.output.prompt_{lenses.key(row)}",
                              (BLK / "commands" / f"{n['command']}.md").read_text(encoding="utf-8"))
                self.assertLessEqual({f"{lenses.key(row)}_go", f"prompt_{lenses.key(row)}"},
                                     set(node("lens-route")["output_format"]["required"]))
        self.assertEqual(node("lens-collect")["trigger_rule"], "all_done")
        self.assertEqual(node("lens-exit")["trigger_rule"], "all_done")
        self.assertEqual(node("lens-exit")["with"], {"collected": {"from": "$lens-collect.output", "if_skipped": None}})

    def test_lens_node_is_the_lens_itself(self):
        """レンズの節は定義を貼った節そのもの: 道具は Read・Grep・Glob だけ（子を起こす Agent・Skill を持たない。持ち主 2026-10-01）"""
        for row in lenses.LENSES:
            with self.subTest(row["lens"]):
                n = node(f"lens-{row['lens']}")
                self.assertEqual(set(n["allowed_tools"]), {"Read", "Grep", "Glob"})
                self.assertEqual(n["settingSources"], ["user"])

    def test_collect_reads_every_lens(self):
        """集め役は全部のレンズの節の出口を、飛ばされた・落ちた節は null で受ける（with: の鍵は lenses.input_name と同じ）"""
        w = node("lens-collect")["with"]
        self.assertEqual({f"INPUTS_{k.upper()}" for k in w}, {lenses.input_name(r) for r in lenses.LENSES})
        for row in lenses.LENSES:
            self.assertEqual(w[lenses.key(row)], {"from": f"$lens-{row['lens']}.output", "if_skipped": None})
        self.assertEqual(set(node("lens-collect")["depends_on"]),
                         {"lens-route", *[f"lens-{r['lens']}" for r in lenses.LENSES]})


    def test_review_prompt_reads_lens_only_in_round_one(self):
        """1 回目の審査役の指示書は brief の lens を検算して穴にせよと言い、2 回目（手直しの差分）の指示書は lens を読ませない"""
        one = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        self.assertIn("`lens`", one)
        self.assertIn("無検算で写すな", one)
        self.assertNotIn("`lens`", (ROOT / "blk-refix" / "commands" / "review2.md").read_text(encoding="utf-8"))


class LensBoardCase(RF.DeltaBoardCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, linekit.lens_plugin(self.tmp))
        env.start()
        self.addCleanup(env.stop)

    def board_obj(self):
        return entry.open_board(self.board, allow_halted=True)

    def script(self, name, repo, **inputs):
        p = self.run_script("blk-lens", name, repo, **inputs)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(validate_schema(out, node(f"lens-{name}")["output_format"]), [])
        return out

    # -- 振り分け
    def test_route_pastes_definition_and_writes_rows(self):
        """定義が引ければ go。指示書は定義の本文と修正の差分のパス・変わったファイルを持つ。lens.json に pending の行"""
        repo = self.fixed()
        out = self.script("route", repo)
        d = refix.fix_delta(self.board_obj())
        self.assertIs(out["silent_failure_hunter_go"], True)
        self.assertIn(linekit.LENS_DEF_BODY, out["prompt_silent_failure_hunter"])
        self.assertIn(d["file"], out["prompt_silent_failure_hunter"])
        self.assertIn('["stats.py"]', out["prompt_silent_failure_hunter"])
        self.assertNotIn("model: inherit", out["prompt_silent_failure_hunter"], "前付けは剥がす")
        rows = lens.read(self.board_obj())
        self.assertEqual([(r["lens"], r["state"], r["go"]) for r in rows], [("silent-failure-hunter", "pending", True)])

    def test_route_without_definition_does_not_route_with_reason(self):
        """定義が役の設定に無いレンズは起こさない（go 偽・指示書は空）。lens.json には not_routed と理由"""
        repo = self.fixed()
        with mock.patch.object(lenses.rolekit, "agent_def", return_value=None):
            out = lenses.route(self.board)
        self.assertEqual((out["silent_failure_hunter_go"], out["prompt_silent_failure_hunter"]), (False, ""))
        self.assertIn("入っていない", out["why"])
        row = lens.read(self.board_obj())[0]
        self.assertEqual((row["state"], row["go"]), ("not_routed", False))
        self.assertIn("pr-review-toolkit:silent-failure-hunter", row["reason"])

    def test_route_rule_false_is_not_routed(self):
        """振り分けの規則が go を偽にしたレンズは、規則の理由つきで not_routed（報告の未確認のレンズに出る）"""
        self.fixed()
        rows = tuple({**r, "route": lambda files: (False, "変わったファイルに例外の扱いが無い")} for r in lenses.LENSES)
        with mock.patch.object(lenses, "LENSES", rows):
            lenses.route(self.board)
        b = self.board_obj()
        self.assertEqual(lens.read(b)[0]["reason"], "変わったファイルに例外の扱いが無い")
        self.assertIn("silent-failure-hunter: 起こさなかった（変わったファイルに例外の扱いが無い）", lens.report_lines(b))

    def test_route_needs_fix_delta(self):
        """今の周の修正の差分が無い盤面では振り分けは 2（配線の誤り）。控えは残さない"""
        repo, _ = self.judged()
        p = self.run_script("blk-lens", "route", repo)
        self.assertEqual((p.returncode, p.stdout), (2, ""))
        self.assertIsNone(lens.read(self.board_obj()))

    # -- 集め役
    def test_collect_marks_findings_with_lens_name(self):
        """走ったレンズの指摘は出どころ（レンズの名）つきで ran"""
        repo = self.fixed()
        self.script("route", repo)
        out = self.script("collect", repo, silent_failure_hunter=json.dumps({"findings": [FINDING]}, ensure_ascii=False))
        self.assertEqual((out["ok"], out["ran"], out["failed"], out["not_routed"]), (True, 1, 0, 0))
        row = lens.read(self.board_obj())[0]
        self.assertEqual((row["state"], row["findings"]), ("ran", [{"lens": "silent-failure-hunter", **FINDING}]))

    def test_collect_records_failed_lens_and_succeeds(self):
        """落ちたレンズ（出口 null）・形の違う出口は failed と理由を記録し、集め役そのものは ok"""
        repo = self.fixed()
        for given, why in (("null", "出口が無い"), ('{"findings": "x"}', "形が違う")):
            with self.subTest(given):
                self.script("route", repo)
                out = self.script("collect", repo, silent_failure_hunter=given)
                self.assertEqual((out["ok"], out["failed"]), (True, 1))
                row = lens.read(self.board_obj())[0]
                self.assertEqual(row["state"], "failed")
                self.assertIn(why, row["reason"])

    def test_collect_without_routes_is_not_ok(self):
        """振り分けが控えを書いていない（落ちた）なら集め役は ok: false と理由"""
        repo = self.fixed()
        out = self.script("collect", repo, silent_failure_hunter="null")
        self.assertIs(out["ok"], False)
        self.assertIn("控えが無い", out["reason"])

    # -- 境
    def exit_stops(self, collected, why):
        """集め役の出口 collected で境を回すと、盤面を by works:lens で止めて ok: false。後ろの手直しの境の節は stop"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge
        repo = self.fixed()
        out = self.script("exit", repo, collected=collected)
        self.assertIs(out["ok"], False)
        b = self.board_obj()
        self.assertEqual(b.state["stop"]["by"], lens.STOP_BY)
        self.assertIn(f"レンズの集め役が終わらなかった: {why}", b.state["stop"]["reason"])
        got = line_edge.edge(self.board, "refix", repo, run_id="run-7", adapter_mode="optional", final_gate="")
        self.assertEqual((got["stop"], got["go"]), (True, False))

    def test_exit_stops_board_when_collector_failed(self):
        self.exit_stops("null", "集め役の出口が無い")

    def test_exit_stops_board_when_collector_not_ok(self):
        self.exit_stops(json.dumps({"ok": False, "reason": "控えが無い"}, ensure_ascii=False), "控えが無い")

    def test_exit_passes_ok_collector(self):
        repo = self.fixed()
        self.script("route", repo)
        got = self.script("collect", repo, silent_failure_hunter=json.dumps(linekit.LENS_REPLY, ensure_ascii=False))
        out = self.script("exit", repo, collected=json.dumps(got, ensure_ascii=False))
        self.assertEqual((out["ok"], out["lens_file"]), (True, got["lens_file"]))
        self.assertFalse(self.board_obj().state.get("stop"))

    # -- 差分の審査の brief
    def test_cut_brief_carries_lens_rows(self):
        """1 回目の審査役の brief の lens に、指摘を出どころつきで、落ちた・起こさなかったレンズを理由つきで載せる"""
        repo = self.fixed()
        lenses.route(self.board)
        lenses.collect(self.board, {"INPUTS_SILENT_FAILURE_HUNTER": json.dumps({"findings": [FINDING]}, ensure_ascii=False)})
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["lens"], [{"lens": "silent-failure-hunter", "state": "ran", "reason": "",
                                          "findings": [{"lens": "silent-failure-hunter", **FINDING}]}])
        self.assertNotIn("lens_error", brief)

    def test_cut_brief_without_lens_run_and_broken_file(self):
        """レンズを走らせていない周は lens が空。控えが壊れていれば空と lens_error（黙って空にしない）"""
        repo = self.fixed()
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["lens"], [])
        self.assertNotIn("lens_error", brief)
        self.board_obj().work(lens.LENS_FILE).write_text("{", encoding="utf-8")
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["lens"], [])
        self.assertIn("読めない", brief["lens_error"])

    def test_review2_brief_has_no_lens(self):
        """手直しの差分にはレンズが当たらないので、2 回目の審査役の brief は lens を持たない"""
        repo, _ = self.refixed()
        self.assertTrue(refix.route(self.board)["review2"])
        brief = json.loads(pathlib.Path(refix.cut(self.board, 2, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertNotIn("lens", brief)
        self.assertNotIn("lens_error", brief)

    # -- 報告
    def test_report_lists_unseen_lenses(self):
        """報告の「未確認のレンズ」に落ちたレンズと理由、手直しの差分の 1 行。レンズを走らせない run は節を出さない"""
        repo = self.fixed()
        rep = report.build(self.board.resolve(), judged=None, tests=None, start=None)
        self.assertNotIn("## 未確認のレンズ", pathlib.Path(rep["report_file"]).read_text(encoding="utf-8"))
        lenses.route(self.board)
        lenses.collect(self.board, {"INPUTS_SILENT_FAILURE_HUNTER": "null"})
        text = pathlib.Path(report.build(self.board.resolve(), judged=None, tests=None, start=None)["report_file"]).read_text(
            encoding="utf-8")
        section = text.split("## 未確認のレンズ", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- silent-failure-hunter: 落ちた（レンズの節の出口が無い", section)
        self.assertIn(lens.REFIX_NOTE, section)

    def test_report_lines_name_broken_file_and_all_ran(self):
        repo = self.fixed()
        b = self.board_obj()
        b.work(lens.LENS_FILE).write_text("[]", encoding="utf-8")
        self.assertIn("レンズの控え", lens.report_lines(b)[0])
        lenses.route(self.board)
        lenses.collect(self.board, {"INPUTS_SILENT_FAILURE_HUNTER": json.dumps(linekit.LENS_REPLY, ensure_ascii=False)})
        self.assertEqual(lens.report_lines(self.board_obj()), ["なし（振り分けたレンズは全部走った）", lens.REFIX_NOTE])


if __name__ == "__main__":
    unittest.main()
