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
