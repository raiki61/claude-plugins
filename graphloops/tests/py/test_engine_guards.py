"""engine の守りの口（盤面の競り・rules の欠陥・人が打つ口の拒否）を、盤面を差し替えて直に呼ぶ検査——graphcheck が init で
弾く形でも、init の後に graph・rules・盤面が書き換わると実行時の口に届く。盤面を回す端から端までの台本は tests/simulate*.py"""
import argparse
import json
import os
import signal
import types

import pytest

from conftest import REPO
from engine import commands, util
from engine.advance import run_driver_node
from engine.board import Board
from engine.util import BoardConflict, Reject


class FakeBoard:
    """commands が触る盤面の欄だけを持つ差し替え"""
    def __init__(self, instances=None, rules=None, state=None, graph=None, nodes=None):
        self.rd = {"instances": instances or {}}
        self.rules = rules
        self.state = state or {}
        self.graph = graph or {}
        self.nodes = nodes or {}
        self.held_trace = None
        self.traced = []

    def trace(self, op, **kw):
        self.traced.append(op)

    def save(self):
        pass

    def is_runner(self, n):
        return False


def test_board_update_gives_up_after_retries(monkeypatch):
    """版の衝突は読み直して当て直すが、上限を超えたら黙って None を返さず衝突を上げる"""
    opened = []

    class Conflicting(FakeBoard):
        def __init__(self, d):
            super().__init__()
            opened.append(d)

        def save(self):
            raise BoardConflict("版が進んだ")

    monkeypatch.setattr(commands, "Board", Conflicting)
    with pytest.raises(BoardConflict):
        commands._board_update("d", lambda b: "当てた")
    assert len(opened) == commands.CONFLICT_RETRIES


def test_still_mine_false_when_instance_left_the_round(tmp_path):
    """周が進んで今の周に自分の instance が無いなら、自分の試行ではない（落ちずに偽）"""
    (tmp_path / "state.json").write_text(json.dumps({"rounds": [{"instances": {}}]}), encoding="utf-8")
    assert commands._still_mine(tmp_path, {"id": "p1.x", "out_path": "o"})() is False


@pytest.mark.parametrize("redraw", [["gone"], ["p1.done"]])
def test_add_refuses_redraw_of_non_waiting_instance(tmp_path, monkeypatch, capsys, redraw):
    """rules の add が、今の周に無い・待っていない instance を描き直せと言ったら rules の欠陥として止める"""
    rules = types.SimpleNamespace(add=lambda b, got, reason: {"msg": "積んだ", "redraw": redraw})
    fb = FakeBoard(instances={"p1.done": {"id": "p1.done", "status": "done"}}, rules=rules)
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    f = tmp_path / "add.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        commands.cmd_add(argparse.Namespace(dir=str(tmp_path), file=str(f), reason="検査"))
    assert "rules の欠陥" in capsys.readouterr().err


def _add(tmp_path, monkeypatch, got):
    """rules の add が got を返す盤面で cmd_add を呼ぶ。返すのは差し替えの盤面"""
    rules = types.SimpleNamespace(add=lambda b, items, reason: got)
    fb = FakeBoard(instances={"p1.x": {"id": "p1.x", "status": "pending", "out_path": str(tmp_path / "o"), "attempts": 1}}, rules=rules)
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    monkeypatch.setattr(commands, "reissue", lambda b, prev, reason: {"id": prev["id"], "attempts": 2, "prompt_file": "p.a2",
                                                                     "out_path": str(tmp_path / "o.a2"), "launch": {"kind": "cli"}})
    f = tmp_path / "add.json"
    f.write_text("{}", encoding="utf-8")
    commands.cmd_add(argparse.Namespace(dir=str(tmp_path), file=str(f), reason="検査"))
    return fb


def test_add_accepts_a_plain_message_from_rules(tmp_path, monkeypatch, capsys):
    """rules の add は文だけを返してもよい（描き直す instance が無い）"""
    fb = _add(tmp_path, monkeypatch, "積んだ")
    assert capsys.readouterr().out.strip() == "ok 積んだ" and "redrawn" not in fb.traced


