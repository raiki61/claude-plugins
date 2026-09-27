"""回す側の節を engine が起こす形（回し役なしの run。init の既定）と、道具の一覧を持たない役を狭めて起こす形の柵。

書き換える節の子は、パスで縛った Edit・Write と OS の sandbox の中の Bash だけを持ち、書けるのは作業ツリーの根の中だけ——.git・ほかの
作業ツリー・盤面・利用者の設定は denyWrite。関数を直に呼ぶ検査で、実物の claude は起こさない（実物で拒まれることの確かめは
docs/graphloops-rearchitecture.md の手順 H の実測の段落）。
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

from conftest import PLUGIN, REPO
from engine import advance, commands, declared, role_run, runner, util
from engine.board import Board
from engine.rules import load_rules
from engine.schema import load_graph

LOOP = PLUGIN / "scripts" / "loop.py"
GRAPH = PLUGIN / "graphs" / "review-loop.json"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """本体 1 つと linked worktree 1 つ。engine の git とプロセスの cwd は本体に向け、sandbox は使える場とし、PATH の claude は在る物と
    する——走らせた機械の PATH・cwd の .claude/settings.json に緑が依らない"""
    r = tmp_path / "main"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "base")
    git(r, "worktree", "add", "-q", str(tmp_path / "other"), "-b", "other")
    monkeypatch.setattr(util, "GIT_CWD", str(r))
    monkeypatch.chdir(r)
    monkeypatch.setattr(role_run, "sandbox_available", lambda: True)
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **kw: "/fake/bin/claude" if name == "claude" else real_which(name, *a, **kw))
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
    perm = advance.runner_form(False, edits, str(repo), str(board), role_run.repo_deny(str(repo))[0] or ())
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
    guard = commands._git_state_guard(lambda text: seen.append(text), tmp_path, "p3.fix")
    assert guard("ok") is None and seen == ["ok"]
    (repo / "b.txt").write_text("b\n")
    assert guard("still-ok") is None                                   # 作業ツリーのファイルは変えてよい
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "by the child")
    assert "HEAD" in (guard("late") or "") and seen == ["ok", "still-ok"]


def test_git_state_guard_accepts_shared_refs_moved_by_another_run_with_a_trace(repo, tmp_path):
    """stash と作業ツリーの一覧は全作業ツリーで共有する（git-worktree の REFS 節）——並行の run が動かしても受け付け、trace に残す"""
    seen = []
    guard = commands._git_state_guard(lambda text: seen.append(text), tmp_path, "p3.fix")
    (repo / "a.txt").write_text("並行の run の編集\n", encoding="utf-8")
    git(repo, "stash", "push", "-q", "-m", "並行の run")
    git(repo, "worktree", "add", "-q", str(tmp_path / "late"), "-b", "late")
    assert guard("ok") is None and seen == ["ok"]
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["op"], r["instance"], r["moved"]) for r in rows] == [("git_shared_moved", "p3.fix", ["stash", "worktrees"])]
    assert guard("again") is None and len((tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()) == 1


# ---------------------------------------------------------------- skill の節（局所レビュー）
def test_skill_form_reads_only_and_needs_the_sandbox(repo, tmp_path, monkeypatch):
    perm = role_run.skill_permission(str(repo), str(tmp_path / "b"))
    assert perm["form"] == "sandbox" and {"Skill", "Agent"} <= set(perm["tools"]) and {"Skill", "Agent"} <= set(perm["allowed_tools"])
    assert not set(role_run.WRITE_TOOLS) & set(perm["tools"]) and "Bash" not in perm["allowed_tools"]
    assert os.path.realpath(repo) in json.loads(perm["settings"])["sandbox"]["filesystem"]["denyWrite"]   # /simplify も書けない
    monkeypatch.setattr(role_run, "sandbox_available", lambda: False)
    assert role_run.skill_permission(str(repo), str(tmp_path / "b")) is None   # 立たない場は会話に返す


def _skill_board(tmp_path, repo, lens_def):
    graph = load_graph(GRAPH)[0]
    b = types.SimpleNamespace(graph=graph, dir=tmp_path / "b", state={"engine_runners": {"at": "t"}, "inputs": {"cwd": str(repo)}})
    b.dir.mkdir()
    inst = {"id": "p1.local_review", "node": "p1.local_review", "prompt_file": str(tmp_path / "p.md"), "out_path": str(tmp_path / "o.json"),
            "skills": graph["nodes"]["p1.local_review"]["skills"]}
    return b, inst, graph["nodes"]["p1.local_review"], lens_def


def test_skill_node_launches_with_lens_definitions_and_falls_back_to_the_conversation(repo, tmp_path, monkeypatch):
    b, inst, n, _ = _skill_board(tmp_path, repo, None)
    monkeypatch.setattr(advance, "agent_def", lambda t: {"body": f"{t} の本文", "tools": ["Read"]})
    spec = advance.runner_launch_spec(b, inst, n)
    assert spec["skill"] is True and spec["on_fail"] == "handoff" and spec["edits"] is False and "Agent" in spec["tools"]
    role = pathlib.Path(spec["argv"][spec["argv"].index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")
    lenses = [e["skill"] for e in n["skills"] if ":" in e["skill"]]
    assert lenses and all(f"- {x}: " in role for x in lenses) and "general-purpose" in role
    # 書く子の前置きを継がない（食い違う指示を並べない）——読むだけの子の共通の決まりは skill_preamble が自分で持つ
    assert "Agent）は起こせない" not in role and "Edit・Write で直せ" not in role
    assert "JSON だけ" in role and "人の方針の文書" in role
    written = sorted(p.read_text(encoding="utf-8") for p in (b.dir / "roles").glob("*.lens.txt"))
    assert written == sorted(f"{x} の本文" for x in lenses)                   # 子が Read で読む定義の写し
    monkeypatch.setattr(advance, "agent_def", lambda t: None)                 # レンズの定義が無い環境
    inst2 = dict(inst)
    assert advance.runner_launch_spec(b, inst2, n) is None and "定義がこの環境に無い" in inst2["runner_unlaunched"]
    monkeypatch.setattr(role_run, "sandbox_available", lambda: False)         # sandbox が立たない場
    inst3 = dict(inst)
    assert advance.runner_launch_spec(b, inst3, n) is None and "sandbox" in inst3["runner_unlaunched"]


def test_a_board_that_measured_a_nested_sandbox_hands_writers_back_and_refuses_delegates(repo, tmp_path, monkeypatch):
    """確かめの子が入れ子の sandbox と固めた盤面では、next が書き換える節と skill の節を会話に返し（runner_unlaunched に理由と外し方）、
    任せ先は柵が外し方を名指して拒む（14）。読むだけの回す側の節は今どおり起こす"""
    b, inst, n, _ = _skill_board(tmp_path, repo, None)
    monkeypatch.setattr(advance, "agent_def", lambda t: {"body": "本文", "tools": ["Read"]})
    b.state["child_tmp_probe"] = {"sandbox": False, "writable": None, "why": "確かめの子の Bash が sandbox の初期化で落ちた（Sandbox ...）"}
    skill = dict(inst)
    assert advance.runner_launch_spec(b, skill, n) is None and "excludedCommands" in skill["runner_unlaunched"]
    writer = {**inst, "id": "p3.fix", "node": "p3.fix"}
    assert advance.runner_launch_spec(b, writer, b.graph["nodes"]["p3.fix"]) is None and "--reprobe" in writer["runner_unlaunched"]
    reader = {**inst, "id": "p0.base", "node": "p0.base"}
    assert advance.runner_launch_spec(b, reader, b.graph["nodes"]["p0.base"])["kind"] == "runner"
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    got = commands._delegate_refusal({"delegate": {"model": "sonnet"}}, {"argv": ["x"], "stdin": str(stdin),
                                                                       "unsandboxable": advance.sandbox_down(b)}, tmp_path / "b", [])
    assert "sandbox の中で走らせられない" in got and "excludedCommands" in got


def test_relaunch_reprobe_clears_the_fixed_probe_and_reissues_a_handed_back_node(real_board, monkeypatch):
    """relaunch --reprobe は盤面に固めた確かめを消してから出し直す——入れ子の sandbox と測って会話に返した節（runner_unlaunched）も
    出し直せる。旗の無い relaunch はそういう節（回す側が自分でやる節）を拒む"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    st["child_tmp_probe"] = {"sandbox": False, "writable": None, "why": "入れ子", "tries": 1}
    st["rounds"][-1]["instances"]["p0.base"]["runner_unlaunched"] = "入れ子の sandbox——会話に返す"
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    r = loop(repo, "relaunch", "--node", "p0.base", "--reason", "外し方を当てた", "--dir", str(d))
    assert r.returncode == 1 and "他へ渡して待っている instance でない" in r.stderr
    r = loop(repo, "relaunch", "--node", "p0.base", "--reason", "外し方を当てた", "--reprobe", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    after = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert "child_tmp_probe" not in after and after["rounds"][-1]["instances"]["p0.base"]["attempts"] == 2
    assert "reprobe" in (d / "trace.jsonl").read_text(encoding="utf-8")


def test_skill_refusal_rebuilds_the_skill_form(repo, tmp_path, monkeypatch):
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    b, inst, n, _ = _skill_board(tmp_path, repo, None)
    monkeypatch.setattr(advance, "agent_def", lambda t: {"body": "本文", "tools": ["Read"]})
    spec = {**advance.runner_launch_spec(b, inst, n), "stdin": str(stdin)}
    assert commands.launch_refusal({"launch": spec}, cwd=str(repo), board_dir=b.dir) is None
    assert "道具" in commands.launch_refusal({"launch": {**spec, "tools": spec["tools"] + ["Edit"]}}, cwd=str(repo), board_dir=b.dir)
    assert "縛れない" in commands.launch_refusal({"launch": {**spec, "edits": True}}, cwd=str(repo), board_dir=b.dir)
    widened = _swap("--allowedTools", lambda v: v + ",Edit")(spec["argv"])
    assert "--allowedTools" in commands.launch_refusal({"launch": {**spec, "argv": widened}}, cwd=str(repo), board_dir=b.dir)
    monkeypatch.setattr(role_run, "sandbox_available", lambda: False)
    assert "縛れない" in commands.launch_refusal({"launch": spec}, cwd=str(repo), board_dir=b.dir)


def test_skill_child_gets_no_background_wait_ceiling(repo, tmp_path, monkeypatch):
    """Agent を持つ子の環境に、背景の subagent の待ちの上限を外す値を渡す（人の方針: 期限を足さない）"""
    seen = {}
    monkeypatch.setattr(commands, "launch_refusal", lambda *a: None)
    monkeypatch.setattr(commands, "_sandbox_probe", lambda d, i: {"sandbox": True, "writable": True})
    monkeypatch.setattr(commands, "run_role", lambda *a, **kw: (seen.update(kw), {"ok": True, "why": None, "session_id": None,
                                                                                 "superseded": False, "runs": [], "rejections": []})[1])
    inst = {"id": "p1.local_review", "node": "p1.local_review", "out_path": str(tmp_path / "o.json"),
            "launch": {"kind": "runner", "skill": True, "argv": ["x"], "stdin": "x"}}
    commands.launch_one(tmp_path, inst, 0, cwd=str(repo))
    assert seen["env"]["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"


def test_run_role_stops_without_resuming_when_the_acceptance_hands_back(tmp_path):
    """受け付けが HandBack を投げたら続きを頼まずに止まり、handback を返す（会話に返す）"""
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    env = json.dumps({"type": "result", "subtype": "success", "result": "{}", "session_id": "s1"})
    argv = [sys.executable, "-c", f"print({env!r})"]

    def accept(_text):
        raise util.HandBack("起こせないレンズ")
    got = role_run.run_role(argv, str(prompt), str(tmp_path / "o.json"), accept=accept, resume_argv=argv + ["{session_id}"], max_resumes=2)
    assert got["handback"] is True and got["ok"] is False and len(got["runs"]) == 1 and "起こせないレンズ" in got["why"]


def _child(tmp_path, first):
    """1 回目は first（標準出力・終了コード）で終わり、続き（--resume を足した語）は成功の包みを返す子。受けた標準入力は stdin.<n> に残す"""
    ok = json.dumps({"type": "result", "subtype": "success", "result": "{}", "session_id": "s1"})
    code = (f"import sys, pathlib\nn = len(list(pathlib.Path({str(tmp_path)!r}).glob('stdin.*')))\n"
            f"pathlib.Path({str(tmp_path)!r}, f'stdin.{{n}}').write_bytes(sys.stdin.buffer.read())\n"
            f"if '--resume' in sys.argv:\n    print({ok!r}); sys.exit(0)\n{first}\n")
    return [sys.executable, "-c", code]


@pytest.mark.parametrize("first,max_resumes,resumed", [
    pytest.param("print('{\"type\": \"result\", \"subtype\": \"error_during_execution\", \"errors\": [\"x\"], \"session_id\": \"s1\"}'); "
                 "sys.exit(1)", 2, True, id="error-envelope-exit-1"),
    pytest.param("print('{\"type\": \"result\", \"subtype\": \"error_max_turns\", \"session_id\": \"s1\"}')", 2, True, id="error-envelope-exit-0"),
    pytest.param("print('{\"type\": \"result\", \"subtype\": \"error_during_execution\", \"session_id\": \"s1\"}'); sys.exit(1)", 0, False,
                 id="background-does-not-resume"),
    pytest.param("import os, signal; print('{\"type\": \"result\", \"session_id\": \"s1\"}', flush=True); os.kill(os.getpid(), signal.SIGTERM)",
                 2, False, id="signal-does-not-resume"),
])
def test_run_role_resumes_once_after_a_turn_that_never_reached_acceptance(tmp_path, first, max_resumes, resumed):
    """返答を受け付けに回せずに終わった回（役が誤りで終わった・exit が正）は、会話の番号が在れば 1 回だけ、拒みと別の文で続きを頼む。
    信号で止まった回と、続きを頼まない節（max_resumes 0。背景の線）は頼まない。記録の語（crashes）は拒み（rejections）と分ける"""
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    argv = _child(tmp_path, first)
    got = role_run.run_role(argv, str(prompt), str(tmp_path / "o.json"), accept=lambda t: None, resume_argv=argv + ["--resume", "{session_id}"],
                            max_resumes=max_resumes)
    assert got["rejections"] == [] and got["resumes"] == 0
    if resumed:
        assert got["ok"] is True and [r["kind"] for r in got["runs"]] == ["first", "crash_resume"] and len(got["crashes"]) == 1
        note = (tmp_path / "stdin.1").read_text(encoding="utf-8")
        assert "受け付けに回せないまま終わった" in note and "形だけ直せ" not in note
    else:
        assert got["ok"] is False and len(got["runs"]) == 1 and got["crashes"] == []


def test_run_role_crash_resume_is_counted_apart_from_rejections(tmp_path):
    """続きの 1 回が落ちた後に拒みが来ても、拒みの続きの上限は減っていない"""
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    argv = _child(tmp_path, "print('{\"type\": \"result\", \"subtype\": \"error_during_execution\", \"session_id\": \"s1\"}'); sys.exit(1)")
    seen = []
    got = role_run.run_role(argv, str(prompt), str(tmp_path / "o.json"), accept=lambda t: (seen.append(t), None if len(seen) > 1 else "形が違う")[1],
                            resume_argv=argv + ["--resume", "{session_id}"], max_resumes=1)
    assert got["ok"] is True and [r["kind"] for r in got["runs"]] == ["first", "crash_resume", "resume"]
    assert got["resumes"] == 1 and got["rejections"] == ["形が違う"] and len(got["crashes"]) == 1


# ---------------------------------------------------------------- 対象リポジトリの deny（.claude/settings.json）
def _declare_deny(repo, text):
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(text, encoding="utf-8")


def test_repo_deny_is_copied_into_every_bash_form(repo, tmp_path):
    _declare_deny(repo, json.dumps({"permissions": {"deny": ["Bash(bash tests/run.sh:*)"], "allow": ["Bash(rm:*)"]}, "hooks": {}}))
    want = {"deny": ["Bash(bash tests/run.sh:*)"]}
    denied = role_run.repo_deny(str(repo))[0]
    tooled = role_run.tooled_permission(["Read", "Bash"], str(repo), str(tmp_path / "b"), denied)
    edit = advance.runner_form(False, True, str(repo), str(tmp_path / "b"), denied)
    skill = advance.runner_form(True, False, str(repo), str(tmp_path / "b"), denied)
    for perm in (tooled, edit, skill):
        assert json.loads(perm["settings"])["permissions"] == want   # allow・hooks は写さない
    assert json.loads(role_run.delegate_settings(["/p"], denied))["permissions"] == want
    assert role_run.tooled_permission(["Read"], str(repo), deny=denied)["settings"] == "{}"   # Bash を持たない役には要らない


def test_repo_deny_merges_the_local_settings_like_claude_code(repo):
    """Claude Code は .claude/settings.json と .claude/settings.local.json の一覧を合わせる——engine の子にも両方の deny を、置き場の順に
    重なりを除いて写す"""
    _declare_deny(repo, json.dumps({"permissions": {"deny": ["Bash(a:*)", "Bash(b:*)"]}}))
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"deny": ["Bash(b:*)", "Bash(c:*)", "Bash(c:*)"]}}),
                                                         encoding="utf-8")
    assert role_run.repo_deny(str(repo)) == (["Bash(a:*)", "Bash(b:*)", "Bash(c:*)"], None)
    (repo / ".claude" / "settings.json").unlink()
    assert role_run.repo_deny(str(repo)) == (["Bash(b:*)", "Bash(c:*)"], None)


