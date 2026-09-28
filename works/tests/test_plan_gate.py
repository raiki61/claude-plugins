"""修正前の関所（p2.human_gate）が、決め手の在る項目を人に聞かずに通すか。写しの RL を読み、線 A の核の差し替え
（entry.CORE_OVERRIDES）を盤面と同じ口（DiskBoard._apply_overrides）で当て、機械の節 human_gate を偽の盤面で直に呼ぶ（FAST。
盤面・git・子のプロセスなし）。決め手の出どころ decided_by が在り undecided_because が空で柵の印 fences が無い行は通して
state.works.gate_passes に出どころつきで残し、柵の印か undecided_because の在る行・欄の無い行は今までどおり聞く"""
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import board  # noqa: E402
import entry  # noqa: E402
from engine.rules import registry  # noqa: E402

NARROW = {"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま"}
DECIDED = {"decided_by": "依頼の本文: 空の列の mean は今までどおり例外でよい", "undecided_because": "", "fences": []}
FACE = {"key": "clamp の上限の意味が変わる", "unit_keys": ["u"], "kind": "regression", "where": "stats.py clamp",
        "why": "上限を超えた値に lo を返す今の振る舞いに頼る呼び手が在れば結果が変わる", "severity": "block"}


class PlanGateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def gate(self, narrows=(), faces=()):
        """差し替えを当てた写しの RL で p2.human_gate を回す。(返り, 偽の盤面)"""
        outs = {"p2.fix_plan": {"plan": [{"unit_keys": ["u"], "narrows": list(narrows)}]},
                "p2.plan_review": {"faces": list(faces)}}
        b = types.SimpleNamespace(
            round=1, dir=self.tmp, loop_state={},
            record={"process": {"human_items": [], "policy": {}}},
            # 名指しした方針の文書が無い: 固定した版（無し）から変わっていない
            state={"inputs": {"policy_md": str(self.tmp / "no-policy.md"), "cwd": str(self.tmp)}, "works": {}},
            output_of_round=lambda nid, rnd: outs.get(nid))
        holder = types.SimpleNamespace(rules=board.rules_module(), state=b.state)
        board.DiskBoard._apply_overrides(holder, entry.CORE_OVERRIDES)
        b.rules = holder.rules
        return registry(holder.rules, "BUILTINS")["human_gate"](b, "p2.human_gate"), b

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


if __name__ == "__main__":
    unittest.main()
