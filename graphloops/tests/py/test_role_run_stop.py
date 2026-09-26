"""graphloops/engine/role_run.py の子を止める部品——run_tree の中断・_started_at（居ない番号）・probe_group と stop_group の
印の後始末。OS の分岐は role_run の os を差し替えて両側を見る（CI は 3 OS で回すが、それぞれの OS では片側しか通らない）。
子プロセスを本当に止める端から端までの形は tests/simulate.py の test_role_run が見る。"""
import json
import os
import subprocess
import sys
import types

import pytest

from engine import role_run


def mark(tmp_path, pgid=4242):
    m = tmp_path / "out.json.pgid"
    m.write_text(json.dumps({"pgid": pgid}), encoding="utf-8")
    return m


def test_run_tree_kills_the_tree_when_waiting_breaks(tmp_path, monkeypatch):
    """時間切れ以外で待ちが破れても（Ctrl-C など）、子を止めてから同じ例外を上げる"""
    seen = []

    class Broken(subprocess.Popen):
        def communicate(self, *a, **k):
            if seen:   # 止める口が数え上げに起こす ps は普通に待つ
                return super().communicate(*a, **k)
            seen.append(self)
            raise KeyboardInterrupt

    monkeypatch.setattr(role_run.subprocess, "Popen", Broken)
    try:
        with pytest.raises(KeyboardInterrupt):
            role_run.run_tree([sys.executable, "-c", "import time; time.sleep(120)"], cwd=tmp_path, timeout=None)
        assert seen and seen[0].poll() is not None   # _kill が止めて wait まで済ませている
    finally:
        for p in seen:
            if p.poll() is None:
                p.kill()
                p.wait()


@pytest.mark.parametrize("stderr,want", [("", role_run.GONE), ("ps: 読めない", None)])
def test_started_at_empty_ps_output(monkeypatch, stderr, want):
    """ps が何も出さないのは『居ない』。誤りの文が在るなら『確かめられない』"""
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix"))
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", stderr))
    assert role_run._started_at(4242) == want


@pytest.mark.parametrize("osname,want,kept", [("nt", (None, None), False), ("posix", (4242, None), True)])
def test_probe_group_when_leader_is_gone(tmp_path, monkeypatch, osname, want, kept):
    """長が居ないとき、Windows は止める物が無い（印を消す）、POSIX は孫が残りうるので止める側に倒す"""
    m = mark(tmp_path)
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name=osname))
    monkeypatch.setattr(role_run, "_started_at", lambda pid: role_run.GONE)
    assert role_run.probe_group(str(m)) == want
    assert m.exists() == kept


@pytest.mark.parametrize("rc,started,fails", [
    pytest.param(0, 123.0, False, id="taskkill-ok"),
    pytest.param(1, role_run.GONE, False, id="taskkill-failed-but-gone"),
    pytest.param(1, 123.0, True, id="taskkill-failed-and-alive"),
])
def test_stop_group_windows(tmp_path, monkeypatch, rc, started, fails):
    """Windows の taskkill: 非 0 でも相手が居なくなっていれば止まったと数える。止まったら印を消す"""
    m = mark(tmp_path)
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(role_run, "probe_group", lambda f: (4242, None))
    monkeypatch.setattr(role_run, "_started_at", lambda pid: started)
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, rc, "", "err"))
    why = role_run.stop_group(str(m))
    assert (why is not None and "taskkill" in why) == fails
    assert m.exists() == fails


def proc(pid, pgid=4242, stat="S", ppid=1, started=100.0, uid=501):
    return role_run._Proc(pid, ppid, pgid, uid, started, stat)


def posix(monkeypatch, members, sent, eperm=False):
    """role_run の os を POSIX の代役に替える。members(sent) が数え上げの答え（{pid: _Proc}）、sent は送った (宛先, 信号)。
    eperm なら送る口が PermissionError（sandbox の中から別のグループへ送った形）"""
    def send(kind):
        def f(target, sig):
            if sig == 0:
                if not any(pid == target for pid in members(sent)):
                    raise ProcessLookupError
                return
            sent.append((kind, target, sig))
            if eperm:
                raise PermissionError(1, "Operation not permitted")
        return f
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix", killpg=send("pg"), kill=send("pid")))
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: (members(sent), None))
    monkeypatch.setattr(role_run, "STOP_SIGNALS", (15, 9))
    monkeypatch.setattr(role_run, "KILL_GRACE", 0.3)
    monkeypatch.setattr(role_run, "probe_group", lambda f: (4242, None))


