"""loop.py run（engine/runner.py）・盤面の錠（engine/filelock.py）・止めた run を続ける口（engine/resume.py）の検査。

回し手の筋（仕分け・一時停止・落ちた launch の拾い直し・kill -9 の後の引き継ぎ）は、loop.py の代わりに盤面の JSON を直に書く
代役の CLI（FAKE_CLI）で回す——本物の claude -p も役の定義も要らない。入口の配線（錠の下で走る・止まった種類の終了コード・
踏んだ問題に残さない値）と続ける口は、本物の loop.py で review-loop の盤面を作って確かめる。1 周を止めて続ける端から端までの
台本は simulate_review.py の test_stop_after_round"""
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

import pytest

from conftest import PLUGIN, REPO
from engine import filelock, runner
from engine.util import Reject

LOOP = PLUGIN / "scripts" / "loop.py"
POSIX = os.name == "posix"


# ---------------------------------------------------------------- 盤面の形（classify）
def inst(iid, **kw):
    return {"id": iid, "node": iid, "status": "pending", "out_path": f"/nowhere/{iid}.json", "emitted_at": "2026-09-26T00:00:00+09:00", **kw}


def state(*insts, **kw):
    return {"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {i["id"]: i for i in insts}}], **kw}


ROLE = {"kind": "agent"}


@pytest.mark.parametrize("st, kind", [
    (state(inst("a", launch=ROLE)), "busy"),                                                    # 起こせる節が在る
    (state(inst("a", launch=ROLE, launched_at="t", launch_state="running")), "busy"),           # 走っている
    (state(inst("a")), "handoff"),                                                              # launch の無い節は会話へ
    (state(inst("a", unfenced={"at": "t"})), "handoff"),                                        # 柵を外した任せ先も会話へ
    (state(inst("a", launch={"kind": "delegate", "background": True})), "handoff"),             # 背景の線は回し手が立てない
    (state(inst("a", launch=ROLE, launched_at="t", launch_state="ended", attempt_log=[{"reason": "拒否が上限"}])), "needs_human"),
    (state(inst("a", launch=ROLE), pending_human={"node": "x"}), "awaiting_human"),
    (state(status="stopped", halted={"by": "stop_after_round", "node": "c"}), "round_limit"),
    (state(status="stopped", halted={"by": "unattended", "node": "c", "reason": "r"}), "needs_human"),
    (state(status="stopped", halted={"by": "answer", "node": "c"}), "done"),
    (state(inst("a", status="done"), status="converged"), "done"),
    (state(inst("a", status="done")), "stuck"),                                                 # 何も無いのに終わっていない
])
def test_classify_reads_only_generic_marks(st, kind):
    assert runner.classify(st)["kind"] == kind


def test_handoff_wins_over_needs_human_but_both_are_reported():
    c = runner.classify(state(inst("a"), inst("b", launch=ROLE, launched_at="t", launch_state="ended")))
    assert c["kind"] == "handoff" and [x["id"] for x in c["needs_human"]] == ["b"]


# ---------------------------------------------------------------- 盤面の錠
HOLD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from engine import filelock
with filelock.board_lock(sys.argv[2]):
    print("held", flush=True)
    time.sleep(float(sys.argv[3]))
"""


def test_board_lock_serializes_processes_and_nests_in_one(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", HOLD, str(PLUGIN), str(tmp_path), "1.5"], stdout=subprocess.PIPE, text=True, encoding="utf-8")
    assert p.stdout.readline().strip() == "held"
    assert filelock.try_hold(tmp_path / filelock.BOARD_LOCK_NAME) is None   # 別のプロセスが持っている間は取れない
    t0 = time.monotonic()
    with filelock.board_lock(tmp_path):
        waited = time.monotonic() - t0
        with filelock.board_lock(tmp_path):   # 同じスレッドの入れ子は自分を待たない
            pass
    p.wait()
    assert waited > 0.5


def test_board_lock_makes_other_threads_wait(tmp_path):
    lk, order = filelock.board_lock(tmp_path), []
    with lk:
        t = threading.Thread(target=lambda: (lk.__enter__(), order.append("other"), lk.__exit__(None, None, None)))
        t.start()
        time.sleep(0.2)
        order.append("me")
    t.join()
    assert order == ["me", "other"]


@pytest.mark.parametrize("cmd, args, whole", [
    ("done", ["--node", "x"], True), ("add", ["--file", "f", "--reason", "r"], True), ("answer", ["--text", "continue"], True),
    ("relaunch", ["--node", "x", "--reason", "r"], False), ("launch", [], False), ("stop", ["--reason", "r"], False),
])
def test_entry_runs_board_writers_under_the_board_lock(tmp_path, monkeypatch, cmd, args, whole):
    """入口（loop.py）は、短い書き手を丸ごと盤面の錠の下で走らせ、launch・relaunch・stop の当て直しの錠（BOARD_LOCK）を
    プロセスをまたぐ盤面の錠に差し替える"""
    import importlib.util
    from engine import commands
    spec = importlib.util.spec_from_file_location("loop_entry", LOOP)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    seen = {}
    lk = filelock.board_lock(tmp_path)
    monkeypatch.setattr(commands, f"cmd_{cmd}", lambda a: seen.update(held=lk._depth > 0, lock=commands.BOARD_LOCK))
    monkeypatch.setattr(commands, "BOARD_LOCK", commands.BOARD_LOCK)
    monkeypatch.setattr(sys, "argv", ["loop.py", cmd, *args, "--dir", str(tmp_path)])
    entry.main()
    assert seen == {"held": whole, "lock": lk}


# ---------------------------------------------------------------- 本物の loop.py の盤面
def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def loop(cwd, *a, env=None):
    return subprocess.run([sys.executable, str(LOOP), *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env)


@pytest.fixture()
def review(tmp_path):
    """review-loop の盤面（宣言した一式は緑の 1 段）。p0.local_checks は engine が走らせ、p0.base・p0.premises は会話に返る"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "s", "argv": [sys.executable, "-c", "print('1 passed')"]}]}), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    d = tmp_path / "st"
    r = loop(repo, "init", "--loop", "review-loop", "--request", "検査", "--dir", str(d), "--validator", str(REPO / "scripts" / "review-record.py"))
    assert r.returncode == 0, r.stderr
    return repo, d


def last_json(stdout):
    return json.loads(stdout.strip().splitlines()[-1])


def test_run_foreground_launches_what_engine_can_and_hands_back_the_rest(review, tmp_path):
    repo, d = review
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data")}
    r = loop(repo, "run", "--foreground", "--dir", str(d), env=env)
    out = last_json(r.stdout)
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert r.returncode == 13 and out["stop"] == "handoff" and out["code"] == 13
    assert sorted(h["id"] for h in out["handoff"]) == ["p0.base", "p0.premises"]
    assert st["rounds"][-1]["instances"]["p0.local_checks"]["status"] == "done"   # engine が走らせる節は回し手が起こした
    assert out["runner"]["pid"] and not runner._runner_alive(d)                    # 抜けたら錠は空く
    assert not (tmp_path / "data").exists()   # 日常の止まり方は踏んだ問題として残さない
    events = [json.loads(x)["event"] for x in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines() if '"op": "run"' in x]
    assert events == ["start", "launch", "launched", "stop"]


def test_watch_returns_handoff_at_once_and_does_not_start_a_second_runner(review):
    repo, d = review
    h = filelock.try_hold(d / runner.RUN_LOCK)   # 別の回し手が居る形
    try:
        loop(repo, "next", "--dir", str(d))
        r = loop(repo, "run", "--dir", str(d))
    finally:
        filelock.release(h)
    assert r.returncode == 13 and not (d / runner.RUNNER_JSON).exists()


def test_watch_limit_returns_still_running_without_stopping_the_runner(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps(state(inst("a", launch=ROLE, launched_at="t", launch_state="running"))), encoding="utf-8")
    h = filelock.try_hold(tmp_path / runner.RUN_LOCK)
    monkeypatch.setattr(runner, "WATCH_LIMIT_S", 0.3)
    monkeypatch.setattr(runner, "POLL_S", 0.05)
    try:
        kind, _c, _d = runner.watch(tmp_path)
        assert kind == "still_running" and runner._runner_alive(tmp_path)
    finally:
        filelock.release(h)


def done_file(tmp_path, name, obj):
    f = tmp_path / f"{name}.json"
    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return f


def test_concurrent_writers_lose_nothing(review, tmp_path):
    """会話の done 2 本と人の add を同時に打っても、どれも受け付けられ、盤面の版は 3 つ進む（錠が無いと 1 本ぶんが黙って消えた）"""
    repo, d = review
    assert loop(repo, "run", "--foreground", "--dir", str(d)).returncode == 13
    head = git(repo, "rev-parse", "HEAD").strip()
    base = done_file(tmp_path, "base", {"base_sha": head, "method": "4 依頼者の名指し", "commits": 0, "merge_commit": False, "intent_to_add": [],
                                        "touches_gates": False, "touches_external_seams": False, "touches_user_path": False,
                                        "touches_security_surface": False, "material": {"status": "clean", "checked": "検査"}})
    prem = done_file(tmp_path, "prem", {"constraints": [{"text": "検査", "measured_how": "検査", "kind": "仮説"}]})
    add = done_file(tmp_path, "add", [{"where": "a.py", "text": "検査の依頼"}])
    rev0 = json.loads((d / "state.json").read_text(encoding="utf-8"))["rev"]
    cmds = [["done", "--node", "p0.base", "--output", str(base)], ["done", "--node", "p0.premises", "--output", str(prem)],
            ["add", "--file", str(add), "--reason", "検査"]]
    ps = [subprocess.Popen([sys.executable, str(LOOP), *c, "--dir", str(d)], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                           encoding="utf-8")
          for c in cmds]
    outs = [(p.wait(), p.stderr.read()) for p in ps]
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert [rc for rc, _ in outs] == [0, 0, 0], outs
    assert st["rev"] == rev0 + 3
    assert all(st["rounds"][-1]["instances"][i]["status"] == "done" for i in ("p0.base", "p0.premises"))


def test_resume_opens_the_next_round_only_for_a_round_limit_halt(review):
    repo, d = review
    sp = d / "state.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    for by, want in (("answer", "続けられるのは"), (None, "止まっていない")):
        s = {**st, "status": "stopped", **({"halted": {"by": by, "node": "converge", "round": 1}} if by else {})}
        if not by:
            s["status"] = "running"
        sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        r = loop(repo, "resume", "--reason", "検査", "--stop-after-round", "2", "--dir", str(d))
        assert r.returncode == 1 and want in r.stderr, r.stderr
    sp.write_text(json.dumps({**st, "status": "stopped", "stop_after_round": 1,
                              "halted": {"by": "stop_after_round", "node": "converge", "round": 1}}, ensure_ascii=False), encoding="utf-8")
    r = loop(repo, "resume", "--reason", "検査", "--stop-after-round", "1", "--dir", str(d))
    assert r.returncode == 1 and "以下" in r.stderr
    assert loop(repo, "resume", "--reason", "検査", "--dir", str(d)).returncode == 2   # 次の止め周を決めない呼びは引数の誤り
    r = loop(repo, "resume", "--reason", "検査", "--stop-after-round", "3", "--dir", str(d))
    after = json.loads(sp.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    assert after["round"] == 2 and after["status"] == "running" and "halted" not in after and after["stop_after_round"] == 3
    assert after["resumes"][0]["prev_halted"]["by"] == "stop_after_round" and after["resumes"][0]["reason"] == "検査"
    assert after["rounds"][0]["instances"] == st["rounds"][0]["instances"]   # 1 周目の試行は起こし直さない


def test_resume_refuses_an_empty_reason(tmp_path):
    with pytest.raises(Reject, match="理由が空"):
        from engine import resume
        resume.cmd_resume(argparse.Namespace(reason=" ", stop_after_round=2, no_stop_after_round=False), tmp_path)


# ---------------------------------------------------------------- 代役の CLI で回し手の筋を回す
FAKE_CLI = r'''
import json, os, pathlib, sys, time
args = sys.argv[1:]
d = pathlib.Path(args[args.index("--dir") + 1])
sp = d / "state.json"
def load(): return json.loads(sp.read_text(encoding="utf-8"))
def save(s):
    tmp = d / f"state.{os.getpid()}.tmp"; tmp.write_text(json.dumps(s), encoding="utf-8"); os.replace(tmp, sp)
def log(x):
    with open(d / "cli.log", "a", encoding="utf-8") as f: f.write(x + "\n")
cmd = args[0]
log(cmd + (" " + args[2] if cmd in ("done", "relaunch") else ""))
s = load(); insts = s["rounds"][-1]["instances"]
if cmd == "next":
    adds = d / "next_adds.json"
    later = d / "next_adds_later.json"   # 1 本目の launch の後の next で出る波
    if later.exists() and (d / "launch.started").exists():
        later.replace(adds)
    if adds.exists():
        for i in json.loads(adds.read_text(encoding="utf-8")): insts.setdefault(i["id"], i)
        adds.unlink(); save(s)
elif cmd == "launch":
    ids = [k for k, i in insts.items() if i["status"] == "pending" and i.get("launch") and not i.get("launched_at")]
    for k in ids: insts[k].update(launched_at="t", launch_state="running")
    save(s)
    (d / "launch.started").write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(float((d / "launch_sleep").read_text()) if (d / "launch_sleep").exists() else 0)
    if (d / "launch_crash").exists():
        (d / "launch_crash").unlink(); os._exit(9)
    s = load()
    for k in ids: s["rounds"][-1]["instances"][k].update(status="done", launch_state="ended")
    save(s)
elif cmd == "done":
    insts[args[2]]["status"] = "done"; save(s)
elif cmd == "relaunch":
    i = insts[args[2]]
    for k in ("launched_at", "launch_state"): i.pop(k, None)
    i["attempts"] = i.get("attempts", 1) + 1; save(s)
'''


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    cli = tmp_path / "fake_loop.py"
    cli.write_text(FAKE_CLI, encoding="utf-8")
    monkeypatch.setattr(runner, "LOOP", cli)
    monkeypatch.setattr(runner, "POLL_S", 0.05)
    d = tmp_path / "st"
    d.mkdir()
    (d / "trace.jsonl").write_text("", encoding="utf-8")
    return d, cli


def put(d, st):
    (d / "state.json").write_text(json.dumps(st), encoding="utf-8")


def cli_log(d):
    p = d / "cli.log"
    return p.read_text(encoding="utf-8").split() if p.exists() else []


def test_runner_launches_until_nothing_is_left(fake):
    d, _ = fake
    put(d, state(inst("a", launch=ROLE), status="running"))
    (d / "next_adds_later.json").write_text(json.dumps([inst("b", launch=ROLE)]), encoding="utf-8")   # 1 本目の後に次の波が出る形
    kind, _r = runner.run_as_runner(d)
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert kind == "stuck" and {k: v["status"] for k, v in st["rounds"][-1]["instances"].items()} == {"a": "done", "b": "done"}
    assert cli_log(d).count("launch") == 2 and not list((d / runner.MARKS).glob("*.json"))


def test_runner_hands_the_same_try_to_human_when_launch_marks_nothing(fake):
    """launch が 1 つも起こさずに終わる（起こした印が付かない）なら、起こし直しの輪を回さずに抜ける"""
    d, cli = fake
    cli.write_text("import sys\nsys.exit(0) if sys.argv[1] != 'launch' else sys.exit(2)\n", encoding="utf-8")
    put(d, state(inst("a", launch=ROLE)))
    kind, r = runner.run_as_runner(d)
    assert kind == "stuck" and "起こさずに終わった" in r.detail


def test_runner_picks_up_a_crashed_launch(fake):
    """launch が締めの前に落ちた試行: 置き場に返答が在れば役を起こさずに受け付ける"""
    d, _ = fake
    out = d / "a.json"
    out.write_text("{}", encoding="utf-8")
    put(d, state(inst("a", launch=ROLE, out_path=str(out))))
    (d / "launch_crash").write_text("", encoding="utf-8")
    runner.run_as_runner(d)
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert st["rounds"][-1]["instances"]["a"]["status"] == "done" and cli_log(d) == ["next", "launch", "done", "a", "next"]


def test_runner_relaunches_a_crashed_launch_without_an_answer_once(fake):
    d, _ = fake
    put(d, state(inst("a", launch=ROLE)))
    (d / "launch_crash").write_text("", encoding="utf-8")
    runner.run_as_runner(d)
    log = cli_log(d)
    assert log[:5] == ["next", "launch", "relaunch", "a", "next"] and log.count("launch") == 2


def spawn_runner(d, cli):
    code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); from engine import runner; runner.LOOP = pathlib.Path(sys.argv[2]); "
            "runner.POLL_S = 0.05; got = runner.run_as_runner(sys.argv[3]); "
            "sys.exit(128 + got[1].signum if got and got[0] == 'signal' else 0)")
    return subprocess.Popen([sys.executable, "-c", code, str(PLUGIN), str(cli), str(d)], start_new_session=True)


