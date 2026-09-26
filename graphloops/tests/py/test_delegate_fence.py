"""任せ先（delegate）の柵: 守る場所を git から引く・本物の写しを作る・権限と sandbox の形・起こす瞬間の突き合わせ。

配布先で Agent ツールの任せ先が本物の作業ツリーで git reset --hard を打った事故（2026-09-25）への直しの、関数を直に呼ぶ検査。
盤面を端から端まで回す検査（next が launch を付ける・launch が写しの上で起こす・背景の線）は tests/simulate_review.py に在る。
"""
import json
import os
import pathlib
import shutil
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


def _delegate_board(tmp_path, graph):
    import types
    return types.SimpleNamespace(graph=graph, dir=tmp_path / "board")


def test_delegate_launch_spec_needs_the_graph_words(tmp_path):
    """graph に launch.delegate が無ければ任せ先の起こし方を組まない（None——回す側に柵を組めないと言う）"""
    from engine.advance import delegate_launch_spec
    assert delegate_launch_spec(_delegate_board(tmp_path, {}), {}, {"delegate": {"model": "haiku"}}, {}) is None


def test_delegate_launch_spec_resolves_claude_on_path(repo, tmp_path, monkeypatch):
    """起こす語の claude は PATH で引いた実体に置き換える（前置の層の後ろ）。引けなければ missing に名前を残す"""
    from engine import advance
    spec = {"argv": ["claude", "-p", "--model", "{model}"], "via": ["{python}", "{plugin_root}/scripts/with-auth.py"], "preamble": "p"}
    b = _delegate_board(tmp_path, {"launch": {"delegate": spec}})
    inst = {"id": "p4.ci", "prompt_file": str(tmp_path / "p.md"), "out_path": str(tmp_path / "o.json")}
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/bin/{name}")
    got = advance.delegate_launch_spec(b, inst, {"delegate": {"model": "haiku"}}, {})
    assert got["argv"][2] == "/opt/bin/claude" and "missing" not in got
    monkeypatch.setattr(shutil, "which", lambda name: None)
    got = advance.delegate_launch_spec(b, inst, {"delegate": {"model": "haiku"}}, {})
    assert got["argv"][2] == "claude" and got["missing"] == "claude"


# ---- 0.20.2 の取りまとめで足した検査（変異の腕が bash の台本でも pytest でも生き残った所） ----

def _board(tmp_path, launch):
    import types
    g = {"launch": {"delegate": launch}} if launch is not None else {"launch": {}}
    return types.SimpleNamespace(graph=g, dir=tmp_path / "board")


def _inst(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x")
    return {"id": "p0.x", "prompt_file": str(prompt), "out_path": str(tmp_path / "out.json")}


def test_delegate_launch_spec_is_none_without_launch_delegate(repo, tmp_path):
    """graph に launch.delegate が無ければ起こす語を作らない（回す側が Agent で起こす古い graph）"""
    from engine import advance
    assert advance.delegate_launch_spec(_board(tmp_path, None), _inst(tmp_path), {"delegate": {"model": "haiku"}}, {}) is None


def test_delegate_launch_spec_writes_the_preamble_and_fills_the_holes(repo, tmp_path):
    from engine import advance
    spec = {"argv": [sys.executable, "--model", "{model}", "--settings", "{settings}"], "preamble": "前置きの文\n",
            "via": ["{python}"]}
    got = advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), {"delegate": {"model": "haiku"}}, {})
    role = tmp_path / "board" / "roles" / "delegate.txt"
    assert role.read_text(encoding="utf-8") == "前置きの文\n"
    assert got["argv"][0] == sys.executable and got["argv"][2:4] == ["--model", "haiku"]
    assert json.loads(got["argv"][5])["sandbox"]["filesystem"]["denyWrite"] == util.protected_paths([tmp_path / "board"])
    assert "unprotected" not in got and "missing" not in got and "background" not in got


def test_delegate_launch_spec_without_preamble_via_or_model(repo, tmp_path):
    """前置き・via・model を持たない graph でも落ちない（空の役の文・前置きの層なし・空の model）"""
    from engine import advance
    spec = {"argv": [sys.executable, "--model", "{model}"]}
    got = advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), {"delegate": {}}, {})
    assert (tmp_path / "board" / "roles" / "delegate.txt").read_text(encoding="utf-8") == ""
    assert got["argv"] == [shutil.which(sys.executable), "--model", ""]


def test_delegate_launch_spec_marks_unprotected_and_missing(repo, tmp_path, monkeypatch):
    """守る場所を git から引けない・起こすコマンドが無い、を launch に書く（launch_refusal と回す側が読む）"""
    from engine import advance
    monkeypatch.setattr(advance, "protected_paths", lambda extra=(): None)
    spec = {"argv": ["graphloops-no-such-command-x", "-p"]}
    got = advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), {"delegate": {}}, {})
    assert "守る場所" in got["unprotected"]
    assert got["missing"] == "graphloops-no-such-command-x"


