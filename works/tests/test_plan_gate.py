"""修正前の関所（p2.human_gate）が、決め手の在る項目を人に聞かずに通すか。写しの RL を読み、線 A の核の差し替え
（entry.CORE_OVERRIDES）を盤面と同じ口（DiskBoard._apply_overrides）で当て、機械の節 human_gate を偽の盤面で直に呼ぶ（FAST。
盤面・git・子のプロセスなし）。決め手の出どころ decided_by が在り undecided_because が空で柵の印 fences が無い行は通して
state.works.gate_passes に出どころつきで残し、柵の印か undecided_because の在る行・欄の無い行は今までどおり聞く"""
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
import board  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import line_edge  # noqa: E402
import plan  # noqa: E402
import report  # noqa: E402
from engine.rules import registry  # noqa: E402

NARROW = {"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま"}
DECIDED = {"decided_by": "依頼の本文: 空の列の mean は今までどおり例外でよい", "undecided_because": "", "fences": []}
FACE = {"key": "clamp の上限の意味が変わる", "unit_keys": ["u"], "kind": "regression", "where": "stats.py clamp",
        "why": "上限を超えた値に lo を返す今の振る舞いに頼る呼び手が在れば結果が変わる", "severity": "block"}


class GateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def gate(self, narrows=(), faces=(), questions=(), units=()):
        """差し替えを当てた写しの RL で p2.human_gate を回す。(返り, 偽の盤面)"""
        outs = {"p2.fix_plan": {"plan": [{"unit_keys": ["u"], "narrows": list(narrows)}]},
                "p2.plan_review": {"faces": list(faces)}}
        b = types.SimpleNamespace(
            round=1, dir=self.tmp, loop_state={},
            record={"process": {"human_items": [], "policy": {}}, "questions": list(questions), "units": list(units)},
            # 名指しした方針の文書が無い: 固定した版（無し）から変わっていない
            state={"inputs": {"policy_md": str(self.tmp / "no-policy.md"), "cwd": str(self.tmp)}, "works": {},
                   "validator": str(board.VALIDATOR_PATH), "graph": str(board.GRAPH_PATH)},
            output_of_round=lambda nid, rnd: outs.get(nid), work=lambda name: self.tmp / name)
        holder = types.SimpleNamespace(rules=board.rules_module(), state=b.state)
        board.DiskBoard._apply_overrides(holder, entry.CORE_OVERRIDES)
        b.rules = holder.rules
        return registry(holder.rules, "BUILTINS")["human_gate"](b, "p2.human_gate"), b


class PlanGateCase(GateBase):
    def test_decided_narrow_passes_and_is_recorded(self):
        got, b = self.gate(narrows=[{**NARROW, **DECIDED}])
        self.assertEqual(got, {"ok": True})
        passes = b.state["works"].get("gate_passes") or []
        self.assertEqual([(p["node"], p["by"], p["decided_by"]) for p in passes],
                         [("p2.human_gate", "decided", DECIDED["decided_by"])])
        self.assertIn(NARROW["what"], passes[0]["item"])

    def test_decided_regression_face_passes(self):
        got, b = self.gate(faces=[{**FACE, **DECIDED}])
        self.assertEqual(got, {"ok": True})
        self.assertEqual([p["by"] for p in b.state["works"].get("gate_passes") or []], ["decided"])

    def test_fenced_narrow_asks_even_if_decided(self):
        got, _ = self.gate(narrows=[{**NARROW, **DECIDED, "fences": ["external_write"]}])
        self.assertEqual(got.get("decision"), "ask", got)

    def test_undecided_narrow_asks(self):
        got, _ = self.gate(narrows=[{**NARROW, **DECIDED, "undecided_because": "世界の解が 2 つに割れる"}])
        self.assertEqual(got.get("decision"), "ask", got)

    def test_mixed_rows_ask_only_the_undecided(self):
        """決め手の在る行と欄の無い行が並べば、欄の無い行だけを聞き、決め手の在る行は項目に出さず記録に残す"""
        got, b = self.gate(narrows=[{**NARROW, **DECIDED}, {"what": "負の上限の clamp", "why": "上限が負の時の結果が変わる"}])
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(len(got["ask"]["items"]), 1)
        self.assertIn("負の上限の clamp", got["ask"]["items"][0])
        self.assertEqual([p["by"] for p in b.state["works"].get("gate_passes") or []], ["decided"])


