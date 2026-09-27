"""回す側の節を engine が起こす形（init --engine-runners）と、道具の一覧を持たない役を狭めて起こす形の柵。

書き換える節の子は、パスで縛った Edit・Write と OS の sandbox の中の Bash だけを持ち、書けるのは作業ツリーの根の中だけ——.git・ほかの
作業ツリー・盤面・利用者の設定は denyWrite。関数を直に呼ぶ検査で、実物の claude は起こさない（実物で拒まれることの確かめは
docs/graphloops-rearchitecture.md の手順 H の実測の段落）。
"""
import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

from conftest import PLUGIN, REPO
from engine import advance, commands, role_run, runner, util
from engine.rules import load_rules
from engine.schema import load_graph

LOOP = PLUGIN / "scripts" / "loop.py"
GRAPH = PLUGIN / "graphs" / "review-loop.json"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """本体 1 つと linked worktree 1 つ。engine の git は本体に向け、sandbox は使える場とする"""
    r = tmp_path / "main"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "base")
    git(r, "worktree", "add", "-q", str(tmp_path / "other"), "-b", "other")
    monkeypatch.setattr(util, "GIT_CWD", str(r))
    monkeypatch.setattr(role_run, "sandbox_available", lambda: True)
    return r


def _edit_perm(repo, board):
    return role_run.runner_permission(True, str(repo), str(board), util.protected_paths([board]), util.repo_root())


def test_edit_form_binds_write_tools_and_denies_everything_but_the_tree(repo, tmp_path):
    board = tmp_path / "board"
    perm = _edit_perm(repo, board)
    assert perm["form"] == "edit" and perm["permission_mode"] == "dontAsk"
    assert {"Edit", "Write", "Bash"} <= set(perm["tools"]) and not {"MultiEdit", "NotebookEdit"} & set(perm["tools"])
    assert "Edit(./**)" in perm["allowed_tools"] and "Write(./**)" in perm["allowed_tools"]
    assert not {"Edit", "Write", "Bash"} & set(perm["allowed_tools"])   # 縛りの無い書く道具・丸ごとの Bash は許さない
    sb = json.loads(perm["settings"])["sandbox"]
    assert sb["allowUnsandboxedCommands"] is False and sb["failIfUnavailable"] and sb["network"]["allowedDomains"] == []
    deny = set(sb["filesystem"]["denyWrite"])
    real = os.path.realpath
    assert real(repo) not in deny and os.path.abspath(repo) not in deny           # 作業ツリーの根の中は書ける
    for p in (repo / ".git", tmp_path / "other", board, util.PLUGIN_ROOT, pathlib.Path.home() / ".gitconfig"):
        assert real(p) in deny, p


def test_edit_form_in_a_linked_worktree_denies_its_gitdir_pointer(repo, tmp_path, monkeypatch):
    """linked worktree の .git は gitdir を指すファイル——書き換えると engine が打つ git の行き先が変わるので、根の中でも名指す"""
    other = tmp_path / "other"
    monkeypatch.setattr(util, "GIT_CWD", str(other))
    deny = set(json.loads(_edit_perm(other, tmp_path / "b")["settings"])["sandbox"]["filesystem"]["denyWrite"])
    assert os.path.realpath(other / ".git") in deny and os.path.realpath(other) not in deny
    assert os.path.realpath(repo) in deny and os.path.realpath(repo / ".git" / "worktrees" / "other") in deny


def test_edit_form_refuses_a_tree_nested_under_another_tree(repo, tmp_path, monkeypatch):
    """<repo>/.claude/worktrees/<名前> の形: 祖先を名指しすると根の中にも書けず、外すと祖先に書ける——起こさない"""
    nested = repo / ".claude" / "worktrees" / "x"
    git(repo, "worktree", "add", "-q", str(nested), "-b", "nested")
    monkeypatch.setattr(util, "GIT_CWD", str(nested))
    assert role_run.edit_deny(util.protected_paths([tmp_path / "b"]), util.repo_root()) is None
    assert _edit_perm(nested, tmp_path / "b") is None


