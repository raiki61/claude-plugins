"""直す義務と、そこから外れた単位の正本（conflict.fix_duty）と、それを読む修正の受け付け（blk-fix の fix-accept）。

- fix_duty: 答え待ちの fork・escalate の出どころ・ask_human の単位・関所で答えて戻した単位を混ぜた盤面で、owed と excused は
  互いに素で、合わせて修正役が書いてよい単位（gatemarks.fixable）を覆い、excused は問いの key・裁定の id を理由に持つ。
  写しの RL と線 A の核の差し替えを偽の盤面に当てる（test_plan_gate と同じ口。盤面・git・子のプロセスなし）
- 受け付け: excused の単位を changes に書いた返答は、NOT_OPENED と別の文で理由を名指して拒む。輪の最後の回だけは、その単位の
  直しを作業ツリーから戻して changes から外し、残りで受け付けを通し直す（人の答え 2026-10-02: 審査が示した狭めない案）。
  受け付けの部品は mock にする
"""
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import conflict  # noqa: E402
import gatemarks  # noqa: E402
from test_plan_gate import FORK, FORK_UNIT, OTHER_UNIT, GateBase  # noqa: E402

ESC_UNIT = "stats.py median: 偶数の長さの中央値が決まらない"
ASKED_UNIT = "stats.py clamp: 下限と上限が逆の時の扱い"
BACK_UNIT = "stats.py mode: 同数の時の選び方"
ESC = {"key": "q-median", "kind": "stuck", "status": "escalate", "origin": ESC_UNIT, "reason": "推し: 平均を返す"}
BACK = {**FORK, "key": "q-mode", "origin": BACK_UNIT}
UNITS = [{"key": k, "label": "block"} for k in (FORK_UNIT, OTHER_UNIT, ESC_UNIT, ASKED_UNIT, BACK_UNIT)]


class TestFixDuty(GateBase):
    def board(self):
        got, b = self.gate(questions=[FORK, ESC, BACK], units=UNITS)
        mode = next(i for i in got["ask"]["items"] if BACK["key"] in i)
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": [mode],
                                                   "answer": "continue", "note": "", "node": "p2.human_gate"})
        (self.tmp / conflict.FILE).write_text(json.dumps({"items": [
            {"id": "c1-1", "unit_key": ASKED_UNIT, "ruling": {"decision": conflict.ASK}}]}), encoding="utf-8")
        return b

    def test_owed_and_excused_split_fixable_with_reasons(self):
        b = self.board()
        owed, excused = conflict.fix_duty(b)
        self.assertEqual(owed, {OTHER_UNIT, BACK_UNIT}, "関所で答えて戻した単位は義務に残る")
        self.assertEqual(owed & set(excused), set())
        self.assertLessEqual(gatemarks.fixable(b), owed | set(excused))
        self.assertIn(FORK["key"], excused[FORK_UNIT])
        self.assertIn(ESC["key"], excused[ESC_UNIT])
        self.assertIn("ask_human の裁定 c1-1", excused[ASKED_UNIT])
        self.assertEqual(conflict.excused_units(b), excused)
        self.assertEqual(conflict.nothing_owed_but_excused(b), {}, "義務が残る盤面は空の changes を通さない")

    def test_excused_reason_reads_withheld_by_not_a_copy(self):
        b = self.board()
        with mock.patch.object(gatemarks, "withheld_by", return_value={FORK_UNIT: ESC}):
            _, excused = conflict.fix_duty(b)
        self.assertIn(ESC["key"], excused[FORK_UNIT])
        self.assertNotIn(ESC_UNIT, excused)

    def test_unreadable_conflicts_keep_asked_unit_owed(self):
        b = self.board()
        (self.tmp / conflict.FILE).write_text("{", encoding="utf-8")
        owed, excused = conflict.fix_duty(b)
        self.assertIn(ASKED_UNIT, owed, "控えが読めなければ ask_human を義務から外さない")
        self.assertNotIn(ASKED_UNIT, excused)


