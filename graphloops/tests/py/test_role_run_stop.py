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