def test_edit_form_needs_the_sandbox_and_the_read_form_falls_back(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(role_run, "sandbox_available", lambda: False)
    assert _edit_perm(repo, tmp_path / "b") is None                     # Bash 抜きの書く子に黙って落とさない
    read = role_run.runner_permission(False, str(repo), str(tmp_path / "b"))
    assert read["form"] == "read_only" and read["tools"] == list(role_run.RUNNER_READ_TOOLS)


def test_read_form_is_the_investigator_form(repo, tmp_path):
    """読むだけの節は道具つきの役（investigator）と同じ形——sandbox の中で測るコマンドを走らせられる（人の答え 2026-09-27）"""
    read = role_run.runner_permission(False, str(repo), str(tmp_path / "b"))
    want = role_run.tooled_permission(list(role_run.RUNNER_READ_TOOLS), str(repo), str(tmp_path / "b"))
    assert read["form"] == "sandbox" and {k: read[k] for k in want} == want
    assert not set(role_run.WRITE_TOOLS) & set(read["tools"])


def _runner_launch(repo, board, stdin, edits=True):
    perm = role_run.runner_permission(edits, str(repo), str(board), util.protected_paths([board]) if edits else None,
                                      util.repo_root() if edits else None)
    words = ["claude", "-p", "--model", "opus", "--effort", "high", "--tools", ",".join(perm["tools"]),
             "--allowedTools", ",".join(perm["allowed_tools"]), "--permission-mode", perm["permission_mode"],
             "--settings", perm["settings"], "--permission-prompts", "none", "--setting-sources", "",
             "--append-system-prompt-file", str(stdin), "--output-format", "json"]
    return {"kind": "runner", "argv": commands.launch_prefix() + words, "stdin": str(stdin), "resume_argv": None,
            "tools": perm["tools"], "form": perm["form"], "edits": edits, "model": "opus", "effort": "high"}


@pytest.mark.parametrize("edits", [True, False])
def test_runner_refusal_accepts_the_engine_shape(repo, tmp_path, edits):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    launch = _runner_launch(repo, tmp_path / "b", stdin, edits)
    assert commands.launch_refusal({"launch": launch}, cwd=str(repo), board_dir=tmp_path / "b") is None


def _swap(flag, fn):
    return lambda a: [fn(x) if i and a[i - 1] == flag else x for i, x in enumerate(a)]


@pytest.mark.parametrize("mutate, want", [
    (_swap("--allowedTools", lambda v: v.replace("Edit(./**)", "Edit")), "--allowedTools"),        # 縛りの無い書く道具
    (_swap("--allowedTools", lambda v: v + ",Bash"), "--allowedTools"),                            # 丸ごとの Bash
    (_swap("--tools", lambda v: v + ",MultiEdit"), "--tools"),
    (_swap("--permission-mode", lambda v: "acceptEdits"), "--permission-mode"),                    # 許可に無い rm を通す形
    (_swap("--settings", lambda v: json.dumps({"sandbox": {**json.loads(v)["sandbox"], "filesystem": {"denyWrite": [
        p for p in json.loads(v)["sandbox"]["filesystem"]["denyWrite"] if not p.endswith(os.sep + ".git")]}}})), "denyWrite"),
    (_swap("--settings", lambda v: json.dumps({"sandbox": {**json.loads(v)["sandbox"], "allowUnsandboxedCommands": True}})), "--settings"),
    (lambda a: a + ["--add-dir", "/"], "--add-dir"),
    (lambda a: a + ["--dangerously-skip-permissions"], "--dangerously-skip-permissions"),
])
def test_runner_refusal_arms(repo, tmp_path, mutate, want):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _runner_launch(repo, tmp_path / "b", stdin)
    why = commands.launch_refusal({"launch": {**good, "argv": mutate(good["argv"])}}, cwd=str(repo), board_dir=tmp_path / "b") or ""
    assert want in why


def test_runner_refusal_rebuilds_the_fence_and_refuses_a_widened_tool_list(repo, tmp_path, monkeypatch):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _runner_launch(repo, tmp_path / "b", stdin)
    assert "道具" in (commands.launch_refusal({"launch": {**good, "tools": good["tools"] + ["NotebookEdit"]}},
                                            cwd=str(repo), board_dir=tmp_path / "b") or "")
    git(repo, "worktree", "add", "-q", str(tmp_path / "late"), "-b", "late")     # next の後に作業ツリーが足された
    assert "denyWrite" in (commands.launch_refusal({"launch": good}, cwd=str(repo), board_dir=tmp_path / "b") or "")
    monkeypatch.setattr(role_run, "sandbox_available", lambda: False)
    assert "縛れない" in (commands.launch_refusal({"launch": good}, cwd=str(repo), board_dir=tmp_path / "b") or "")


def test_git_state_guard_rejects_a_moved_head(repo, tmp_path):
    seen = []
    guard = commands._git_state_guard(lambda text: seen.append(text))
    assert guard("ok") is None and seen == ["ok"]
    (repo / "b.txt").write_text("b\n")
    assert guard("still-ok") is None                                   # 作業ツリーのファイルは変えてよい
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "by the child")
    assert "HEAD" in (guard("late") or "") and seen == ["ok", "still-ok"]


# ---------------------------------------------------------------- 狭める形（comment-analyzer）
WIDE = {"file": "x.md", "tools": ["*"], "model": "inherit", "effort": None, "body": "役の本文"}
NARROW = {"tools": ["Read", "Glob", "Grep", "Bash"], "model": "sonnet", "effort": "high"}


