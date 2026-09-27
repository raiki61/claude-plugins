"""engine が子の書いた物を測る口——道具つきの役の前後の突合（中身の木の id・区間の重なり）・書き換える節の申告の両方向の記録・
書き換える子の専用の一時の置き場の数えと確かめ・外から来た JSON と引数の孤立サロゲートの検め。本物の git の使い捨てのリポジトリの上で直に呼ぶ"""
import argparse
import os
import pathlib
import re
import subprocess

import pytest

from engine import commands, declared, util
from engine.util import AnswerReject, Reject


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    for name in ("a.py", "old.py", "keep.py"):
        (r / name).write_text(f"{name}\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "base")
    (r / "a.py").write_text("既に M\n", encoding="utf-8")   # レビュー対象は定義上ぜんぶ変更済み
    monkeypatch.setattr(util, "GIT_CWD", str(r))
    return r


class Board:
    def __init__(self, instances, nodes, runners=("writer",)):
        self.rd = {"instances": instances}
        self.nodes = nodes
        self.graph = {"runners": list(runners)}
        self.state = {"round": 1}
        self.round = 1


T0, T1, T2, T3 = "2026-09-27T10:00:00+09:00", "2026-09-27T10:05:00+09:00", "2026-09-27T10:10:00+09:00", "2026-09-27T10:15:00+09:00"


def guarded(iid="r1.inv", run_by="investigator", emitted_at=T1):
    return {"id": iid, "node": iid, "status": "pending", "run_by": run_by, "emitted_at": emitted_at, "tree_before": util.porcelain(),
            "tree_before_id": util.worktree_tree()}


def other(iid, status="pending", done_at=None, run_by="tester"):
    return {"id": iid, "node": iid, "status": status, "run_by": run_by, **({"done_at": done_at} if done_at else {})}


# ---------------------------------------------------------------- 道具つきの役の前後の突合
def test_rewriting_an_already_modified_file_is_caught_by_the_tree_id(repo):
    """既に ' M' のファイルの中身だけを書き換えても porcelain は同じ——木の id で拒む（区間に書き手が重ならない）"""
    inst = guarded()
    b = Board({inst["id"]: inst}, {inst["id"]: {}})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    assert util.porcelain() == inst["tree_before"]
    with pytest.raises(Reject, match="中身 a.py"):
        commands._tree_guard(b, inst["id"], inst, None)


@pytest.mark.parametrize("new_file", [False, True])
@pytest.mark.parametrize("writer, node", [(other("p0.local_checks"), {"engine_run": True}),   # engine が走らせる節
                                          (other("p3.fix", run_by="writer"), {})])            # 回す側の節（graph の runners）
def test_change_with_a_writer_in_the_interval_is_recorded_not_refused(repo, writer, node, new_file):
    """区間に作業ツリーへ書きうる手が重なるなら、中身の書き換えも並びの変化も帰属を断定せず記録だけ残す（人の関所 2 周目の条件 1）"""
    inst = guarded()
    b = Board({inst["id"]: inst, writer["id"]: writer}, {inst["id"]: {}, writer["id"]: node})
    (repo / ("new.py" if new_file else "a.py")).write_text("一式の副産物\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    row = b.state["git_mismatches"][0]
    assert row["concurrent_writers"] == [writer["id"]] and "断定しない" in row["accepted"]
    assert (row["diff"] if new_file else row["content"]) == (["?? new.py"] if new_file else ["a.py"])


@pytest.mark.parametrize("done_at, refused", [(T2, False), (T1, False), (T0, True)])
def test_a_writer_done_inside_the_interval_still_overlaps(repo, done_at, refused):
    """区間の途中で済んだ書き手も重なる（今の status でなく区間で数える。同じ秒は重なりに倒す）。区間より前に済んだ書き手は重ならない"""
    inst = guarded()
    w = other("p0.local_checks", status="done", done_at=done_at)
    b = Board({inst["id"]: inst, w["id"]: w}, {inst["id"]: {}, w["id"]: {"engine_run": True}})
    (repo / "a.py").write_text("一式の副産物\n", encoding="utf-8")
    if refused:
        with pytest.raises(Reject, match="中身 a.py"):
            commands._tree_guard(b, inst["id"], inst, None)
    else:
        commands._tree_guard(b, inst["id"], inst, None)
        assert b.state["git_mismatches"][0]["concurrent_writers"] == ["p0.local_checks"]


def test_the_interval_starts_at_the_first_attempt_the_tree_base_came_from(repo):
    """起こし直した試行の区間は、木の基準を写した系譜の最初の試行から——attempt_log の頭が settle の行（prev_emitted_at を持たない）
    でも、今の試行の emitted_at に倒さない"""
    inst = {**guarded(emitted_at=T3), "attempt_log": [{"at": T2, "kind": "failed", "reason": "子が落ちた"},
                                                      {"at": T3, "reason": "起こし直し", "prev_emitted_at": T0}]}
    w = other("p0.local_checks", status="done", done_at=T1)
    b = Board({inst["id"]: inst, w["id"]: w}, {inst["id"]: {}, w["id"]: {"engine_run": True}})
    assert commands._overlapping(b, inst) == ([], ["p0.local_checks"])


def test_instance_without_tree_id_is_compared_by_names_with_a_trace(repo):
    """前の版の engine が出した instance（木の id が無い）は並びだけで比べ、測れなかった痕跡を残して通す"""
    inst = guarded()
    del inst["tree_before_id"]
    b = Board({inst["id"]: inst}, {inst["id"]: {}})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    assert b.state["unevaluable"][0]["trigger"] == "r1.inv.tree_before_id"


# ---------------------------------------------------------------- 書き換える節の申告の両方向の突合（記録だけ）
def fix_board(repo, round_base=None, others=()):
    inst = {"id": "p3.fix", "node": "p3.fix", "status": "pending", "run_by": "writer", "emitted_at": T1, "tree_before_id": util.worktree_tree()}
    b = Board({"p3.fix": inst, **{o["id"]: o for o in others}}, {"p3.fix": {"declared_files": "changes[].files[]"},
                                                                  **{o["id"]: {"engine_run": True} for o in others}})
    b.rd["tree_base"] = {"p3.fix": round_base or inst["tree_before_id"]}
    return b, inst


def out(*files):
    return {"changes": [{"files": list(files)}]}


def declared_rows(b):
    return [r for r in b.state.get("git_mismatches", []) if r.get("kind") == "declared"]


def test_declared_mismatch_is_recorded_in_both_directions_not_refused(repo):
    """書いたのに申告に無い・申告したのに変わっていないは、拒まずに記録へ倒す（区間の差には重なる手の書き込みも入る）"""
    b, inst = fix_board(repo, others=[other("p0.local_checks")])
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    (repo / "made.txt").write_text("テストが作った\n", encoding="utf-8")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out("keep.py", "a.py"), None)
    row, = declared_rows(b)
    assert (row["undeclared"], row["unwritten"], row["overlapping"]) == (["made.txt"], ["a.py"], ["p0.local_checks"])
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out("keep.py", "made.txt"), "会話の writer の理由")
    assert len(declared_rows(b)) == 1   # 合っていれば行を積まない