class TestAcceptExcused(unittest.TestCase):
    MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
    HELD = "stats.py clamp: 上限を超えた値に lo を返す"
    WHY = "答え待ちの問い q-1（fork・held）"

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script", BLK / "scripts" / "accept.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.board = mock.MagicMock()
        self.recounted = []
        self.revert = mock.MagicMock(return_value="/b/r1/fix-parked-1.patch")
        self.unrevert = mock.MagicMock()
        patches = [
            mock.patch.object(self.mod.tddloop, "frozen_problems", return_value=[]),
            mock.patch.object(self.mod, "check_writes", side_effect=lambda reply, *a, **k: {"problems": [], "reply": reply}),
            mock.patch.object(self.mod, "take_conflicts", side_effect=lambda reply, *a, **k: (reply, None)),
            mock.patch.object(self.mod, "fix_unit_keys", side_effect=self.keys),
            mock.patch.object(self.mod, "check_pack_copy", return_value=""),
            mock.patch.object(self.mod, "check_tests", return_value=([], "")),
            mock.patch.object(self.mod.fixgates, "problems", return_value=[]),   # 事後の関門の束（test_fix_gates が見る）
            mock.patch.object(self.mod.fixgates, "skipped", return_value=[]),
            mock.patch.object(self.mod, "check_plan_scope", return_value=([], None)),   # 修正案の範囲の照らし（git を読む）
            mock.patch.object(self.mod.recount, "accept_fix", side_effect=self.recount),
            mock.patch.object(self.mod.entry, "open_board", return_value=self.board),
            mock.patch.object(self.mod.writes, "trace"),
            mock.patch.object(self.mod.conflict, "waiting", return_value=[]),   # 案の直しを待つ単位は無い（控えない）
            # 1 回目に受け付けた返答の控えは無い（1 回目の修正の段。盤面は mock なので控えを読ませない）
            mock.patch.object(self.mod.conflict, "held_reply", return_value=(None, pathlib.Path("/b/r1/fix-held-reply.json"))),
            mock.patch.object(self.mod, "revert_units", self.revert),
            mock.patch.object(self.mod, "unrevert_units", self.unrevert),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.accept_ok = True

    def keys(self, reply, board):
        return [c["unit_key"] for c in reply["changes"]], {self.MEAN}, {self.HELD: self.WHY}

    def recount(self, reply, *a, commit=True):
        if commit:   # 盤面に渡した呼びだけを数える（乾いた照らし commit=False は数えない）
            self.recounted.append([c["unit_key"] for c in reply["changes"]])
        if not self.accept_ok:
            return {"ok": False, "reason": "写しの受け付けが拒んだ", "changes": []}
        return {"ok": True, "reason": "", "changes": [{k: c[k] for k in ("unit_key", "files", "what")} for c in reply["changes"]]}

    def run_accept(self, iteration, rows=None):
        reply = {"changes": rows or [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                                     {"unit_key": self.HELD, "files": ["clamp.py"], "what": "上限の枝を直した"}],
                 "bash_writes": [{"path": "clamp.py", "why": "整形の道具で書いた"}]}
        with mock.patch.dict("os.environ", {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "", "INPUTS_PASS": "first"}):
            return self.mod.with_done(self.mod.accept_fix(reply, pathlib.Path("/b"), "", pathlib.Path("/r")))

    def test_excused_unit_is_rejected_with_its_reason(self):
        got = self.run_accept("1")
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        self.assertIn(self.mod.EXCUSED, got["reason"])
        self.assertIn(self.WHY, got["reason"])
        self.assertNotIn(self.mod.NOT_OPENED, got["reason"])
        self.revert.assert_not_called()

    def test_last_round_drops_only_the_excused_unit(self):
        got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual([c["unit_key"] for c in got["changes"]], [self.MEAN])
        self.assertEqual(self.recounted, [[self.MEAN]])
        self.revert.assert_called_once()
        self.assertIn(self.HELD, repr(self.revert.call_args), "外れた単位の直しを作業ツリーから戻す")
        self.assertNotIn(self.MEAN, repr(self.revert.call_args), "ほかの単位の直しは戻さない")
        self.board.trace.assert_any_call(self.mod.EXCUSED_DROPPED_OP, node=self.mod.recount.ROLE,
                                         excused={self.HELD: self.WHY}, patch="/b/r1/fix-parked-1.patch")
        self.unrevert.assert_not_called()

    def test_last_round_restores_the_dropped_fix_when_the_rest_fails(self):
        self.accept_ok = False
        got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.unrevert.assert_called_once()
        self.assertNotIn(self.mod.EXCUSED_DROPPED_OP, repr(self.board.trace.call_args_list))

    def test_last_round_with_shared_file_rejects_the_whole_reply(self):
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": self.HELD, "files": ["stats.py"], "what": "上限の枝を直した"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertIn(self.WHY, got["reason"])
        self.revert.assert_not_called()

    def test_last_round_with_unparkable_row_keeps_the_excused_fix(self):
        # 最後の回でも、止めてよくない確かめの行（重なり）が既に積まれていれば外れた単位の直しを戻さず、丸ごと拒んで
        # 外れた単位の行も並べる（作業ツリーに触らない。通し直しの数え直しも回さない）
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": self.HELD, "files": ["clamp.py"], "what": "上限の枝を直した"},
                {"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertEqual({r["check"] for r in got["rejects"]}, {"duplicate", "excused"}, got)
        self.revert.assert_not_called()
        self.unrevert.assert_not_called()

    def test_key_outside_duty_and_excused_is_not_opened(self):
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": "作り話の単位", "files": ["x.py"], "what": "x"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertIn(self.mod.NOT_OPENED, got["reason"])
        self.revert.assert_not_called()


class TestAcceptReadsDuty(unittest.TestCase):
    MEAN, HELD, WHY = TestAcceptExcused.MEAN, TestAcceptExcused.HELD, TestAcceptExcused.WHY

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script", BLK / "scripts" / "accept.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.board = mock.MagicMock()

    def test_unit_keys_read_the_duty_not_fixable(self):
        """fix_unit_keys は gatemarks.fixable でなく conflict.fix_duty の義務と外れた単位を返す"""
        self.board.rd = {"instances": {self.mod.recount.FIX_NODE: {"status": "pending", "launched_at": "t", "pointers": None}}}
        self.board.deps_met.return_value = True
        self.board.nodes = {self.mod.recount.FIX_NODE: {}}
        reply = {"changes": [{"unit_key": self.MEAN}, {"unit_key": self.HELD}]}
        with mock.patch.object(self.mod.entry, "open_board", return_value=self.board), \
                mock.patch.object(self.mod.conflict, "fix_duty", return_value=({self.MEAN}, {self.HELD: self.WHY})), \
                mock.patch.object(gatemarks, "fixable", return_value={self.MEAN, self.HELD}):
            got = self.mod.fix_unit_keys(reply, pathlib.Path("/b"))
        self.assertEqual(got, ([self.MEAN, self.HELD], {self.MEAN}, {self.HELD: self.WHY}))

    def test_conflicts_are_checked_against_the_duty(self):
        """食い違いの申し出は直す義務の単位にだけ受ける（答え待ちの単位は義務に無い）"""
        seen = {}
        with mock.patch.object(self.mod.entry, "open_board", return_value=self.board), \
                mock.patch.object(self.mod.conflict, "owed_units_but_asked", return_value={self.MEAN}), \
                mock.patch.object(self.mod.conflict, "asked_keys", return_value=set()), \
                mock.patch.object(gatemarks, "fixable", return_value={self.MEAN, self.HELD}), \
                mock.patch.object(self.mod.querytest, "judge_hits", return_value=None), \
                mock.patch.object(self.mod.conflict, "problems", side_effect=lambda items, **k: seen.update(k) or ["x"]):
            self.mod.take_conflicts({"changes": [], "conflicts": [{"unit_key": self.HELD}]}, pathlib.Path("/b"),
                                    pathlib.Path("/r"), "first")
        self.assertEqual(seen["owed"], {self.MEAN})


if __name__ == "__main__":
    unittest.main()
