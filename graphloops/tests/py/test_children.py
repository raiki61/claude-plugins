"""graphloops/engine/children.py（loop.py children）——盤面の印から、この run が起こした子の残りを一覧する・止める口。
止める既定は印を書いたプロセス（launch）がもう居ない止め残しだけで、走っている試行は明示の旗のときだけ。
本物の子を止める検査は OS で見送らない（POSIX は数え上げの道、Windows は taskkill /T /F の道を通る）。"""
import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

from engine import children, role_run
from engine.util import Reject

LOOP = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "loop.py"
GROUP = ({"start_new_session": True} if os.name == "posix"
         else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})


def board(tmp_path, rounds=()):
    d = tmp_path / "board"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"rounds": list(rounds)}), encoding="utf-8")
    return d


def put(path, mark):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mark), encoding="utf-8")
    return path


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def sleeper():
    """眠る子。この検査のプロセスが握る標準入力の管の EOF まで眠る（検査が消えれば終わる）"""
    return subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE, **GROUP)


def settle(p, within=30):
    """止めた子が居なくなるまで数え直す（1 回見では回収前・終わりの途中を生きていると読む）"""
    t0 = time.monotonic()
    while p.poll() is None and time.monotonic() - t0 < within:
        time.sleep(0.05)
    return p.poll() is not None


def test_survey_names_the_instance_and_round_of_each_mark_without_signals(tmp_path, monkeypatch):
    """盤面の下の印を全部拾い（前の周・前の試行・背景の線も）、周と instance を名指す。一覧は信号を送らない"""
    d = tmp_path / "board"
    out1 = d / "out" / "r1" / "a.json"
    out2 = d / "out" / "r2" / "a.a2.json"
    lane = d / "lanes" / "x.json"
    rounds = [{"round": 1, "instances": {"a": {"id": "a", "status": "done", "out_path": str(out1)}}},
              {"round": 2, "instances": {"a": {"id": "a", "status": "pending", "out_path": str(out2),
                                                "attempt_log": [{"prev_out_path": str(d / "out" / "r2" / "a.json")}]},
                                          "l": {"id": "l", "status": "done", "out_path": str(d / "out" / "r2" / "l.json"),
                                                "launch": {"background": True, "result_path": str(lane)}}}}]
    d.mkdir()
    (d / "state.json").write_text(json.dumps({"rounds": rounds}), encoding="utf-8")
    for p in (out1, d / "out" / "r2" / "a.json", lane.with_name("x.json.tmp")):
        put(pathlib.Path(role_run.pgid_path(p)), {"pgid": 4242, "owner": 1})
    monkeypatch.setattr(role_run, "_started_at", lambda pid: 100.0)
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: ({}, None))
    monkeypatch.setattr(role_run, "_stop_tree", lambda *a, **k: pytest.fail("一覧が信号を送った"))
    rows = {r["mark"]: r for r in children.survey(d)}
    assert {k: (r["round"], r["instance"]) for k, r in rows.items()} == {
        os.path.join("lanes", "x.json.tmp.pgid"): (2, "l"),
        os.path.join("out", "r1", "a.json.pgid"): (1, "a"),
        os.path.join("out", "r2", "a.json.pgid"): (2, "a")}


@pytest.mark.parametrize("owner,state", [pytest.param(None, children.UNKNOWN, id="old-mark"),
                                         pytest.param("self", children.RUNNING, id="running"),
                                         pytest.param("dead", children.LEFT, id="left")])
