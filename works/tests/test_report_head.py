"""機械の報告の冒頭 3（report.head_stop）の interrupted の行。盤面を開かず、偽の盤面（state と dir だけ）で関数を直に呼ぶ（FAST。
git・子のプロセスなし）。run 31 は目の支度の節が exit 2 で落ちた——冒頭 3 はどの節がなぜ落ちたかを言い、原因を取り消し・abandon・
上限に決め打ちしない。run の外の report.sh の道（Archon の run の状態の語だけを持つ）の行も保つ"""
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import report  # noqa: E402

GUESSED_CAUSES = "取り消し・abandon・役の出し直しの上限のどれか"


def fake_board(tmp) -> types.SimpleNamespace:
    """止めていない盤面（stop・halted なし。trace.jsonl なし）"""
    return types.SimpleNamespace(state={}, dir=pathlib.Path(tmp))


class HeadStopInterruptedCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.b = fake_board(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_failed_node_and_error_in_head(self):
        """落ちた節を渡すと、冒頭 3 に節の名前と誤りの文（1 行目）が出て、原因の決め打ちは出ない"""
        failed = [{"node": "eyeing__r1-minimality-prep",
                   "error": "BoardGap: 盤面の ready に r1.minimality が無い\nTraceback (most recent call last):"}]
        try:
            lines = report.head_stop(self.b, interrupted="failed", failed=failed)
        except TypeError as e:
            self.fail(f"head_stop が落ちた節を受けない: {e}")
        text = "\n".join(lines)
        self.assertIn("eyeing__r1-minimality-prep", text)
        self.assertIn("BoardGap: 盤面の ready に r1.minimality が無い", text)
        self.assertNotIn("Traceback", text, "誤りの文は 1 行目だけ")
        self.assertNotIn(GUESSED_CAUSES, text)

    def test_archon_status_kept_for_report_sh(self):
        """run の外の report.sh の道（落ちた節を渡さない）は、今までどおり途中で終わった行に Archon の run の状態を出す"""
        text = "\n".join(report.head_stop(self.b, interrupted="cancelled"))
        self.assertIn(report.INTERRUPTED_HEAD, text)
        self.assertIn("Archon の run の状態は cancelled", text)


class ResumedRunCase(unittest.TestCase):
    """resume の後の run（run 43・54 の形）: 1 回目で上流の節と result が落ち、resume で上流の節が済んで report が走る。
    report より下流の result は今の試みでまだ走れないので、その前の試みの失敗で結末を interrupted にしない。
    報告の節（darkfactory/scripts/report.py）の main を、出来事と report.build を差し替えて直に呼ぶ（盤面・git・子のプロセスなし）"""

    def test_prior_attempt_failures_do_not_interrupt(self):
        import importlib.util
        import os
        import reads
        fixing = "fixing__fix-loop.fix"

        def ev(kind, step=None, error=None):
            return {"event_type": kind, "step_name": step, "data": {"error": error} if error else {}}
        events = [ev("workflow_started"),
                  ev("node_started", fixing), ev("node_failed", fixing, "一度目の誤り"),
                  ev("node_started", "report"), ev("node_completed", "report"),
                  ev("node_started", "result"), ev("node_failed", "result", "Script node 'result' failed [exit 1]"),
                  ev("workflow_failed"),
                  ev("workflow_started"),
                  ev("node_started", fixing), ev("node_completed", fixing),
                  ev("node_started", "report")]
        spec = importlib.util.spec_from_file_location("_report_script_resumed",
                                                      ROOT / "darkfactory" / "scripts" / "report.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as art:
            (pathlib.Path(art) / "board").mkdir()
            (pathlib.Path(art) / "board" / "state.json").write_text("{}", encoding="utf-8")
            env = {n: "null" for n in mod.INPUTS}
            env.update({"INPUTS_EYES": json.dumps({"go": False}), "ARTIFACTS_DIR": art, "WORKFLOW_ID": "run-43"})
            got = {}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(reads, "events_for", return_value=events), \
                    mock.patch.object(report, "build", side_effect=lambda *a, **kw: got.update(kw) or {"ok": True}), \
                    mock.patch("script_io._emit"):
                self.assertEqual(mod.main(), 0)
        self.assertIsNone(got["interrupted"], got.get("failed"))
        self.assertNotIn("result", [f["node"] for f in got["failed"] or []])


EVENTS_DIR = pathlib.Path(__file__).resolve().parent / "events"


def recorded_events(name="verbose-p13.json") -> list:
    """録った Archon v0.11.1 の出力（workflow get --verbose --events --json）の events。節の費用は data.spend.costUsd に在り、
    AI 費用 0 の run なので全部 {source: unavailable, reason: not_applicable}"""
    return json.loads((EVENTS_DIR / name).read_text(encoding="utf-8"))["events"]


GREEN_WITH_CMD = {"ok": True, "green": True, "log": "/x/p4.ci.log", "by": "engine",
                  "suites": [{"name": "pytest", "exit": 0}, {"name": "root pytest", "exit": 0}, {"name": "test_cmd", "exit": 0}]}
GREEN_NO_CMD = {"ok": True, "green": True, "log": "/x/p4.ci.log", "by": "engine",
                "suites": [{"name": "pytest", "exit": 0}, {"name": "root pytest", "exit": 0}]}


class FinalTestSuitesCase(unittest.TestCase):
    """最後のテストの緑の行（報告の冒頭 1 の report.head_decisions と最後の関所の文 line_edge._final_text）は、ログのパスだけでなく
    走らせた一式の名（run_final の suites）と走らせなかった物（渡されていない test_cmd）を出す——何を根拠にした緑かを人に見せる"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.b = types.SimpleNamespace(state={}, dir=pathlib.Path(self._tmp.name), record={"process": {}}, round=1,
                                       output_of_round=lambda nid, n: {})

    def head_text(self, tests):
        from unittest import mock
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report, "_conflict_line", return_value=""), \
                mock.patch.object(report, "_rejudge_changes", return_value=[]), \
                mock.patch.object(report, "_premise_hypotheses", return_value=[]), \
                mock.patch.object(report, "_pr_lines", return_value=[]):
            lines = report.head_decisions(self.b, {}, tests=tests)
        return next(x for x in lines if x.startswith("最後のテスト"))

    def gate_text(self, tests):
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge
        text = line_edge._final_text(self.b, "緑", tests, "", ([], []), self._tmp.name, "run-1")
        return text.split("- run の作業ツリー")[0]

    def test_report_green_line_names_suites(self):
        line = self.head_text(GREEN_WITH_CMD)
        for name in ("pytest", "root pytest", "test_cmd"):
            self.assertIn(name, line)

    def test_report_green_line_names_unrun_test_cmd(self):
        line = self.head_text(GREEN_NO_CMD)
        self.assertIn("pytest", line)
        self.assertIn("走らせなかった", line)
        self.assertIn("test_cmd", line)

    def test_final_gate_names_suites(self):
        text = self.gate_text(GREEN_WITH_CMD)
        for name in ("pytest", "root pytest", "test_cmd"):
            self.assertIn(name, text)

    def test_final_gate_names_unrun_test_cmd(self):
        text = self.gate_text(GREEN_NO_CMD)
        self.assertIn("走らせなかった", text)
        self.assertIn("test_cmd", text)

    def test_final_gate_role_needed_after_blk_ci_says_it_ran(self):
        """任せ先の CI の役が p4.ci を渡し終えた後の関所は、頭の『緑』と同じ盤面を読み『blk-ci が走らせる』と言わない"""
        self.b.node_state = lambda nid: "done"
        self.b.record["materials"] = {"local_checks": {"status": "clean"}}
        tests = {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
        text = self.gate_text(tests)
        import line_edge  # （gate_text が sys.path に足した後）
        self.assertEqual(line_edge._tests_head(self.b, tests), "緑")
        self.assertNotIn("blk-ci が走らせる", text)
        self.assertIn("status clean", text)

    def test_report_head_role_needed_after_blk_ci_matches_final_gate(self):
        """報告の冒頭も関所と同じ盤面を読む: blk-ci が clean で渡し終えた後は『緑』で、関所と同じ一式の行を出す"""
        self.b.node_state = lambda nid: "done"
        self.b.record["materials"] = {"local_checks": {"status": "clean"}}
        tests = {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
        line = self.head_text(tests)
        self.assertTrue(line.startswith("最後のテスト: 緑"), line)
        suites = self.gate_text(tests).split("- テストの一式: ")[1].split("\n")[0]
        self.assertIn(suites, line)

    def test_role_needed_not_run_is_not_said_ran(self):
        """blk-ci の素材が not_run・not_applicable の時は、関所も冒頭も『走らせた』と書かず、走らせなかった側に status を出す"""
        self.b.node_state = lambda nid: "done"
        tests = {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
        for status in ("not_run", "not_applicable"):
            self.b.record["materials"] = {"local_checks": {"status": status}}
            for text in (self.gate_text(tests), self.head_text(tests)):
                self.assertIn("走らせた: 無い", text)
                self.assertIn(f"走らせなかった: 宣言の段・test_cmd（任せ先の CI の役 blk-ci が走らせなかった: 素材の status {status}）",
                              text)
            self.assertTrue(self.head_text(tests).startswith("最後のテストが赤"))

    def test_no_suites_line_when_final_tests_did_not_run(self):
        """走れなかった（節が落ちた出口）・走らなかった（出口が無い）時は『走らせなかった: 無い』を出さない"""
        failed = {"ok": False, "reason": "節が落ちた", "log": ""}
        self.assertNotIn("走らせなかった", self.head_text(failed))
        for tests in (failed, None):
            self.assertNotIn("テストの一式", self.gate_text(tests))


def node_done(step, cost):
    """節の費用が数の出来事。**推測**: 数が入る時の data.spend.costUsd の形は録った実物に 0 件で、有限の数と置いた"""
    return {"event_type": "node_completed", "step_name": step, "data": {"spend": {"costUsd": cost}}}


class HeadCostCase(unittest.TestCase):
    """費用の行（report.head_cost）。節の費用の欄は Archon v0.11.1 の実物の data.spend.costUsd。報告されなかった費用
    （source unavailable）は 0 と混ぜず、出どころを添えて『取れない』と出す（Archon #3295・#3420）。報告は run の中で走るので、
    run の和は取らず、節の和を『途中』として出す。包みの起動の記録は空で渡す（盤面を開かない）"""

    def test_recorded_unavailable_names_field_and_reason(self):
        """録った実物（costUsd が全部 unavailable）→ 1 行の『取れない』に、見た欄・source・reason・版"""
        lines = report.head_cost(None, "run-1", events=recorded_events(), launches=[])
        self.assertEqual(len(lines), 1, lines)
        for word in ("取れない", "data.spend.costUsd", "unavailable", "not_applicable", "v0.11.1"):
            self.assertIn(word, lines[0])

    def test_guessed_keys_are_not_read(self):
        """版の外の欄（平らな cost_usd・data.cost_usd・data.costUsd・total_cost_usd）だけの出来事は数えず、『取れない』に
        見た欄の名と版を添える"""
        events = [{"event_type": "node_completed", "step_name": "a", "cost_usd": 0.5},
                  {"event_type": "node_completed", "step_name": "b", "data": {"cost_usd": 0.6}},
                  {"event_type": "node_completed", "step_name": "c", "data": {"costUsd": 0.5}},
                  {"event_type": "node_completed", "step_name": "d", "data": {"total_cost_usd": 0.7}}]
        lines = report.head_cost(None, "run-1", events=events, launches=[])
        self.assertEqual(len(lines), 1, lines)
        for word in ("取れない", "data.spend.costUsd", "v0.11.1"):
            self.assertIn(word, lines[0])

    def test_spend_cost_is_read(self):
        """data.spend.costUsd が数なら節の費用に出る"""
        lines = report.head_cost(None, "run-1", events=[node_done("a", 0.01), node_done("b", 0.02)], launches=[])
        text = "\n".join(lines)
        self.assertIn("費用 a: 0.01 USD", text)
        self.assertIn("費用 b: 0.02 USD", text)

    def test_workflow_completed_is_not_run_total(self):
        """workflow_completed の cost_usd（v0.11.1 の実物に無い）は run の和に読まない。合計は節の和の途中"""
        events = [node_done("a", 0.01), node_done("b", 0.02),
                  {"event_type": "workflow_completed", "data": {"cost_usd": 0.025}}]
        lines = report.head_cost(None, "run-1", events=events, launches=[])
        total = [x for x in lines if x.startswith("費用の合計")]
        self.assertEqual(len(total), 1, lines)
        self.assertIn("0.03 USD", total[0])
        self.assertIn("途中", total[0])
        self.assertNotIn("0.025", "\n".join(lines))

    def test_running_total_is_partial(self):
        """run の和が無い（報告は run の中で走る）間の合計は、途中の節の和だと言う"""
        lines = report.head_cost(None, "run-1", events=[node_done("a", 0.01)], launches=[])
        total = [x for x in lines if x.startswith("費用の合計")]
        self.assertEqual(len(total), 1, lines)
        self.assertIn("途中", total[0])

    def test_use_show_calls_only_existing_report_names(self):
        """use.sh show（dev/lib.sh）は節ごとの費用を報告の費用の行（report.head_cost）から import して出す。呼ぶ名前が report に
        無いと、show は例外を飲んで『取れない』とだけ出し、節ごとの費用が黙って消える"""
        import re
        called = set(re.findall(r"\breport\.(\w+)\(", (ROOT / "dev" / "lib.sh").read_text(encoding="utf-8")))
        self.assertIn("head_cost", called)
        self.assertEqual(sorted(n for n in called if not hasattr(report, n)), [])

    def test_continued_is_not_subtracted(self):
        """継いだ会話の起動の費用は引かない（costUsd が累積か 1 回分かは測れていない）。行に『累積かどうか未確認』"""
        events = [node_done("judging__judge-loop.judge", 0.0284), node_done("rejudging__rj-loop.rejudge", 0.0615)]
        launches = [{"at": "2026-09-27T10:00:00+09:00", "node": "judge", "session": {"mode": "new", "id": "S1"}},
                    {"at": "2026-09-27T10:05:00+09:00", "node": "rejudge",
                     "session": {"mode": "continued", "id": "S1", "of": "judge", "from": "S1"}}]
        rows = {r["node"]: r for r in report.cost_rows(events, launches)}
        self.assertIn("rejudge", rows, "data.spend.costUsd の費用が行にならない")
        self.assertEqual((rows["rejudge"]["actual"], rows["rejudge"]["continued_from"]), (0.0615, "judge"))
        hit = [x for x in report.head_cost(None, "run-1", events=events, launches=launches) if x.startswith("費用 rejudge:")]
        self.assertEqual(len(hit), 1)
        self.assertIn("0.0615 USD", hit[0])
        self.assertIn("累積かどうか未確認", hit[0])
        self.assertNotIn("を引いた", hit[0])


# 写しの検証器（.shared/core/scripts/review-record.py）が 1 周目にいつも出す帳尻の行
FIRST_ROUND = "前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）"
REAL_BLOCKER = "R3 が redesign-needed（理由: 見本の阻害）"
GREEN = {"ok": True, "green": True, "log": "/logs/final.log", "suites": [], "by": "engine"}
RED = {"ok": True, "green": False, "log": "/logs/final-red.log", "suites": [], "by": "engine"}
NEED_FIX = {"ok": True, "open_units": ["k"], "need_fix": True, "judgment_file": "/b/j.json", "one_shot": False}
EYES_PASS = {r: {"status": "pass", "reason": "見本"} for r in ("R1", "R2", "R3", "R4")}


def validator_out(*lines, count=None) -> str:
    """review-record.py の exit 1 の出力の形（見出し『収束を妨げるもの N 件:』と bullet の箇条）"""
    n = len(lines) if count is None else count
    return "\n".join([f"収束を妨げるもの {n} 件:", *(f"  - {x}" for x in lines)])


def gate(code, out="") -> dict:
    """gate_record の返りの形（記録は検証器を通り、今の周は締めてある）"""
    return {"exit": code, "accepted": True, "out": out, "tail": out, "traces": {}, "round_closed": True}


class ResidueOutcomeCase(unittest.TestCase):
    """残り（名指しの帳尻の行を除いた検証器の阻害・最後のテストの赤・独立の目の block）が在れば fixed を名乗らず round_limit。
    偽の盤面（止めていない・人に聞いていない）で decide_outcome を直に呼ぶ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.b = fake_board(self._tmp.name)
        self.b.work = lambda name: self.b.dir / name   # 食い違いの申し出の控えは無い（人に回した単位なし）

    def tearDown(self):
        self._tmp.cleanup()

    def decide(self, g, *, tests=GREEN, **kw):
        try:
            return report.decide_outcome(self.b, g, tests=tests, judged=NEED_FIX, **kw)
        except TypeError as e:
            self.fail(f"decide_outcome が {sorted(kw)} を受けない: {e}")

    def test_round_limit_is_an_outcome(self):
        self.assertIn("round_limit", report.OUTCOMES)

    def test_first_round_line_only_is_fixed(self):
        """1 周で止める run の帳尻の行だけ（exit 1）→ fixed に届く"""
        self.assertEqual(self.decide(gate(1, validator_out(FIRST_ROUND))), "fixed")

    def test_real_blocker_with_first_round_line_is_round_limit(self):
        self.assertEqual(self.decide(gate(1, validator_out(REAL_BLOCKER, FIRST_ROUND))), "round_limit")

    def test_prev_round_line_is_not_suppressed(self):
        """『前ラウンドに阻害要因が N 件あった』は名指しの帳尻の行ではない → round_limit"""
        prev = "前ラウンドに阻害要因が 2 件あった（連続 2 ラウンドの 1 ラウンド目。今ラウンドが阻害なしでも収束は次ラウンド）"
        self.assertEqual(self.decide(gate(1, validator_out(prev))), "round_limit")

    def test_count_mismatch_is_round_limit(self):
        """見出しの N と箇条の数が合わない exit 1 → fail-closed"""
        self.assertEqual(self.decide(gate(1, validator_out(FIRST_ROUND, count=2))), "round_limit")

    def test_no_heading_is_round_limit(self):
        """見出しが無い exit 1 → fail-closed"""
        self.assertEqual(self.decide(gate(1, "読めない出力")), "round_limit")

    def test_red_final_tests_is_round_limit(self):
        self.assertEqual(self.decide(gate(0), tests=RED), "round_limit")

    def test_eye_block_is_round_limit(self):
        """独立の目の R3 が redesign-needed → round_limit"""
        eyeing = {"ok": True, "reason": "", "reviews": {**EYES_PASS, "R3": {"status": "redesign-needed", "reason": "目"}}}
        self.assertEqual(self.decide(gate(0), eyeing=eyeing), "round_limit")

    def test_eyeing_not_ok_is_round_limit(self):
        self.assertEqual(self.decide(gate(0), eyeing={"ok": False, "reason": "目が拒まれた", "reviews": EYES_PASS}),
                         "round_limit")

    def test_eyes_all_pass_is_fixed(self):
        self.assertEqual(self.decide(gate(0), eyeing={"ok": True, "reason": "", "reviews": EYES_PASS}), "fixed")

    def test_first_round_constant_matches_validator(self):
        """除く帳尻の行の定数は、写しの検証器の本文に字のまま在る（写しが変われば赤になり、黙って除かない）"""
        const = getattr(report, "FIRST_ROUND_LINE", None)
        self.assertIsNotNone(const, "report.FIRST_ROUND_LINE が無い")
        src = (ROOT / ".shared" / "core" / "scripts" / "review-record.py").read_text(encoding="utf-8")
        self.assertIn(f'"{const}"', src)
        self.assertEqual(const, FIRST_ROUND)


class NextRequestUnitRowsCase(unittest.TestCase):
    """修正の not_done と人に回した単位は、next_request が単位の行を 1 つ持つ。検証器の『[block] 未解消: <key>』を残りから
    もう 1 行渡さない（同じ単位が次の run に 2 件の依頼で届かない）。ほかの阻害の行は渡す"""

    def test_unit_rows_not_doubled(self):
        b = types.SimpleNamespace(state={"outputs": {"p3.fix": {"round": 1}}}, round=1, loop_state={},
                                  output_of_round=lambda nid, rnd: {"changes": [], "not_done": [{"unit_key": "u-left", "why": "範囲外"}]})
        asked = [{"unit_key": "u-asked", "ruling": {"text": "人が決める"}, "between": ["a", "b"]}]
        left = [{"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {k}"} for k in ("u-left", "u-asked", "u-other")]
        with mock.patch.object(report, "_asked", return_value=asked):
            items = report.next_request(b, left=left)
        for k in ("u-left", "u-asked"):
            self.assertEqual(sum(k in i["text"] for i in items), 1, items)
        self.assertIn(left[2], items)


if __name__ == "__main__":
    unittest.main()
