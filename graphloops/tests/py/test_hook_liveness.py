"""読了のフックが終わった run に書かないこと・init の自己点検（フックが動くか・この盤面を見つけるか）・linked worktree の盤面の知らせ。
本物の git の使い捨てのリポジトリと、本物のフックのプロセス（hooks/record-read.py）の上で直に呼ぶ"""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from engine import commands, util

PLUGIN = pathlib.Path(__file__).resolve().parents[2]
HOOK = PLUGIN / "hooks" / "record-read.py"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


def fire(cwd, path):
    payload = {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Read", "tool_use_id": "toolu_t",
               "cwd": str(cwd), "tool_input": {"file_path": str(path)}, "tool_response": {"type": "text"}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr


def board(gitdir, loop, run, status):
    """`<gitdir>/graphloops/<loop>/<run>/`（state.json の status を持つ）を作り、current をそこへ向ける"""
    d = pathlib.Path(gitdir) / "graphloops" / loop / run
    d.mkdir(parents=True)
    if status is not None:
        (d / "state.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    (d.parent / "current").write_text(str(d) + "\n", encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "doc.md").write_text("doc\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "base")
    return r.resolve()


def test_terminal_status_copy_matches_engine():
    """フックは engine を読み込まない（Read のたびに走る）ので終わりの値を写して持つ——写しが engine とずれたら赤"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gl_record_read", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert tuple(mod.TERMINAL_STATUS) == tuple(util.TERMINAL_STATUS)


def test_hook_writes_only_live_runs(repo):
    """current が終わった run を指したままでも書かない（2026-10-19: 終わった run に 3 日で 1,310 行溜まった）。回っている run には書く"""
    git_dir = repo / ".git"
    running = board(git_dir, "research-loop", "r1", "running")
    stopped = board(git_dir, "review-loop", "r2", "stopped")
    converged = board(git_dir, "x-loop", "r3", "converged")
    bare = board(git_dir, "y-loop", "r4", None)
    fire(repo, repo / "doc.md")
    assert (running / "reads.jsonl").is_file()
    for d in (stopped, converged, bare):
        assert not (d / "reads.jsonl").exists(), d


def test_selfcheck_passes_and_leaves_board_untouched(repo):
    d = board(repo / ".git", "research-loop", "r1", "running")
    assert commands.hook_selfcheck(d, repo) is None
    # **本物の盤面に試しの行を書かない**——在るだけで hook_evidence が none から absent に変わる
    assert not (d / "reads.jsonl").exists()


def test_selfcheck_names_board_the_hook_cannot_find(repo):
    d = board(repo / ".git", "research-loop", "r1", "running")
    (d.parent / "current").unlink()
    why = commands.hook_selfcheck(d, repo)
    assert why and "行き着かない" in why and str(d) in why


def test_selfcheck_names_missing_registration(tmp_path, monkeypatch, repo):
    root = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "hooks", root / "hooks")
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": []}}), encoding="utf-8")
    monkeypatch.setattr(commands, "PLUGIN_ROOT", root)
    d = board(repo / ".git", "research-loop", "r1", "running")
    why = commands.hook_selfcheck(d, repo)
    assert why and "登録" in why and "転写の走査だけ" in why


def test_selfcheck_names_hook_that_writes_nothing(tmp_path, monkeypatch, repo):
    """登録の語は在るが、走っても行を書かない（python が無い・本体が壊れた）"""
    root = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "hooks", root / "hooks")
    (root / "hooks" / "record-read.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    monkeypatch.setattr(commands, "PLUGIN_ROOT", root)
    d = board(repo / ".git", "research-loop", "r1", "running")
    why = commands.hook_selfcheck(d, repo)
    assert why and "行を書かない" in why


def test_worktree_board_notice(repo, tmp_path):
    """linked worktree の git ディレクトリの下の盤面だけを名指し、写す先（共有の .git の boards-archive）を出す"""
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt))
    wt_gitdir = pathlib.Path(git(wt, "rev-parse", "--path-format=absolute", "--git-dir").strip()).resolve()
    d = board(wt_gitdir, "review-loop", "r1", "running")
    why = commands.worktree_board_notice(d)
    assert why and "git worktree remove" in why and str(wt.resolve()) in why
    assert str(repo / ".git" / "graphloops" / "boards-archive" / wt_gitdir.name) in why
    assert commands.worktree_board_notice(board(repo / ".git", "review-loop", "r0", "running")) is None   # 本体の .git の下
    assert commands.worktree_board_notice(tmp_path / "elsewhere") is None                                # --dir で外に置いた盤面


def test_selfcheck_failure_is_a_notice_not_a_crash(repo, monkeypatch):
    """一時の置き場に書けない（TMPDIR が書けないなど）——init は盤面と current を書いた後に呼ぶので、落とさずに知らせの文にする"""
    def unwritable(*a, **k):
        raise PermissionError("検査用")
    monkeypatch.setattr(commands.tempfile, "TemporaryDirectory", unwritable)
    d = board(repo / ".git", "research-loop", "r1", "running")
    why = commands.hook_selfcheck(d, repo)
    assert why and "PermissionError" in why and "確かめていない" in why
