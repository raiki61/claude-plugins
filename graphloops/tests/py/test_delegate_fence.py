"""任せ先（delegate）の柵: 守る場所を git から引く・本物の写しを作る・権限と sandbox の形・起こす瞬間の突き合わせ。

配布先で Agent ツールの任せ先が本物の作業ツリーで git reset --hard を打った事故（2026-09-25）への直しの、関数を直に呼ぶ検査。
盤面を端から端まで回す検査（next が launch を付ける・launch が写しの上で起こす・背景の線）は tests/simulate_review.py に在る。
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from engine import commands, role_run, util


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """本体 1 つと linked worktree 1 つ。engine の git は本体に向ける（盤面の inputs.cwd と同じ）"""
    r = tmp_path / "main"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    (r / "gone.txt").write_text("g\n")
    (r / ".gitignore").write_text("ignored/\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "base")
    git(r, "worktree", "add", "-q", str(tmp_path / "other"), "-b", "other")
    monkeypatch.setattr(util, "GIT_CWD", str(r))
    return r


def test_protected_paths_names_tree_gitdirs_worktrees_and_board(repo, tmp_path):
    board = tmp_path / "board"
    got = util.protected_paths([board])
    real = lambda p: os.path.realpath(p)
    for p in (repo, repo / ".git", tmp_path / "other", board, util.PLUGIN_ROOT, pathlib.Path.home() / ".gitconfig"):
        assert real(p) in got, p
    # 綴りと実体の両方（macOS の /var と /private/var）
    assert os.path.abspath(repo) in got
    assert got == sorted(set(got))


def test_protected_paths_linked_worktree_names_its_gitdir_and_the_common_dir(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(util, "GIT_CWD", str(tmp_path / "other"))
    got = util.protected_paths()
    assert os.path.realpath(repo / ".git" / "worktrees" / "other") in got
    assert os.path.realpath(repo / ".git") in got
    assert os.path.realpath(repo) in got


def test_protected_paths_none_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(util, "GIT_CWD", str(tmp_path))
    assert util.protected_paths() is None


def test_copy_worktree_mirrors_uncommitted_state_without_touching_the_real_git(repo, tmp_path):
    (repo / "a.txt").write_text("changed\n")
    (repo / "new.txt").write_text("n\n")
    (repo / "gone.txt").unlink()
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x").write_text("x\n")
    before = git(repo, "worktree", "list", "--porcelain"), git(repo, "status", "--porcelain")
    dst = util.copy_worktree(tmp_path / "copy")
    c = pathlib.Path(dst)
    assert (c / "a.txt").read_text() == "changed\n"
    assert (c / "new.txt").read_text() == "n\n"
    assert not (c / "gone.txt").exists()
    assert not (c / "ignored").exists()
    assert git(c, "rev-parse", "HEAD") == git(repo, "rev-parse", "HEAD")
    assert git(c, "status", "--porcelain") == before[1]
    # 本物の .git に何も足していない（worktree の登録も index も）
    assert (git(repo, "worktree", "list", "--porcelain"), git(repo, "status", "--porcelain")) == before
    # 写しは独立の clone（.git はディレクトリで、本物の gitdir を指すファイルではない）
    assert (c / ".git").is_dir()


def test_delegate_permission_does_not_preallow_bash_and_has_no_write_tools():
    mode, allowed = role_run.delegate_permission()
    assert mode == "default"
    assert "Bash" in role_run.DELEGATE_TOOLS and "Bash" not in allowed
    assert not set(role_run.DELEGATE_TOOLS) & set(role_run.WRITE_TOOLS)


def test_delegate_settings_is_strict_and_stable():
    s = json.loads(role_run.delegate_settings(["/x", "/y"]))["sandbox"]
    assert s["enabled"] and s["autoAllowBashIfSandboxed"] and s["failIfUnavailable"]
    assert s["allowUnsandboxedCommands"] is False
    assert s["filesystem"]["denyWrite"] == ["/x", "/y"]
    assert role_run.delegate_settings(["/x", "/y"]) == role_run.delegate_settings(["/x", "/y"])


def _good_launch(board, stdin):
    mode, allowed = role_run.delegate_permission()
    words = ["claude", "-p", "--model", "haiku", "--tools", ",".join(role_run.DELEGATE_TOOLS), "--allowedTools", ",".join(allowed),
             "--permission-mode", mode, "--permission-prompts", "none", "--setting-sources", "",
             "--settings", role_run.delegate_settings(util.protected_paths([board])), "--append-system-prompt-file", str(stdin),
             "--output-format", "json"]
    return {"kind": "delegate", "argv": commands.launch_prefix() + words, "stdin": str(stdin), "resume_argv": None}


def test_delegate_refusal_accepts_the_engine_shape(repo, tmp_path):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    assert commands.launch_refusal({"launch": _good_launch(tmp_path / "b", stdin), "delegate": {"model": "haiku"}}, board_dir=tmp_path / "b") is None


@pytest.mark.parametrize("mutate, want", [
    (lambda a: [x.replace("Bash,", "Bash,Write,", 1) if x.startswith("Bash,") else x for x in a], "--tools"),
    (lambda a: [("dontAsk" if x == "default" else x) for x in a], "--permission-mode"),
    (lambda a: [x.replace("Read,", "Bash,Read,", 1) if x.startswith("Read,") else x for x in a], "--allowedTools"),
    (lambda a: a + ["--add-dir", "/"], "--add-dir"),
    (lambda a: a + ["--dangerously-skip-permissions"], "--dangerously-skip-permissions"),
    (lambda a: [x for i, x in enumerate(a) if not (x == "--setting-sources" or (i and a[i - 1] == "--setting-sources"))], "--setting-sources"),
])
def test_delegate_refusal_arms(repo, tmp_path, mutate, want):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _good_launch(tmp_path / "b", stdin)
    why = commands.launch_refusal({"launch": {**good, "argv": mutate(good["argv"])}, "delegate": {"model": "haiku"}}, board_dir=tmp_path / "b") or ""
    assert want in why


def test_delegate_refusal_rebuilds_the_fence_at_launch_time(repo, tmp_path):
    """next の後に作業ツリーが足されたら、argv の名指しが今の守る場所と揃わないので起こさない"""
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _good_launch(tmp_path / "b", stdin)
    git(repo, "worktree", "add", "-q", str(tmp_path / "late"), "-b", "late")
    assert "--settings" in (commands.launch_refusal({"launch": good, "delegate": {"model": "haiku"}}, board_dir=tmp_path / "b") or "")
    # 盤面を名指ししない柵（board 無し）も起こさない
    assert "守る場所" in (commands.launch_refusal({"launch": _good_launch(tmp_path / "b", stdin), "delegate": {"model": "haiku"}}, board_dir=None) or "")


def test_delegate_refusal_when_git_cannot_name_the_fence(repo, tmp_path, monkeypatch):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _good_launch(tmp_path / "b", stdin)
    monkeypatch.setattr(util, "GIT_CWD", str(tmp_path / "nowhere"))
    assert "守る場所" in (commands.launch_refusal({"launch": good, "delegate": {"model": "haiku"}}, board_dir=tmp_path / "b") or "")


def test_run_role_without_deadline_waits_to_the_end(tmp_path):
    """背景の線は期限で止めない——run_role に時間の上限は無く、子の終了まで待つ"""
    prompt = tmp_path / "p"
    prompt.write_text("hi")
    out = tmp_path / "o"
    argv = [sys.executable, "-c", "import sys,time; sys.stdin.read(); time.sleep(0.2); print('done-body')"]
    r = role_run.run_role(argv, prompt, out)
    assert r["ok"] and not r["superseded"] and out.read_text().strip() == "done-body"
