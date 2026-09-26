"""graphloops/engine/role_run.py の子を止める部品——run_tree の中断・_started_at（居ない番号）・probe_group と stop_group の
印の後始末。OS の分岐は role_run の os を差し替えて両側を見る（CI は 3 OS で回すが、それぞれの OS では片側しか通らない）。
子プロセスを本当に止める端から端までの形は tests/simulate.py の test_role_run が見る。"""
import json
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


def test_stop_group_posix_group_already_gone(tmp_path, monkeypatch):
    """信号を送る前にグループが消えていたら、止まったと数えて印を消す"""
    m = mark(tmp_path)

    def killpg(pgid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(role_run, "STOP_SIGNALS", (15, 9))
    monkeypatch.setattr(role_run, "probe_group", lambda f: (4242, None))
    assert role_run.stop_group(str(m)) is None
    assert not m.exists()


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
def test_stop_group_posix_watches_the_group(tmp_path, monkeypatch, dies_after):
    """信号を送った後はグループの生存（kill(-pgid, 0)）を見て、消えたら止まったと数える。消えなければ SIGKILL の後も残ったと言う"""
    m = mark(tmp_path)
    sent = []

    def killpg(pgid, sig):
        if sig == 0:
            if dies_after is not None and dies_after in sent:
                raise ProcessLookupError
            return
        sent.append(sig)

    monkeypatch.setattr(role_run, "os", types.SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(role_run, "STOP_SIGNALS", (15, 9))
    monkeypatch.setattr(role_run, "KILL_GRACE", 0.3)
    monkeypatch.setattr(role_run, "probe_group", lambda f: (4242, None))
    why = role_run.stop_group(str(m))
    if dies_after is None:
        assert why == "グループ 4242 が SIGKILL の後も残っている" and sent == [15, 9] and m.exists()
    else:
        assert why is None and sent == [15] and not m.exists()


def test_run_role_without_resume_argv_stops_after_a_rejection(tmp_path):
    """続ける語（resume_argv）の無い役は、会話の番号が在っても拒否の後に続きを頼まず 1 起動で止まる"""
    prompt = tmp_path / "p.md"
    prompt.write_text("指示書", encoding="utf-8")
    env = json.dumps({"type": "result", "subtype": "success", "result": "散文", "session_id": "s-1"})
    argv = [sys.executable, "-c", f"print({env!r})"]
    r = role_run.run_role(argv, prompt, tmp_path / "out.json", accept=lambda t: "JSON でない", max_resumes=2)
    assert not r["ok"] and r["session_id"] == "s-1" and len(r["runs"]) == 1 and r["rejections"] == ["JSON でない"]