def test_delegate_launch_spec_background_needs_a_result_place(repo, tmp_path):
    from engine import advance
    spec = {"argv": [sys.executable]}
    n = {"delegate": {"background": True, "result_to": "loop.lane.result"}}
    got = advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), n, {"loop": {"lane": {"result": "/r.json"}}})
    assert got["background"] is True and got["result_path"] == "/r.json"
    with pytest.raises(SystemExit):
        advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), n, {"loop": {}})


def test_delegate_refusal_without_stdin(repo, tmp_path):
    good = _good_launch(tmp_path / "b", tmp_path / "p.md")
    del good["stdin"]
    assert "材料" in (commands.launch_refusal({"launch": good, "delegate": {"model": "haiku"}}, board_dir=tmp_path / "b") or "")


def test_launch_one_removes_the_work_place_when_the_copy_fails(repo, tmp_path, monkeypatch):
    """写しを作れない回は、作りかけの置き場（graphloops-delegate-*）を残さずに理由を返す"""
    import tempfile
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.setattr(commands, "launch_refusal", lambda inst, cwd=None, d=None: None)

    def boom(dst):
        pathlib.Path(dst).mkdir()
        raise util.Reject("写せない")
    monkeypatch.setattr(commands, "copy_worktree", boom)
    inst = {"id": "p0.x", "node": "p0.x", "out_path": str(tmp_path / "o"),
            "launch": {"kind": "delegate", "background": True, "result_path": str(tmp_path / "r"), "argv": ["x"], "stdin": "x"}}
    got = commands.launch_one(str(tmp_path / "board"), inst, 0)
    assert got["ok"] is False and "写せない" in got["why"]
    assert list(tmp.iterdir()) == []


def test_kill_sends_sigkill_to_a_group_that_ignores_sigterm(monkeypatch):
    """SIGTERM を無視する子も、猶予の後に木ごと止める（Windows は taskkill /T /F の枝で同じく止まる）"""
    monkeypatch.setattr(role_run, "KILL_GRACE", 0.5)
    kw = ({"start_new_session": True} if os.name == "posix"
          else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    code = "import signal,sys,time\nif hasattr(signal,'SIGTERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(60)"
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, **kw)
    try:
        assert p.stdout.readline().strip() == b"ready"
        role_run._kill(p)
        p.wait(timeout=15)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_git_why_names_the_exit_when_stderr_is_empty(repo):
    why = []
    assert util.git("rev-parse", "--verify", "-q", "no-such-ref", why=why) is None
    assert why == ["exit 1（標準エラーは空）"]


def test_protected_paths_names_the_default_claude_config_dir(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert os.path.realpath(pathlib.Path.home() / ".claude") in util.protected_paths()


def test_copy_worktree_rejects_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(util, "GIT_CWD", str(tmp_path))
    with pytest.raises(util.Reject):
        util.copy_worktree(tmp_path / "copy")


def test_copy_worktree_rejects_when_the_clone_fails(repo, tmp_path):
    dst = tmp_path / "copy"
    dst.mkdir()
    (dst / "occupied").write_text("x")
    with pytest.raises(util.Reject):
        util.copy_worktree(dst)


def test_copy_worktree_rejects_when_git_cannot_list_the_changes(repo, tmp_path, monkeypatch):
    real = util.git
    monkeypatch.setattr(util, "git", lambda *a, **k: None if a[:1] == ("diff",) else real(*a, **k))
    with pytest.raises(util.Reject):
        util.copy_worktree(tmp_path / "copy")


def test_copy_worktree_keeps_a_gitlink_directory_and_drops_a_deleted_symlink(repo, tmp_path):
    """git diff が名指すが作業ツリーに無いパスのうち、写しの側がディレクトリの物（中身を持たない submodule）は消さず、
    symlink（指し先の無い物。is_file では拾えない）は消す。symlink を作れない Windows の checkout ではただのファイルになる"""
    head = git(repo, "rev-parse", "HEAD").strip()
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="no-such-target",
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},ln")
    git(repo, "commit", "-q", "-m", "gitlink and symlink")
    assert not (repo / "sub").exists() and not os.path.lexists(repo / "ln")
    c = pathlib.Path(util.copy_worktree(tmp_path / "copy"))
    assert (c / "sub").is_dir()
    assert not os.path.lexists(c / "ln")


def test_graphcheck_background_delegate_without_reads_is_ng_not_a_crash(tmp_path):
    """背景の任せ先の節が reads を持たない graph は、例外で死なずに NG の診断文で落ちる"""
    import copy
    import importlib.util
    from conftest import PLUGIN, REPO
    spec = importlib.util.spec_from_file_location("graphcheck", PLUGIN / "scripts" / "graphcheck.py")
    gc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    g = copy.deepcopy(json.loads((PLUGIN / "graphs" / "review-loop.json").read_text(encoding="utf-8")))
    bg = [k for k, v in g["nodes"].items() if isinstance(v.get("delegate"), dict) and v["delegate"].get("background")]
    assert bg
    del g["nodes"][bg[0]]["reads"]
    (tmp_path / "graphs").mkdir()
    shutil.copytree(PLUGIN / "prompts", tmp_path / "prompts")
    shutil.copytree(PLUGIN / "rules", tmp_path / "rules")
    path = tmp_path / "graphs" / "review-loop.json"
    path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    lines = []
    ok = gc.check(path, str(REPO / "scripts" / "review-record.py"), emit=lines.append)
    out = "\n".join(map(str, lines))
    assert not ok and "背景の任せ先は delegate.result_to" in out, out[-300:]