def _entrances(repo, tmp_path, monkeypatch):
    """Bash を持つ子の入口の全部（回す側の読む節・書く節・skill の節・任せ先・Bash を持つ道具つきの役）と、Bash を持たない役——
    [(名前, instance, Bash を持つか)]。宣言は読める状態で組む（壊すのは呼び元）"""
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    board = tmp_path / "b"
    monkeypatch.setattr(advance, "agent_def", lambda t: {"body": "本文", "tools": ["Read"]})
    b, inst, n, _ = _skill_board(tmp_path, repo, None)
    skill = {**advance.runner_launch_spec(b, inst, n), "stdin": str(stdin)}
    monkeypatch.setattr(commands, "agent_def", lambda t: {"tools": ["Read", "Bash"] if "bash" in t else ["Read"], "model": "m", "effort": "e",
                                                          "body": "b"})
    return [("runner-read", {"launch": _runner_launch(repo, board, stdin, edits=False)}, True),
            ("runner-edit", {"launch": _runner_launch(repo, board, stdin, edits=True)}, True),
            ("skill", {"launch": skill}, True),
            ("delegate", {"launch": {"kind": "delegate", "argv": ["x"], "stdin": str(stdin)}, "delegate": {"model": "sonnet"}}, True),
            ("tooled-bash", {"agent_type": "p:bash", "launch": {"kind": "tooled", "argv": ["x"], "stdin": str(stdin)}}, True),
            ("tooled-read", {"agent_type": "p:read", "launch": {"kind": "tooled", "argv": ["x"], "stdin": str(stdin)}}, False)], board


