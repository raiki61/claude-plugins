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
