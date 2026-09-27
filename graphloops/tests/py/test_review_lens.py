"""局所レビューの条件付きのレンズ（skills[].applies_cond）——graphcheck の形の縛りと、受け付けの柵
local_review_covers_lenses が engine の評価した applies を読むこと。条件の関数そのものの真偽は simulate_review.py の
条件の真偽表（CONDS を全部覆う表）が、engine が節を出す時点に applies を足すことは同じ台本の test_local_review_lens_rows が持つ"""
import copy
import json

import pytest

from conftest import PLUGIN, REVIEW_GRAPH_PATH, run_graphcheck
from engine.util import Reject
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))
RULES = load_rules(REVIEW_GRAPH_PATH, load_graph(REVIEW_GRAPH_PATH)[0])
NID = "p1.local_review"


def lens(g, name):
    return next(e for e in g["nodes"][NID]["skills"] if e["skill"] == name)


def base_schema(g):
    """出口の節 p0.base の schema はブロックの出口のファイルに在る——壊すために本文を graph に直に戻す"""
    blk = json.loads((PLUGIN / "blocks" / "review-loop" / "prereq" / "exit.schema.json").read_text(encoding="utf-8"))
    g["nodes"]["p0.base"]["schema"] = blk["properties"]["p0.base"]
    return g["nodes"]["p0.base"]["schema"]


def test_graphcheck_accepts_the_shipped_graph(sandbox):
    ok, out = run_graphcheck(sandbox, copy.deepcopy(GRAPH))
    assert ok, out[-300:]


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda g: lens(g, "/security-review").pop("applies_cond"), "対で持つ", id="false-without-cond"),
    pytest.param(lambda g: lens(g, "/simplify").__setitem__("applies_cond", "security_surface_touched"), "対で持つ", id="true-with-cond"),
    pytest.param(lambda g: lens(g, "/security-review").__setitem__("applies_cond", "no_such_cond"), "CONDS の名前でない", id="unknown-cond"),
    pytest.param(lambda g: lens(g, "/security-review").__setitem__("applies_cond", 1), "applies_cond は文字列", id="cond-not-string"),
    pytest.param(lambda g: base_schema(g)["properties"].pop("touches_security_surface"),
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


def _append(g):
    return g["launch"]["append"]


def _receipt(g):
    return g["nodes"]["p3.delta_gates"]["delegate"]


@pytest.mark.parametrize("breaks,want", [
    pytest.param(lambda g: _append(g)[0].__setitem__("to", "everyone"), "launch.append[0] は", id="append-unknown-target"),
    pytest.param(lambda g: _append(g)[0]["files"].append("../prompts/no-such.md"), "no-such.md が無い", id="append-missing-file"),
    pytest.param(lambda g: _append(g)[0]["reads"].remove("record.process.checks"), "段の reads に無い", id="append-hole-not-in-reads"),
    pytest.param(lambda g: _append(g)[0]["files"].append("../prompts/review-loop/request-scope.md"), "段の reads に無い",
                 id="append-request-needs-its-read"),
    pytest.param(lambda g: _receipt(g).__setitem__("receipt", {"lane": 1}), "delegate.receipt は", id="receipt-off-schema"),
    pytest.param(lambda g: _receipt(g).__setitem__("background", False), "delegate.receipt は", id="receipt-without-background"),
])
def test_graphcheck_rejects_append_and_receipt_shapes(sandbox, breaks, want):
    """起こす子の形ごとの段（launch.append）と背景の線の受領の形（delegate.receipt）の静的な検査は、赤くなる例を 1 つずつ持つ"""
    g = copy.deepcopy(GRAPH)
    breaks(g)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and want in out, out[-300:]


def test_graphcheck_rejects_append_hole_off_loop_keys(sandbox):
    """段の穴の loop.<鍵> も節のプロンプトの穴と同じ照らし（LOOP_KEYS と state_schema の木）に通る——段の reads に在っても綴り違いは落ちる"""
    (sandbox / "prompts" / "loop-typo.md").write_text("{{?loop.no_such_key}}\n", encoding="utf-8")
    g = copy.deepcopy(GRAPH)
    _append(g)[0]["files"].append("../prompts/loop-typo.md")
    _append(g)[0]["reads"].append("loop.no_such_key")
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and "launch.append[0]: ../prompts/loop-typo.md の穴" in out and "LOOP_KEYS に無い" in out, out[-300:]


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


@pytest.mark.parametrize("launch_state,handed_back", [
    pytest.param("running", True, id="engine-child-hands-back"),
    pytest.param("ended", False, id="conversation-after-handback-is-accepted"),
    pytest.param(None, False, id="conversation-run-is-accepted"),
])
def test_awaiting_human_from_an_engine_child_goes_back_to_the_conversation(launch_state, handed_back):
    """engine が起こした子が起こせないレンズを awaiting_human で返したら、受け付けずに会話へ返す（HandBack）——人を起こし手にしない。
    会話が返した awaiting_human は今までどおり受け付ける"""
    b = FakeBoard([cond_lens(applies=True, applies_why="w"), UNCOND])
    if launch_state:
        b.rd["instances"][NID].update(launch={"kind": "runner", "skill": True, "on_fail": "handoff"}, launch_state=launch_state)
    out = answer(False, status="awaiting_human")
    if handed_back:
        with pytest.raises(RULES.HandBack, match="/s（理由）"):
            RULES.local_review_covers_lenses(b, NID, out, None)
    else:
        assert RULES.local_review_covers_lenses(b, NID, out, None) is None
    assert RULES.local_review_covers_lenses(b, NID, answer(True), None) is None   # 起こせた返答は子でも受け付ける


def test_fix_record_keeps_the_declarations_the_cond_reads_across_rounds():
    """security_surface_touched は前のどの周の申告も record.process.fixes から読むので、p3.fix の writes がその欄を残す"""
    pick = next(w for w in GRAPH["nodes"]["p3.fix"]["writes"] if w.get("to") == "process.fixes")["pick"]
    assert {"security_surface_changed", "seams_changed"} <= set(pick)