@pytest.mark.parametrize("where", ["settings.json", "settings.local.json"])
@pytest.mark.parametrize("text", ["{壊れた", json.dumps({"permissions": {"deny": "Bash(x)"}}), json.dumps({"permissions": []})])
def test_unreadable_repo_deny_refuses_every_bash_entrance_naming_the_file(repo, tmp_path, monkeypatch, where, text):
    """宣言の deny を読めないとき、黙って落として起こさない（fail-closed）——直す 1 か所（ファイル）を名指す。拒むのは柵の入口の 1 か所
    （launch_refusal）で、Bash を持つ子の入口の全部に当たり、Bash を持たない役には当たらない"""
    rows, board = _entrances(repo, tmp_path, monkeypatch)
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / where).write_text(text, encoding="utf-8")
    denied, why = role_run.repo_deny(str(repo))
    assert denied is None and where in why
    for name, inst, bash in rows:
        got = commands.launch_refusal(inst, cwd=str(repo), board_dir=board) or ""
        assert (where in got) == bash, (name, got)


def test_settings_fence_refuses_a_different_permissions_value(repo, tmp_path):
    _declare_deny(repo, json.dumps({"permissions": {"deny": ["Bash(bash tests/run.sh:*)"]}}))
    stdin = tmp_path / "p.md"
    stdin.write_text("x")
    good = _runner_launch(repo, tmp_path / "b", stdin, edits=False)
    assert commands.launch_refusal({"launch": good}, cwd=str(repo), board_dir=tmp_path / "b") is None
    for perms in ({"deny": []}, {"deny": ["Bash(bash tests/run.sh:*)"], "allow": ["Bash(bash tests/run.sh:*)"]}):
        bad = _swap("--settings", lambda v: json.dumps({**json.loads(v), "permissions": perms}))(good["argv"])
        assert "permissions" in (commands.launch_refusal({"launch": {**good, "argv": bad}}, cwd=str(repo), board_dir=tmp_path / "b") or "")
    dropped = _swap("--settings", lambda v: json.dumps({k: x for k, x in json.loads(v).items() if k != "permissions"}))(good["argv"])
    assert "キー" in (commands.launch_refusal({"launch": {**good, "argv": dropped}}, cwd=str(repo), board_dir=tmp_path / "b") or "")