def test_stop_group_posix_group_already_gone(tmp_path, monkeypatch):
    """信号を送る前に木の仲間が居なければ、送らずに止まったと数えて印を消す"""
    m = mark(tmp_path)
    sent = []
    posix(monkeypatch, lambda s: {}, sent)
    assert role_run.stop_group(str(m)) is None
    assert not m.exists() and sent == []


def test_stop_group_reads_the_reuse_mark_before_probing(tmp_path, monkeypatch):
    """再利用の目印（印の更新時刻）は probe_group より先に読む——確かめた後に子が終わって印が消えても、_stop_tree に目印が渡る"""
    m = mark(tmp_path)
    written = m.stat().st_mtime
    got = {}

    def probe(f):
        m.unlink()   # 確かめた直後に子が終わり、launch の側が印を消した
        return 4242, None
    monkeypatch.setattr(role_run, "probe_group", probe)
    monkeypatch.setattr(role_run, "_stop_tree", lambda pgid, leader=None, born=None: got.update(born=born))
    assert role_run.stop_group(str(m)) is None and got["born"] == written


def test_stop_group_posix_zombies_only_is_gone(tmp_path, monkeypatch):
    """仲間がゾンビ（回収待ち）だけなら止まったと数える——macOS はゾンビだけのグループへの killpg を EPERM で拒む"""
    m = mark(tmp_path)
    sent = []
    posix(monkeypatch, lambda s: {4242: proc(4242, stat="Z")}, sent, eperm=True)
    assert role_run.stop_group(str(m)) is None
    assert not m.exists() and sent == []


def test_stop_group_posix_eperm_on_a_live_member_says_why_at_once(tmp_path, monkeypatch):
    """生きた仲間が居るのに送れない（sandbox の中から別のグループへ）なら、待たずに原因を言い、印を残す"""
    m = mark(tmp_path)
    sent = []
    posix(monkeypatch, lambda s: {4242: proc(4242)}, sent, eperm=True)
    why = role_run.stop_group(str(m))
    assert why == "グループ 4242 に信号を送れない（[Errno 1] Operation not permitted）"
    assert sent == [("pg", 4242, 15)] and m.exists()


def test_stop_group_posix_signals_members_outside_the_group(tmp_path, monkeypatch):
    """グループの外へ出た仲間にも送る: 長が仲間のグループには killpg、長の居ないグループの仲間には 1 本ずつ"""
    m = mark(tmp_path)
    sent = []
    tree = {4242: proc(4242), 5000: proc(5000, pgid=5000), 6000: proc(6000, pgid=7777)}
    posix(monkeypatch, lambda s: tree if not s else {}, sent)
    assert role_run.stop_group(str(m)) is None
    assert sorted(sent) == [("pg", 4242, 15), ("pg", 5000, 15), ("pid", 6000, 15)]


@pytest.mark.parametrize("platform,tools,want", [
    pytest.param("win32", {"bwrap", "socat"}, False, id="windows"),
    pytest.param("linux", {"socat"}, False, id="linux-without-bwrap"),
    pytest.param("linux", {"bwrap"}, False, id="linux-without-socat"),
    pytest.param("linux", {"bwrap", "socat"}, True, id="linux-with-both"),
])
def test_sandbox_available_off_macos(monkeypatch, platform, tools, want):
    """macOS 以外: Linux で bwrap と socat の両方が在り、bwrap が名前空間を作れるときだけ真。ほかは bwrap を試さずに偽"""
    ran = []
    monkeypatch.setattr(role_run, "sys", types.SimpleNamespace(platform=platform))
    monkeypatch.setattr(role_run, "shutil", types.SimpleNamespace(which=lambda n: f"/usr/bin/{n}" if n in tools else None))
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: ran.append(argv) or subprocess.CompletedProcess(argv, 0, b"", b""))
    assert role_run.sandbox_available() is want
    assert bool(ran) == want


def test_sandbox_available_on_macos_needs_only_sandbox_exec(monkeypatch):
    """macOS は sandbox-exec が在れば真（bwrap は試さない）"""
    ran = []
    monkeypatch.setattr(role_run, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(role_run, "shutil", types.SimpleNamespace(which=lambda n: "/usr/bin/sandbox-exec" if n == "sandbox-exec" else None))
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: ran.append(argv))
    assert role_run.sandbox_available() is True and not ran


@pytest.mark.parametrize("worktrees", [pytest.param((False, [], "失敗"), id="worktree-list-fails"),
                                       pytest.param((True, ["worktree /w"], ""), id="no-common-dir")])
