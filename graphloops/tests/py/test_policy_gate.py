"""人の方針の文書の置き場（rules/policy_input.py）と、人の決定権のゲートが人に聞く行（rules/review-loop.py の human_gate の部品）。
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
    return types.SimpleNamespace(state={"inputs": {"cwd": str(tmp_path), "policy_md": named}}, round=1, loop_state={}, dir=tmp_path / "state", graph=G,
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
    outs = {"p2.fix_plan": {"plan": [{"unit_keys": ["u1"], "narrows": [{"what": "能力 A", "why": "理由"}]}, {"unit_keys": ["u2"], "narrows": []}]},
            "p2.plan_review": {"faces": [{"kind": "copy", "key": "写し", "why": "w"}, {"kind": "regression", "key": "後退", "why": "w"},
                                         {"kind": "policy", "key": "方針", "why": "w"}]}}
    got = RULES._plan_gate_items(board(tmp_path, outs=outs))
    assert [k for k, _, _ in got] == ["regression", "regression", "policy"] and "能力 A" in got[0][1]
    assert len({i for _, _, i in got}) == 3 and all(len(i) == 1 and ":" in i[0] for _, _, i in got)
    assert RULES._plan_gate_items(board(tmp_path)) == []   # 事前審査が走らなかった周は聞く行が無い


def asked(b, nid, monkeypatch):
    """human_gate が人に聞く行（素通りなら空）——方針の文書の変化は無く、直す義務の単位も無い盤面として呼ぶ"""
    monkeypatch.setattr(RULES, "git", lambda *a, **k: None)
    monkeypatch.setattr(RULES, "_view", lambda b_, fn: None)
    monkeypatch.setattr(RULES, "_owed_units", lambda v: set())
    b.record.setdefault("units", [])
    b.dir = b.dir.parent
    got = RULES.human_gate(b, nid)
    return got["ask"]["items"] if got.get("decision") == "ask" else []


def rows(*texts):
    return [{"text": t} for t in texts]


def test_r4_gate_does_not_reask_passed_rows(tmp_path, monkeypatch):
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": rows("X", "Y")}, "policy_conflicts": rows("P", "Q")}}
    rid = lambda field, x: RULES._gate_row_id("r4", field, x)   # noqa: E731
    passed = [{"answer": "continue", "asked": ["R4 が BASE から消えたと見た能力: X", "R4 が見た人の方針とのぶつかり: P"],
               "asked_ids": [rid("lost", "X"), rid("policy_conflicts", "P")]},
              {"answer": "stop", "asked": ["R4 が BASE から消えたと見た能力: Y", "R4 が見た人の方針とのぶつかり: Q"],
               "asked_ids": [rid("lost", "Y"), rid("policy_conflicts", "Q")]}]
    got = asked(board(tmp_path, outs=outs, human_items=passed), "r4.human_gate", monkeypatch)
    assert got == ["R4 が BASE から消えたと見た能力: Y", "R4 が見た人の方針とのぶつかり: Q"]


def test_answers_without_ids_are_asked_again(tmp_path, monkeypatch):
    """ID を持たない旧い盤面の答え（asked_ids の無い行）は本文で照合せず、もう一度聞く（聞き直すのが安全側）"""
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": rows("X")}}}
    legacy = [{"answer": "continue", "asked": ["R4 が BASE から消えたと見た能力: X"]}]
    assert asked(board(tmp_path, outs=outs, human_items=legacy), "r4.human_gate", monkeypatch) == ["R4 が BASE から消えたと見た能力: X"]


def test_r4_rows_of_the_old_string_form_are_asked_not_crashed(tmp_path, monkeypatch):
    """前の版の R4 の返答（行が文字列。周の途中で版を上げた盤面）は same_as の無い行として読み、落ちずに聞く"""
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": ["X"]}, "policy_conflicts": ["P"]}}
    assert asked(board(tmp_path, outs=outs), "r4.human_gate", monkeypatch) == ["R4 が BASE から消えたと見た能力: X",
                                                                               "R4 が見た人の方針とのぶつかり: P"]


def test_gate_rows_passed_once_are_not_reasked_in_any_round_or_gate(tmp_path, monkeypatch):
    """人が continue で一度通した行は、周とゲートを問わず聞き直さない（人のゲート round 2 の答え）——出どころの ID（修正案の狭めは単位と
    what、事前審査の穴は語と key）が同じなら言い回し（why・本文）が変わっても聞かず、R4 が same_as で同じ行と名指した行も聞かない。
    what が変わった狭め・key が変わった穴は新しい行として聞く"""
    plan = {"p2.fix_plan": {"plan": [{"unit_keys": ["u1"], "narrows": [{"what": "能力 A", "why": "理由"}]}]},
            "p2.plan_review": {"faces": [{"kind": "regression", "key": "k: 含む", "why": "後退の本文"}]}}
    b1 = board(tmp_path, outs=plan)
    first = asked(b1, "p2.human_gate", monkeypatch)
    assert first == ["修正案 1 が狭める能力: 能力 A——理由", "事前審査の穴 [regression] 「k: 含む」: 後退の本文"]
    ph = {"node": "p2.human_gate", **RULES.human_gate(b1, "p2.human_gate")["ask"]}
    RULES.human_gate_answered(b1, ph, "continue")
    items = b1.record["process"]["human_items"]
    assert items[0]["asked_ids"] == [i[0] for _, _, i in RULES._plan_gate_items(b1)] and len(set(items[0]["asked_ids"])) == 2
    later = {"p2.fix_plan": {"plan": [{"unit_keys": ["u1"], "narrows": [{"what": "能力 A", "why": "言い換えた理由"},
                                                                         {"what": "能力 B", "why": "新しい理由"}]},
                                      {"unit_keys": ["u2"], "narrows": [{"what": "能力 A", "why": "理由"}]}]},
             "p2.plan_review": {"faces": [{"kind": "regression", "key": "k: 含む", "why": "言い換えた本文"},
                                          {"kind": "policy", "key": "別の穴", "why": "w"}]}}
    b2 = board(tmp_path, outs=later, human_items=items)
    b2.round = 2
    # 本文が同じでも単位の違う狭めは別の中身——聞く
    assert asked(b2, "p2.human_gate", monkeypatch) == ["修正案 1 が狭める能力: 能力 B——新しい理由", "修正案 2 が狭める能力: 能力 A——理由",
                                                       "事前審査の穴 [policy] 「別の穴」: w"]
    a, f = items[0]["asked_ids"]
    r4 = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": [{"text": "能力 A——理由", "same_as": a},
                                                                              {"text": "後退の本文", "same_as": f}, {"text": "新しい"}]}}}
    assert asked(board(tmp_path, outs=r4, human_items=items), "r4.human_gate", monkeypatch) == ["R4 が BASE から消えたと見た能力: 新しい"]


def test_r4_rows_naming_rows_passed_before_the_fix_are_not_reasked(tmp_path, monkeypatch):
    """R4 が修正前のゲートで人が通した狭め・穴と同じ能力を見たら、その行の ID を same_as で返す——人が通した ID なら聞かない（人のゲート
    round 2 の r4.human_gate の答え: ここで再掲されること自体が後退）。人が通していない ID・知らない ID を名指しても聞く（安全側）"""
    plan = {"p2.fix_plan": {"plan": [{"unit_keys": ["u1"], "narrows": [{"what": "能力 A——途中に区切り", "why": "理由"}]}]},
            "p2.plan_review": {"faces": [{"kind": "regression", "key": "k", "why": "後退の本文"}]}}
    b1 = board(tmp_path, outs=plan)
    ph = {"node": "p2.human_gate", **RULES.human_gate(b1, "p2.human_gate")["ask"]} if asked(b1, "p2.human_gate", monkeypatch) else None
    RULES.human_gate_answered(b1, ph, "continue")
    a, f = b1.record["process"]["human_items"][0]["asked_ids"]
    lost = [{"text": "修正案 1 の狭めと同じ", "same_as": a}, {"text": "事前審査の穴と同じ", "same_as": f}, {"text": "知らない ID", "same_as": "face:x"},
            {"text": "新しく消えた能力"}]
    b2 = board(tmp_path, outs={**plan, "r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": lost}}},
               human_items=b1.record["process"]["human_items"])
    assert asked(b2, "r4.human_gate", monkeypatch) == ["R4 が BASE から消えたと見た能力: 知らない ID", "R4 が BASE から消えたと見た能力: 新しく消えた能力"]
    ph = {"node": "r4.human_gate", **RULES.human_gate(b2, "r4.human_gate")["ask"]}
    RULES.human_gate_answered(b2, ph, "continue")
    b3 = board(tmp_path, outs={**plan, "r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": lost}}},
               human_items=b2.record["process"]["human_items"])
    b3.round = 2
    assert asked(b3, "r4.human_gate", monkeypatch) == []   # 後の周も、同じ行は聞き直さない


WHAT = "入れ子の場で書くノードを会話に返す"


def _named(tmp_path, ref, source="gate_answer", unit="u1", request="", findings=(), what=WHAT):
    plan = {"p2.fix_plan": {"plan": [{"unit_keys": ["u1"], "narrows": [{"what": WHAT, "why": "人が名指した道", "named": "n1"}]}]},
            "p2.diagnose": {"named_narrowings": [{"key": "n1", "unit_key": unit, "what": what, "source": source, "ref": ref}]}}
    b = board(tmp_path, outs=plan, human_items=[{"round": 1, "node": "p2.human_gate", "answer": "continue", "asked": ["別の行"],
                                                 "asked_ids": ["face:passed"]},
                                                {"round": 1, "node": "r4.human_gate", "answer": "stop", "asked": ["止めた行"],
                                                 "asked_ids": ["r4:stopped"]}])
    b.round = 2
    b.state["inputs"]["request"] = request
    b.record["process"]["request_findings"] = [{"origin": "add --reason の自由文", "findings": [{"text": t} for t in findings]}]
    return b


@pytest.mark.parametrize("ref,source,unit,req,findings,what,passes", [
    pytest.param("gate:face:passed", "gate_answer", "u1", "", (), WHAT, True, id="gate-answer-row-passed"),
    pytest.param("gate:r4:stopped", "gate_answer", "u1", "", (), WHAT, False, id="gate-answer-row-stopped"),
    pytest.param("gate:face:unknown", "gate_answer", "u1", "", (), WHAT, False, id="gate-answer-row-not-asked"),
    pytest.param("gate:r1:p2.human_gate", "gate_answer", "u1", "", (), WHAT, False, id="gate-answer-by-round-and-node-only"),
    pytest.param("request:入れ子の場は会話に返してよい", "request", "u1", "…入れ子の場は会話に返してよい。", (), WHAT, True, id="request-quote"),
    pytest.param("request:入れ子の場は会話に返してよい", "request", "u1", "", ("入れ子の場は会話に返してよい",), WHAT, False,
                 id="quote-only-in-an-added-batch"),
    pytest.param("request:返してよい", "request", "u1", "返してよい", (), WHAT, False, id="quote-too-short"),
    pytest.param("gate:face:passed", "gate_answer", "u9", "", (), WHAT, False, id="named-for-another-unit"),
    pytest.param("gate:face:passed", "gate_answer", "u1", "", (), "入れ子の場で書くノードを 13 で返す", False, id="named-what-differs"),
])
def test_named_narrowing_passes_only_when_the_judge_bound_it_to_the_owner(tmp_path, monkeypatch, ref, source, unit, req, findings, what,
                                                                          passes):
    """名指しと判じるのは判定役（p2.diagnose の named_narrowings）で、修正案は key を指し、名指しの what を字面のまま写す——機械は中身
    （what と単位）と出どころ（init の依頼の本文の 10 字以上の引用・人が continue で答えたゲートの行の ID）が結ばれていることを確かめる。
    add の一括（機械の線・ツールも積む）は持ち主の本文に数えない。通した狭めは聞かずに記録の gate_named_passes に残り、報告の知らせに
    並ぶ。結べない狭めは今どおり聞く（人のゲート round 2 の条件 4）"""
    b = _named(tmp_path, ref, source, unit, req, findings, what)
    got = asked(b, "p2.human_gate", monkeypatch)
    assert (got == []) == passes
    rows = b.record["process"].get("gate_named_passes") or []
    assert (len(rows) == 1 and rows[0]["named"]["ref"] == ref and "修正案 1" in rows[0]["row"]) == passes
    if passes:
        b.loop_state = {}
        b.state["notes"] = []
        assert any("聞かずに通した狭め" in n and ref in n for n in RULES.notices(b))


def test_r4_must_answer_policy_conflicts():
    schema = G["nodes"]["r4.hidden_scope"]["schema"]
    assert "policy_conflicts" in schema["required"] and schema["properties"]["policy_conflicts"]["type"] == "array"


def test_change_keeps_copies_and_diff_out_of_row(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("守る 1\n", encoding="utf-8")
    b = board(tmp_path, named="p.md")
    pol = PI.resolve(b, git_at(".git"), Reject)
    assert PI.change(b, git_at(".git"), pol) is None
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


def test_record_change_sets_and_clears(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("守る 1\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    proc = {"policy_change": {"stale": True}}   # policy を持たない proc は、方針の版を記録する前に init した盤面
    PI.record_change(b, git_at(".git"), proc)
    assert proc == {}
    proc = {"policy": PI.resolve(b, git_at(".git"), Reject)}
    f.write_text("守る 1\n書き足し\n", encoding="utf-8")
    PI.record_change(b, git_at(".git"), proc)
    assert proc["policy_change"]["from"] == proc["policy"]["sha256"]
    f.write_text("守る 1\n", encoding="utf-8")
    PI.record_change(b, git_at(".git"), proc)
    assert "policy_change" not in proc



def test_human_kinds_are_face_kinds():
    enum = G["nodes"]["p2.plan_review"]["schema"]["properties"]["faces"]["items"]["properties"]["kind"]["enum"]   # load_graph が $ref を展開した形
    assert RULES.HUMAN_FACE_KINDS and set(RULES.HUMAN_FACE_KINDS) <= set(enum)
    assert set(RULES.HUMAN_FACE_KINDS) <= set(RULES.PLAN_ONLY_FACE_KINDS) <= set(enum)


def test_r4_gate_tolerates_answers_without_asked(tmp_path, monkeypatch):
    """人の答えの行に asked が無くても（手で直した記録）、聞く行の突合で落ちない"""
    outs = {"r4.hidden_scope": {"capability_inventory": {"fired": True, "lost": rows("X")}}}
    got = asked(board(tmp_path, outs=outs, human_items=[{"answer": "continue"}]), "r4.human_gate", monkeypatch)
    assert got == ["R4 が BASE から消えたと見た能力: X"]


def test_policy_change_without_fixed_policy(tmp_path):
    """記録に方針の固定が無い盤面（方針を足す前に始めた run）でも、今の文書が在れば変化として挙げる"""
    f = tmp_path / "p.md"
    f.write_text("方針\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    b.dir = tmp_path
    ch = RULES.policy_input.change(b, RULES.git, b.record["process"].get("policy") or {})
    assert (ch["path"], ch["from"], ch["to"]) == (str(f), None, PI.file_sha(str(f)))


def test_human_gate_names_a_policy_file_that_is_gone(tmp_path, monkeypatch):
    """固定した方針の文書が消えたなら、消えた置き場を名指して人に聞く"""
    monkeypatch.setattr(RULES, "git", lambda *a, **k: None)
    b = board(tmp_path)
    b.dir = tmp_path
    b.record["process"]["policy"] = {"path": str(tmp_path / "gone.md"), "sha256": "a" * 64, "amendments": []}
    got = RULES.human_gate(b, "r4.human_gate")
    assert got["decision"] == "ask" and got["ask"]["kinds"] == ["policy_changed"] and len(got["ask"]["items"]) == 1
    assert got["ask"]["items"][0].startswith(f"人の方針の文書 {tmp_path / 'gone.md'} が固定した版から変わった: sha256 {'a' * 12} → 消えた")


def test_human_gate_answered_without_kinds(tmp_path):
    """kinds の無い問いへの答え: 台帳の kinds は空の一覧で、方針の文書の変化は固定し直さない（policy_changed を聞いていない）"""
    b = board(tmp_path)
    b.record["process"]["policy"] = {"path": None, "sha256": None, "amendments": []}
    b.loop_state["policy_change"] = {"path": "p.md", "from": None, "to": "b" * 64}
    RULES.human_gate_answered(b, {"node": "r4.human_gate", "items": ["行"]}, "continue")
    assert b.record["process"]["human_items"] == [{"round": 1, "kinds": [], "asked": ["行"], "asked_ids": [RULES._gate_row_id("policy", "行")],
                                                   "answer": "continue", "note": "", "node": "r4.human_gate"}]
    assert b.record["process"]["policy"] == {"path": None, "sha256": None, "amendments": []} and "policy_change" not in b.loop_state


def test_file_sha_without_a_path_is_none():
    """置き場の無い（None・空の）方針の文書は sha を持たない——パスを作って開きに行かない"""
    assert PI.file_sha(None) is None and PI.file_sha("") is None


def test_change_row_names_both_copies():
    """ゲートの行は、前の版と今の版の写しの置き場を名指す（無い側だけ『（無い）』）"""
    row = PI.change_row({"path": "p.md", "from": "a" * 64, "to": "b" * 64, "from_copy": "/x/old.md", "to_copy": None,
                         "diff_file": "/x/d.diff"})
    assert "前の版の写し /x/old.md" in row and "今の版の写し （無い）" in row and "差分 /x/d.diff" in row


def test_gate_answer_keeps_inputs_and_watches_the_amended_path(tmp_path):
    """ゲートで方針の文書の変更を通しても run の入力（inputs.policy_md）は init のまま——通した置き場は記録（process.policy）と
    その amendments にだけ残り、以後の見張り（change）はそこから引く。消えた文書を通した後は既定の置き場を見張る"""
    f = tmp_path / "p.md"
    f.write_text("前の版\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    b.record["process"]["policy"] = {**PI.resolve(b, git_at(".git"), Reject), "amendments": []}
    f.write_text("通す版\n", encoding="utf-8")
    ch = PI.change(b, git_at(".git"), b.record["process"]["policy"])
    b.loop_state["policy_change"] = ch
    RULES.human_gate_answered(b, {"node": "r4.human_gate", "kinds": ["policy_changed"], "items": ["行"]}, "continue")
    pol = b.record["process"]["policy"]
    assert b.state["inputs"]["policy_md"] == str(f.resolve()) and pol["sha256"] == ch["to"] and len(pol["amendments"]) == 1
    assert PI.change(b, git_at(".git"), pol) is None   # 通した版を見張る——同じ中身なら変化なし
    f.unlink()
    gone = PI.change(b, git_at(".git"), pol)
    b.loop_state["policy_change"] = gone
    RULES.human_gate_answered(b, {"node": "r4.human_gate", "kinds": ["policy_changed"], "items": ["行"]}, "continue")
    assert b.state["inputs"]["policy_md"] == str(f.resolve()) and pol["sha256"] is None and pol["path"] is None and pol["copy"] is None
    assert PI.watched(b, git_at(".git"), pol) is None


def test_gone_policy_reaches_roles_as_absent(tmp_path):
    """消えた方針の文書をゲートで通した後、役へ渡す方針の段（policy-paste の穴）は『読めない』でなく『（この周には無い）』で埋まる
    ——見張る先と渡す先が同じ pol の path を読む"""
    from engine.render import ABSENT, Renderer
    f = tmp_path / "p.md"
    f.write_text("前の版\n", encoding="utf-8")
    b = board(tmp_path, named=str(f))
    b.record["process"]["policy"] = {**PI.resolve(b, git_at(".git"), Reject), "amendments": []}
    f.unlink()
    b.loop_state["policy_change"] = PI.change(b, git_at(".git"), b.record["process"]["policy"])
    RULES.human_gate_answered(b, {"node": "r4.human_gate", "kinds": ["policy_changed"], "items": ["行"]}, "continue")
    hole = (PLUGIN / "prompts" / "policy-paste.md").read_text(encoding="utf-8")
    out = Renderer({"record": b.record}, ["record.process.policy.path"]).render(hole)
    assert ABSENT in out and "読めない" not in out