def test_tooled_roles_keep_a_bare_read_for_board_files_outside_the_tree(repo, tmp_path):
    """盤面は linked worktree の .git/worktrees の下（作業ディレクトリの外）に在りうる——Read は置き場を縛らずに許す"""
    for tools in (["Read", "Grep"], ["Read", "Glob", "Grep", "Bash"]):
        assert "Read" in role_run.tooled_permission(tools, str(repo), str(tmp_path / "b"))["allowed_tools"]


# ---------------------------------------------------------------- 見える化（status・run の報告）
def test_trace_costs_take_each_conversation_max_and_say_what_they_count(tmp_path):
    rows = [{"op": "role_run", "node": "p3.fix", "session_id": "s1", "total_cost_usd": 0.5},
            {"op": "role_run", "node": "p3.fix", "session_id": "s1", "total_cost_usd": 0.8},   # 続きの往復（会話の累計）
            {"op": "role_run", "node": "p2.diagnose", "session_id": "s2", "total_cost_usd": 0.25},
            {"op": "launched", "node": "p3.fix", "session_id": "s3", "total_cost_usd": 9}]
    (tmp_path / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n[1]\n\n書きかけ", encoding="utf-8")
    got = role_run.trace_costs(tmp_path / "trace.jsonl")
    assert got["usd"] == 1.05 and got["by_node"] == {"p2.diagnose": 0.25, "p3.fix": 0.8} and "会話そのもの" in got["what"]
    assert got["skipped"] == 2 and "skipped" in got["what"]   # 辞書でない行と書きかけの行。空行は数えない
    assert role_run.trace_costs(tmp_path / "none.jsonl") is None


def test_waiting_shows_the_time_since_launch_only_for_running_children():
    inst = {"emitted_at": util.now(), "attempts": 2, "launched_at": util.now(), "launch_state": "running"}
    assert util.waiting(inst) == {"elapsed_min": 0, "attempts": 2, "launched_min": 0}
    assert "launched_min" not in util.waiting({**inst, "launch_state": "ended"})


def test_status_and_the_run_report_share_one_liveness(tmp_path):
    """走っている試行の見せ方（経過・子のグループが生きているか）は role_run.liveness の 1 本——engine の口（status）が回し手の層を
    import しない（runner は外側の薄い層）"""
    inst = {"emitted_at": util.now(), "launched_at": util.now(), "launch_state": "running", "out_path": str(tmp_path / "o.json")}
    assert role_run.liveness(inst) == {**util.waiting(inst), "alive": False}          # 印が無い＝子は居ない
    assert "alive" not in role_run.liveness({**inst, "launch_state": "ended"})
    src = (PLUGIN / "engine" / "commands.py").read_text(encoding="utf-8")
    assert "from .runner" not in src and "_group_alive" not in src


# ---------------------------------------------------------------- 子の形ごとの段（launch.append）
POLICY_SEG = ["../prompts/policy-path.md", "../prompts/policy.md", "../prompts/review-loop/test-scope.md"]


@pytest.mark.parametrize("runner_node,tools,want", [
    pytest.param(True, None, [*POLICY_SEG, "../prompts/board-files.md"], id="runner"),
    pytest.param(False, ["Read", "Grep", "Bash"], [*POLICY_SEG, "../prompts/board-files.md"], id="bash-role"),
    pytest.param(False, ["Read", "Grep"], ["../prompts/board-files.md"], id="reading-role"),
    pytest.param(False, [], [], id="isolated-role"),
])
def test_launch_appends_follow_the_child_shape(runner_node, tools, want):
    graph = load_graph(GRAPH)[0]
    role = None if tools is None else {"tools": tools}
    got = advance.launch_appends(graph, {}, role, runner_node)
    assert [f for seg in got for f in seg["files"]] == want
    assert "inputs.request" not in [r for seg in got for r in seg["reads"]]   # 依頼の本文は段で配らない（人の関所の条件 4）
    assert advance.launch_appends(graph, {}, None, False) == []               # 定義の読めない役（道具が分からない）


def test_emitted_prompt_carries_the_appended_sections(real_board):
    """段（launch.append）の本文は、節の指示書の正本（render.node_prompt）の中で役の指示書に入る——回す側の節の prompt_file に
    方針・手元で走らせてよい範囲・盤面のファイルの読み方の見出しが 1 度ずつ在る"""
    repo, d = real_board
    r = loop(repo, "next", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    base = next(i for i in json.loads(r.stdout)["ready"] if i["id"] == "p0.base")
    text = pathlib.Path(base["prompt_file"]).read_text(encoding="utf-8")
    for head in ("## 人の方針", "## 手元で走らせてよい範囲", "## 盤面のファイルの読み方"):
        assert text.count(head) == 1, head


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
@pytest.mark.parametrize("rc", [0, 1])
def test_recover_relaunches_a_tree_editing_child_only_if_untouched_and_once(tmp_path, monkeypatch, rc):
    """書き換える子の launch が受け付けの前に居なくなったら、relaunch --if-untouched を 1 回だけ打つ（触っていないと測れなければ
    engine が拒み、人に渡す）。同じ試行が 2 度落ちたら拾わない"""
    got = []
    monkeypatch.setattr(runner, "_cli", lambda d, *a: (got.append(a), (rc, "", "作業ツリーが起こした時点と違う"))[1])
    r = runner._Runner(tmp_path)
    inst = {"id": "p3.fix", "launch": {"kind": "runner", "edits": True}, "out_path": str(tmp_path / "o.json")}
    tmp_path.joinpath("o.json").write_text("{}", encoding="utf-8")   # 置き場に返答が在っても done で拾わない
    why = r.recover(inst)
    assert [a[:4] for a in got] == [("relaunch", "--node", "p3.fix", "--if-untouched")]
    assert (why is None) if rc == 0 else ("自動では起こし直さない" in why and "起こした時点と違う" in why)
    again = r.recover(inst)
    assert again and "起こし直した後も" in again and len(got) == 1


def test_classify_names_why_each_node_is_handed_back():
    st = {"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {
        "lane": {"id": "lane", "status": "pending", "launch": {"kind": "delegate", "background": True}},
        "p0.base": {"id": "p0.base", "status": "pending"},
        "p1.local_review": {"id": "p1.local_review", "status": "pending", "launch": {"kind": "runner", "skill": True, "on_fail": "handoff"},
                            "launch_state": "ended", "attempt_log": [{"kind": "handback", "reason": "会話に返す: 起こせないレンズ"}]},
        "p3.fix": {"id": "p3.fix", "status": "pending", "runner_unlaunched": "sandbox が立たない"}}}]}
    c = runner.classify(st)
    why = {i["id"]: i["handoff_why"] for i in c["handoff"]}
    assert "背景の任せ先" in why["lane"] and "--no-engine-runners" in why["p0.base"] and why["p3.fix"] == "sandbox が立たない"
    assert "起こせないレンズ" in why["p1.local_review"] and c["needs_human"] == []   # 子が届かなかった skill の節は人でなく会話へ