def wait_for(pred, limit=20.0):
    t = time.monotonic() + limit
    while time.monotonic() < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(not POSIX, reason="信号でプロセスグループを止める形は POSIX の物")
def test_sigterm_waits_for_launched_roles_and_starts_nothing_new(fake):
    d, cli = fake
    put(d, state(inst("a", launch=ROLE)))
    (d / "launch_sleep").write_text("1.5", encoding="utf-8")
    (d / "next_adds.json").write_text(json.dumps([]), encoding="utf-8")
    p = spawn_runner(d, cli)
    assert wait_for(lambda: (d / "launch.started").exists())
    (d / "next_adds.json").write_text(json.dumps([inst("b", launch=ROLE)]), encoding="utf-8")
    os.kill(p.pid, signal.SIGTERM)
    assert p.wait(30) == 128 + signal.SIGTERM
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))["rounds"][-1]["instances"]
    assert st["a"]["status"] == "done" and "b" not in st          # 起こし済みは終わりまで待ち、次の next も打たない
    assert not runner._runner_alive(d) and cli_log(d).count("launch") == 1


@pytest.mark.skipif(not POSIX, reason="kill -9 の後に残る launch のグループを見る形は POSIX の物")
def test_next_runner_waits_for_launch_left_by_a_killed_runner(fake):
    d, cli = fake
    put(d, state(inst("a", launch=ROLE)))
    (d / "launch_sleep").write_text("1.5", encoding="utf-8")
    p = spawn_runner(d, cli)
    assert wait_for(lambda: (d / "launch.started").exists())
    os.kill(p.pid, signal.SIGKILL)
    p.wait(10)
    kind, _r = runner.run_as_runner(d)   # 錠は OS が外した——次の回し手が取り、前の launch の終わりを待つ
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))["rounds"][-1]["instances"]
    assert st["a"]["status"] == "done" and cli_log(d).count("launch") == 1 and kind == "stuck"
