"""人の方針の文書の置き場（rules/policy_input.py）と、人の決定権の関所が人に聞く行（rules/review-loop.py の human_gate の部品）。
関数を直に呼ぶ検査。盤面を回す端から端までの台本は simulate_review.py の test_policy_reaches_roles・test_human_gate"""
import types

import pytest

from conftest import PLUGIN
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = PLUGIN / "graphs" / "review-loop.json"
G = load_graph(GRAPH)[0]
RULES = load_rules(GRAPH, G)
PI = RULES.policy_input


class Reject(Exception):
    pass


def board(tmp_path, named=None, outs=None, human_items=()):
    return types.SimpleNamespace(state={"inputs": {"cwd": str(tmp_path), "policy_md": named}}, round=1, loop_state={},
                                 record={"process": {"human_items": list(human_items)}},
                                 output_of_round=lambda nid, rnd: (outs or {}).get(nid))


def git_at(common):
    return lambda *a: common + "\n" if a == ("rev-parse", "--git-common-dir") else None


def test_default_is_under_git_common_dir(tmp_path):
    assert PI.default_path(git_at(".git"), tmp_path) == (tmp_path / ".git" / "graphloops" / "policy.md").resolve()
    assert PI.default_path(git_at(str(tmp_path / "main.git")), "/elsewhere") == (tmp_path / "main.git" / "graphloops" / "policy.md").resolve()


def test_default_found_when_present(tmp_path):
    f = tmp_path / ".git" / "graphloops" / "policy.md"
    f.parent.mkdir(parents=True)
    f.write_text("方針\n", encoding="utf-8")
    b = board(tmp_path)
    got = PI.resolve(b, git_at(".git"), Reject)
    assert got["path"] == str(f.resolve()) and len(got["sha256"]) == 64 and b.state["inputs"]["policy_md"] == got["path"]


def test_absent_default_is_none(tmp_path):
    b = board(tmp_path)
    assert PI.resolve(b, git_at(".git"), Reject) == {"path": None, "sha256": None}
    assert PI.resolve(board(tmp_path), lambda *a: None, Reject)["path"] is None   # git の置き場が引けない


def test_named_relative_is_resolved_and_missing_is_rejected(tmp_path):
    (tmp_path / "p.md").write_text("方針\n", encoding="utf-8")
    b = board(tmp_path, named="p.md")
    assert PI.resolve(b, git_at(".git"), Reject)["path"] == str((tmp_path / "p.md").resolve())
    with pytest.raises(Reject):
        PI.resolve(board(tmp_path, named="no/such.md"), git_at(".git"), Reject)


def test_plan_gate_lists_narrows_and_only_human_kinds(tmp_path):
    outs = {"p2.fix_plan": {"plan": [{"narrows": [{"what": "能力 A", "why": "理由"}]}, {"narrows": []}]},
            "p2.plan_review": {"faces": [{"kind": "copy", "key": "写し", "why": "w"}, {"kind": "regression", "key": "後退", "why": "w"},
                                         {"kind": "policy", "key": "方針", "why": "w"}]}}
    got = RULES._plan_gate_items(board(tmp_path, outs=outs))
    assert [k for k, _ in got] == ["regression", "regression", "policy"] and "能力 A" in got[0][1]
    assert RULES._plan_gate_items(board(tmp_path)) == []   # 事前審査が走らなかった周は聞く行が無い


def test_r4_gate_does_not_reask_passed_rows(tmp_path):
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": ["X", "Y"]}}}
    passed = [{"answer": "continue", "asked": ["R4 が BASE から消えたと見た能力: X"]},
              {"answer": "stop", "asked": ["R4 が BASE から消えたと見た能力: Y"]}]
    got = RULES._r4_gate_items(board(tmp_path, outs=outs, human_items=passed))
    assert got == [("regression", "R4 が BASE から消えたと見た能力: Y")]



def test_human_kinds_are_face_kinds():
    """人に聞く語の一覧（rules の HUMAN_FACE_KINDS）は、事前審査の穴の語彙（graph の $defs.face_kind の enum）の空でない部分集合"""
    enum = G["nodes"]["p2.plan_review"]["schema"]["properties"]["faces"]["items"]["properties"]["kind"]["enum"]   # load_graph が $ref を展開した形
    assert RULES.HUMAN_FACE_KINDS and set(RULES.HUMAN_FACE_KINDS) <= set(enum)
    # 事前審査だけの語（修正差分のレビューが拒む）も語彙の中で、人に聞く語を含む
    assert set(RULES.HUMAN_FACE_KINDS) <= set(RULES.PLAN_ONLY_FACE_KINDS) <= set(enum)