def test_accept_tree_change_is_kept_on_the_declared_row(repo):
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), "テストの副産物を消し忘れた")
    row, = declared_rows(b)
    assert row["undeclared"] == ["keep.py"] and row["unwritten"] == [] and row["accepted"] == "テストの副産物を消し忘れた"


def test_renamed_file_counts_as_written_under_its_old_name(repo):
    """差の名前に改名の古い側が出ない設定（diff.renames）でも、消えた古い側の申告を『変わっていない』にしない"""
    b, inst = fix_board(repo)
    git(repo, "mv", "old.py", "new_name.py")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out("old.py", "new_name.py"), None)
    assert declared_rows(b) == []


def test_retried_instance_declares_the_round_total(repo):
    """差し戻しで出し直した instance は、周の基準（最初に出した時点）から申告の累計を突き合わせる——前の試行の分を申告してよく、
    前の試行と今の試行の間に機械の節が作った物（一式の副産物）は今の試行の区間の外"""
    first = util.worktree_tree()
    (repo / "keep.py").write_text("前の試行が直した\n", encoding="utf-8")
    (repo / "suite_made.txt").write_text("緑の確認の副産物\n", encoding="utf-8")
    b, inst = fix_board(repo, round_base=first)
    (repo / "a.py").write_text("今の試行が直した\n", encoding="utf-8")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out("keep.py", "a.py"), None)
    assert declared_rows(b) == []


def test_instance_without_tree_id_skips_the_declared_check_with_a_trace(repo):
    b, inst = fix_board(repo)
    del inst["tree_before_id"]
    b.rd.pop("tree_base")
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), None)
    assert b.state["unevaluable"][0]["trigger"] == "p3.fix.declared_files" and declared_rows(b) == []


@pytest.mark.parametrize("broken", ["now", "diff"])
def test_tree_unavailable_with_a_tree_id_refuses_instead_of_recording(repo, monkeypatch, broken):
    """木の id を持つ instance で今の木・木の差が取れない回は、測れない痕跡へ倒さずに拒む——環境の失敗で申告の突合を素通りさせない"""
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    monkeypatch.setattr(commands, "worktree_tree" if broken == "now" else "tree_names_between", lambda *a, **k: None)
    with pytest.raises(Reject, match="木"):
        commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), None)
    assert "unevaluable" not in b.state and declared_rows(b) == []


