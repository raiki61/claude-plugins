"""規則の関数の新しい形（手順 3 の 3-6）: 読み口（宣言した欄だけ・読んだ値は写し）で呼び、書き込みは effects で頼み、engine が
graph の state_schema の合わせ方（x-reducer）で当てる。拒否は例外でなく ok: false。run の状態は effect の口だけで書き、loop.py patch は
合わせ方を飛ばした上書きとして痕跡に残す。"""
import copy
import json
import shutil
import subprocess
import sys

import pytest

from conftest import PLUGIN, REVIEW_GRAPH_PATH, REVIEW_VALIDATOR, graphcheck, run_graphcheck
from engine import commands, effects
from engine.rules import load_rules
from engine.util import AnswerReject
from test_hist import make, rd

GRAPH = json.loads(REVIEW_GRAPH_PATH.read_text(encoding="utf-8"))
SCHEMA = GRAPH["state_schema"]


def die_msg(fn, capsys):
    with pytest.raises(SystemExit):
        fn()
    return capsys.readouterr().err


# ---------------------------------------------------------------- 合わせ方（engine/effects.py）
@pytest.mark.parametrize("before, eff, after", [
    ({}, ("outcome", "overwrite", "stopped"), {"outcome": "stopped"}),
    ({"outcome": "stopped"}, ("outcome", "overwrite", None), {}),
    ({"in_round_answers": [{"n": 1}]}, ("in_round_answers", "append", [{"n": 2}]), {"in_round_answers": [{"n": 1}, {"n": 2}]}),
    ({"lanes": {"a": {"state": "running", "round": 1}}}, ("lanes", "merge_by_key", {"a": {"state": "merged"}, "b": {"round": 2}}),
     {"lanes": {"a": {"state": "merged", "round": 1}, "b": {"round": 2}}}),
    ({}, ("request_fixed_at", "set_once", 2), {"request_fixed_at": 2}),
    ({"request_fixed_at": 1}, ("request_fixed_at", "set_once", 2), {"request_fixed_at": 1}),   # 一方向の旗は下げない・動かさない
    ({"diff_file": "旧い鍵"}, ("diff_file", "overwrite", None), {}),                             # 宣言の外の旧い鍵は外すだけ受ける
])
def test_reducers(before, eff, after):
    loop = copy.deepcopy(before)
    effects.apply_effects(loop, [{"to": "loop." + eff[0], "reducer": eff[1], "value": eff[2]}], SCHEMA, "検査")
    assert loop == after


@pytest.mark.parametrize("eff, words", [
    ({"to": "loop.outcome", "reducer": "append", "value": ["x"]}, "合わせ方は overwrite"),
    ({"to": "loop.no_such", "reducer": "overwrite", "value": 1}, "宣言していない"),
    ({"to": "record.base", "reducer": "overwrite", "value": 1}, "{to: 'loop.<鍵>'"),
    ({"to": "loop.lanes.x", "reducer": "merge_by_key", "value": {}}, "最上位の鍵 1 つ"),
    ({"to": "loop.lanes", "reducer": "merge_by_key", "value": []}, "値は辞書"),
])
def test_reducers_refuse_what_the_schema_does_not_declare(eff, words, capsys):
    assert words in die_msg(lambda: effects.apply_effects({}, [eff], SCHEMA, "検査"), capsys)


def test_the_shipped_review_loop_declares_a_reducer_for_every_run_state_key():
    assert effects.declares_reducers(SCHEMA) and all(p.get("x-reducer") in effects.REDUCERS for p in SCHEMA["properties"].values())
    research = json.loads((PLUGIN / "graphs" / "research-loop.json").read_text(encoding="utf-8")).get("state_schema")
    assert not effects.declares_reducers(research)   # 移していない research-loop は今の書き方のまま（保存の時の照らしも今のまま）


# ---------------------------------------------------------------- 読み口と包み（Board.rule・commands.post_check）
def test_view_shows_declared_fields_as_copies(tmp_path):
    b = make(tmp_path, 1, [rd(1)], record={"materials": {}, "units": [{"key": "u", "label": "block"}], "questions": [], "process": {}})

    @b.rules.cond_reads("record.units")
    def mutate(v):
        v("record.units")[0]["label"] = "info"   # 写しを書き換えても盤面に届かない
        return v("record.units")[0]["label"]

    assert b.rule("mutate", mutate) == (True, "block") and b.record["units"][0]["label"] == "block"


def test_view_refuses_undeclared_fields(tmp_path, capsys):
    b = make(tmp_path, 1, [rd(1)])

    @b.rules.cond_reads("record.units")
    def peek(v):
        return v("record.questions")

    assert "宣言していない欄" in die_msg(lambda: b.rule("peek", peek), capsys)


