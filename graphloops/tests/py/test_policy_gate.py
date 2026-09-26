"""人の方針の文書の置き場（rules/policy_input.py）と、人の決定権の関所が人に聞く行（rules/review-loop.py の human_gate の部品）。
関数を直に呼ぶ検査。盤面を回す端から端までの台本は simulate_review.py の test_policy_reaches_roles・test_human_gate"""
import pathlib
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
    return types.SimpleNamespace(state={"inputs": {"cwd": str(tmp_path), "policy_md": named}}, round=1, loop_state={}, dir=tmp_path / "state",
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
    assert got["copy"] == str(tmp_path / "state" / "policy" / f"{got['sha256']}.md") and pathlib.Path(got["copy"]).read_text(encoding="utf-8") == "方針\n"


def test_absent_default_is_none(tmp_path):
    b = board(tmp_path)
    assert PI.resolve(b, git_at(".git"), Reject) == {"path": None, "sha256": None, "copy": None}
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
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": ["X", "Y"]}, "policy_conflicts": ["P", "Q"]}}
    passed = [{"answer": "continue", "asked": ["R4 が BASE から消えたと見た能力: X", "R4 が見た人の方針とのぶつかり: P"]},
              {"answer": "stop", "asked": ["R4 が BASE から消えたと見た能力: Y", "R4 が見た人の方針とのぶつかり: Q"]}]
    got = RULES._r4_gate_items(board(tmp_path, outs=outs, human_items=passed))
    assert got == [("regression", "R4 が BASE から消えたと見た能力: Y"), ("policy", "R4 が見た人の方針とのぶつかり: Q")]


def test_r4_must_answer_policy_conflicts():
    schema = G["nodes"]["r4.hidden_scope"]["schema"]
    assert "policy_conflicts" in schema["required"] and schema["properties"]["policy_conflicts"]["type"] == "array"


def test_change_keeps_copies_and_diff_out_of_row(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("守る 1\n", encoding="utf-8")
    b = board(tmp_path, named="p.md")
    pol = PI.resolve(b, git_at(".git"), Reject)
    assert PI.change(b, git_at(".git"), pol) is None   # 変わっていなければ None
    f.write_text("守る 1\n書き足し BODY-X\n", encoding="utf-8")
    ch = PI.change(b, git_at(".git"), pol)
    assert ch["from"] == pol["sha256"] and ch["to"] != ch["from"] and ch["from_copy"] == pol["copy"]
    assert pathlib.Path(ch["to_copy"]).read_text(encoding="utf-8") == f.read_text(encoding="utf-8")
    assert "+書き足し BODY-X" in pathlib.Path(ch["diff_file"]).read_text(encoding="utf-8")
    row = PI.change_row(ch)
    assert ch["diff_file"] in row and "BODY-X" not in row   # 行は置き場だけ——本文は人の答えの台帳を通って回す側に貼られる


def test_change_without_pinned_copy_does_not_fake_diff(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("今の版\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    ch = PI.change(b, git_at(".git"), {"path": str(f), "sha256": "0" * 64})   # 写しを取らない版で init した盤面
    assert ch["diff_file"] is None and "写し" in ch["diff_missing"]
    ch = PI.change(board(tmp_path, named=str(f)), git_at(".git"), {"path": None, "sha256": None, "copy": None})   # init の時点で文書が無い
    assert "+今の版" in pathlib.Path(ch["diff_file"]).read_text(encoding="utf-8")



def test_human_kinds_are_face_kinds():
    enum = G["nodes"]["p2.plan_review"]["schema"]["properties"]["faces"]["items"]["properties"]["kind"]["enum"]   # load_graph が $ref を展開した形
    assert RULES.HUMAN_FACE_KINDS and set(RULES.HUMAN_FACE_KINDS) <= set(enum)
    # 事前審査だけの語（修正差分のレビューが拒む）も語彙の中で、人に聞く語を含む
    assert set(RULES.HUMAN_FACE_KINDS) <= set(RULES.PLAN_ONLY_FACE_KINDS) <= set(enum)


def test_r4_gate_tolerates_answers_without_asked(tmp_path):
    """人の答えの行に asked が無くても（手で直した記録）、聞く行の突合で落ちない"""
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": ["X"]}}}
    got = RULES._r4_gate_items(board(tmp_path, outs=outs, human_items=[{"answer": "continue"}]))
    assert got == [("regression", "R4 が BASE から消えたと見た能力: X")]


def test_policy_change_without_fixed_policy(tmp_path):
    """記録に方針の固定が無い盤面（方針を足す前に始めた run）でも、今の文書が在れば変化として挙げる"""
    f = tmp_path / "p.md"
    f.write_text("方針\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    b.dir = tmp_path
    ch = RULES._policy_change(b)
    assert (ch["path"], ch["from"], ch["to"]) == (str(f), None, PI.file_sha(str(f)))


def test_human_gate_names_a_policy_file_that_is_gone(tmp_path, monkeypatch):
    """固定した方針の文書が消えた（今の置き場が引けない）なら、置き場を『（無い）』と書いて人に聞く"""
    monkeypatch.setattr(RULES, "git", lambda *a, **k: None)
    b = board(tmp_path)
    b.dir = tmp_path
    b.record["process"]["policy"] = {"path": str(tmp_path / "gone.md"), "sha256": "a" * 64, "amendments": []}
    got = RULES.human_gate(b, "r4.human_gate")
    assert got["decision"] == "ask" and got["ask"]["kinds"] == ["policy_changed"] and len(got["ask"]["items"]) == 1
    assert got["ask"]["items"][0].startswith(f"人の方針の文書 （無い） が固定した版から変わった: sha256 {'a' * 12} → 消えた")


def test_human_gate_answered_without_kinds(tmp_path):
    """kinds の無い問いへの答え: 台帳の kinds は空の一覧で、方針の文書の変化は固定し直さない（policy_changed を聞いていない）"""
    b = board(tmp_path)
    b.record["process"]["policy"] = {"path": None, "sha256": None, "amendments": []}
    b.loop_state["policy_change"] = {"path": "p.md", "from": None, "to": "b" * 64}
    RULES.human_gate_answered(b, {"node": "r4.human_gate", "items": ["行"]}, "continue")
    assert b.record["process"]["human_items"] == [{"round": 1, "kinds": [], "asked": ["行"], "answer": "continue", "note": "",
                                                   "node": "r4.human_gate"}]
    assert b.record["process"]["policy"] == {"path": None, "sha256": None, "amendments": []} and "policy_change" not in b.loop_state