def test_declared_spelling_is_rewritten_in_the_reply_to_the_repo_relative_form(repo):
    """綴りの揺れ（./・\\ 区切り・根の中の絶対パス）は受け付けで返答そのものを書き換える——rules・記録にも同じ名前が届く。根の外は
    そのまま（旧い綴りの文字列の配列の葉も同じ関数で書き換わる）"""
    root = util.repo_root()
    reply = {"changes": [{"files": ["./keep.py", "sub\\x.py", str(repo / "made.txt"), "../outside.py", "/elsewhere/y.py"]}]}
    commands.pointers.rewrite_at(reply, "changes[].files[]", lambda v: commands._repo_rel(v, root))
    assert reply["changes"][0]["files"] == ["keep.py", "sub/x.py", "made.txt", "../outside.py", "/elsewhere/y.py"]
    old = {"changes": [{"files": ["./keep.py"]}]}
    commands.pointers.rewrite_at(old, "changes[].files", lambda v: commands._repo_rel(v, root))
    assert old == {"changes": [{"files": ["keep.py"]}]}


# ---------------------------------------------------------------- 書き換える子の専用の一時の置き場
def on_board(monkeypatch, b):
    monkeypatch.setattr(commands, "_board_update", lambda d, fn, allow_halted=False: fn(b))


@pytest.mark.parametrize("session_at", [("sess-1",), ("-repo", "sess-1"), ("projects", "-repo", "sess-1")])
def test_child_tmp_is_counted_without_the_childs_session_and_removed(tmp_path, monkeypatch, session_at):
    """子の会話の置き場は、段の深さを問わず名前が session_id の段を外す"""
    b = Board({}, {})
    on_board(monkeypatch, b)
    tmp = tmp_path / "gl-w-x"
    sess = tmp.joinpath(*session_at) / "tasks"
    sess.mkdir(parents=True)
    (sess / "t.json").write_text("claude 自身", encoding="utf-8")
    (tmp / "pytest-of-u").mkdir()
    (tmp / "pytest-of-u" / "x.txt").write_text("子の Bash", encoding="utf-8")
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, "sess-1")
    row, = b.state["git_mismatches"]
    assert (row["kind"], row["measured"], row["files"], row["sample"]) == ("outside_tmp", True, 1, ["pytest-of-u/x.txt"])
    assert not tmp.exists()


def test_child_tmp_with_only_the_session_leaves_no_row(tmp_path, monkeypatch):
    b = Board({}, {})
    on_board(monkeypatch, b)
    tmp = tmp_path / "gl-w-z"
    (tmp / "-repo" / "sess-1").mkdir(parents=True)
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, "sess-1")
    assert "git_mismatches" not in b.state and not tmp.exists()


def test_empty_child_tmp_says_it_could_not_measure(tmp_path, monkeypatch):
    b = Board({}, {})
    on_board(monkeypatch, b)
    tmp = tmp_path / "gl-w-y"
    tmp.mkdir()
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, None)
    row, = b.state["git_mismatches"]
    assert row["measured"] is False and "測れていない" in row["note"]


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="権限 000 の段は POSIX の一般の利用者でだけ読めない")
def test_unreadable_part_of_the_child_tmp_is_not_counted_as_measured(tmp_path, monkeypatch):
    b = Board({}, {})
    on_board(monkeypatch, b)
    tmp = tmp_path / "gl-w-u"
    (tmp / "locked").mkdir(parents=True)
    (tmp / "locked" / "x.txt").write_text("x", encoding="utf-8")
    (tmp / "locked").chmod(0)
    try:
        commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, None)
    finally:
        (tmp / "locked").chmod(0o700)
    row, = b.state["git_mismatches"]
    assert row["measured"] is False and "数えられない" in row["note"]


def test_child_tmp_is_kept_when_the_trace_cannot_be_written(tmp_path, monkeypatch, capsys):
    def refuse(d, fn, allow_halted=False):
        raise util.BoardConflict("競った")
    monkeypatch.setattr(commands, "_board_update", refuse)
    tmp = tmp_path / "gl-w-k"
    tmp.mkdir()
    (tmp / "x.txt").write_text("子の Bash", encoding="utf-8")
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, None)
    assert (tmp / "x.txt").is_file() and str(tmp) in capsys.readouterr().err


class ProbeBoard:
    """launch_one が盤面を読み書きする所（Board(d)・_board_update）だけの偽物。state は全部の開き直しで共有する"""
    state = {}

    def __init__(self, d):
        self.round = 1

    def save(self):
        pass


