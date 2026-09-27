"""外の土台から規則を呼ぶ口（scripts/gl.py）: 本物の盤面を読んで規則の関数を呼び、JSON 1 行を返す。盤面にも作業ツリーにも書かない。
拒否も終了コード 0 で返し、読めないときだけ 2（試作 gl_accept.py と同じ約束）。周は盤面の周で、前の周の出力も読む。
gl accept は done と同じ検査の鎖（engine の commands.check_reply）を通す——done が拒む返答は gl も拒む。"""
import copy
import json
import shutil
import subprocess
import sys

import pytest

from conftest import PLUGIN, REPO, REVIEW_GRAPH_PATH
from engine import commands
from engine.board import Board
from engine.util import AnswerReject, Reject
from test_hist import make, rd

GL = PLUGIN / "scripts" / "gl.py"
UNITS = [{"key": "u1", "label": "block", "disposition": "do-now", "reason": "r"}]


def gl(*args):
    r = subprocess.run([sys.executable, str(GL), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


def files(d):
    return {p.relative_to(d).as_posix(): p.stat().st_mtime_ns for p in d.rglob("*") if p.is_file()}


def round2(tmp_path):
    outs = {("p2.plan_review", 2): {"faces": [{"key": "穴", "kind": "copy", "unit_keys": ["u1"], "why": "w"}]},
            ("p2.fix_plan", 1): {"plan": [{"unit_keys": ["前の周"]}]}}
    return make(tmp_path, 2, [rd(1), rd(2)], outs=outs,
                record={"materials": {}, "units": UNITS, "questions": [], "reviews": {}, "scalars": {}, "process": {}})


def test_cond_reads_the_board_round(tmp_path):
    b = round2(tmp_path)
    code, got = gl("cond", "--dir", b.dir, "--name", "after_first_round")
    assert code == 0 and got["ok"] and got["value"] is True and got["why"]
    assert gl("cond", "--dir", b.dir, "--name", "units_open")[1]["value"] is True


def test_accept_calls_new_form_checks_in_round_two_without_writing(tmp_path):
    b = round2(tmp_path)
    before = files(b.dir)
    good = tmp_path / "plan.json"
    good.write_text(json.dumps({"plan": [{"unit_keys": ["u1"], "approach": "a" * 20, "adds": [], "removes": [],
                                          "shrink_first": "s" * 20, "narrows": []}]}), encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p2.fix_plan", "--reply", good)
    assert code == 0 and got["ok"] and got["called"] and got["form"] == "new" and got["effects"] == []
    assert got["pending"] is False   # 1 周目の instance しか無い——照らせるが、done が今受け付ける instance は無い
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"plan": [{**json.loads(good.read_text())["plan"][0], "unit_keys": ["前の周"]}]}), encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p2.fix_plan", "--reply", bad)
    assert code == 0 and got["ok"] is False and "今の周に直す単位に無い key" in got["reason"]
    notjson = tmp_path / "x.json"
    notjson.write_text("読めない返答", encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p2.fix_plan", "--reply", notjson)
    assert code == 0 and got["ok"] is False
    assert files(b.dir) == before   # 盤面の置き場に何も書いていない


def test_accept_does_not_call_legacy_checks(tmp_path):
    b = round2(tmp_path)
    reply = tmp_path / "j.json"
    reply.write_text("{}", encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p2.diagnose", "--reply", reply)
    assert code == 0 and got["called"] is False and got["form"] == "legacy"


def test_machine_calls_new_form_builtins_only(tmp_path):
    b = round2(tmp_path)
    rv = {"faces": [{"key": "k", "kind": "copy", "where": "a.py", "cite": "c", "why": "w"}], "checks": []}
    b2 = make(tmp_path / "m", 2, [rd(1), rd(2)], outs={("p3.delta_review", 2): rv})
    code, got = gl("machine", "--dir", b2.dir, "--node", "p3.delta_owed")
    assert code == 0 and got["called"] and got["out"]["owed"] == 1 and got["out"]["rows"][0]["key"] == "k"
    code, got = gl("machine", "--dir", b.dir, "--node", "p1.worktree_before")
    assert code == 0 and got["called"] is False and got["form"] == "legacy"


def test_exit_gives_the_node_schema_and_compares_a_copy(tmp_path):
    code, got = gl("exit", "--graph", REVIEW_GRAPH_PATH, "--node", "p2.fix_plan")
    assert code == 0 and got["ok"] and got["schema"]["required"] == ["plan"]
    same = tmp_path / "same.json"
    same.write_text(json.dumps(got["schema"]), encoding="utf-8")
    assert gl("exit", "--graph", REVIEW_GRAPH_PATH, "--node", "p2.fix_plan", "--against", same) == (0, {"ok": True, "diffs": []})
    other = copy.deepcopy(got["schema"])
    other["required"] = []
    same.write_text(json.dumps(other), encoding="utf-8")
    code, got = gl("exit", "--graph", REVIEW_GRAPH_PATH, "--node", "p2.fix_plan", "--against", same)
    assert code == 0 and got["ok"] is False and got["diffs"] and got["diffs"][0].startswith("$.required")


def test_unreadable_inputs_exit_2(tmp_path):
    assert gl("cond", "--dir", tmp_path / "nothing", "--name", "units_open")[0] == 2
    b = round2(tmp_path)
    assert gl("cond", "--dir", b.dir, "--name", "no_such_cond")[0] == 2
    assert gl("accept", "--dir", b.dir, "--node", "p2.fix_plan", "--reply", tmp_path / "missing.json")[0] == 2


# ---------------------------------------------------------------- done と同じ鎖（3-6 の 1 本目の gl は空・被覆・段を写し落としていた）
RESEARCH_GRAPH_PATH = PLUGIN / "graphs" / "research-loop.json"
QUESTION = {"question": "q", "domain": "d", "constraints": [{"text": "t", "source": "s", "origin": "独立出典", "breaks_if_false": "b"}],
            "thickness": "軽量", "thickness_decider": "既定", "thickness_reason": "r"}
FINDING = lambda cid: {"id": cid, "verdict": "確証", "evidence": "e", "sources": ["https://example.org"], "conditions": "c"}   # noqa: E731


def pending(nid, iid=None, item=None):
    return {"id": iid or nid, "node": nid, "status": "pending", **({"item": item} if item is not None else {})}


def research_board(tmp_path, instances, thickness=None):
    b = make(tmp_path, 1, [rd(1, done=("p0.clusters", "p0.terms", "p0.generation"), instances=instances)], graph=RESEARCH_GRAPH_PATH,
             record={"materials": {}, "claims": [{"id": c} for c in ("a1", "a2", "b1", "b2")], "clusters": [], "gates": {}, "process": {}})
    st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
    st.update({"validator": str(REPO / "scripts" / "research-record.py"), "loop_name": "research-loop", "thickness": thickness})
    (b.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return Board(b.dir)


def done_says(tmp_path, b, iid, text):
    """同じ返答を loop.py done の中身（accept_output）に盤面の写しで当てる ——（ok, 拒否の文）"""
    d = tmp_path / "done-copy"
    shutil.copytree(b.dir, d)
    try:
        commands.accept_output(Board(d), iid, text, "検査")
        return True, ""
    except (AnswerReject, Reject) as e:
        return False, str(e)


CASES = {
    # 本文を返す節の空の返答（schema の無い節）
    "empty_text": (lambda t: make(t, 1, [rd(1, done=("report.cold_check",), instances={"report": pending("report")})]),
                   "report", "   \n", "返答が空"),
    # 扇の項目に無い鍵（instance の id で指す）
    "cover_extra": (lambda t: research_board(t, {"p1.checker[c]": pending("p1.checker", "p1.checker[c]", {"key": "c", "claims": [{"id": "a"}]})}),
                    "p1.checker[c]", json.dumps({"cluster": "c", "findings": [FINDING("z")]}), "項目に無い id"),
    # 段の降格
    "downgrade": (lambda t: research_board(t, {"p0.question": pending("p0.question")}, thickness="重厚"),
                  "p0.question", json.dumps(QUESTION, ensure_ascii=False), "下げようとしている"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_accept_refuses_what_done_refuses(tmp_path, case):
    build, target, text, words = CASES[case]
    b = build(tmp_path / "b")
    reply = tmp_path / "reply.txt"
    reply.write_text(text, encoding="utf-8")
    before = files(b.dir)
    code, got = gl("accept", "--dir", b.dir, "--node", target, "--reply", reply)
    ok, why = done_says(tmp_path, b, target, text)
    assert code == 0 and got["ok"] is False and words in got["reason"]
    assert ok is False and words in why
    assert files(b.dir) == before


def test_accept_takes_the_instance_id_for_fan_out_items(tmp_path):
    """扇の節は同じ節に instance が並ぶ——instance の id で指せばその項目で照らす（節の id だと最後の instance の項目になる）。
    --item は外から項目を渡す口のまま残る"""
    b = research_board(tmp_path / "b", {
        "p1.checker[a]": pending("p1.checker", "p1.checker[a]", {"key": "a", "claims": [{"id": "a1"}]}),
        "p1.checker[b]": pending("p1.checker", "p1.checker[b]", {"key": "b", "claims": [{"id": "b1"}, {"id": "b2"}]})})
    reply = tmp_path / "r.json"
    reply.write_text(json.dumps({"cluster": "a", "findings": [FINDING("a1")]}), encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p1.checker[a]", "--reply", reply)
    assert code == 0 and got["ok"] and got["pending"] is True and "remaining" not in got
    assert done_says(tmp_path, b, "p1.checker[a]", reply.read_text(encoding="utf-8"))[0] is True
    code, got = gl("accept", "--dir", b.dir, "--node", "p1.checker", "--reply", reply)   # 節の id は最後の instance（b）の項目で照らす
    assert code == 0 and got["ok"] is False and "項目に無い id" in got["reason"]
    item = tmp_path / "item.json"
    item.write_text(json.dumps({"key": "a", "claims": [{"id": "a1"}, {"id": "a2"}]}), encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p1.checker", "--reply", reply, "--item", item)
    assert code == 0 and got["ok"] and got["remaining"] == ["a2"]   # done なら欠けた分を出し直す項目


def test_accept_applies_effects_to_the_copy_before_the_record_check(tmp_path, monkeypatch, capsys):
    """節ごとの整合が返した effects は、写しの loop に当ててから記録の整合を見る（done と同じ順）。盤面には書かない"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gl_mod", PLUGIN / "scripts" / "gl.py")
    glm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(glm)
    b = round2(tmp_path)
    seen = {}
    eff = [{"to": "loop.outcome", "reducer": "overwrite", "value": "stopped"}]
    monkeypatch.setitem(b.rules.POST_CHECKS, b.nodes["p2.fix_plan"]["post_check"],
                        b.rules.cond_reads()(lambda v, *a: {"ok": True, "effects": eff}))
    monkeypatch.setattr(b.rules, "check_record", lambda bb, nid: seen.setdefault("loop", dict(bb.loop_state)) and [])
    monkeypatch.setattr(glm, "board", lambda d: b)
    before = files(b.dir)
    reply = tmp_path / "plan.json"
    reply.write_text(json.dumps({"plan": [{"unit_keys": ["u1"], "approach": "a" * 20, "adds": [], "removes": [],
                                           "shrink_first": "s" * 20, "narrows": []}]}), encoding="utf-8")
    assert glm.main(["accept", "--dir", str(b.dir), "--node", "p2.fix_plan", "--reply", str(reply)]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["ok"] and got["effects"] == eff and seen["loop"] == {"outcome": "stopped"} and files(b.dir) == before


def test_accept_names_whether_the_check_was_reached(tmp_path):
    """form は節の宣言で決まり、called は節ごとの整合まで届いたか——型で落ちた返答は呼んでいない"""
    b = round2(tmp_path)
    reply = tmp_path / "x.json"
    reply.write_text("{}", encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "p2.fix_plan", "--reply", reply)
    assert code == 0 and got["ok"] is False and got["form"] == "new" and got["called"] is False


def test_request_applies_add_to_a_copy(tmp_path):
    """loop.py add と同じ rules の add を盤面の写しに当て、積んだ後の依頼の一覧を返す（盤面には積まない）"""
    b = make(tmp_path, 1, [rd(1)])
    before = files(b.dir)
    req = tmp_path / "req.json"
    req.write_text(json.dumps([{"where": "a.py", "text": "直して"}], ensure_ascii=False), encoding="utf-8")
    code, got = gl("request", "--dir", b.dir, "--file", req, "--reason", "人")
    assert code == 0 and got["ok"] and got["request_findings"][-1]["findings"][0]["where"] == "a.py" and got["note"]
    req.write_text(json.dumps([{"where": "a.py"}]), encoding="utf-8")
    code, got = gl("request", "--dir", b.dir, "--file", req, "--reason", "人")
    assert code == 0 and got["ok"] is False and "add の形" in got["reason"]
    assert files(b.dir) == before


def test_exit_strips_the_note_keyword_but_keeps_fields_named_note(tmp_path):
    from engine.schema import strip_notes
    code, raw = gl("exit", "--graph", REVIEW_GRAPH_PATH, "--node", "p2.diagnose")
    code2, got = gl("exit", "--graph", REVIEW_GRAPH_PATH, "--node", "p2.diagnose", "--strip-notes")
    cq = lambda sch: sch["properties"]["units"]["items"]["properties"]["class_query"]   # noqa: E731
    assert code == code2 == 0 and got["schema"] == strip_notes(raw["schema"])
    assert "note" in cq(raw["schema"]) and "note" not in cq(got["schema"])            # 注記の語は落ちる
    assert "note" in cq(got["schema"])["properties"]                                   # note という名前の欄は残る


def test_accept_upgrading_the_tier_writes_nothing_beside_the_board(tmp_path):
    """段の昇格は写しの盤面にだけ当たる——昇格の痕跡（trace.jsonl の行）も盤面の置き場に書かない"""
    b = research_board(tmp_path / "b", {"p0.question": pending("p0.question")}, thickness="軽量")
    reply = tmp_path / "q.json"
    reply.write_text(json.dumps({**QUESTION, "thickness": "重厚"}, ensure_ascii=False), encoding="utf-8")
    before = files(b.dir)
    code, got = gl("accept", "--dir", b.dir, "--node", "p0.question", "--reply", reply)
    assert code == 0 and got["ok"] and files(b.dir) == before


def test_pending_says_whether_done_could_take_it_now(tmp_path):
    """pending は engine の門（accept_gate）を通るか——deps が未了・止めた run なら done は拒むので偽"""
    full = {"materials": {}, "units": [], "questions": [], "reviews": {}, "scalars": {}, "process": {}}
    b = make(tmp_path / "w", 1, [rd(1, instances={"report": pending("report")})], record=full)
    reply = tmp_path / "r.md"
    reply.write_text("報告", encoding="utf-8")
    code, got = gl("accept", "--dir", b.dir, "--node", "report", "--reply", reply)
    assert code == 0 and got["pending"] is False and "deps" in done_says(tmp_path, b, "report", "報告")[1]
    b2 = make(tmp_path / "d", 1, [rd(1, done=("report.cold_check",), instances={"report": pending("report")})], record=full)
    assert gl("accept", "--dir", b2.dir, "--node", "report", "--reply", reply)[1]["pending"] is True
    st = json.loads((b2.dir / "state.json").read_text(encoding="utf-8"))
    st["halted"] = {"node": "p2.human_gate", "round": 1}   # 周の途中の問いで止めた run——done は instance を問わず拒む
    (b2.dir / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    assert gl("accept", "--dir", b2.dir, "--node", "report", "--reply", reply)[1]["pending"] is False
    assert "止めた" in done_says(tmp_path / "h", Board(b2.dir), "report", "報告")[1]
