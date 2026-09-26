"""外の土台から規則を呼ぶ口（scripts/gl.py）: 本物の盤面を読んで規則の関数を呼び、JSON 1 行を返す。盤面にも作業ツリーにも書かない。
拒否も終了コード 0 で返し、読めないときだけ 2（試作 gl_accept.py と同じ約束）。周は盤面の周で、前の周の出力も読む。"""
import copy
import json
import subprocess
import sys

from conftest import PLUGIN, REVIEW_GRAPH_PATH
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