def test_add_redraw_retires_the_old_answer_and_leaves_a_trace(tmp_path, monkeypatch, capsys):
    """描き直した instance の前の置き場に在った物は .stale-a<試行> へ退け、描き直したことを trace に残す"""
    (tmp_path / "o").write_text("前の試行の返答", encoding="utf-8")
    fb = _add(tmp_path, monkeypatch, {"msg": "積んだ", "redraw": ["p1.x"]})
    assert not (tmp_path / "o").exists() and (tmp_path / "o.stale-a1").read_text(encoding="utf-8") == "前の試行の返答"
    out = capsys.readouterr().out
    assert "redrawn" in fb.traced and "p1.x を試行 2 として描き直した" in out and "engine が起こさない節" not in out


def test_add_redraw_of_a_node_engine_does_not_launch_says_so(tmp_path, monkeypatch, capsys):
    """engine が起こさない節（launch の無い試行）を描き直したら、前の試行を止めて新しい指示書で起こせと言う"""
    rules = types.SimpleNamespace(add=lambda b, items, reason: {"msg": "積んだ", "redraw": ["p1.x"]})
    fb = FakeBoard(instances={"p1.x": {"id": "p1.x", "status": "pending", "out_path": str(tmp_path / "o")}}, rules=rules)
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    monkeypatch.setattr(commands, "reissue", lambda b, prev, reason: {"id": "p1.x", "attempts": 2, "prompt_file": "p.a2",
                                                                     "out_path": str(tmp_path / "o.a2")})
    f = tmp_path / "add.json"
    f.write_text("{}", encoding="utf-8")
    commands.cmd_add(argparse.Namespace(dir=str(tmp_path), file=str(f), reason="検査"))
    assert "engine が起こさない節なので" in capsys.readouterr().out


def _relaunch(tmp_path, monkeypatch, out_paths, stop_why=None):
    """relaunch を差し替えの盤面で呼ぶ。out_paths は Board を開くたびに instance が持つ置き場（最後の値が続く）"""
    opened = []

    def board(d):
        path = out_paths[min(len(opened), len(out_paths) - 1)]
        opened.append(path)
        return FakeBoard(instances={"p1.x": {"id": "p1.x", "node": "p1.x", "status": "pending", "out_path": path,
                                             "launch": {"kind": "cli"}}}, nodes={"p1.x": {}})

    reissued = []
    monkeypatch.setattr(commands, "Board", board)
    monkeypatch.setattr(commands, "probe_group", lambda m: (None, None))
    monkeypatch.setattr(commands, "stop_group", lambda m: stop_why)
    monkeypatch.setattr(commands, "reissue", lambda b, prev, reason: reissued.append(prev) or
                        {"id": "p1.x", "out_path": str(tmp_path / "o.a2"), "attempts": 2})
    commands.cmd_relaunch(argparse.Namespace(dir=str(tmp_path), node="p1.x", reason="検査"))
    return reissued


def test_relaunch_refuses_when_another_relaunch_won(tmp_path, monkeypatch):
    """読んでから書くまでに別の relaunch が起こし直していたら、新しい試行を作らない"""
    reissued = []
    with pytest.raises(Reject, match="別の relaunch"):
        reissued = _relaunch(tmp_path, monkeypatch, [str(tmp_path / "o"), str(tmp_path / "o.a2")])
    assert reissued == []


def test_relaunch_dies_when_previous_child_survives(tmp_path, monkeypatch, capsys):
    """新しい試行は作ったが前の試行の子が止まらないなら、成功を印字せずに止める（launch するなと言う）"""
    with pytest.raises(SystemExit):
        _relaunch(tmp_path, monkeypatch, [str(tmp_path / "o")], stop_why="グループ 4242 が SIGKILL の後も残っている")
    out = capsys.readouterr()
    assert "前の試行の子を止められない" in out.err and "relaunched" not in out.out


