"""直す義務の 5 つの集合を、同じ見本の盤面で、それぞれ消費する所の入口から作って突き合わせる（FAST。盤面・git・子のプロセスなし）。

5 つの集合: 修正役への約束（fixrules.owed_values が指示書に埋める値）・受け付けが通す単位（accept.fix_unit_keys）・TDD の
振り分けの義務（tddloop.start が作る st を _owed で読む）・片付け後の確かめの免除（assert_changed.nothing_owed）・報告の保留
（report.head3 の件数と gatemarks.held_lines の「答えが無いと直さない単位」）。正本は conflict.fix_duty と gatemarks で、
この試験は正本を直に比べず、各入口が正本を読んで返した物だけを比べる（入口が自前の式に替われば赤になる）。

見本の盤面は test_fix_duty の物（開いた単位・答え待ちの fork の出どころ・escalate の出どころ・ask_human の単位・関所で答えて
戻した単位）。設計どおりの差は KNOWN_DIFF に {関係: 理由} で載せる。期限は置かない。差が消えたら赤にして人に表から消させる
（test_layers の KNOWN と同じ向きで、表は減らす方向にだけ変える）
"""
import importlib.util
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))

import conflict  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402
import gatemarks  # noqa: E402
import recount  # noqa: E402
import report  # noqa: E402
import tddloop  # noqa: E402
import test_fix_duty as fd  # noqa: E402
from test_fix_duty import ASKED_UNIT, BACK_UNIT, ESC_UNIT, UNITS  # noqa: E402
from test_plan_gate import FORK_UNIT, OTHER_UNIT, GateBase  # noqa: E402