def test_post_check_turns_ok_false_into_answer_reject_and_checks_the_reply(tmp_path, capsys, monkeypatch):
    b = make(tmp_path, 1, [rd(1)])
    nid = "p0.premises"
    good = {"constraints": [{"text": "t", "measured_how": "m", "kind": "仮説"}]}
    assert commands.post_check(b, nid, good, None) == (good, [], [])
    with pytest.raises(AnswerReject, match="measured_output"):
        commands.post_check(b, nid, {"constraints": [{"text": "t", "measured_how": "m", "kind": "実測"}]}, None)
    # 補った返答は節の schema で照らし直す（合わない補いは rules の欠陥として止める）
    monkeypatch.setitem(b.rules.POST_CHECKS, "measured_needs_output", b.rules.cond_reads()(lambda v, *a: {"ok": True, "reply": {"x": 1}}))
    assert "補った返答が節" in die_msg(lambda: commands.post_check(b, nid, good, None), capsys)


def test_effects_from_a_new_form_builtin_are_applied_and_kept_out_of_the_output(tmp_path, monkeypatch):
    from engine.advance import run_driver_node
    b = make(tmp_path, 1, [rd(1)])
    fn = b.rules.cond_reads()(lambda v, nid: {"ok": True, "owed": 0, "rows": [],
                                              "effects": [{"to": "loop.outcome", "reducer": "overwrite", "value": "stopped"}]})
    monkeypatch.setitem(b.rules.BUILTINS, "delta_owed", fn)
    assert run_driver_node(b, "p3.delta_owed", b.nodes["p3.delta_owed"], []) is True
    assert b.loop_state == {"outcome": "stopped"}
    assert "effects" not in json.loads((b.dir / "out" / "r1" / "p3.delta_owed.json").read_text(encoding="utf-8"))


def test_moved_post_checks_and_builtins_take_the_view():
    """移した受け付け・機械の節は読み口を受け、旧い形のまま残す物は名指しで数える（残りは次の run——移し終えたら表から消す）"""
    rules = load_rules(REVIEW_GRAPH_PATH, GRAPH)
    legacy = sorted(k for k, fn in rules.POST_CHECKS.items() if not isinstance(getattr(fn, "reads", None), tuple))
    assert legacy == ["fix_covers_open_units", "judge_output", "local_review_covers_lenses", "r2_design"]
    assert isinstance(rules.BUILTINS["delta_owed"].reads, tuple)


# ---------------------------------------------------------------- run の状態は effect の口だけで書く（graphcheck）
def test_direct_loop_writes_are_found():
    src = ("def f(b):\n    rec, ls = b.record, b.loop_state\n    ls['x'] = 1\n    b.loop_state.setdefault('y', []).append(1)\n"
           "    del ls['z']\n    return ls.get('a')\n")
    assert [ln for ln, _ in graphcheck.direct_loop_writes(src)] == [3, 4, 4, 5]


def test_graphcheck_refuses_direct_loop_writes_in_rules_that_declare_reducers(tmp_path):
    shutil.copytree(PLUGIN / "prompts", tmp_path / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp_path / "rules")
    (tmp_path / "graphs").mkdir()
    f = tmp_path / "rules" / "review-loop.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n\ndef _sneak(b):\n    b.loop_state['outcome'] = 'x'\n", encoding="utf-8")
    ok, out = run_graphcheck(tmp_path, GRAPH)
    assert not ok and "盤面の loop を直に書いている" in out


@pytest.mark.parametrize("breaks, words", [
    (lambda g: g["state_schema"]["properties"]["outcome"].__setitem__("x-reducer", "sum"), "を engine が知らない"),
    (lambda g: g["state_schema"]["properties"]["escalated"]["properties"]["round"].__setitem__("x-reducer", "overwrite"), "効かない"),
    (lambda g: g["state_schema"]["properties"]["outcome"].pop("x-reducer"), "x-reducer が無い"),
])
def test_graphcheck_checks_the_reducer_words_and_places(sandbox, breaks, words):
    g = copy.deepcopy(GRAPH)
    breaks(g)
    ok, out = run_graphcheck(sandbox, g)
    assert not ok and words in out


# ---------------------------------------------------------------- 手当て（loop.py patch）は合わせ方を飛ばした上書き
@pytest.mark.parametrize("path, value, want", [
    ("state.loop.escalated", {"round": 1}, {"escalated": "set_once"}),
    ("state.loop", {"outcome": "stopped"}, {"outcome": "overwrite"}),
    ("record.round", 1, None),
])
def test_patch_records_the_bypassed_reducer(tmp_path, path, value, want):
    b = make(tmp_path, 1, [rd(1)])
    val = tmp_path / "v.json"
    val.write_text(json.dumps(value), encoding="utf-8")
    r = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "loop.py"), "patch", "--path", path, "--file", str(val),
                        "--reason", "検査", "--dir", str(b.dir)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    row = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["patches"][-1]
    assert row.get("bypass") == want