def test_init_removes_run_dir_when_on_init_refuses(tmp_path, monkeypatch, capsys):
    """rules の入口（on_init）が拒んだら、作った置き場を消してから同じ失敗を上げる"""
    real = commands.hook

    def on_init(b, a):
        util.die("入口が拒んだ")

    monkeypatch.setattr(commands, "hook", lambda rules, name: on_init if name == "on_init" else real(rules, name))
    monkeypatch.setattr(util, "GIT_CWD", util.GIT_CWD)   # Board が書き換える大域を戻す
    monkeypatch.chdir(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# 見立て\n", encoding="utf-8")
    d = tmp_path / "run"
    a = argparse.Namespace(loop="research-loop", graph=None, request="この見立ては正しいか", document=str(doc), input=None,
                           thickness=None, decider=None, unattended=False, stop_after_round=None, dir=str(d),
                           validator=str(REPO / "scripts" / "research-record.py"), lang=None)
    with pytest.raises(SystemExit):
        commands.cmd_init(a)
    assert "入口が拒んだ" in capsys.readouterr().err   # 置き場を作った後の入口で止まった（手前の検査で止まったのではない）
    assert not d.exists()


@pytest.mark.parametrize("state", [pytest.param({}, id="no-inputs"), pytest.param({"inputs": {"cwd": ""}}, id="empty-cwd")])
def test_launch_without_recorded_cwd_uses_callers_cwd(tmp_path, monkeypatch, state):
    """盤面に対象の場所（inputs.cwd）が無い・空なら、役は launch を呼んだ場所で起こす（advance.launch_cwd が os.getcwd に倒す）"""
    monkeypatch.chdir(tmp_path)
    inst = {"id": "p1.x", "node": "p1.x", "out_path": "o", "launch": {"kind": "cli"}}
    monkeypatch.setattr(commands, "_board_update", lambda d, fn, **k: [inst] if fn.__name__ == "mark" else None)
    monkeypatch.setattr(commands, "Board", lambda d: FakeBoard(state=state))
    monkeypatch.setattr(commands, "kill_all", lambda: None)
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    got = []
    monkeypatch.setattr(commands, "launch_one", lambda d, i, m, cwd: got.append(cwd) or {"id": i["id"], "ok": True, "out_path": "o"})
    commands.cmd_launch(argparse.Namespace(dir=str(tmp_path), node=None))
    assert got == [os.getcwd()]


def test_cond_refuses_unknown_name(capsys):
    """graph の cond が rules の CONDS に無い名前なら、盤面を読まずに止める（init の後に rules が変わった run）"""
    with pytest.raises(SystemExit):
        Board.cond(types.SimpleNamespace(rules=types.SimpleNamespace(CONDS={})), "no_such_cond")
    assert "CONDS に無い" in capsys.readouterr().err


def test_driver_ask_without_options_waits_for_human(tmp_path):
    """機械の節が選択肢なしで人に聞いたら、落ちずに人の番にする（選択肢の検査は在るものだけに当てる）"""
    b = FakeBoard(rules=types.SimpleNamespace(BUILTINS={"ask": lambda b, nid: {"decision": "ask", "ask": {"question": "どうする"}}}),
                  state={"outputs": {}, "unattended": False})
    b.dir, b.round = tmp_path, 1
    b.rd["done"] = {}
    assert run_driver_node(b, "p4.gate", {"builtin": "ask"}, []) is False
    assert b.state["pending_human"] == {"node": "p4.gate", "question": "どうする"}


def research_run(tmp_path, monkeypatch):
    """research-loop の盤面を 1 つ作って置き場を返す（Board を本物で開く検査の土台）"""
    monkeypatch.setattr(util, "GIT_CWD", util.GIT_CWD)   # Board が書き換える大域を戻す
    monkeypatch.chdir(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# 見立て\n", encoding="utf-8")
    d = tmp_path / "run"
    commands.cmd_init(argparse.Namespace(loop="research-loop", graph=None, request="この見立ては正しいか", document=str(doc), input=None,
                                         thickness=None, decider=None, unattended=False, stop_after_round=None, dir=str(d),
                                         validator=str(REPO / "scripts" / "research-record.py"), lang=None))
    return str(d)


def test_engine_run_on_a_role_node_is_not_planned(tmp_path, monkeypatch):
    """engine_run は回す側の節の宣言——init の後に graph が書き換わり（盤面の graph は途中で直せる。advance.graph_changed）役の節に
    engine_run が付いても、役の節は走らせるだけの節にしない（graphcheck が init で弾く形を、実行時の口も持つ）"""
    from engine.advance import emit_instance
    b = Board(research_run(tmp_path, monkeypatch))
    nid = "p0.independence_review"
    assert not b.is_runner(b.nodes[nid])   # 台本の前提: 役の節
    b.nodes[nid]["engine_run"] = {"builtin": "declared_checks", "why": "書き換えた graph"}
    inst = emit_instance(b, nid)
    assert inst.get("mode") != "engine_run" and (inst.get("launch") or {}).get("kind") != "engine_run"


def test_save_refuses_when_the_board_moved_on(tmp_path, monkeypatch, capsys):
    """読んだ後に別のプロセスが盤面を進めていたら、書かずに版の衝突を上げ、何が残っているかを言う"""
    d = research_run(tmp_path, monkeypatch)
    first, second = Board(d), Board(d)
    first.save()
    with pytest.raises(BoardConflict, match="盤面が読んだ後に進んでいる"):
        second.save()


@pytest.mark.parametrize("ret", [pytest.param((1, "理由"), id="not-bool"), pytest.param((True, 5), id="reason-not-str")])
def test_run_cond_refuses_a_malformed_return(capsys, ret):
    """条件の関数の返りは（真偽, 理由の文）だけ——1 を真に・数を理由に読み替えない"""
    from engine.board import run_cond

    def fn(v):
        return ret
    fn.reads = ()
    with pytest.raises(SystemExit):
        run_cond("c", fn, {})
    assert "返りが（真偽, 理由の文）でない" in capsys.readouterr().err


def test_cond_view_overlay_answers_the_path_itself_and_below():
    """重ね書きした path そのものは重ね書きの値を、その下は値の中を引く（盤面の本物の値へ落とさない）"""
    from engine.board import CondView
    v = CondView("c", ("record.x",), {"record": {"x": {"y": "盤面"}}}, overlay={"record.x": {"y": "重ね書き"}})
    assert v("record.x") == {"y": "重ね書き"} and v("record.x.y") == "重ね書き"


def test_cond_view_keeps_one_unevaluable_row_per_trigger_and_round():
    from engine.board import CondView
    state = {"round": 2}
    v = CondView("c", (), {}, state=state)
    v.unevaluable("a", "測れない")
    v.unevaluable("a", "また測れない")   # 同じ周の同じ部品は 1 行
    v.unevaluable("b", "こちらも測れない")
    assert [(u["trigger"], u["round"]) for u in state["unevaluable"]] == [("a", 2), ("b", 2)]


def test_refuse_expression_conds_names_the_first_three_and_more(tmp_path, capsys):
    """式で書いた条件の節を 3 つまで名指し、4 つ以上なら『ほか』を添える"""
    from engine.board import refuse_expression_conds
    nodes = {f"n{i}": {"cond": {"path": "x", "op": "eq", "value": 1}} for i in range(4)}
    with pytest.raises(SystemExit):
        refuse_expression_conds(tmp_path / "graphs" / "g.json", nodes)
    assert "n0, n1, n2 ほか" in capsys.readouterr().err


def test_parse_flags_refuses_a_flag_without_value():
    assert commands._parse_flags(["-p", "--model"], ("-p", "--model")) == (None, "旗 --model に値が無い")


SANDBOX_WANT = json.dumps({"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["/w"], "allowWrite": []}}})


@pytest.mark.parametrize("value,want,words", [
    pytest.param("[]", "{}", "--settings のキーが", id="not-an-object"),
    pytest.param(json.dumps({"sandbox": {"enabled": True}}), SANDBOX_WANT, "denyWrite が文字列の一覧でない", id="no-filesystem"),
    pytest.param(json.dumps({"sandbox": {"enabled": True, "filesystem": {"allowWrite": []}}}), SANDBOX_WANT,
                 "denyWrite が文字列の一覧でない", id="no-deny"),
    pytest.param(json.dumps({"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["/w", 1], "allowWrite": []}}}), SANDBOX_WANT,
                 "denyWrite が文字列の一覧でない", id="deny-not-strings"),
])
def test_settings_refusal_refuses_odd_shapes(value, want, words):
    why = commands._settings_refusal(value, want)
    assert why is not None and words in why, why


def test_settings_refusal_accepts_a_superset_of_deny():
    got = json.dumps({"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["/w", "/more"], "allowWrite": []}}})
    assert commands._settings_refusal(got, SANDBOX_WANT) is None


def test_argv_refusal_refuses_roles_that_can_write_before_reading_flags():
    """ファイルを書く道具・全部の道具を持つ役は、旗を読む前に拒む（旗の形の拒否に化けない）"""
    argv = commands.launch_prefix() + ["claude", "-p"]
    for tools in (["Read", "Write"], ["*"]):
        why = commands._argv_refusal(argv, {}, {"tools": tools}, None)
        assert why is not None and "ファイルを書く道具を持つ役" in why, why


def test_engine_run_result_is_dropped_when_relaunched_meanwhile(tmp_path, monkeypatch):
    """走らせている間に起こし直された（今の instance の置き場が変わった）なら、組んだ返答を書かずに『起こし直された古い試行』で返る"""
    from engine.advance import helper_argv
    inst = {"id": "p0.x", "node": "p0.x", "out_path": str(tmp_path / "o"),
            "launch": {"kind": "engine_run", "steps": [{"name": "parallel-pr.py", "argv": helper_argv("parallel-pr.py")}]}}
    monkeypatch.setattr(commands, "run_steps", lambda *a, **k: [{"name": "parallel-pr.py", "exit": 0, "wall_s": 0.0}])
    monkeypatch.setattr(commands, "repo_root", lambda *a, **k: str(tmp_path))
    fb = FakeBoard(instances={"p0.x": {**inst, "status": "pending", "out_path": str(tmp_path / "o.a2")}})
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    got = commands.launch_engine_run(str(tmp_path), inst)
    assert got.get("superseded") and got["why"] == commands.SUPERSEDED and not (tmp_path / "o").exists()


def test_engine_fallback_keeps_the_attempt_log(tmp_path, monkeypatch):
    """任せ先に回した新しい試行は、前の試行の起こし直しの記録を引き継いで 1 行足す"""
    prev = {"id": "p0.x", "node": "p0.x", "status": "pending", "out_path": "o", "emitted_at": "t0", "attempts": 2,
            "attempt_log": [{"at": "t0", "reason": "前の起こし直し"}]}
    fb = FakeBoard(instances={"p0.x": prev})
    monkeypatch.setattr(commands, "_board_update", lambda d, fn: fn(fb))
    made = {}
    monkeypatch.setattr(commands, "emit_instance", lambda b, nid, item, attempt, engine_fallback: made.update(
        id=nid, emitted_at="t1", attempts=attempt, engine_fallback=engine_fallback) or made)
    assert commands._engine_fallback(str(tmp_path), "p0.x", "交差が在る") == "p0.x"
    assert [x["reason"] for x in made["attempt_log"]] == ["前の起こし直し", "交差が在る"] and made["attempts"] == 3
    assert "engine_fallback" in fb.traced


class RunnerBoard(FakeBoard):
    def is_runner(self, n):
        return True


def test_relaunch_accepts_an_engine_run_node_without_delegate(tmp_path, monkeypatch):
    """engine が起こした試行（launch を持つ）は、回す側の節（engine_run）で任せ先が無くても起こし直せる"""
    fb = RunnerBoard(instances={"p4.ci": {"id": "p4.ci", "node": "p4.ci", "status": "pending", "out_path": str(tmp_path / "o"),
                                          "launch": {"kind": "engine_run"}}}, nodes={"p4.ci": {}})
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    monkeypatch.setattr(commands, "_board_update", lambda d, fn: fn(fb))
    monkeypatch.setattr(commands, "probe_group", lambda m: (None, None))
    monkeypatch.setattr(commands, "stop_group", lambda m: None)
    monkeypatch.setattr(commands, "reissue", lambda b, prev, reason: {"id": "p4.ci", "out_path": str(tmp_path / "o.a2"), "attempts": 2})
    commands.cmd_relaunch(argparse.Namespace(dir=str(tmp_path), node="p4.ci", reason="検査"))
    assert "relaunched" in fb.traced


def test_relaunch_stops_the_marks_of_earlier_attempts_too(tmp_path, monkeypatch):
    """前の relaunch が止め切れずに残した子も止め直す——今の試行と attempt_log の前の置き場の印を全部止める"""
    fb = FakeBoard(instances={"p1.x": {"id": "p1.x", "node": "p1.x", "status": "pending", "out_path": str(tmp_path / "o.a2"),
                                       "launch": {"kind": "cli"}, "attempt_log": [{"prev_out_path": str(tmp_path / "o")}]}},
                   nodes={"p1.x": {}})
    stopped = []
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    monkeypatch.setattr(commands, "_board_update", lambda d, fn: fn(fb))
    monkeypatch.setattr(commands, "probe_group", lambda m: (None, None))
    monkeypatch.setattr(commands, "stop_group", lambda m: stopped.append(m))
    monkeypatch.setattr(commands, "reissue", lambda b, prev, reason: {"id": "p1.x", "out_path": str(tmp_path / "o.a3"), "attempts": 3})
    commands.cmd_relaunch(argparse.Namespace(dir=str(tmp_path), node="p1.x", reason="検査"))
    assert stopped == [str(tmp_path / "o.a2") + ".pgid", str(tmp_path / "o") + ".pgid"]


def test_launch_settle_logs_failed_only_without_rejections(tmp_path, monkeypatch):
    """拒否が上限まで続いた試行は resume・rejected の行だけ（失敗の行を重ねない）。拒否の無い失敗は failed の行"""
    inst = {"id": "p1.x", "node": "p1.x", "status": "pending", "out_path": "o", "launch": {"kind": "cli"}}
    rows = []

    class Tracing(FakeBoard):
        def trace(self, op, **kw):
            rows.append({"op": op, **kw})
    fb = Tracing(instances={"p1.x": inst})
    monkeypatch.setattr(commands, "Board", lambda d: fb)
    monkeypatch.setattr(commands, "_board_update", lambda d, fn, **k: fn(fb))
    monkeypatch.setattr(commands, "kill_all", lambda: None)
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    monkeypatch.setattr(commands, "launch_one", lambda d, i, m, cwd: {"id": "p1.x", "ok": False, "out_path": "o", "why": "受け付けが拒んだ: y",
                                                                      "rejections": ["x", "y"], "resumes": 1, "stderr": "e" * 300})
    commands.cmd_launch(argparse.Namespace(dir=str(tmp_path), node=None))
    assert [x["kind"] for x in inst["attempt_log"]] == ["resume", "rejected"]
    launched = [x for x in rows if x["op"] == "launched"]
    assert len(launched) == 1 and launched[0]["stderr"] == "e" * 200   # 標準エラーの末尾を trace に残す


def test_argv_refusal_compares_tools_as_sets(tmp_path):
    """--tools・--allowedTools は並びを問わない（役の定義の並びと engine の並びが違っても同じ道具）"""
    body = tmp_path / "role.txt"
    body.write_text("役の本文", encoding="utf-8")
    d = {"tools": ["Read", "Grep"], "model": "m", "effort": "e", "body": "役の本文"}
    perm = {"allowed_tools": ["Read", "Grep"], "permission_mode": "dontAsk", "settings": "{}"}
    argv = commands.launch_prefix() + ["claude", "-p", "--model", "m", "--effort", "e", "--tools", "Grep,Read", "--setting-sources", "",
                                       "--append-system-prompt-file", str(body), "--output-format", "json", "--allowedTools", "Grep,Read",
                                       "--permission-mode", "dontAsk", "--permission-prompts", "none", "--settings", "{}"]
    assert commands._argv_refusal(argv, {}, d, perm) is None


def test_pointer_resolve_skips_a_missing_field():
    """番号で指す欄を返答が持たない（任意の欄を省いた）なら、置き換える物が無いだけ——落ちない"""
    from engine import pointers
    out = {"other": 1}
    assert pointers.resolve(out, [{"at": "units[].key", "from": ["record.units"]}], [{"at": "units[].key", "names": ["u1"]}]) == []
    assert out == {"other": 1}
    rows = {"units": [5, {"key": 1}]}   # 行が object でない（数）なら飛ばし、object の行だけ置き換える
    assert pointers.resolve(rows, [{"at": "units[].key", "from": ["record.units"]}], [{"at": "units[].key", "names": ["u1"]}]) == []
    assert rows == {"units": [5, {"key": "u1"}]}


def test_pointer_widen_needs_a_list():
    from engine import pointers
    with pytest.raises(ValueError, match="pointers は schema を持つ節の配列"):
        pointers.widen({"n": {"pointers": {"at": "x"}, "schema": {"type": "object"}}})


@pytest.mark.parametrize("row", [pytest.param(5, id="not-an-object"),
                                 pytest.param({"at": "x", "from": ["a"], "extra": 1}, id="unknown-key"),
                                 pytest.param({"from": ["a"]}, id="no-at"),
                                 pytest.param({"at": "x", "from": "a"}, id="from-not-a-list")])
def test_pointer_widen_refuses_odd_rows(row):
    from engine import pointers
    with pytest.raises(ValueError, match=r"pointers\[0\] は"):
        pointers.widen({"n": {"pointers": [row], "schema": {"type": "object"}}})


def test_pointer_widen_needs_a_string_field():
    """番号で指せるのは文字列の欄だけ（数の欄を番号か名前に広げない）"""
    from engine import pointers
    with pytest.raises(ValueError, match="文字列の欄に無い"):
        pointers.widen({"n": {"pointers": [{"at": "x", "from": ["a"]}],
                              "schema": {"type": "object", "properties": {"x": {"type": "integer"}}}}})


def test_pointer_resolve_without_a_snapshot_for_a_later_pointer():
    """出した後に graph が pointers を足した（固めた一覧が足りない）なら、番号を名前に戻さずに名前で書けと返す"""
    from engine import pointers
    out = {"a": 1, "b": 1}
    errs = pointers.resolve(out, [{"at": "a", "from": ["x"]}, {"at": "b", "from": ["y"]}], [{"at": "a", "names": ["n1"]}])
    assert out == {"a": "n1", "b": 1} and len(errs) == 1 and "固めていない" in errs[0]
    keyless = {"a": 1}   # 固めた一覧の行に名前の欄が無かった（None）番号は名前に戻せない
    errs = pointers.resolve(keyless, [{"at": "a", "from": ["x"]}], [{"at": "a", "names": [None]}])
    assert keyless == {"a": 1} and len(errs) == 1 and "no に無い" in errs[0]
    flag = {"a": True}   # 真偽は番号ではない（True を 1 番と読まない）
    assert pointers.resolve(flag, [{"at": "a", "from": ["x"]}], [{"at": "a", "names": ["n1"]}]) == [] and flag == {"a": True}
