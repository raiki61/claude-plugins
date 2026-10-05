"""直す義務と、そこから外れた単位の正本（conflict.fix_duty）と、それを読む修正の受け付け（blk-fix の fix-accept）。

- fix_duty: 答え待ちの fork・escalate の出どころ・ask_human の単位・関所で答えて戻した単位を混ぜた盤面で、owed と excused は
  互いに素で、合わせて修正役が書いてよい単位（gatemarks.fixable）を覆い、excused は問いの key・裁定の id を理由に持つ。
  写しの RL と線 A の核の差し替えを偽の盤面に当てる（test_plan_gate と同じ口。盤面・git・子のプロセスなし）
- 受け付け: excused の単位を changes に書いた返答は、NOT_OPENED と別の文で理由を名指して拒む。輪の最後の回は、その行を数えずに
  単位の行を changes から外し（直しは作業ツリーに残す。依頼 241）、ほかの単位に結んだ行の単位は止める（依頼 242）。
  受け付けの部品は mock にする（最後の回の結びは fake_settle。足跡は返答の行の files だけ）
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


def fake_settle(mod, owed, excused):
    """受け付けの last_settle の代わり（盤面・git を読まない）: 足跡は返答の行の files だけ、届く試験は無し、直す義務は owed、
    義務の外は excused とこの受け付けがもう止めた単位。by_copy（写しの拒否）で止める単位が無いのに義務の残りが在れば park_owed"""
    def settle(texts, reply, board, base_rev, repo, state, parked, by_copy=False, declared=None):
        rows = [c for c in reply.get("changes") or [] if isinstance(c, dict)]
        out = set(excused) | set(parked)
        keys = set(owed) | set(excused) | {c.get("unit_key") for c in rows}
        feet = mod.parking.footprint(rows, [], repo)
        got = mod.parking.settle(texts, keys=keys, feet=feet, reached={}, owed=set(owed) - out, out_of_duty=out,
                                 changed=set(), declared=declared)
        if by_copy and not got.park and set(owed) - out:
            got = mod.parking.park_owed(texts, feet=feet, owed=set(owed), out_of_duty=out)
        return got, out
    return settle


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
        self.parked = []
        self.declared = []   # 書き込みの出どころの突き合わせが見た bash_writes
        self.revert = mock.MagicMock(return_value="/b/r1/fix-parked-1.patch")
        patches = [
            mock.patch.object(self.mod.tddloop, "frozen_problems", return_value=[]),
            mock.patch.object(self.mod, "check_writes", side_effect=lambda reply, *a, **k: self.declared.append(
                reply.get(self.mod.writes.FIELD)) or {"problems": [], "reply": reply}),
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
            mock.patch.object(self.mod, "last_settle", fake_settle(self.mod, {self.MEAN}, {self.HELD: self.WHY})),
            mock.patch.object(self.mod.conflict, "park", side_effect=lambda b, rows, **k: self.parked.extend(
                r["unit_key"] for r in rows)),
            mock.patch.object(self.mod.conflict, "write_rulings"),
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
        self.assertNotIn("戻し", self.mod.EXCUSED, "外れた単位の直しを戻させない（依頼 241）")
        self.assertNotIn(self.mod.NOT_OPENED, got["reason"])
        self.revert.assert_not_called()

    def test_last_round_drops_only_the_excused_unit(self):
        got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual([c["unit_key"] for c in got["changes"]], [self.MEAN])
        self.assertEqual(self.recounted, [[self.MEAN]])
        self.revert.assert_not_called()   # 外れた単位の直しは作業ツリーに残す（依頼 241）
        self.assertEqual(self.parked, [])
        self.board.trace.assert_any_call(self.mod.ABSORBED_OP, node=self.mod.recount.ROLE, dropped=[self.HELD],
                                         absorbed=[f"{self.mod.EXCUSED}{self.HELD}（{self.WHY}）"])

    def test_last_round_keeps_bash_writes_of_the_dropped_unit(self):
        """外した行の直しは残るので、その書き込みの申告（bash_writes）も突き合わせに渡したまま（通し直さない）"""
        self.run_accept("3")
        self.assertEqual(self.declared, [[{"path": "clamp.py", "why": "整形の道具で書いた"}]])

    def test_last_round_with_shared_file_drops_the_row(self):
        """戻さないので、外す行がファイルをほかの行と共にしても行だけを外して通す"""
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": self.HELD, "files": ["stats.py"], "what": "上限の枝を直した"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual(self.recounted, [[self.MEAN]])
        self.revert.assert_not_called()

    def test_last_round_duplicate_parks_and_excused_row_is_absorbed(self):
        # 最後の回: 重なりの行は MEAN に結んで止め（stats.py を戻す）、外れた単位の行は数えずに行だけを外す（clamp.py は戻さない）
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": self.HELD, "files": ["clamp.py"], "what": "上限の枝を直した"},
                {"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"], got["changes"]), (True, True, []), got)
        self.assertEqual(self.parked, [self.MEAN])
        self.revert.assert_called_once()
        self.assertEqual(self.revert.call_args.args[3], {"stats.py"}, "外れた単位の直しは戻さない")
        self.assertEqual(self.recounted, [[]])

    def test_key_outside_duty_and_excused_is_not_opened(self):
        # 最後の回: 開いていない作り話の単位の行はその単位に結んで止め、その足跡 x.py を戻す。MEAN は受ける
        rows = [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                {"unit_key": "作り話の単位", "files": ["x.py"], "what": "x"}]
        got = self.run_accept("3", rows)
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual([c["unit_key"] for c in got["changes"]], [self.MEAN])
        self.assertEqual(self.parked, ["作り話の単位"])
        self.assertEqual(self.revert.call_args.args[3], {"x.py"})


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

    def test_declared_keys_bind_without_text_matching(self):
        """declared の文は文照合を使わず declared の単位に結ぶ（別の単位の足跡のパスを名指しても）。declared に無い文は今の bind"""
        import inspect
        parking = self.mod.parking
        self.assertIn("declared", inspect.signature(parking.settle).parameters)
        A, B = "a.py f: 直す", "b.py g: 直す"
        feet = {A: {"a.py"}, B: {"b.py"}}
        base = dict(keys={A, B}, feet=feet, reached={}, owed={A, B}, out_of_duty=set(), changed=set())
        declared_text = "食い違い[0]: 名指し 'b.py:99' の行がファイルに無い"
        by_path = "b.py を直した行の拒否"
        nothing = "どの単位も名指さない行"
        got = parking.settle([declared_text], declared={declared_text: {A}}, **base)
        self.assertEqual(sorted(got.park), [A], got)
        self.assertEqual(got.unbound, {})
        self.assertEqual(got.how, {declared_text: "declared"})
        got = parking.settle([declared_text, by_path], declared={declared_text: {A}}, **base)
        self.assertEqual(sorted(got.park), [A, B], got)
        self.assertEqual(got.how, {declared_text: "declared", by_path: "text"})
        got = parking.settle([nothing], declared={declared_text: {A}}, **base)
        self.assertEqual(sorted(got.park), [A, B], "declared に無い文は結べず義務の全部")
        self.assertEqual(got.how, {nothing: "unbound"})
        self.assertEqual(list(got.unbound), [nothing])

    def test_conflicts_are_checked_against_the_duty(self):
        """食い違いの申し出は直す義務の単位にだけ受ける（答え待ちの単位は義務に無い）"""
        seen = {}
        with mock.patch.object(self.mod.entry, "open_board", return_value=self.board), \
                mock.patch.object(self.mod.conflict, "owed_units_but_asked", return_value={self.MEAN}), \
                mock.patch.object(self.mod.conflict, "held_by_rulings", return_value={}), \
                mock.patch.object(self.mod.conflict, "asked_keys", return_value=set()), \
                mock.patch.object(gatemarks, "fixable", return_value={self.MEAN, self.HELD}), \
                mock.patch.object(self.mod.querytest, "judge_hits", return_value=None), \
                mock.patch.object(self.mod.conflict, "problems_by_entry", create=True,
                                  side_effect=lambda items, **k: seen.update(k) or [(0, None, ["x"])]):
            self.mod.take_conflicts({"changes": [], "conflicts": [{"unit_key": self.HELD}]}, pathlib.Path("/b"),
                                    pathlib.Path("/r"), "first")
        self.assertEqual(seen.get("owed"), {self.MEAN})


if __name__ == "__main__":
    unittest.main()