def test_classify_hands_an_ended_child_to_a_human_unless_its_last_word_is_handback():
    """起こして終わったのに受け付けていない試行の振り分けは classify の 1 か所で、attempt_log の最後の語だけで決める（宣言は見ない）"""
    ended = {"status": "pending", "launch_state": "ended"}
    st = {"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {
        "p3.fix": {"id": "p3.fix", **ended, "launch": {"kind": "runner", "edits": True},
                   "attempt_log": [{"kind": "rejected", "reason": "拒みが続いた"}]},
        "p1.local_review": {"id": "p1.local_review", **ended, "launch": {"kind": "runner", "skill": True},
                            "attempt_log": [{"kind": "rejected", "reason": "x"}, {"kind": "handback", "reason": "届かなかった"}]},
        "p0.base": {"id": "p0.base", **ended, "launch": {"kind": "runner", "on_fail": "handoff"},
                    "attempt_log": [{"kind": "failed", "reason": "語が failed"}]}}}]}
    c = runner.classify(st)
    assert c["kind"] == "handoff" and [i["id"] for i in c["handoff"]] == ["p1.local_review"]
    assert c["needs_human"] == [{"id": "p3.fix", "why": "拒みが続いた"}, {"id": "p0.base", "why": "語が failed"}]


def _settled(tmp_path, monkeypatch, launch, result):
    """本物の cmd_launch の締め（settle）を 1 節ぶん通した後の instance"""
    d = tmp_path / "st"
    d.mkdir()
    inst = {"id": "n", "node": "n", "status": "pending", "out_path": str(tmp_path / "o.json"), "launch": launch}
    st = {"rounds": [{"round": 1, "instances": {"n": inst}}]}

    class B:
        def __init__(self, *_a):
            self.rd, self.state, self.graph = st["rounds"][-1], {}, {}

        def trace(self, *a, **kw):
            pass
    monkeypatch.setattr(commands, "Board", B)
    monkeypatch.setattr(commands, "_board_update", lambda d_, fn, allow_halted=False: fn(B()))
    monkeypatch.setattr(commands, "launch_cwd", lambda b: str(tmp_path))
    monkeypatch.setattr(commands, "launch_one", lambda *a: {"id": "n", "node": "n", "out_path": inst["out_path"], "session_id": None,
                                                           "superseded": False, "resumes": 0, "rejections": [], "done": None, "stderr": "",
                                                           **result})
    monkeypatch.setattr(commands, "mark_launch_failures", lambda *a: None)
    commands.cmd_launch(argparse.Namespace(dir=str(d), node=None))
    return inst