def test_delegate_launch_spec_resolves_the_command_and_the_resume_words(repo, tmp_path):
    """起こす語の頭は PATH で引いた実体に置き換え（柵の突き合わせと子の起動が同じ実体を指す）、resume の語も同じく組む"""
    from engine import advance
    spec = {"argv": ["git", "-p"], "resume": ["git", "--resume", "{session_id}"]}
    got = advance.delegate_launch_spec(_board(tmp_path, spec), _inst(tmp_path), {"delegate": {}}, {})
    assert got["argv"] == [shutil.which("git"), "-p"]
    assert got["resume_argv"] == [shutil.which("git"), "--resume", "{session_id}"]


def test_delegate_refusal_needs_the_engine_prefix(repo, tmp_path):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _good_launch(tmp_path / "b", stdin)
    bare = good["argv"][len(commands.launch_prefix()):]
    assert "前置" in (commands.launch_refusal({"launch": {**good, "argv": bare}}, board_dir=tmp_path / "b") or "")


def test_launch_one_background_delegate_has_no_deadline_and_places_the_answer(repo, tmp_path, monkeypatch):
    """背景の任せ先は期限を過ぎていても止めずに待ち、返答を線の置き場に置く（書きかけの .tmp は残さない）。
    子の TMPDIR は作ってある置き場を指す"""
    import tempfile
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.setattr(commands, "launch_refusal", lambda inst, cwd=None, d=None: None)
    board = tmp_path / "board"
    board.mkdir()
    prompt = tmp_path / "p.md"
    prompt.write_text("x")
    result = tmp_path / "lane.json"
    code = "import json,os,sys,time; sys.stdin.read(); time.sleep(2); print(json.dumps({'tmp': os.path.isdir(os.environ['TMPDIR'])}))"
    inst = {"id": "p3.x", "node": "p3.x", "out_path": str(tmp_path / "o"), "deadline_at": commands.now(),
            "launch": {"kind": "delegate", "background": True, "result_path": str(result), "argv": [sys.executable, "-c", code],
                       "stdin": str(prompt)}}
    (tmp_path / "o").write_text("受領の返答", encoding="utf-8")   # 背景の節の out_path は受領の返答の置き場（done 済み）
    # 起こした直後に盤面を読んで自分の試行かを確かめる（still_mine）——背景の任せ先は受領を done にしてから起こす
    (board / "state.json").write_text(json.dumps({"rounds": [{"instances": {"p3.x": {"out_path": inst["out_path"], "status": "done"}}}]}),
                                      encoding="utf-8")
    got = commands.launch_one(str(board), inst, 2)
    assert got["ok"] is True, got.get("why")
    assert json.loads(result.read_text(encoding="utf-8")) == {"tmp": True}
    assert not pathlib.Path(str(result) + ".tmp").exists()
    assert (tmp_path / "o").read_text(encoding="utf-8") == "受領の返答"   # 線の返答で受領の置き場を上書きしない


def test_kill_returns_once_the_group_is_gone(monkeypatch):
    """SIGTERM で終わる子なら、猶予を使い切らずにすぐ戻る（グループが空になった時点で止めたと数える）"""
    import time
    monkeypatch.setattr(role_run, "KILL_GRACE", 20)
    kw = ({"start_new_session": True} if os.name == "posix"
          else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen([sys.executable, "-c", "print('ready', flush=True); import time; time.sleep(60)"], stdout=subprocess.PIPE, **kw)
    try:
        assert p.stdout.readline().strip() == b"ready"
        t = time.monotonic()
        role_run._kill(p)
        assert p.poll() is not None and time.monotonic() - t < 10
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_copy_worktree_replaces_a_symlink_instead_of_writing_through_it(repo, tmp_path):
    """HEAD で symlink だったパスを作業ツリーでただのファイルにした回、写しの symlink を先に外してから写す——外さずに写すと
    指し先（a.txt）を書き換える。symlink を作れない Windows の checkout ではただのファイルなので同じく上書きで済む"""
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input="a.txt",
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},ln")
    git(repo, "commit", "-q", "-m", "symlink")
    (repo / "ln").write_text("plain\n")
    c = pathlib.Path(util.copy_worktree(tmp_path / "copy"))
    assert not (c / "ln").is_symlink() and (c / "ln").read_text() == "plain\n"
    assert (c / "a.txt").read_text() == "a\n"
