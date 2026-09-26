"""人が途中で止める口（loop.py stop）の部品——後始末の節の選び方・graph の宣言の柵・止めた試行の締め出し・research の結末の畳み方
（走っている run の途中の仕上げは記録を書き換えない）と、導出の判定が自分で持つ暫定の形・検証器が止まった記録の空の欄を受ける形。盤面を回す端から端までの台本は simulate_review.py の test_stop_midround と
simulate.py の test_stop_midway"""
import argparse
import copy
import json
import shutil
import subprocess
import sys
import types

import pytest

from conftest import PLUGIN, REPO
from engine import commands
from engine.rules import load_rules
from engine.schema import load_graph
from engine.util import Reject

REVIEW = load_graph(PLUGIN / "graphs" / "review-loop.json")[0]
RESEARCH_PATH = PLUGIN / "graphs" / "research-loop.json"
RESEARCH = load_graph(RESEARCH_PATH)[0]
RULES = load_rules(RESEARCH_PATH, RESEARCH)
VALIDATOR = REPO / "scripts" / "research-record.py"
EXAMPLE = json.loads((REPO / "templates" / "research-record.example.json").read_text(encoding="utf-8"))


def test_after_stop_only_the_report_side_runs():
    """止めた後に走らせるのは宣言の節の下流だけ（両 loop とも報告の節に届く）"""
    assert commands.stop_descendants(REVIEW["nodes"], REVIEW["stop"]["node"]) == {"report.human_items", "report.cold_check", "report"}
    assert commands.stop_descendants(RESEARCH["nodes"], RESEARCH["stop"]["node"]) == {"p5.adapt", "report", "reflect"}


def test_stop_requires_a_reason():
    with pytest.raises(Reject, match="理由が空"):
        commands.cmd_stop(argparse.Namespace(reason="  \n", dir=None))


def test_still_mine_false_for_stopped_attempt(tmp_path):
    """人が止めた試行は自分の物でない——止めた後に続きの往復の子を起こさない"""
    inst = {"id": "p2.diagnose", "out_path": "o"}
    (tmp_path / "state.json").write_text(json.dumps({"rounds": [{"instances": {"p2.diagnose": {**inst, "status": "stopped"}}}]}), encoding="utf-8")
    assert commands._still_mine(tmp_path, inst)() is False
    (tmp_path / "state.json").write_text(json.dumps({"rounds": [{"instances": {"p2.diagnose": {**inst, "status": "pending"}}}]}), encoding="utf-8")
    assert commands._still_mine(tmp_path, inst)() is True


@pytest.mark.parametrize("decl, why", [
    ({"node": "no.such"}, "節に無い"),
    ({"node": "p2.diagnose"}, "機械の節"),
    ({"node": "p1.worktree_after"}, "報告の節"),
])
def test_graphcheck_refuses_bad_stop_decl(tmp_path, decl, why):
    """stop.node は在る機械の節で、下流に報告の節（pre=finalize）を持つ——p1.worktree_after は機械の節だが、下流の報告は
    p2 以降を経るので届く。届かない宣言の形は、報告の節の pre を外した写しで作る"""
    for sub in ("graphs", "prompts", "rules"):
        shutil.copytree(PLUGIN / sub, tmp_path / sub)
    gp = tmp_path / "graphs" / "review-loop.json"
    g = json.loads(gp.read_text(encoding="utf-8"))
    g["stop"] = decl
    if why == "報告の節":
        g["nodes"]["report"].pop("pre")
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(PLUGIN / "scripts"))
    import graphcheck
    lines = []
    assert graphcheck.check(gp, emit=lines.append) is False
    assert any(why in str(x) and "stop.node" in str(x) for x in lines), lines


def research_board(outcome=None, status="running", halted=None, rederiver=None, **rec_over):
    rec = {"question": "問い", "constraints": [{"text": "c"}], "clusters": [], "claims": [], "gates": {
        "rederiver": rederiver or {"status": "not_applicable"}, "cold_reader": {"status": "not_applicable"},
        "cartographer": {"status": "not_applicable"}}, "sampling": {"status": "not_applicable"}, "process": {},
        "decisions": {"decide_now": ["d"], "poc": [], "human_only": []}, "convergence": {"outcome": outcome}, **rec_over}
    state = {"thickness": "標準", "status": status}
    if halted:
        state["halted"] = halted
    return types.SimpleNamespace(record=rec, state=state, loop_state={}, round=1, nodes=RESEARCH["nodes"], latest_output=lambda nid: None)


def test_research_initial_record_is_undecided():
    conv = RULES.init_record("標準", "既定")["convergence"]
    assert conv["outcome"] is None and "stopped_reason" not in conv


def test_research_finalize_while_running_writes_nothing_until_the_board_stops():
    """走っている run の途中の仕上げは、盤面の写し（読了の柵の痕跡）のほかは記録を書き換えない（照合前の主張を外さない・結末を
    書かない）。止めた後の仕上げは止めた事実で畳む"""
    b = research_board(claims=[{"id": "C1", "cluster": "k", "claim": "c", "load_bearing": True}],
                       clusters=[{"key": "k", "claims_submitted": 1}])
    b.state["read_through_unchecked"] = [{"why": "w"}]
    before = copy.deepcopy(b.record)
    RULES.finalize(b)
    assert b.record["process"].pop("read_through_unchecked") == [{"why": "w"}]
    assert b.record == before
    b.state.update(status="stopped", halted={"by": "stop_after_round", "reason": "1 周目の締めの後"})
    RULES.finalize(b)
    conv = b.record["convergence"]
    assert conv["outcome"] == "stopped" and "stop_after_round: 1 周目の締めの後" in conv["stopped_reason"]
    assert [c["id"] for c in b.record["process"]["unchecked_claims"]] == ["C1"]