def test_protected_paths_is_undecided_when_git_answers_partly(tmp_path, monkeypatch, worktrees):
    """共有の .git か作業ツリーの一覧のどちらかが引けなければ、守る場所は決まらない（None——sandbox の形を選ばない）"""
    common = (True, [], "") if worktrees[0] else (True, [str(tmp_path / ".git")], "")
    monkeypatch.setattr(role_run, "_git", lambda cwd, *args: common if "rev-parse" in args else worktrees)
    assert role_run.protected_paths(tmp_path) is None


def test_started_at_on_windows_reads_the_cim_answer(monkeypatch):
    """Windows は PowerShell の答え（alive:<FILETIME>）を開始時刻に読む（ps の etime として読まない）"""
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "alive:116444736000000000\r\n", ""))
    assert role_run._started_at(4242) == 0.0


def test_parse_cim_needs_the_alive_prefix():
    assert role_run.parse_cim("116444736000000000") is None   # 接頭の無い数を開始時刻と読まない


def test_started_at_unreadable_etime_is_unknown(monkeypatch):
    """ps が読めない etime を返したら『確かめられない』（None）"""
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix"))
    monkeypatch.setattr(role_run.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "読めない\n", ""))
    assert role_run._started_at(4242) is None


def test_parse_etime_refuses_four_fields():
    assert role_run.parse_etime("1:02:03:04") is None   # [[dd-]hh:]mm:ss より多い区切りを時刻と読まない


def test_run_role_reports_a_role_it_could_not_start(tmp_path):
    """子を起こせなかった回は『起こせない』と理由を言う（空の標準出力の包みの誤りに化けない）"""
    prompt = tmp_path / "p.md"
    prompt.write_text("指示書", encoding="utf-8")
    r = role_run.run_role(["no-such-command-gl-test"], prompt, tmp_path / "out.json")
    assert not r["ok"] and r["why"].startswith("起こせない: ") and len(r["runs"]) == 1


@pytest.mark.parametrize("dies_after", [pytest.param(15, id="dies-on-term"), pytest.param(None, id="never-dies")])
def test_stop_group_posix_watches_the_tree(tmp_path, monkeypatch, dies_after):
    """送った後は数え直して、仲間が消えたら止まったと数える。消えなければ SIGKILL の後も残った仲間を名指しする"""
    m = mark(tmp_path)
    sent = []
    posix(monkeypatch, lambda s: {} if dies_after in [sig for _, _, sig in s] else {4242: proc(4242), 4300: proc(4300, pgid=4300)}, sent)
    why = role_run.stop_group(str(m))
    if dies_after is None:
        assert why == "グループ 4242 の木が SIGKILL の後も残っている（pid 4242（pgid 4242・S）, pid 4300（pgid 4300・S））"
        assert [sig for _, _, sig in sent] == [15, 15, 9, 9] and m.exists()
    else:
        assert why is None and [sig for _, _, sig in sent] == [15, 15] and not m.exists()


def test_stop_group_posix_unreadable_table_is_not_stopped(tmp_path, monkeypatch):
    """全プロセスの表が読めなければ、グループへは今どおり送るが、外へ出た子孫を確かめていないので止まったと言わない"""
    m = mark(tmp_path)
    sent = []
    posix(monkeypatch, lambda s: {}, sent)
    monkeypatch.setattr(role_run, "_tree_members", lambda pgid, known=None, born=None: (None, "ps が無い"))
    why = role_run.stop_group(str(m))
    assert why.startswith("止める相手を数え上げられない（ps が無い）") and ("pg", 4242, 15) in sent and m.exists()


def members_of(monkeypatch, rows, sessions, me=100):
    """_tree_members を、全プロセスの表と getsid の答えを差し替えて呼ぶ口を返す（sessions の値が例外ならそれを上げる）"""
    def getsid(pid):
        v = sessions.get(pid, 1)
        if isinstance(v, BaseException):
            raise v
        return v
    monkeypatch.setattr(role_run, "_ps_all", lambda: ({r.pid: r for r in rows}, None))
    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix", getsid=getsid, getpid=lambda: me, getuid=lambda: 501))
    return lambda pgid, known=None, born=None: role_run._tree_members(pgid, known, born)