FORK_UNIT = "stats.py mean: 空の列の扱いが決まらない"
OTHER_UNIT = "stats.py clamp: 上限を超えた値に lo を返す"
FORK = {"key": "q-empty-mean", "kind": "fork", "status": "held", "origin": FORK_UNIT, "options": ["例外", "0 を返す"],
        "reason": "空の列の意味が 2 つに割れる。推し: 例外——呼び手が既に例外を捕まえている"}
UNITS = [{"key": FORK_UNIT, "label": "block"}, {"key": OTHER_UNIT, "label": "block"}]


class LedgerAsksCase(GateBase):
    """問いの台帳で人に聞く状態の fork・escalate が修正前の関所の項目に載り（無人の run では載せず、修正を飛ばさない）、関所の
    continue でその出どころが直す義務に戻り（一言の「保留: <key>」は戻さない）、最後の関所の文と報告の冒頭が「無い」と書かずに並べる"""

    def answer(self, b, got, note=""):
        """写しの human_gate_answered と同じ形の行を積む"""
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": note, "node": "p2.human_gate"})

    def owed(self, b):
        return conflict.owed_units_but_asked(b)

    def final_text(self, b):
        b.state["outputs"] = {}
        return line_edge._final_text(b, "緑", {}, "", ([], []), self.tmp, "run-1")

    def head(self, b):
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report, "_conflict_line", return_value=""), \
                mock.patch.object(report, "_rejudge_changes", return_value=[]), \
                mock.patch.object(report, "_premise_hypotheses", return_value=[]), \
                mock.patch.object(report, "_pr_lines", return_value=[]), \
                mock.patch.object(report.querytest, "unproven_lines", return_value=[]), \
                mock.patch.object(report.querytest, "closure_lines", return_value=[]):
            return "\n".join(report.head_decisions(b, {}, tests=None))

    def test_held_fork_is_asked_with_options_and_recommendation(self):
        got, _ = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(got["ask"]["kinds"], ["fork"])
        row = got["ask"]["items"][0]
        for needle in (FORK["key"], "例外・0 を返す", "推し: 例外", FORK_UNIT):
            self.assertIn(needle, row)
        text = plan.gate_text({"node": "p2.human_gate", **got["ask"]})
        self.assertIn(gatemarks.ASK_GATE_HEAD, text)
        self.assertIn("問いの理由の推しで直す", text)
        self.assertIn("保留: <問いの key>", text)
        self.assertNotIn(gatemarks.ASK_GATE_HEAD, plan.gate_text({"node": "p2.human_gate", "kinds": ["regression"],
                                                                  "items": ["x"], "question": "q"}))

    def test_recommendation_missing_is_said(self):
        got, _ = self.gate(questions=[{**FORK, "reason": "空の列の意味が 2 つに割れる"}], units=UNITS)
        self.assertIn("推し: 判定の役が書いていない", got["ask"]["items"][0])

    def test_decided_or_non_fork_held_question_is_not_asked(self):
        for q in ({**FORK, "status": "decided", "resolution": "例外"}, {**FORK, "kind": "field", "origin": None}):
            with self.subTest(q["status"] + q["kind"]):
                got, _ = self.gate(questions=[q], units=UNITS)
                self.assertEqual(got, {"ok": True})

    def test_escalate_is_asked(self):
        got, _ = self.gate(questions=[{**FORK, "kind": "stuck", "status": "escalate"}], units=UNITS)
        self.assertEqual(got["ask"]["kinds"], ["escalate"])

    def test_continue_returns_the_fork_origin_to_the_owed_units(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(self.owed(b), {OTHER_UNIT})
        self.answer(b, got, note="例外で")
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})
        self.assertIn(FORK_UNIT, "\n".join(gatemarks.returned_lines(b)))
        self.assertEqual(gatemarks.plan_gate_items(b), [])   # 答えた問いは関所に 2 度出さない
        self.assertIn("関所で continue を受けた", self.final_text(b))

    def test_hold_note_keeps_the_fork_origin_exempt(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.answer(b, got, note=f"狭めは通す。保留: {FORK['key']}")
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_hold_note_names_only_the_whole_key(self):
        """「保留: q-empty-mean-2」は key が前方で重なる q-empty-mean を保留にしない"""
        longer = {**FORK, "key": FORK["key"] + "-2", "origin": OTHER_UNIT}
        got, b = self.gate(questions=[FORK, longer], units=UNITS)
        self.answer(b, got, note=f"保留: {longer['key']}。")
        self.assertEqual(self.owed(b), {FORK_UNIT})

    def test_hold_note_lists_several_keys(self):
        """関所の文と同じ「・」「/」で並べた「保留: q-a・q-b」は、並べた問いをどれも保留にする"""
        other = {**FORK, "key": FORK["key"] + "-b", "origin": OTHER_UNIT}
        for sep in ("・", "/", "／", "、", " "):
            with self.subTest(sep=sep):
                got, b = self.gate(questions=[FORK, other], units=UNITS)
                self.answer(b, got, note=f"保留: {FORK['key']}{sep}{other['key']}")
                self.assertEqual(self.owed(b), set())

    def test_stop_or_another_gate_does_not_return_the_origin(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        b.record["process"]["human_items"].append({"round": 1, "kinds": ["fork"], "asked": got["ask"]["items"],
                                                   "answer": "stop", "note": "", "node": "p2.human_gate"})
        b.record["process"]["human_items"].append({"round": 1, "kinds": ["regression"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "", "node": "r4.human_gate"})
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_unattended_run_does_not_open_the_gate_for_questions_only(self):
        """無人の run: 保留の問いだけでは関所を開かず（無人の殻の stop で修正が飛ばない）、出どころだけを今どおり飛ばし、ほかの
        単位は直す義務に残る（BASE で直せていた単位を失わない）。狭めの在る関所は今どおり開く（問いの行は載せない）"""
        (self.tmp / "r1").mkdir()
        (self.tmp / "r1" / "start.json").write_text('{"unattended": "true"}', encoding="utf-8")
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got, {"ok": True})
        self.assertEqual(self.owed(b), {OTHER_UNIT})
        self.assertIn(FORK["key"], self.head(b))   # 答えの無い問いは報告の冒頭に並ぶ
        got, _ = self.gate(narrows=[NARROW], questions=[FORK], units=UNITS)
        self.assertEqual((got["ask"]["kinds"], len(got["ask"]["items"])), (["regression"], 1))

    def test_held_questions_are_listed_not_none(self):
        """最後の関所の文と報告の冒頭: 台帳の保留（fork でない awaiting も）を並べ、『盤面の問い: 無い』と書かない"""
        awaiting = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr", "reason": "人が確かめる"}
        _, b = self.gate(questions=[FORK, awaiting], units=UNITS)
        for name, text in (("最後の関所", self.final_text(b)), ("報告の冒頭", self.head(b))):
            with self.subTest(name):
                self.assertNotIn("盤面の問い: 無い", text)
                self.assertIn(FORK["key"], text)
                self.assertIn(awaiting["key"], text)
        _, empty = self.gate(units=UNITS)
        self.assertIn("盤面の問い: 無い", self.final_text(empty))
        self.assertNotIn(gatemarks.ASK_HEAD, self.head(empty))


if __name__ == "__main__":
    unittest.main()