def test_research_load_zero_reason_comes_from_the_clusters_output():
    """荷重の主張が 0 件の理由は p0.clusters の返答が正本——仕上げはその出力から写し、loop に残った旧い写しは読まない"""
    b = research_board(outcome="stopped", status="stopped", halted={"by": "stop", "reason": "検査用"},
                       claims=[{"id": "C1", "cluster": "k", "claim": "c", "load_bearing": False, "verdict": "確証"}],
                       clusters=[{"key": "k", "claims_submitted": 1}])
    b.loop_state["load_zero_reason"] = "旧い写し"
    RULES.finalize(b)
    assert "load_zero_reason" not in b.record["process"]
    b.latest_output = lambda nid: {"load_zero_reason": "どの主張も結論を支えない（検査用）"} if nid == "p0.clusters" else None
    RULES.finalize(b)
    assert b.record["process"]["load_zero_reason"] == "どの主張も結論を支えない（検査用）"


def test_research_rederiver_verdict_carries_its_own_state():
    """導出の判定のうち突合が確定させる物（pass）は not_run と暫定の判定で書き、突合の来ない判定（unverifiable・redesign-needed）は
    確定の判定で書く。止まった run の仕上げはどちらもそのまま残す——暫定か確定かを記録の欄が持つ"""
    w = {"op": "rederiver_first_verdict", "to": "gates.rederiver"}
    b = research_board(outcome="stopped", stopped_reason="人が止めた")
    RULES.rederiver_first_verdict(b, "p3.rederiver", {"verdict": "pass", "reason": "問いは立っている"}, w)
    RULES.finalize(b)
    g = b.record["gates"]["rederiver"]
    assert g["status"] == "not_run" and g["provisional"] == {"verdict": "pass", "reason": "問いは立っている"} and "突合" in g["reason"]
    for v in ("unverifiable", "redesign-needed"):
        b = research_board(outcome="stopped", stopped_reason=f"rederiver {v}")
        RULES.rederiver_first_verdict(b, "p3.rederiver", {"verdict": v, "reason": "r"}, w)
        RULES.finalize(b)
        assert b.record["gates"]["rederiver"] == {"verdict": v, "reason": "r"}


def test_research_compare_due_and_provisional_read_one_rule():
    for verdict in ("pass", "unverifiable", "redesign-needed"):
        vals = {"rd.new_discrepancies": 0, "out.p3.rederiver.verdict": verdict}
        due, _ = RULES.rederiver_compare_due(vals.get)
        b = research_board()
        RULES.rederiver_first_verdict(b, "p3.rederiver", {"verdict": verdict, "reason": "r"}, {"to": "gates.rederiver"})
        assert due == RULES.compare_confirms(verdict) == (b.record["gates"]["rederiver"].get("status") == "not_run")


def validate(rec, tmp_path):
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), str(f)], capture_output=True, text=True, encoding="utf-8", timeout=120)


def stopped_empty(gaps=True):
    rec = copy.deepcopy(EXAMPLE)
    rec["convergence"] = {"rounds_total": 1, "consecutive_zero": 0, "outcome": "stopped", "stopped_reason": "人が止めた"}
    for k in rec["gates"]:
        rec["gates"][k] = {"status": "not_run", "reason": "止めた"} if k != "cartographer" else {"status": "not_applicable", "reason": "標準"}
    rec["sampling"] = {"status": "not_applicable", "reason": "無し"}
    rec["claims"], rec["clusters"] = [], []
    rec["process"] = {"rerolls": 0, "unrefuted_load_bearing": []}
    if gaps:
        rec["process"]["stopped_gaps"] = {"claims": "照合の前に止めた", "clusters": "照合の前に止めた"}
    return rec


def test_validator_accepts_declared_gaps_only_on_stopped_records(tmp_path):
    assert validate(stopped_empty(), tmp_path).returncode == 0
    r = validate(stopped_empty(gaps=False), tmp_path)
    assert r.returncode == 2 and "clusters" in r.stdout + r.stderr   # 申告の無い空は今までどおり落とす
    rec = stopped_empty()
    rec["convergence"] = {"rounds_total": 1, "consecutive_zero": 0, "outcome": "converged"}
    r = validate(rec, tmp_path)
    assert r.returncode == 2 and "収束を名乗りながら空の欄" in r.stdout + r.stderr
    rec = stopped_empty()
    rec["process"]["stopped_gaps"]["constraints"] = "腐った申告"
    r = validate(rec, tmp_path)
    assert r.returncode == 2 and "申告の腐り" in r.stdout + r.stderr
    rec = stopped_empty()
    rec["process"]["stopped_gaps"]["notes"] = "知らない欄"
    assert validate(rec, tmp_path).returncode == 2