def test_tree_members_follows_group_session_and_parents(monkeypatch):
    """仲間はグループ・セッション（setpgid で抜けた孫）・親子の鎖（setsid で抜けた孫とその子）で拾い、自分と祖先は除く。
    前に数えた pid は同じ開始時刻で居るときだけ起点にする（番号の再利用で木の外へ送らない）"""
    rows = [proc(1, pgid=1, ppid=0), proc(100, pgid=100, ppid=1), proc(4242, ppid=100),
            proc(4300, pgid=4300, ppid=4242),                    # setpgid で抜けた孫（セッションは 4242 のまま）
            proc(4400, pgid=4400, ppid=4242), proc(4401, pgid=4400, ppid=4400),   # setsid で抜けた孫とその子
            proc(4500, pgid=4500, ppid=1),                       # 長が死んだ後の孤児（セッションは 4242）
            proc(9000, pgid=9000, ppid=1, started=500.0),        # 前に数えた番号が再利用された別物
            proc(9100, pgid=9100, ppid=1, started=100.0)]        # 前に数えた、同じ開始時刻の仲間
    count = members_of(monkeypatch, rows, {4242: 4242, 4300: 4242, 4400: 4400, 4401: 4400, 4500: 4242, 100: 4242})
    found, why = count(4242, known={9000: 100.0, 9100: 100.0})
    assert sorted(found) == [4242, 4300, 4400, 4401, 4500, 9100] and why is None


@pytest.mark.parametrize("leader_started,want", [pytest.param(100.0, [4242, 4300], id="same-leader"),
                                                  pytest.param(900.0, [], id="number-reused")])
def test_tree_members_ignores_a_reused_leader_number(monkeypatch, leader_started, want):
    """長の番号に、長を起こした時刻（born）より後に始まったプロセスが居れば、番号は再利用されている——グループとセッションでは
    拾わない（止める間に木が消え、無関係なプロセスがその番号で setsid した形に SIGKILL を送らない）"""
    rows = [proc(100, pgid=100), proc(4242, started=leader_started), proc(4300, pgid=4300, ppid=1, started=leader_started)]
    count = members_of(monkeypatch, rows, {4242: 4242, 4300: 4242})
    found, why = count(4242, born=100.0)
    assert sorted(found) == want and why is None


def test_tree_members_unreadable_session_of_the_same_user(monkeypatch):
    """同じ利用者のプロセスのセッションが読めなければ、仲間か決められないので理由を返す（他の利用者の物は問わない）"""
    rows = [proc(100, pgid=100), proc(4242), proc(8000, pgid=8000), proc(8100, pgid=8100, uid=0)]
    count = members_of(monkeypatch, rows, {4242: 4242, 8000: PermissionError(), 8100: PermissionError()})
    found, why = count(4242)
    assert sorted(found) == [4242] and why == "セッションの番号を読めないプロセスが在り、木の仲間かを決められない（pid [8000]）"


def test_run_role_without_resume_argv_stops_after_a_rejection(tmp_path):
    """続ける語（resume_argv）の無い役は、会話の番号が在っても拒否の後に続きを頼まず 1 起動で止まる"""
    prompt = tmp_path / "p.md"
    prompt.write_text("指示書", encoding="utf-8")
    env = json.dumps({"type": "result", "subtype": "success", "result": "散文", "session_id": "s-1"})
    argv = [sys.executable, "-c", f"print({env!r})"]
    r = role_run.run_role(argv, prompt, tmp_path / "out.json", accept=lambda t: "JSON でない", max_resumes=2)
    assert not r["ok"] and r["session_id"] == "s-1" and len(r["runs"]) == 1 and r["rejections"] == ["JSON でない"]



def test_kill_all_says_which_tree_it_could_not_stop(monkeypatch, capsys):
    """止め切れなかった木は理由を標準エラーに出す（黙って止めたことにしない）"""
    class Fake:
        pid = 4242
    monkeypatch.setattr(role_run, "LIVE", {Fake()})
    monkeypatch.setattr(role_run, "_kill", lambda p: "検査用の止め切れない理由")
    role_run.kill_all()
    assert "NG 子の木を止め切れない（pid 4242）: 検査用の止め切れない理由" in capsys.readouterr().err


def test_stop_handler_marks_stopping_then_raises(monkeypatch):
    """止める信号の口は、止め始めた印を立て（以後に起こす子はすぐ止まる）、生きている子を止めてから StopSignal を上げる"""
    import signal
    seen = {}
    monkeypatch.setattr(signal, "signal", lambda sig, fn: seen.setdefault("fn", fn))
    monkeypatch.setattr(role_run, "kill_all", lambda: seen.setdefault("killed", role_run._STOPPING.is_set()))
    role_run.install_stop_handlers()
    try:
        with pytest.raises(role_run.StopSignal):
            seen["fn"](15, None)
        assert role_run._STOPPING.is_set() and seen["killed"] is True
    finally:
        role_run._STOPPING.clear()


def test_stop_tree_reaps_the_leader_it_holds(monkeypatch):
    """長の Popen を持って止めるときは待つ間に回収する——回収しない長はゾンビのままグループに残り、消滅が見えない"""
    monkeypatch.setattr(role_run, "KILL_GRACE", 2)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        assert role_run._stop_tree(p.pid, leader=p) is None
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
