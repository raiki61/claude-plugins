"""機械の報告の冒頭 3（report.head_stop）の interrupted の行。盤面を開かず、偽の盤面（state と dir だけ）で関数を直に呼ぶ（FAST。
git・子のプロセスなし）。run 31 は目の支度の節が exit 2 で落ちた——冒頭 3 はどの節がなぜ落ちたかを言い、原因を取り消し・abandon・
上限に決め打ちしない。run の外の report.sh の道（Archon の run の状態の語だけを持つ）の行も保つ"""
import pathlib
import sys
import tempfile
import types
import unittest

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
    return {"event_type": "node_completed", "step_name": step, "data": {"cost_usd": cost}}


class HeadCostCase(unittest.TestCase):
    """費用の行（report.head_cost）。節の費用の欄は Archon の実測の cost_usd だけを読む（issue #2334）。run の合計は節の和でなく
    workflow の終わりの出来事の cost_usd（fan-out の包みと子が両方 cost_usd を持ち、節の和は二重に数える。issue #3508）。
    包みの起動の記録は空で渡す（盤面を開かない）"""

    def test_guessed_keys_are_not_read(self):
        """推測の鍵（costUsd・total_cost_usd）だけの出来事は費用に数えない"""
        events = [{"event_type": "node_completed", "step_name": "a", "data": {"costUsd": 0.5}},
                  {"event_type": "node_completed", "step_name": "b", "data": {"total_cost_usd": 0.7}}]
        lines = report.head_cost(None, "run-1", events=events, launches=[])
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("取れない", lines[0])

    def test_run_total_from_workflow_end(self):
        """workflow の終わりの cost_usd が合計。節の和（0.03）と食い違えば両方を出す"""
        events = [node_done("a", 0.01), node_done("b", 0.02),
                  {"event_type": "workflow_completed", "data": {"cost_usd": 0.025}}]
        lines = report.head_cost(None, "run-1", events=events, launches=[])
        self.assertIn("費用の合計: 0.025 USD", "\n".join(lines))
        self.assertTrue(any("節の和" in x and "0.03" in x for x in lines), lines)

    def test_running_total_is_partial(self):
        """workflow の終わりの出来事がまだ無い（走っている）間の合計は、途中の節の和だと言う"""
        lines = report.head_cost(None, "run-1", events=[node_done("a", 0.01)], launches=[])
        total = [x for x in lines if x.startswith("費用の合計")]
        self.assertEqual(len(total), 1, lines)
        self.assertIn("途中", total[0])


if __name__ == "__main__":
    unittest.main()
