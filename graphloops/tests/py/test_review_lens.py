"""局所レビューの条件付きのレンズ（skills[].applies_cond）——graphcheck の形の縛りと、受け付けの柵
local_review_covers_lenses が engine の評価した applies を読むこと。条件の関数そのものの真偽は simulate_review.py の
条件の真偽表（CONDS を全部覆う表）が、engine が節を出す時点に applies を足すことは同じ台本の test_local_review_lens_rows が持つ"""
import copy
import json

import pytest

from conftest import REVIEW_GRAPH_PATH, run_graphcheck
from engine.util import Reject
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))
RULES = load_rules(REVIEW_GRAPH_PATH, load_graph(REVIEW_GRAPH_PATH)[0])
NID = "p1.local_review"


def lens(g, name):
    return next(e for e in g["nodes"][NID]["skills"] if e["skill"] == name)


def test_graphcheck_accepts_the_shipped_graph(sandbox):
    ok, out = run_graphcheck(sandbox, copy.deepcopy(GRAPH))
    assert ok, out[-300:]


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda g: lens(g, "/security-review").pop("applies_cond"), "対で持つ", id="false-without-cond"),
    pytest.param(lambda g: lens(g, "/simplify").__setitem__("applies_cond", "security_surface_touched"), "対で持つ", id="true-with-cond"),
    pytest.param(lambda g: lens(g, "/security-review").__setitem__("applies_cond", "no_such_cond"), "CONDS の名前でない", id="unknown-cond"),
    pytest.param(lambda g: lens(g, "/security-review").__setitem__("applies_cond", 1), "applies_cond は文字列", id="cond-not-string"),
    pytest.param(lambda g: g["nodes"]["p0.base"]["schema"]["properties"].pop("touches_security_surface"),
                 "applies_cond（cond 'security_surface_touched'）", id="cond-reads-undeclared-field"),
    # 評価は消費する節を出す時点なので、その節の祖先に無い節の出力を読む条件は落ちる
    pytest.param(lambda g: lens(g, "/security-review").__setitem__("applies_cond", "purpose_review_due"),
                 "この節の前（deps の推移閉包）に無い", id="cond-reads-non-ancestor"),
    pytest.param(lambda g: (g["nodes"][NID].pop("cond"), g["nodes"][NID].__setitem__("instance_deps", ["p0.base"])),
                 "skills[].applies_cond も", id="with-instance-deps"),
])
def test_graphcheck_rejects_lens_cond_shapes(sandbox, breaks, want):
    g = copy.deepcopy(GRAPH)
    breaks(g)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and want in out, out[-300:]


class FakeBoard:
    """local_review_covers_lenses が触る面だけ"""
    def __init__(self, skills):
        self.graph = {"nodes": {NID: {"skills": [{k: v for k, v in e.items() if k not in ("applies", "applies_why")} for e in skills]}}}
        self.rd = {"instances": {NID: {"node": NID, "status": "pending", "skills": skills}}}


def cond_lens(**kw):
    return {"skill": "/s", "required": False, "applies_cond": "c", **kw}


def answer(invoked, status="clean", **row):
    return {"material": {"status": status},
            "findings": [{"skill": "/s", "items": [], "failed": "理由", **({} if invoked is None else {"invoked": invoked}), **row},
                         {"skill": "/t", "items": [], "failed": "起こしたが所見なし", "invoked": False}]}


UNCOND = {"skill": "/t", "required": True}


@pytest.mark.parametrize("lens_decl,out,rejected", [
    pytest.param(cond_lens(applies=True, applies_why="w"), answer(False), True, id="applies-true-not-invoked"),
    pytest.param(cond_lens(applies=True, applies_why="w"), answer(None), True, id="applies-true-invoked-missing"),
    pytest.param(cond_lens(applies=True, applies_why="w"), answer(True), False, id="applies-true-invoked"),
    pytest.param(cond_lens(applies=False, applies_why="w"), answer(False), False, id="applies-false-not-invoked"),
    # 呼び出しが落ちて人に上げる行は通す（柵が fail-loud の道を塞がない）
    pytest.param(cond_lens(applies=True, applies_why="w"), answer(False, status="awaiting_human"), False, id="applies-true-awaiting-human"),
    # 評価の値が無い instance（engine を差し替える前に出した等）は当てる側に倒す
    pytest.param(cond_lens(), answer(False), True, id="applies-missing-counts-as-true"),
])
def test_covers_lenses_reads_the_evaluated_applies(lens_decl, out, rejected):
    b = FakeBoard([lens_decl, UNCOND])
    if rejected:
        with pytest.raises(Reject, match="invoked が true でない"):
            RULES.local_review_covers_lenses(b, NID, out, None)
    else:
        assert RULES.local_review_covers_lenses(b, NID, out, None) is None


def test_fix_record_keeps_the_declarations_the_cond_reads_across_rounds():
    """security_surface_touched は前のどの周の申告も record.process.fixes から読むので、p3.fix の writes がその欄を残す"""
    pick = next(w for w in GRAPH["nodes"]["p3.fix"]["writes"] if w.get("to") == "process.fixes")["pick"]
    assert {"security_surface_changed", "seams_changed"} <= set(pick)
