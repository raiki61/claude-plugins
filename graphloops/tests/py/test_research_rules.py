"""research-loop の rules（rules/research-loop.py）の条件の関数を、engine と同じ口（board.run_cond）で直に呼ぶ検査——
形の崩れた欄で落ちない・理由の文が真偽と揃う・条件ごとの真偽表・読了の標本の閾値（S2b で tests/simulate.py の
test_cond_truth_tables・test_threshold_boundaries から移した。対応は MIGRATION.md）。盤面を回す端から端までの台本は
tests/simulate.py と test_sim_research.py"""
import contextlib
import io

import pytest

from conftest import PLUGIN
from engine.board import COND_HEADS, run_cond
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


# --- 条件ごとの真偽表（simulate.py の test_cond_truth_tables から）。文脈を手で組んで engine と同じ口で呼ぶ。期待の "die" は、
# 宣言した欄が default 無しで解決できないと落ちること（偽に倒さない）
def truth(name, ctx):
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return run_cond(name, RULES.CONDS[name], {**{h: {} for h in COND_HEADS}, "round": 1, **ctx})[0]
    except SystemExit:
        return "die"


TRUTH = {
    "constraints_self_written": [({}, False), ({"record": {"constraints": []}}, False),
                                 ({"record": {"constraints": [{"origin": "人"}, {"origin": "surveyor自書"}]}}, True),
                                 ({"record": {"constraints": [{"origin": "人"}]}}, False),
                                 ({"record": {"constraints": {"origin": "surveyor自書"}}}, False)],
    "generation_due": [({}, True), ({"round": 2}, False), ({"round": 2, "loop": {"stuck_hint": True}}, True),
                       ({"round": 2, "loop": {"stuck_hint": False}}, False)],
    "no_new_discrepancies": [({"rd": {"new_discrepancies": 0}}, True), ({"rd": {"new_discrepancies": 2}}, False), ({}, "die")],
    "rederiver_compare_due": [({"rd": {"new_discrepancies": 0}, "out": {"p3.rederiver": {"verdict": "pass"}}}, True),
                              ({"rd": {"new_discrepancies": 0}, "out": {"p3.rederiver": {"verdict": "fail"}}}, False),
                              ({"rd": {"new_discrepancies": 1}}, False), ({"rd": {"new_discrepancies": 0}}, "die")],
    "sampling_due": [({}, False), ({"round": 2, "rd": {"item_counts": {"p1.checker": 0}}}, True),
                     ({"round": 2, "rd": {"item_counts": {"p1.checker": 3}}}, False), ({"round": 2}, "die")],
}


@pytest.mark.small
@pytest.mark.parametrize("name,ctx,want", [pytest.param(n, c, w, id=f"{n}-row{i}")
                                           for n, rows in TRUTH.items() for i, (c, w) in enumerate(rows)])
def test_cond_truth_table(name, ctx, want):
    assert truth(name, ctx) == want


@pytest.mark.small
def test_every_cond_has_a_truth_table():
    assert set(RULES.CONDS) <= set(TRUTH), f"表に無い: {sorted(set(RULES.CONDS) - set(TRUTH))}"


# --- 読了の標本の閾値を、境界の 1 つ内側・ちょうど・1 つ外側で測る（simulate.py の test_threshold_boundaries の①②から。
# ③の扇の項目の大きさは test_engine_parts.py）。どれも閾値から遠い材料しか踏んでいなかったとき、> と >= を取り違えても色が変わらなかった
def usable(n):
    # 相異なる行にする（同じ行が 3 本だと「標本が同じ行に潰れる」別の理由で落ち、下限を測れない）
    return RULES.read_probes("\n\n".join(f"{i}" + "あ" * (n - 1) for i in range(3)))[0]


@pytest.mark.small
def test_line_one_short_of_probe_min_is_not_usable():
    assert not usable(RULES.PROBE_MIN - 1)


@pytest.mark.small
def test_line_exactly_probe_min_is_usable():
    assert usable(RULES.PROBE_MIN)


def outside(head, tail, mid_len=38, n=3):
    """標本に使えない短い行で本文を挟み、射程の外に残る字数を 1 字単位で狙う（本文 120 字・許容 5% ＝ 6 字）"""
    lines = ["あ" * head] + [f"{i}" + "い" * (mid_len - 1) for i in range(n)] + ["う" * tail]
    return RULES.read_probes("\n\n".join(lines))


@pytest.mark.small
def test_outside_exactly_the_allowance_passes():
    probes, why = outside(3, 3)
    assert probes and why is None, why


@pytest.mark.small
def test_outside_one_over_the_allowance_fails_and_says_how_much():
    probes, why = outside(3, 4)
    assert not probes and why and "7 字" in why, why
