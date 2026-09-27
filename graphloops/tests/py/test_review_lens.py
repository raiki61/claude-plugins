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
    # launch.runner を宣言する graph では、どの節も engine が起こす語を宣言から組める（会話に返す 13 を engine の不具合だけにする）
    pytest.param(lambda g: _receipt(g).pop("receipt"), "背景の任せ先に delegate.receipt が無い", id="background-without-receipt"),
    pytest.param(lambda g: g["launch"].pop("delegate"), "任せ先を持つのに launch.delegate が無い", id="delegate-without-launch"),
    pytest.param(lambda g: g["nodes"]["p4.ci"].pop("delegate"), "engine_run の節に delegate が無い", id="engine-run-without-delegate"),
    pytest.param(lambda g: g["launch"].pop("tooled"), "を起こす launch.tooled が無い", id="role-without-tooled"),
])
def test_graphcheck_rejects_append_and_receipt_shapes(sandbox, breaks, want):
    """起こす子の形ごとの段（launch.append）と背景の線の受領の形（delegate.receipt）と、回し役なしの run で起こす語を組めない節の静的な
    検査は、赤くなる例を 1 つずつ持つ"""
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
    """local_review_covers_lenses と notices が触る面だけ。origin は受け付けが instance に置く返答の出どころ（commands.reply_origin）"""
    def __init__(self, skills, origin=None, rnd=1, outputs=None):
        self.graph = {"nodes": {NID: {"skills": [{k: v for k, v in e.items() if k not in ("applies", "applies_why")} for e in skills]}}}
        self.rd = {"instances": {NID: {"node": NID, "status": "pending", "skills": skills, **({"reply_origin": origin} if origin else {})}}}
        self.round, self.state, self.loop_state = rnd, {}, {"outcome": "converged"}
        self.record = {"process": {}}
        self.outs = outputs or {}

    def output_of_round(self, node, rnd):
        return self.outs.get((node, rnd))


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


@pytest.mark.parametrize("status,t_invoked,want", [
    pytest.param("clean", False, "必須のレンズなのに invoked が true でない", id="required-not-invoked"),
    pytest.param("awaiting_human", True, "awaiting_human にできない", id="awaiting-human"),
    pytest.param("awaiting_human", False, "必須のレンズなのに", id="awaiting-human-and-required-not-invoked"),
    pytest.param("clean", True, None, id="required-invoked"),
])
def test_engine_child_reply_needs_required_lenses_and_no_awaiting_human(status, t_invoked, want):
    """engine が起こした子の返答は、必須のレンズの行に invoked: true を求め、awaiting_human を拒む——拒みは同じ会話への続き（上限で人に渡る）。
    会話に返す手番は持たない。同じ返答を会話が渡したなら、今までどおり受け付ける"""
    out = answer(True, status=status)
    out["findings"][1]["invoked"] = t_invoked
    child = FakeBoard([cond_lens(applies=True, applies_why="w"), UNCOND], origin="engine_child")
    if want:
        with pytest.raises(Reject, match=want):
            RULES.local_review_covers_lenses(child, NID, out, None)
    else:
        assert RULES.local_review_covers_lenses(child, NID, out, None) is None
    conv = FakeBoard([cond_lens(applies=True, applies_why="w"), UNCOND], origin="conversation")
    assert RULES.local_review_covers_lenses(conv, NID, out, None) is None


@pytest.mark.parametrize("applies", [True, False])
def test_engine_child_reply_without_an_optional_lens_is_accepted_and_listed(applies):
    """条件が真の周の条件付きのレンズを engine の子が起こさなかった行は、拒まずに受け付けて記録の unverified_lenses に積み、報告の知らせに
    『未確認のレンズ』として並べる（人の関所の答え 2026-09-27 の 3 周目の条件 3）。受け付け直しても同じ周・同じ節の行は重ならない。
    条件外の周のレンズは積まない"""
    b = FakeBoard([cond_lens(applies=applies, applies_why="w"), UNCOND], origin="engine_child")
    out = answer(False)
    out["findings"][1]["invoked"] = True
    for _ in range(2):
        assert RULES.local_review_covers_lenses(b, NID, out, None) is None
    rows = b.record["process"].get("unverified_lenses")
    assert rows == ([{"round": 1, "node": NID, "skill": "/s", "why": "理由"}] if applies else [])
    assert any(x.startswith("未確認のレンズ r1 /s") for x in RULES.notices(b)) == applies


SIMPLIFY = {"skill": "/simplify", "required": True}


@pytest.mark.parametrize("rnd,outs,accepted", [
    pytest.param(2, {("p1.worktree_before", 2): {"changed_since_prev_round": []}}, True, id="nothing-changed-since-last-round"),
    pytest.param(2, {("p1.worktree_before", 2): {"changed_since_prev_round": ["a.py"]}}, False, id="a-file-changed"),
    pytest.param(2, {("p1.worktree_before", 2): {}}, False, id="change-not-measured"),
    pytest.param(2, {("p1.worktree_before", 2): {"changed_since_prev_round": []}, ("p1.worktree_after", 2): {"snapshot": {}}}, False,
                 id="retaken-in-round"),
    pytest.param(1, {("p1.worktree_before", 1): {"changed_since_prev_round": []}}, False, id="first-round"),
])
def test_engine_child_may_carry_simplify_only_when_engine_sees_no_change(rnd, outs, accepted):
    """/simplify の持ち越し（指示書: 直前の周から対象差分にロジックの変更が無い）は、engine が確かめられる周——周の頭の版が前の周から
    1 ファイルも変わっていない——だけ、engine の子の返答でも受け付ける（人の関所の答え 2026-09-27 の 3 周目の条件 1）"""
    b = FakeBoard([SIMPLIFY], origin="engine_child", rnd=rnd, outputs=outs)
    out = {"material": {"status": "clean"}, "simplify_carried": True,
           "findings": [{"skill": "/simplify", "items": [], "failed": "持ち越し: 前の周から変更なし", "invoked": False}]}
    if accepted:
        assert RULES.local_review_covers_lenses(b, NID, out, None) is None
    else:
        with pytest.raises(Reject, match="持ち越しは"):
            RULES.local_review_covers_lenses(b, NID, out, None)
    with pytest.raises(Reject, match="必須のレンズなのに"):
        RULES.local_review_covers_lenses(b, NID, {**out, "simplify_carried": False}, None)   # 持ち越すと言わない行は起こし直させる


def test_fix_record_keeps_the_declarations_the_cond_reads_across_rounds():
    """security_surface_touched は前のどの周の申告も record.process.fixes から読むので、p3.fix の writes がその欄を残す"""
    pick = next(w for w in GRAPH["nodes"]["p3.fix"]["writes"] if w.get("to") == "process.fixes")["pick"]
    assert {"security_surface_changed", "seams_changed"} <= set(pick)