def test_narrowed_def_narrows_only_wide_definitions_without_write_tools():
    d = advance.narrowed_def(WIDE, NARROW)
    assert d["tools"] == NARROW["tools"] and d["model"] == "sonnet" and d["narrowed"]["tools"] == ["*"]
    assert advance.tooled_launchable(d) and not advance.tooled_launchable(WIDE)
    writer = {**WIDE, "tools": ["Read", "Write"]}
    assert advance.narrowed_def(writer, NARROW) is writer                                     # 書く仕事の役は狭めない
    assert advance.narrowed_def(WIDE, {**NARROW, "tools": ["Read", "Edit"]}) is WIDE          # 上限の外の値
    exact = {**WIDE, "tools": ["Read"], "model": "haiku", "effort": "low"}
    assert advance.narrowed_def(exact, NARROW) is exact                                       # 狭める要の無い定義
    assert advance.narrowed_def(None, NARROW) is None and advance.narrowed_def(WIDE, None) is WIDE


def test_launch_refusal_checks_narrowed_values_against_the_reread_definition(repo, tmp_path, monkeypatch):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    monkeypatch.setattr(commands, "agent_def", lambda t: dict(WIDE))
    inst = {"agent_type": "pr-review-toolkit:comment-analyzer",
            "launch": {"kind": "tooled", "argv": ["x"], "stdin": str(stdin), "narrowed": {**NARROW, "tools": ["Read", "Write"]}}}
    assert "狭める形" in (commands.launch_refusal(inst, cwd=str(repo), board_dir=tmp_path / "b") or "")
    monkeypatch.setattr(commands, "agent_def", lambda t: {**WIDE, "tools": ["Read"], "model": "haiku", "effort": "low"})
    inst["launch"]["narrowed"] = NARROW
    assert "狭める形" in (commands.launch_refusal(inst, cwd=str(repo), board_dir=tmp_path / "b") or "")


def test_graph_declares_the_runner_words_and_the_narrow_values():
    g = load_graph(GRAPH)[0]
    spec = g["launch"]["runner"]
    assert {"p3.fix", "p3.delta_fix", "p3.delta_fix2"} <= set(spec["edits"])
    assert all(g["nodes"][x]["run_by"] in g["runners"] for x in spec["edits"])
    assert set(g["launch"]["tooled"]["narrow"]["tools"]) <= set(advance.NARROW_TOOLS)
    tdd = load_graph(PLUGIN / "graphs" / "review-loop-tdd.json")[0]
    assert "p3.tdd_tests" in tdd["launch"]["runner"]["edits"] and tdd["launch"]["runner"]["argv"] == spec["argv"]


# ---------------------------------------------------------------- 回し手・記録
def test_recover_does_not_relaunch_a_tree_editing_child(tmp_path):
    r = runner._Runner(tmp_path)
    why = r.recover({"id": "p3.fix", "launch": {"kind": "runner", "edits": True}, "out_path": str(tmp_path / "o.json")})
    assert why and "自動では起こし直さない" in why and "p3.fix" not in r.recovered


def test_classify_launches_runner_nodes_but_hands_back_background_lanes():
    st = {"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {
        "p3.fix": {"id": "p3.fix", "status": "pending", "launch": {"kind": "runner", "edits": True}},
        "lane": {"id": "lane", "status": "pending", "launch": {"kind": "delegate", "background": True}}}}]}
    c = runner.classify(st)
    assert c["kind"] == "handoff" and [i["id"] for i in c["launchable"]] == ["p3.fix"] and [i["id"] for i in c["handoff"]] == ["lane"]


def test_reads_are_marked_unrecorded_when_the_engine_launched_the_fixer():
    rules = load_rules(GRAPH, load_graph(GRAPH)[0])
    b = types.SimpleNamespace(rd={"instances": {"p3.fix": {"launch": {"kind": "runner"}}}}, state={"engine_runners": {"at": "t"}})
    assert "reads.jsonl" in rules._reads_unrecorded(b, "p3.fix")["unrecorded"]
    assert rules._reads_unrecorded(types.SimpleNamespace(rd={"instances": {"p3.fix": {}}}), "p3.fix") == {}


# ---------------------------------------------------------------- 本物の loop.py の盤面
def loop(cwd, *a):
    return subprocess.run([sys.executable, str(LOOP), *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


@pytest.mark.parametrize("flag", [True, False])
def test_init_flag_decides_whether_runner_nodes_get_a_launch(tmp_path, flag):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    d = tmp_path / "st"
    r = loop(repo, "init", "--loop", "review-loop", "--request", "検査", "--dir", str(d),
             "--validator", str(REPO / "scripts" / "review-record.py"), *(["--engine-runners"] if flag else []))
    assert r.returncode == 0, r.stderr
    r = loop(repo, "next", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    base = next(i for i in out["ready"] if i["id"] == "p0.base")
    if flag:
        assert base["launch"]["kind"] == "runner" and base["launch"]["edits"] is False
        assert base["launch"]["form"] in ("sandbox", "read_only") and any("--engine-runners" in n for n in out["notes"])
    else:
        assert "launch" not in base                          # 旗の無い run は今どおり会話がこなす
