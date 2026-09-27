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
    # 段の穴は、当たる節の本文と reads に入って節のプロンプトの検査に通る（段専用の写しの検査は持たない）
    pytest.param(lambda g: _append(g)[0]["reads"].remove("record.process.checks"), "プロンプトの穴 {{record.process.checks}} が reads に無い",
                 id="append-hole-not-in-reads"),
    pytest.param(lambda g: _append(g)[0]["files"].append("../prompts/review-loop/request-scope.md"), "が reads に無い",
                 id="append-request-needs-its-read"),
    pytest.param(lambda g: g["nodes"]["p2.fix_plan"].__setitem__("prompt_append", ["../prompts/policy-path.md"]),
                 "節 p2.fix_plan: prompt_append の ['../prompts/policy-path.md'] は launch.append の段がこの節に当てる", id="append-dup-in-node"),
    pytest.param(lambda g: g["nodes"]["r1.comment_candidates"].__setitem__("prompt_append", ["../prompts/board-files.md"]),
                 "当てうる（別 plugin の役）", id="append-dup-in-other-plugin-node"),
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
    assert not ok and "プロンプトの穴 {{loop.no_such_key}}" in out and "LOOP_KEYS に無い" in out, out[-300:]


def test_graphcheck_holds_the_runner_paste_fence_on_appended_sections(sandbox):
    """回す側の節に本文を貼らない柵は段の穴にも効く——段が当たる回す側の節の本文として同じ検査に通る（段の穴に file: を足すと赤）"""
    (sandbox / "prompts" / "policy-paste-seg.md").write_text("{{?file:record.process.policy.path}}\n", encoding="utf-8")
    g = copy.deepcopy(GRAPH)
    _append(g)[0]["files"].append("../prompts/policy-paste-seg.md")
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and "{{file:record.process.policy.path}} は回す側（writer）の節に書けない" in out, out[-300:]


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
    all_invoked = answer(True)
    all_invoked["findings"][1]["invoked"] = True
    assert RULES.local_review_covers_lenses(b, NID, all_invoked, None) is None   # 起こせた返答は子でも受け付ける


@pytest.mark.parametrize("cond_applies,t_invoked,handed_back", [
    pytest.param(True, False, True, id="required-not-invoked"),
    pytest.param(False, True, False, id="cond-not-applicable-needs-no-invoked"),
    pytest.param(True, True, False, id="all-invoked"),
])
def test_engine_child_hands_back_when_a_lens_that_applies_was_not_invoked(cond_applies, t_invoked, handed_back):
    """engine の子の返答は、当たるレンズ（必須と、条件が真の周の条件付き）の行に invoked: true が無ければ、awaiting_human を書き忘れても
    会話に返す。条件外の周の条件付きのレンズ（失敗欄に『非該当』）には求めない。会話が done で返した返答には今までどおり求めない"""
    b = FakeBoard([cond_lens(applies=cond_applies, applies_why="w"), UNCOND])
    b.rd["instances"][NID].update(launch={"kind": "runner", "skill": True, "on_fail": "handoff"}, launch_state="running")
    out = answer(cond_applies)
    out["findings"][1]["invoked"] = t_invoked
    if handed_back:
        with pytest.raises(RULES.HandBack, match="/t（起こしたが所見なし）"):
            RULES.local_review_covers_lenses(b, NID, out, None)
    else:
        assert RULES.local_review_covers_lenses(b, NID, out, None) is None
    b.rd["instances"][NID]["launch_state"] = "ended"
    assert RULES.local_review_covers_lenses(b, NID, out, None) is None


def test_fix_record_keeps_the_declarations_the_cond_reads_across_rounds():
    """security_surface_touched は前のどの周の申告も record.process.fixes から読むので、p3.fix の writes がその欄を残す"""
    pick = next(w for w in GRAPH["nodes"]["p3.fix"]["writes"] if w.get("to") == "process.fixes")["pick"]
    assert {"security_surface_changed", "seams_changed"} <= set(pick)