def script(name: str):
    spec = importlib.util.spec_from_file_location(f"duty_sets_{name}", ROOT / "blk-fix" / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 設計どおりの差 {関係: 理由}。直って差が無くなったら赤（行を消す）
KNOWN_DIFF = {
    "held_lines の問いの数 = 答えていない asks の問いの数":
        "held_lines は台帳で人に聞く状態の問いを kind を問わず並べる（gatemarks._asking。fork・escalate 以外の保留も人が決める物）。"
        "直す義務から外す方（gatemarks.asks）は fork と escalate だけ。理由の正本は gatemarks.asks の docstring",
}


class DutySets(GateBase):
    board = fd.TestFixDuty.board

    def setUp(self):
        super().setUp()
        self.b = self.board()
        self.b.dir = self.tmp
        self.b.trace = lambda *a, **k: None
        self.b.deps_met = lambda nid: True
        self.b.nodes = {recount.FIX_NODE: {}}
        self.b.rd = {"instances": {recount.FIX_NODE: {"status": "pending", "launched_at": "t", "pointers": None}}}
        patch = mock.patch.object(entry, "open_board", return_value=self.b)
        patch.start()
        self.addCleanup(patch.stop)

    # ---- 5 つの集合を、消費する所の入口から作る
    def is_open_keys(self) -> list:
        v = self.b.rules.validator_module(self.b)
        return [u["key"] for u in UNITS if v.is_open(u)]

    def promised(self) -> set:
        got = fixrules.owed_values(self.b, {"open_units": json.dumps(self.is_open_keys(), ensure_ascii=False)})
        return set(json.loads(got["open_units"]))

    def accepted(self) -> tuple:
        rows = [{"unit_key": k} for k in sorted(self.is_open_keys())]
        _, owed, excused = script("accept").fix_unit_keys({"changes": rows}, self.tmp)
        return set(owed), dict(excused)

    def tdd_owed(self) -> set:
        suite = self.tmp / "suite.py"
        suite.write_text("", encoding="utf-8")
        with mock.patch.object(tddloop, "run_suite", return_value=([], 0, [])), \
                mock.patch.object(tddloop, "snapshot", return_value=""):
            got = tddloop.start(self.tmp / "tdd", self.tmp, str(suite), json.dumps(self.is_open_keys(), ensure_ascii=False))
        self.assertTrue(got["go"], got)
        st = json.loads(pathlib.Path(got["state_file"]).read_text(encoding="utf-8"))
        return set(tddloop._owed(st)), set(st["excused"])

    def excused_after_clean(self) -> dict:
        """片付け後の確かめが空の申告を通す時の、外れた単位。通さなければ空"""
        with mock.patch.dict("os.environ", {"ARTIFACTS_DIR": str(self.tmp)}):
            line = script("assert_changed").nothing_owed()
        return {k for k in [FORK_UNIT, ESC_UNIT, ASKED_UNIT, OTHER_UNIT, BACK_UNIT] if k in line}

    def reported_waiting(self) -> set:
        """報告が「保留にしたままの問い」に並べる行に載る、答えが無いと直さない単位"""
        out = set()
        for line in gatemarks.held_lines(self.b):
            out |= {k for k in (FORK_UNIT, ESC_UNIT, ASKED_UNIT, OTHER_UNIT, BACK_UNIT) if k in line.split("答えが無いと直さない単位:")[-1]}
        return out

    def reported_count(self) -> int:
        return int(next(line for line in report.head3(self.b, "done") if "保留にしたままの問い" in line).split("保留にしたままの問い ")[1].split(" ")[0])

    # ---- 関係
    def test_promise_and_acceptance_and_tdd_read_one_owed(self):
        owed, excused = self.accepted()
        self.assertEqual(owed, {OTHER_UNIT, BACK_UNIT}, "答えを返した単位は義務に残り、答え待ち・ask_human は外れる")
        self.assertEqual(self.promised(), owed, "約束の一覧 = 受け付けの義務（関所で答えて戻った単位を含み、外れた単位を含まない）")
        tdd_owed, tdd_excused = self.tdd_owed()
        self.assertEqual(tdd_owed, owed, "TDD の義務 = 受け付けの義務 − 食い違いで止めた単位（無し）")
        self.assertEqual(tdd_excused, set(excused), "TDD が外す単位 = 受け付けの外れた単位")
        self.assertEqual(owed & set(excused), set())

    def test_reported_waiting_units_are_the_withheld_excused(self):
        _, excused = self.accepted()
        waiting = {k for k, why in excused.items() if "ask_human" not in why}
        self.assertEqual(self.reported_waiting(), waiting, "報告の「答えが無いと直さない単位」= 外れた単位のうち答え待ちの問いの出どころ")
        self.assertNotIn(ASKED_UNIT, self.reported_waiting(), "ask_human の単位は保留の問いでなく食い違いの行で出る")

    def test_nothing_owed_only_when_owed_is_empty_and_excused_is_not(self):
        self.assertEqual(self.excused_after_clean(), set(), "義務が残る盤面は空の申告を通さない")
        for k in (OTHER_UNIT, BACK_UNIT):
            self.b.record["units"] = [u for u in self.b.record["units"] if u["key"] != k]
        self.b.record["process"]["human_items"] = []
        owed, excused = self.accepted_after_shrink()
        self.assertEqual((owed, bool(excused)), (set(), True))
        self.assertEqual(self.excused_after_clean(), set(excused), "義務が空で外れた単位が在る時だけ通し、外れた単位を並べる")

    def accepted_after_shrink(self) -> tuple:
        owed, excused = conflict.fix_duty(self.b)
        return owed, excused

    def test_known_diff_rows_still_differ(self):
        """KNOWN_DIFF の行は、見本の盤面（保留の問いが fork・escalate だけ）に fork・escalate でない保留を足せば今も食い違う"""
        self.b.record["questions"].append({"key": "q-other", "kind": "stuck", "status": "held", "origin": OTHER_UNIT,
                                           "reason": "推し: 今のまま"})
        diff = {"held_lines の問いの数 = 答えていない asks の問いの数":
                len(gatemarks.held_lines(self.b)) != len(gatemarks.pending(self.b))}
        self.assertEqual(set(KNOWN_DIFF), set(diff), "表の行と、この試験が確かめる関係が揃っている")
        for row, differs in diff.items():
            with self.subTest(row=row):
                self.assertTrue(differs, f"差が消えた（直った）ので KNOWN_DIFF の行を消す: {row}")

    def test_report_count_counts_held_lines(self):
        """報告の冒頭の「保留にしたままの問い」の件数は held_lines の件数（見本の盤面では答えていない fork と escalate の 2 件）"""
        self.assertEqual(self.reported_count(), len(gatemarks.held_lines(self.b)))
        self.assertEqual(self.reported_count(), len(gatemarks.pending(self.b)))


if __name__ == "__main__":
    unittest.main()