def test_stop_by_default_only_stops_marks_whose_launch_is_gone(tmp_path, monkeypatch, owner, state):
    """既定で止めるのは owner（印を書いた launch）が居ない印だけ。走っている・確かめられない印は旗のときだけ止める"""
    d = board(tmp_path)
    who = {"self": os.getpid(), "dead": 777}.get(owner)
    m = put(d / "out" / "r1" / "a.json.pgid", {"pgid": 4242, **({"owner": who} if who else {})})
    past = time.time() - 60
    os.utime(m, (past, past))
    monkeypatch.setattr(role_run, "_started_at", lambda pid: {4242: past - 1, os.getpid(): past - 10}.get(pid, role_run.GONE))
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: ({}, None))
    stopped = []
    monkeypatch.setattr(role_run, "stop_group", lambda f: stopped.append(str(f)))
    rows = children.stop(d, "検査")
    assert rows[0]["state"] == state and (rows[0]["result"] == "stopped") == (state == children.LEFT)
    assert bool(stopped) == (state == children.LEFT)
    rows = children.stop(d, "検査", include_running=True)
    assert rows[0]["result"] == "stopped"
    trace = [json.loads(x) for x in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [t["include_running"] for t in trace] == [False, True] and all(t["op"] == "children_stop" and t["reason"] == "検査" for t in trace)


def test_stop_needs_a_reason(tmp_path):
    with pytest.raises(Reject):
        children.stop(board(tmp_path), "  ")


def test_stop_stops_a_real_left_tree_and_skips_a_running_one(tmp_path):
    """本物の子: launch が居ない印の子は既定で止まり印も消える。自分（生きている launch）が書いた印の子は旗まで残る"""
    d = board(tmp_path)
    left, running = sleeper(), sleeper()
    try:
        ml = put(d / "out" / "r1" / "left.json.pgid", {"pgid": left.pid, "owner": dead_pid()})
        mr = put(d / "out" / "r1" / "run.json.pgid", {"pgid": running.pid, "owner": os.getpid()})
        rows = {r["mark"]: r for r in children.stop(d, "検査")}
        assert rows[os.path.join("out", "r1", "left.json.pgid")]["result"] == "stopped" and settle(left) and not ml.exists()
        assert rows[os.path.join("out", "r1", "run.json.pgid")]["result"] == "skipped" and running.poll() is None and mr.exists()
        rows = children.stop(d, "検査", include_running=True)
        assert [r["result"] for r in rows] == ["stopped"] and settle(running) and not mr.exists()
    finally:
        for p in (left, running):   # 止めるのは持っている Popen だけ（番号で送らない）
            if p.poll() is None:
                p.kill()
                p.wait()


def test_cli_refuses_stop_without_reason_and_flags_without_stop(tmp_path):
    d = board(tmp_path)
    run = lambda *a: subprocess.run([sys.executable, str(LOOP), "children", "--dir", str(d), *a],
                                    capture_output=True, text=True, encoding="utf-8")
    assert run("--stop").returncode == 1
    assert run("--include-running").returncode == 1
    r = run()
    assert r.returncode == 0 and json.loads(r.stdout) == {"children": []}


def test_stop_touches_only_marks_under_its_own_board(tmp_path, monkeypatch):
    """同じ機械の別の run（別の盤面）の印には触れない——引くのは --dir の盤面の下だけ"""
    a, b = board(tmp_path / "a"), board(tmp_path / "b")
    put(a / "out" / "r1" / "x.json.pgid", {"pgid": 11, "owner": 777})
    other = put(b / "out" / "r1" / "x.json.pgid", {"pgid": 22, "owner": 777})
    monkeypatch.setattr(role_run, "_started_at", lambda pid: role_run.GONE if pid == 777 else 1.0)
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: ({}, None))
    stopped = []
    monkeypatch.setattr(role_run, "stop_group", lambda f: stopped.append(pathlib.Path(f)))
    children.stop(a, "検査")
    assert stopped == [a / "out" / "r1" / "x.json.pgid"] and other.exists() and not (b / "trace.jsonl").exists()


def test_stop_leaves_marks_of_pending_instances_to_relaunch_and_stop(tmp_path, monkeypatch):
    """launch が居なくても、instance が受け付けの前（pending）の印は既定で止めない——relaunch・stop の持ち分（盤面を先に書く）"""
    d = tmp_path / "board"
    out = d / "out" / "r1" / "a.json"
    board(tmp_path, [{"round": 1, "instances": {"a": {"id": "a", "status": "pending", "out_path": str(out)}}}])
    put(pathlib.Path(role_run.pgid_path(out)), {"pgid": 11, "owner": 777})
    monkeypatch.setattr(role_run, "_started_at", lambda pid: role_run.GONE if pid == 777 else 1.0)
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: ({}, None))
    stopped = []
    monkeypatch.setattr(role_run, "stop_group", lambda f: stopped.append(f))
    rows = children.stop(d, "検査")
    assert rows[0]["state"] == children.LEFT and rows[0]["result"] == "skipped" and stopped == []
    assert children.stop(d, "検査", include_running=True)[0]["result"] == "stopped"



def test_runner_launch_marks_are_listed_but_never_stopped_or_removed(tmp_path, monkeypatch):
    """回し手（loop.py run）の launch の印は一覧に runner_launch で出る。--include-running でも止めず、印も消さない
    （次の回し手が印の ids から試行を拾い直す）"""
    d = board(tmp_path)
    m = put(d / role_run.RUNNER_MARKS / "4242.json", {"pgid": 4242, "ids": ["p2.diagnose"]})
    monkeypatch.setattr(role_run, "_started_at", lambda pid: role_run.GONE)
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: ({}, None))
    monkeypatch.setattr(role_run, "stop_group", lambda *a, **k: pytest.fail("回し手の印を止めた"))
    rows = children.survey(d)
    assert [(r["mark"], r["state"], r["ids"]) for r in rows] == [(os.path.join(role_run.RUNNER_MARKS, "4242.json"), children.RUNNER_LAUNCH, ["p2.diagnose"])]
    rows = children.stop(d, "検査", include_running=True)
    assert rows[0]["result"] == "skipped" and m.is_file()
