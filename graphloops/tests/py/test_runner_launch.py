"""回す側の節を engine が起こす形（init --engine-runners）と、道具の一覧を持たない役を狭めて起こす形の柵。

書き換える節の子は、パスで縛った Edit・Write と OS の sandbox の中の Bash だけを持ち、書けるのは作業ツリーの根の中だけ——.git・ほかの
作業ツリー・盤面・利用者の設定は denyWrite。関数を直に呼ぶ検査で、実物の claude は起こさない（実物で拒まれることの確かめは
docs/graphloops-rearchitecture.md の手順 H の実測の段落）。
"""
import argparse
import json
import os
import pathlib
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
    (repo / "a.txt").write_text("並行の run の編集\n")
    git(repo, "stash", "push", "-q", "-m", "並行の run")
    git(repo, "worktree", "add", "-q", str(tmp_path / "late"), "-b", "late")
    assert guard("ok") is None and seen == ["ok"]
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["op"], r["instance"], r["moved"]) for r in rows] == [("git_shared_moved", "p3.fix", ["stash", "worktrees"])]
    assert guard("again") is None and len((tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()) == 1


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
        "p1.local_review": {"id": "p1.local_review", "status": "pending"},
        "p3.fix": {"id": "p3.fix", "status": "pending", "runner_unlaunched": "sandbox が立たない"}}}]}
    why = {i["id"]: i["handoff_why"] for i in runner.classify(st)["handoff"]}
    assert "背景の任せ先" in why["lane"] and "skill" in why["p1.local_review"] and why["p3.fix"] == "sandbox が立たない"


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
    (lambda repo, prev: (repo / "a.txt").write_text("途中まで書いた\n"), "起こした時点と違う"),
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
    r = loop(repo, "init", "--loop", "review-loop", "--request", "検査", "--dir", str(d), "--validator", str(REPO / "scripts" / "review-record.py"))
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
