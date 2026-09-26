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