@pytest.mark.parametrize("writable", [True, False])
def test_launch_one_probes_once_and_falls_back_to_the_shared_tmp(tmp_path, monkeypatch, writable):
    """書き換える子の専用の一時の置き場は、run に 1 回だけ確かめの子（いちばん安いモデル・作業ツリーの外）で書けるかを測り、
    書けなければ共有の置き場で起こして、測れていないことを痕跡に残す（人の関所の条件 2）"""
    ProbeBoard.state = {"round": 1}
    monkeypatch.delenv("CLAUDE_CODE_TMPDIR", raising=False)   # engine 自身が claude の子として走る場は親の値を持つ——拾わない
    monkeypatch.setattr(commands, "Board", ProbeBoard)
    monkeypatch.setattr(commands, "launch_refusal", lambda inst, cwd, d: None)
    calls = []

    def fake_run_role(argv, prompt, out_path, **kw):
        env, meta = kw.get("env") or {}, kw.get("meta") or {}
        calls.append({"argv": argv, "env": env, "cwd": kw.get("cwd"), "probe": meta.get("probe")})
        if meta.get("probe") and writable:
            pathlib.Path(env["TMPDIR"], commands.PROBE_FILE).write_text("", encoding="utf-8")
        if not meta.get("probe") and env.get("CLAUDE_CODE_TMPDIR"):
            pathlib.Path(env["TMPDIR"], "made-by-child.txt").write_text("x", encoding="utf-8")
        return {"ok": True, "why": None, "session_id": "s", "superseded": False, "runs": [], "rejections": []}
    monkeypatch.setattr(commands, "run_role", fake_run_role)
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    inst = {"id": "p3.fix", "node": "p3.fix", "out_path": str(tmp_path / "o.json"),
            "launch": {"kind": "runner", "edits": True, "stdin": str(prompt),
                       "argv": ["claude", "-p", "--model", "opus", "--effort", "high", "--output-format", "json"]}}
    for _ in range(2):
        commands.launch_one(str(tmp_path), inst, 0, cwd=str(tmp_path))
    probes, writers = [c for c in calls if c["probe"]], [c for c in calls if not c["probe"]]
    assert len(probes) == 1 and len(writers) == 2
    assert probes[0]["argv"] == ["claude", "-p", "--model", commands.PROBE_MODEL, "--output-format", "json"]
    assert probes[0]["cwd"] != str(tmp_path)
    assert ProbeBoard.state["child_tmp_probe"]["writable"] is writable
    rows = ProbeBoard.state["git_mismatches"]
    if writable:
        assert all(w["env"].get("CLAUDE_CODE_TMPDIR") == w["env"]["TMPDIR"] for w in writers)
        assert [(r["measured"], r["files"]) for r in rows] == [(True, 1), (True, 1)]
    else:
        assert not any(w["env"].get("CLAUDE_CODE_TMPDIR") for w in writers)
        assert [r["measured"] for r in rows] == [False, False]
        assert ProbeBoard.state["unevaluable"][0]["trigger"] == "child_tmp_probe"


# ---------------------------------------------------------------- 外から来た JSON と引数の孤立サロゲート
def test_reply_with_a_lone_surrogate_is_sent_back_to_the_role():
    with pytest.raises(AnswerReject, match=r"\.a\[1\] の 2 字目"):
        commands.parse_output('{"a": ["ok", "x\\ud800"]}')


def test_input_file_with_a_lone_surrogate_is_refused(tmp_path):
    f = tmp_path / "in.json"
    f.write_text('{"k\\udc80": 1}', encoding="utf-8")
    with pytest.raises(Reject, match="の鍵"):
        util.read_input_json(f)


def test_declaration_with_a_lone_surrogate_is_an_error_not_a_crash():
    steps, err = declared.parse('{"suite": [{"name": "\\ud800", "argv": ["x"]}]}')
    assert steps is None and "孤立サロゲート" in err


def test_every_string_argument_but_the_path_only_ones_is_checked():
    from glharness import LOOP, loop_module
    loop = loop_module()
    src = pathlib.Path(LOOP).read_text(encoding="utf-8")
    names = {m.group(1).replace("-", "_") for m in re.finditer(r'add_argument\("--([a-z-]+)"(?![^)]*action=)(?![^)]*type=int)', src)}
    names -= {"by"}   # choices で縛られる（壊れた字は argparse が先に拒む）
    assert {"lang", "accept_tree_change", "agent_id", "thickness", "decider", "loop"} <= names
    for name in sorted(names - set(loop.PATH_ONLY_ARGS)):
        with pytest.raises(Reject, match=f"--{name.replace('_', '-')} の 2 字目"):
            loop.refuse_broken_args(argparse.Namespace(**{name: "a\udce3"}))
    loop.refuse_broken_args(argparse.Namespace(**{n: "a\udce3" for n in loop.PATH_ONLY_ARGS}, request="@d\udce3"))