@pytest.mark.parametrize("launch,result,word", [
    pytest.param({"kind": "runner", "skill": True, "on_fail": "handoff"}, {"ok": False, "why": "子が落ちた"}, "handback", id="skill-crash"),
    pytest.param({"kind": "runner", "skill": True, "on_fail": "handoff"}, {"ok": False, "why": "受け付けが拒んだ", "rejections": ["x"]},
                 "handback", id="skill-rejected"),
    pytest.param({"kind": "runner"}, {"ok": False, "why": "会話に返す: y", "handback": True}, "handback", id="rules-handback"),
    pytest.param({"kind": "runner", "edits": True}, {"ok": False, "why": "子が落ちた", "crashes": ["exit 1"]}, "failed", id="writer-crash"),
])
def test_settle_writes_the_word_classify_reads(tmp_path, monkeypatch, launch, result, word):
    """launch の締めが、受け付けまで届かなかった試行の最後の語を書く——宣言の on_fail は、届かなかった回に書く語の既定。
    受け付けに回せずに続きを頼んだ回は crash_resume として残る"""
    inst = _settled(tmp_path, monkeypatch, launch, result)
    assert inst["launch_state"] == "ended" and inst["attempt_log"][-1]["kind"] == word
    assert ("crash_resume" in [x["kind"] for x in inst["attempt_log"]]) == bool(result.get("crashes"))
    c = runner.classify({"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {"n": {**inst, "id": "n"}}}]})
    assert c["kind"] == ("handoff" if word == "handback" else "needs_human")


def test_done_on_a_running_child_that_hands_back_marks_the_board_and_exits_1(real_board, monkeypatch):
    """launch が締めの前に落ち、回し手が置き場の返答を done した回に受け付けが HandBack を投げても、想定外の例外（exit 2）にしない:
    exit 1 で返し、読み直した盤面に handback の語と ended だけを書く（拒んだ受け付けの途中の書き換えは残さない）"""
    from glharness import inproc
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    inst = st["rounds"][-1]["instances"]["p0.base"]
    inst.update(launch={"kind": "runner", "skill": True, "on_fail": "handoff"}, launch_state="running", launched_at=util.now())
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    pathlib.Path(inst["out_path"]).write_text("{}", encoding="utf-8")

    def hand_back(b, node, *a, **kw):
        b.state["outputs"]["half-written"] = True   # 拒んだ受け付けの途中の書き換え
        raise util.HandBack("起こせないレンズ")
    monkeypatch.setattr(commands, "accept_output", hand_back)
    r = inproc(["done", "--node", "p0.base", "--dir", str(d)], cwd=repo)
    assert r.returncode == 1 and "起こせないレンズ" in r.stderr and "想定外" not in r.stderr
    b = Board(d)
    after = b.rd["instances"]["p0.base"]
    assert after["launch_state"] == "ended" and after["attempt_log"][-1]["kind"] == "handback"
    assert "half-written" not in b.state["outputs"] and runner.classify(b.state)["kind"] == "handoff"


def test_recover_does_not_relaunch_after_the_acceptance_hands_back(tmp_path, monkeypatch):
    """回し手が拾い直す done を受け付けが会話に返したら、全レンズの子を起こし直さない（classify が handoff に出す）"""
    got = []
    monkeypatch.setattr(runner, "_cli", lambda d, *a: (got.append(a[0]), (1, "", "会話に返す"))[1])
    monkeypatch.setattr(runner, "read_state", lambda d: {"rounds": [{"instances": {"p1.local_review": {
        "launch_state": "ended", "attempt_log": [{"kind": "handback", "reason": "会話に返す"}]}}}]})
    (tmp_path / "o.json").write_text("{}", encoding="utf-8")
    inst = {"id": "p1.local_review", "launch": {"kind": "runner", "skill": True}, "out_path": str(tmp_path / "o.json")}
    assert runner._Runner(tmp_path).recover(inst) is None and got == ["done"]


def test_classify_does_not_start_lanes_on_a_halted_or_asking_board():
    lane = {"id": "lane", "status": "pending", "launch": {"kind": "delegate", "background": True, "receipt": {"lane": "/r.json"}}}
    for extra in ({"halted": {"by": "unattended", "node": "x"}}, {"pending_human": {"node": "x"}}):
        c = runner.classify({"status": "running", "round": 1, **extra, "rounds": [{"round": 1, "instances": {"lane": lane}}]})
        assert c["lanes"] == []


def test_classify_leaves_lanes_with_a_receipt_to_the_runner():
    """受領の形（launch.receipt）を持つ背景の線は会話に返さず、回し手が立てる（busy）"""
    lane = {"id": "lane", "status": "pending", "launch": {"kind": "delegate", "background": True, "receipt": {"lane": "/r.json"}}}
    c = runner.classify({"status": "running", "round": 1, "rounds": [{"round": 1, "instances": {"lane": lane}}]})
    assert c["kind"] == "busy" and c["handoff"] == [] and [i["id"] for i in c["lanes"]] == ["lane"]


def test_start_lane_dones_the_receipt_then_detaches_the_launch(tmp_path, monkeypatch):
    got, spawned = [], []
    monkeypatch.setattr(runner, "_cli", lambda d, *a: (got.append(a), (0, "", ""))[1])
    monkeypatch.setattr(runner.subprocess, "Popen", lambda argv, **kw: (spawned.append((argv, kw)), types.SimpleNamespace(pid=7))[1])
    inst = {"id": "p3.delta_gates", "out_path": str(tmp_path / "o.json"), "launch": {"receipt": {"lane": "/r.json"}}}
    assert runner._Runner(tmp_path).start_lane(inst) is None
    assert json.loads((tmp_path / "o.json").read_text(encoding="utf-8")) == {"lane": "/r.json"} and got == [("done", "--node", "p3.delta_gates")]
    argv, kw = spawned[0]
    assert argv[-5:] == ["launch", "--node", "p3.delta_gates", "--dir", str(tmp_path)] and kw["stdin"] == subprocess.DEVNULL
    assert "lane" in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


def test_start_lane_does_not_launch_when_the_receipt_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_cli", lambda d, *a: (1, "", "受領が違う"))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("受領が拒まれたのに線を立てた"))
    inst = {"id": "p3.delta_gates", "out_path": str(tmp_path / "o.json"), "launch": {"receipt": {"lane": "/r.json"}}}
    assert "受領が違う" in runner._Runner(tmp_path).start_lane(inst)


def test_start_lane_marks_the_result_when_the_launch_cannot_start(tmp_path, monkeypatch):
    """受領を done した後に線の launch を起こせなければ、結果の置き場に落ちた印を書き、trace に残す（盤面の線は走っていると読まれない）"""
    monkeypatch.setattr(runner, "_cli", lambda d, *a: (0, "", ""))

    def boom(*a, **kw):
        raise OSError("起こせない")
    monkeypatch.setattr(runner.subprocess, "Popen", boom)
    result = tmp_path / "lane.json"
    inst = {"id": "p3.delta_gates", "out_path": str(tmp_path / "o.json"), "launch": {"receipt": {"lane": str(result)}, "result_path": str(result)}}
    assert runner._Runner(tmp_path).start_lane(inst) is None
    assert "起こせない" in json.loads(result.read_text(encoding="utf-8"))[util.LANE_FAILED]
    assert "lane_failed" in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("result,marked", [
    pytest.param({"ok": False, "why": "柵が拒んだ"}, True, id="refused"),
    pytest.param({"ok": False, "why": "起こし直された", "superseded": True}, False, id="superseded"),
    pytest.param({"ok": True, "why": None}, False, id="ok"),
])
def test_background_launch_that_writes_no_result_leaves_the_failed_mark(real_board, monkeypatch, result, marked):
    """背景の線の launch が結果を書かずに終わったら（柵が拒んだ・子が落ちた）、置き場に落ちた印を書く——rules はそれを『結果が使えない』
    に振り、run の報告は lanes_failed に並べる。起こし直された・人が止めた試行には書かない"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    inst = st["rounds"][-1]["instances"]["p0.base"]
    lane = d / "lanes" / "r1.json"
    lane.parent.mkdir()
    inst.update(status="done", launch={"kind": "delegate", "background": True, "result_path": str(lane), "argv": ["x"], "stdin": "x"})
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(commands, "launch_one", lambda d_, i, m, cwd: {"id": i["id"], "node": i["node"], "out_path": i["out_path"],
                                                                      "session_id": None, "resumes": 0, "rejections": [], "stderr": "", **result})
    monkeypatch.setattr(commands, "mark_launch_failures", lambda *a: None)
    commands.cmd_launch(argparse.Namespace(dir=str(d), node="p0.base"))
    assert lane.exists() == marked
    rows = runner.lanes_failed(Board(d).state)
    assert rows == ([{"id": "p0.base", "round": 1, "why": "柵が拒んだ"}] if marked else [])
    if marked:
        rules = load_rules(GRAPH, load_graph(GRAPH)[0])
        out, errs = rules._lane_result(None, {"result": str(lane), "rev": "r"})
        assert out is None and errs == ["線の launch が受け付けまで届かなかった: 柵が拒んだ"]
        assert not util.write_lane_failed(str(lane), "二度目")          # 書き終えた物を上書きしない


def _touched_prev(repo, tmp_path, monkeypatch, order):
    monkeypatch.setattr(commands, "stop_marks", lambda marks: (order.append("stop"), [])[1])
    real = commands.worktree_tree
    monkeypatch.setattr(commands, "worktree_tree", lambda *a: (order.append("compare"), real(*a))[1])
    return {"id": "p3.fix", "out_path": str(tmp_path / "o.json"), "tree_before_id": util.worktree_tree(),
            "launch_head": list(commands._own_git_marks())}


def test_relaunch_if_untouched_stops_the_old_child_before_comparing(repo, tmp_path, monkeypatch):
    order = []
    prev = _touched_prev(repo, tmp_path, monkeypatch, order)
    commands._refuse_touched(prev, ["mark"])
    assert order == ["stop", "compare"]


@pytest.mark.parametrize("touch, want", [
    (lambda repo, prev: (repo / "a.txt").write_text("途中まで書いた\n", encoding="utf-8"), "起こした時点と違う"),
    (lambda repo, prev: (git(repo, "commit", "-q", "--allow-empty", "-m", "x"), None)[1], "起こした時点と違う"),
    (lambda repo, prev: prev.pop("launch_head"), "盤面に無い"),
])
def test_relaunch_if_untouched_refuses_when_it_cannot_say_untouched(repo, tmp_path, monkeypatch, touch, want):
    prev = _touched_prev(repo, tmp_path, monkeypatch, [])
    touch(repo, prev)
    with pytest.raises(util.Reject, match=want):
        commands._refuse_touched(prev, ["mark"])


def test_relaunch_if_untouched_refuses_when_the_old_child_cannot_be_stopped(repo, tmp_path, monkeypatch):
    prev = _touched_prev(repo, tmp_path, monkeypatch, [])
    monkeypatch.setattr(commands, "stop_marks", lambda marks: ["止まらない"])
    with pytest.raises(util.Reject, match="止め切れない"):
        commands._refuse_touched(prev, ["mark"])


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


@pytest.mark.parametrize("flags,by", [([], "default"), (["--engine-runners"], "flag"), (["--no-engine-runners"], None)])
def test_init_default_lets_the_engine_launch_runner_nodes_and_the_opt_out_keeps_the_conversation(tmp_path, flags, by):
    """旗の無い init は回す側の節も engine が起こす run（既定）。--no-engine-runners の run は今どおり会話がこなす（人の決定 2026-09-27
    『けす』に向けた一段——会話で回す道は旗で残す）。選んだ出どころ（既定か旗か）は盤面に残る"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    d = tmp_path / "st"
    r = loop(repo, "init", "--loop", "review-loop", "--request", "検査", "--dir", str(d),
             "--validator", str(REPO / "scripts" / "review-record.py"), *flags)
    assert r.returncode == 0, r.stderr
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert (st.get("engine_runners") or {}).get("by") == by
    r = loop(repo, "next", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    base = next(i for i in out["ready"] if i["id"] == "p0.base")
    if by:
        assert base["launch"]["kind"] == "runner" and base["launch"]["edits"] is False
        assert base["launch"]["form"] in ("sandbox", "read_only") and any("--no-engine-runners" in n for n in out["notes"])
    else:
        assert "launch" not in base                          # 会話で回す run は今どおり会話がこなす


def test_research_init_gets_no_runner_notice_by_default(tmp_path):
    """launch.runner を持たない graph（research-loop）の旗の無い init は、回し手の注意を出さず、盤面にも回し役なしの印を書かない
    （research-graph の出力を変えない。人の関所 round 2 の条件 7）。旗を明示したときだけ今どおり『効かない』と知らせる"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "m.md").write_text("# 見立て\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    args = ["init", "--loop", "research-loop", "--request", "q", "--document", str(repo / "m.md"),
            "--validator", str(REPO / "scripts" / "research-record.py")]
    r = loop(repo, *args, "--dir", str(tmp_path / "a"))
    assert r.returncode == 0 and "engine-runners" not in r.stderr + r.stdout, r.stderr
    assert "engine_runners" not in json.loads((tmp_path / "a" / "state.json").read_text(encoding="utf-8"))
    r = loop(repo, *args, "--dir", str(tmp_path / "b"), "--engine-runners")
    assert r.returncode == 0 and "効かない" in r.stderr


@pytest.fixture
def real_board(tmp_path, monkeypatch):
    """本物の init の盤面（review-loop。宣言の一式を持つリポジトリ）と、engine の git の向き先"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / declared.DECL_NAME).write_text(json.dumps({"suite": [{"name": "ok", "argv": [sys.executable, "-c", "print(1)"]}]}), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    d = tmp_path / "st"
    r = loop(repo, "init", "--loop", "review-loop", "--request", "検査", "--dir", str(d), "--validator", str(REPO / "scripts" / "review-record.py"),
             "--no-engine-runners")
    assert r.returncode == 0, r.stderr
    monkeypatch.setattr(util, "GIT_CWD", str(repo))
    return repo, d


def test_emit_and_reissue_carry_the_tree_base_of_a_declaring_node(real_board):
    """declared_files を持つ節は出す時点の木の id を持ち、周の基準は最初の試行で決まる。起こし直しは前の試行の基準と、まだ片付けて
    いない専用の一時の置き場の記録を写し、前の版の engine が出した（木の id の無い）試行からは新しい id も周の基準も作らない"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    b = Board(d)
    b.nodes["p0.base"]["declared_files"] = "requirements[].key"
    first = advance.emit_instance(b, "p0.base")
    assert first["tree_before_id"] == util.worktree_tree() == b.rd["tree_base"]["p0.base"]
    first["child_tmp"] = {"dir": "/tmp/gl-w-left", "at": first["emitted_at"]}
    (repo / "a.py").write_text("x = 3\n", encoding="utf-8")
    b.__dict__.pop("_worktree_tree", None)   # 同じ盤面の中の木の写しを捨て、今の木で出し直させる
    again = commands.reissue(b, first, "起こし直し")
    assert again["tree_before_id"] == first["tree_before_id"] == b.rd["tree_base"]["p0.base"]
    assert again["attempt_log"][-1]["prev_emitted_rev"] == first["emitted_rev"] and again["child_tmp"] == first["child_tmp"]
    b.rd["tree_base"].pop("p0.base")
    old = {k: v for k, v in first.items() if k != "tree_before_id"}
    fresh = commands.reissue(b, old, "前の版の試行")
    assert "tree_before_id" not in fresh and "p0.base" not in b.rd["tree_base"]


def test_guarded_role_gets_the_tree_id_when_emitted(real_board):
    """道具つきの役（graph の tree_guard_roles）の節は、出す時点で並び（tree_before）と中身の木の id（tree_before_id）の両方を持つ"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    b = Board(d)
    b.graph["tree_guard_roles"] = ["writer"]
    inst = advance.emit_instance(b, "p0.base")
    assert "declared_files" not in b.nodes["p0.base"]
    assert inst["tree_before"] == util.porcelain() and inst["tree_before_id"] == util.worktree_tree()


def test_emit_without_a_tree_id_keeps_the_git_reason(real_board, monkeypatch):
    """出す時に木の id が取れない回は止めずに痕跡を残し、痕跡に git の言い分を添える"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    b = Board(d)
    b.graph["tree_guard_roles"] = ["writer"]
    monkeypatch.setattr(util, "worktree_tree", lambda why=None: (why.append("fatal: 出す時の言い分"), None)[1])
    inst = advance.emit_instance(b, "p0.base")
    u, = [u for u in b.state["unevaluable"] if u["trigger"] == "p0.base.tree_before_id"]
    assert "tree_before_id" not in inst and "出す時の言い分" in u["why"]


@pytest.mark.parametrize("touched", [False, True])
def test_launch_records_the_head_and_relaunch_if_untouched_compares_it(real_board, monkeypatch, touched):
    """launch は書き換える子の起こした時点の HEAD・枝（launch_head）を盤面に残し、本物の loop.py relaunch --if-untouched はそれと
    木の id を比べて、触っていなければ起こし直し、触っていれば新しい試行を作らずに拒む"""
    repo, d = real_board
    assert loop(repo, "next", "--dir", str(d)).returncode == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    inst = st["rounds"][-1]["instances"]["p0.base"]
    inst["launch"] = {"kind": "runner", "edits": True, "argv": ["claude", "-p"], "stdin": inst["prompt_file"]}
    inst["tree_before_id"] = util.worktree_tree()
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(commands, "launch_one", lambda d_, i, m, cwd: {
        "id": i["id"], "node": i["node"], "out_path": i["out_path"], "ok": False, "why": "子が落ちた", "session_id": None,
        "superseded": False, "resumes": 0, "rejections": [], "done": None, "stderr": ""})
    monkeypatch.setattr(commands, "mark_launch_failures", lambda *a: None)
    commands.cmd_launch(argparse.Namespace(dir=str(d), node="p0.base"))
    assert Board(d).rd["instances"]["p0.base"]["launch_head"] == list(commands._own_git_marks())
    if touched:
        (repo / "a.py").write_text("途中まで書いた\n", encoding="utf-8")
    r = loop(repo, "relaunch", "--node", "p0.base", "--reason", "回し手が拾い直す", "--if-untouched", "--dir", str(d))
    after = Board(d).rd["instances"]["p0.base"]
    if touched:
        assert r.returncode == 1 and "起こした時点と違う" in r.stderr and after.get("attempts", 1) == 1
    else:
        assert r.returncode == 0, r.stderr
        assert after["attempts"] == 2


def test_skip_every_round_skips_the_node_before_it_is_emitted(real_board, tmp_path):
    repo, d = real_board
    r = loop(repo, "skip", "--node", "p0.base", "--reason", "x", "--every-round", "--dir", str(d))
    assert r.returncode == 1 and "optional でない" in r.stderr
    f = tmp_path / "preset.json"
    f.write_text(json.dumps({"p0.local_checks": "CI で回す"}, ensure_ascii=False), encoding="utf-8")
    assert loop(repo, "patch", "--path", "state.preset_skips", "--file", str(f), "--reason", "検査", "--dir", str(d)).returncode == 0
    r = loop(repo, "next", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    assert "p0.local_checks" not in [i["id"] for i in json.loads(r.stdout)["ready"]]
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert st["rounds"][-1]["skipped"] == {"p0.local_checks": "CI で回す"}
    traced = [json.loads(x) for x in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(t.get("op") == "skip" and t.get("node") == "p0.local_checks" and t.get("by") == "every_round" for t in traced)


def test_skip_every_round_is_kept_on_the_board_and_applies_now(real_board):
    repo, d = real_board
    r = loop(repo, "skip", "--node", "p0.local_checks", "--reason", "CI で回す", "--every-round", "--dir", str(d))
    assert r.returncode == 0, r.stderr
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert st["preset_skips"] == {"p0.local_checks": "CI で回す"} and st["rounds"][-1]["skipped"] == {"p0.local_checks": "CI で回す"}
