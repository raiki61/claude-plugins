"""research-loop の rules（rules/research-loop.py）の条件の関数を、engine と同じ口（board.run_cond）で直に呼ぶ検査——
形の崩れた欄で落ちない・理由の文が真偽と揃う。盤面を回す端から端までの台本と条件の真偽表は tests/simulate.py"""
import pytest

from conftest import PLUGIN
from engine.board import run_cond
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = PLUGIN / "graphs" / "research-loop.json"
RULES = load_rules(GRAPH, load_graph(GRAPH)[0])


def cond(name, ctx):
    return run_cond(name, RULES.CONDS[name], ctx)


def test_constraints_self_written_skips_rows_that_are_not_objects():
    assert cond("constraints_self_written", {"record": {"constraints": ["文字列の行", {"origin": "surveyor自書"}]}}) == \
        (True, "surveyor が自書した問い・制約は 1 件")


@pytest.mark.parametrize("stuck,want", [(True, (True, "手詰まり（stuck）の後の周")),
                                        (False, (False, "初回でなく、手詰まり（stuck）の後でもない"))])
def test_generation_due_says_why(stuck, want):
    assert cond("generation_due", {"round": 2, "loop": {"stuck_hint": stuck}}) == want


def test_sampling_due_needs_a_numeric_round():
    assert cond("sampling_due", {"round": None, "rd": {}}) == (False, "round=None（2 周目以降だけ）")


def test_on_stop_keeps_the_unanswered_question_as_a_human_item():
    """人に聞いている最中に止めた run は、答えないまま外した問いを要人間判断（human_items）に残す"""
    import types
    b = types.SimpleNamespace(round=2, record={"convergence": {}, "process": {"human_items": []}})
    info = {"reason": "検査", "unanswered": {"node": "p4.converge", "kinds": ["discrepancy"], "items": ["問い 1"]}}
    assert RULES.on_stop(b, info) is None
    assert b.record["process"]["human_items"] == [{"round": 2, "kinds": ["discrepancy"], "asked": ["問い 1"],
                                                   "answer": "（答えないまま人が止めた: 検査）"}]
    b2 = types.SimpleNamespace(round=1, record={"convergence": {}, "process": {"human_items": []}})
    RULES.on_stop(b2, {"reason": "検査"})
    assert b2.record["process"]["human_items"] == [] and b2.record["convergence"]["outcome"] == "stopped"
