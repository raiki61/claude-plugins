"""engine が子の書いた物を測る口——道具つきの役の前後の突合（中身の木の id・区間の重なり）・書き換える節の申告の両方向の記録・
書き換える子の専用の一時の置き場の数えと確かめ・外から来た JSON と引数の孤立サロゲートの検め。本物の git の使い捨てのリポジトリの上で直に呼ぶ"""
import argparse
import json
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


EDITS = ("p3.fix", "p3.delta_fix", "spec.write")


class Board:
    """_overlapping が読む所（instance・graph の launch.runner.edits）と、突合が書く盤面の state だけの偽物"""

    def __init__(self, instances, nodes=None, graph=None):
        self.rd = {"instances": instances}
        self.nodes = nodes or {}
        self.graph = graph or {"runners": ["writer", "skill"], "launch": {"runner": {"edits": list(EDITS)}}}
        self.state = {"round": 1}
        self.round = 1


T0, T1, T2, T3 = "2026-09-27T10:00:00+09:00", "2026-09-27T10:05:00+09:00", "2026-09-27T10:10:00+09:00", "2026-09-27T10:15:00+09:00"
DECLARED_STEPS = {"kind": "engine_run", "builtin": "declared_checks", "steps": [{"name": "suite", "argv": ["pytest", "-q"]}], "sha": "s"}
HELPER_ONLY = {"kind": "engine_run", "builtin": "parallel_pr", "steps": [{"name": "parallel-pr.py", "argv": commands.helper_argv("parallel-pr.py")}],
               "sha": None}


def guarded(iid="r1.inv", run_by="investigator", emitted_at=T1, emitted_rev=10):
    return {"id": iid, "node": iid, "status": "pending", "run_by": run_by, "emitted_at": emitted_at, "emitted_rev": emitted_rev,
            "tree_before": util.porcelain(), "tree_before_id": util.worktree_tree()}


def other(iid, status="pending", done_at=None, run_by="writer", launch=None, done_rev=None):
    return {"id": iid, "node": iid, "status": status, "run_by": run_by, **({"done_at": done_at} if done_at else {}),
            **({"done_rev": done_rev} if done_rev is not None else {}), **({"launch": launch} if launch else {})}


# ---------------------------------------------------------------- 道具つきの役の前後の突合
def test_rewriting_an_already_modified_file_is_caught_by_the_tree_id(repo):
    """既に ' M' のファイルの中身だけを書き換えても porcelain は同じ——木の id で拒む（区間に書き手が重ならない）"""
    inst = guarded()
    b = Board({inst["id"]: inst})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    assert util.porcelain() == inst["tree_before"]
    with pytest.raises(Reject, match="中身 a.py"):
        commands._tree_guard(b, inst["id"], inst, None)


WRITERS = [pytest.param(other("p0.local_checks", launch=DECLARED_STEPS), id="engine-runs-the-declared-suite"),
           pytest.param(other("spec.write"), id="node-in-launch-runner-edits"),
           pytest.param(other("p3.delta_fix", status="done", done_at=T1, done_rev=11), id="edits-node-done-in-the-same-second-after")]
NOT_WRITERS = [pytest.param(other("p1.provenance"), id="read-only-runner-node"),
               pytest.param(other("p1.local_review", run_by="skill"), id="skill-node"),
               pytest.param(other("p0.parallel_pr", launch=HELPER_ONLY), id="engine-runs-only-a-bundled-helper"),
               pytest.param(other("p0.local_checks", status="done", done_at=T1, done_rev=9, launch=DECLARED_STEPS),
                            id="ancestor-done-in-the-same-second-before"),
               pytest.param(other("p0.local_checks", launch={"kind": "delegate"}), id="delegate-in-a-copy")]


@pytest.mark.parametrize("new_file", [False, True])
@pytest.mark.parametrize("writer", WRITERS)
def test_change_with_a_writer_in_the_interval_is_recorded_not_refused(repo, writer, new_file):
    """区間に作業ツリーへ書きうる手が重なるなら、中身の書き換えも並びの変化も帰属を断定せず記録だけ残す（人の関所 2 周目の条件 1）"""
    inst = guarded()
    b = Board({inst["id"]: inst, writer["id"]: writer})
    (repo / ("new.py" if new_file else "a.py")).write_text("一式の副産物\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    row = b.state["git_mismatches"][0]
    assert row["concurrent_writers"] == [writer["id"]] and "断定しない" in row["accepted"]
    assert (row["diff"] if new_file else row["content"]) == (["?? new.py"] if new_file else ["a.py"])


@pytest.mark.parametrize("new_file", [False, True])
@pytest.mark.parametrize("hand", NOT_WRITERS)
def test_change_with_only_non_writers_in_the_interval_is_refused(repo, hand, new_file):
    """入口 _tree_guard の負の側: 重なるのが書く権限の無い手だけなら、今までどおり拒む（人の関所 2 周目の条件 1・3 周目の条件 5）"""
    inst = guarded()
    b = Board({inst["id"]: inst, hand["id"]: hand})
    (repo / ("new.py" if new_file else "a.py")).write_text("役が書いた\n", encoding="utf-8")
    with pytest.raises(Reject, match="作業ツリーが変わっている"):
        commands._tree_guard(b, inst["id"], inst, None)


@pytest.mark.parametrize("hand, writes", [(p.values[0], True) for p in WRITERS] + [(p.values[0], False) for p in NOT_WRITERS],
                         ids=[p.id for p in WRITERS + NOT_WRITERS])
def test_declared_rows_name_only_writers_as_overlapping(repo, hand, writes):
    """入口 _record_declared の負の側: 申告の食い違いの行の overlapping は、書く権限の無い手を数えない"""
    b, inst = fix_board(repo, others=[hand])
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), None)
    row, = declared_rows(b)
    assert row["overlapping"] == ([hand["id"]] if writes else [])


@pytest.mark.parametrize("done_rev, done_at, refused", [(11, T1, False), (10, T1, True), (9, T1, True), (None, T2, False),
                                                        (None, T1, False), (None, T0, True)])
def test_a_writer_done_inside_the_interval_still_overlaps(repo, done_rev, done_at, refused):
    """区間の途中で済んだ書き手も重なる（今の status でなく区間で数える）。前後は盤面の版（保存ごとに進む論理時計）で分け、同じ秒でも
    区間より前の版で済んだ書き手は重ならない。版を持たない旧い盤面の行だけ時刻で比べ、同じ秒は重なりに倒す"""
    inst = guarded()
    w = other("p0.local_checks", status="done", done_at=done_at, done_rev=done_rev, launch=DECLARED_STEPS)
    b = Board({inst["id"]: inst, w["id"]: w})
    (repo / "a.py").write_text("一式の副産物\n", encoding="utf-8")
    if refused:
        with pytest.raises(Reject, match="中身 a.py"):
            commands._tree_guard(b, inst["id"], inst, None)
    else:
        commands._tree_guard(b, inst["id"], inst, None)
        assert b.state["git_mismatches"][0]["concurrent_writers"] == ["p0.local_checks"]


@pytest.mark.parametrize("prev_rev, want", [(5, ["p0.local_checks"]), (None, ["p0.local_checks"])])
def test_the_interval_starts_at_the_first_attempt_the_tree_base_came_from(repo, prev_rev, want):
    """起こし直した試行の区間は、木の基準を写した系譜の最初の試行から——attempt_log の頭が settle の行（prev_emitted_at を持たない）
    でも、今の試行の emitted_at に倒さない。前の版の engine の試行（版を持たない）が系譜に在れば時刻で比べる"""
    inst = {**guarded(emitted_at=T3, emitted_rev=20), "attempt_log": [{"at": T2, "kind": "failed", "reason": "子が落ちた"},
                                                                      {"at": T3, "reason": "起こし直し", "prev_emitted_at": T0,
                                                                       "prev_emitted_rev": prev_rev}]}
    w = other("p0.local_checks", status="done", done_at=T1, done_rev=8, launch=DECLARED_STEPS)
    b = Board({inst["id"]: inst, w["id"]: w})
    assert commands._overlapping(b, inst) == ([], want)


@pytest.mark.parametrize("graph", ["review-loop", "review-loop-tdd", "research-loop"])
def test_bundled_graphs_have_no_writer_among_the_guarded_roles_stage(repo, graph):
    """同梱の graph の実物で、道具つきの役の区間に同じ段の他の節だけが重なる盤面では書き手が居ない——CI が 3 OS で赤にした形
    （graph の runners の役名で数えると、P1 では常に書き手が居る扱いになった）の回帰の腕"""
    from engine.schema import load_graph
    g, why = load_graph(commands.PLUGIN_ROOT / "graphs" / f"{graph}.json")
    assert not why
    guarded_nodes = [k for k, n in g["nodes"].items() if n.get("run_by") in g.get("tree_guard_roles", [])]
    assert guarded_nodes
    for nid in guarded_nodes:
        stage = g["nodes"][nid].get("stage")
        inst = {**guarded(nid), "node": nid}
        peers = {k: other(k, run_by=n["run_by"]) for k, n in g["nodes"].items()
                 if k != nid and n.get("stage") == stage and not n.get("engine_run")
                 and k not in ((g.get("launch") or {}).get("runner") or {}).get("edits", [])}
        assert peers, nid
        assert commands._overlapping(Board({nid: inst, **peers}, g["nodes"], g), inst)[1] == [], nid


def test_instance_without_tree_id_is_compared_by_names_with_a_trace(repo):
    """前の版の engine が出した instance（木の id が無い）は並びだけで比べ、測れなかった痕跡を残して通す"""
    inst = guarded()
    del inst["tree_before_id"]
    b = Board({inst["id"]: inst})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    assert b.state["unevaluable"][0]["trigger"] == "r1.inv.tree_before_id"


# ---------------------------------------------------------------- 書き換える節の申告の両方向の突合（記録だけ）
def fix_board(repo, round_base=None, others=()):
    inst = {"id": "p3.fix", "node": "p3.fix", "status": "pending", "run_by": "writer", "emitted_at": T1, "emitted_rev": 10,
            "tree_before_id": util.worktree_tree()}
    b = Board({"p3.fix": inst, **{o["id"]: o for o in others}}, {"p3.fix": {"declared_files": "changes[].files[]"}})
    b.rd["tree_base"] = {"p3.fix": round_base or inst["tree_before_id"]}
    return b, inst


def out(*files):
    return {"changes": [{"files": list(files)}]}


def declared_rows(b):
    return [r for r in b.state.get("git_mismatches", []) if r.get("kind") == "declared"]


def test_declared_mismatch_is_recorded_in_both_directions_not_refused(repo):
    """書いたのに申告に無い・申告したのに変わっていないは、拒まずに記録へ倒す（区間の差には重なる手の書き込みも入る）"""
    b, inst = fix_board(repo, others=[other("p0.local_checks", launch=DECLARED_STEPS)])
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


def git_fails(monkeypatch, name):
    """engine の git の口 name を、git の言い分を why に足して None を返す偽物にする"""
    def fail(*a, why=None, **k):
        why = why if why is not None else next((x for x in a if isinstance(x, list)), None)   # worktree_tree(why) は位置で渡る
        if why is not None:
            why.append("fatal: 検査用の git の言い分")
    monkeypatch.setattr(commands, name, fail)


@pytest.mark.parametrize("broken", ["worktree_tree", "tree_names_between"])
def test_tree_unavailable_with_a_tree_id_refuses_instead_of_recording(repo, monkeypatch, broken):
    """木の id を持つ instance で今の木・木の差が取れない回は、測れない痕跡へ倒さずに git の言い分を添えて拒む——環境の失敗で申告の
    突合を素通りさせない"""
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    git_fails(monkeypatch, broken)
    with pytest.raises(Reject, match="検査用の git の言い分"):
        commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), None)
    assert "unevaluable" not in b.state and declared_rows(b) == []


@pytest.mark.parametrize("broken", ["worktree_tree", "tree_names_between"])
def test_tree_unavailable_with_accept_tree_change_is_traced_not_refused(repo, monkeypatch, broken):
    """--accept-tree-change を渡した回は、どの突合でも拒まずに痕跡を残して通す（人の関所 3 周目の条件 3）"""
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    git_fails(monkeypatch, broken)
    commands._record_declared(b, "p3.fix", inst, "changes[].files[]", out(), "自分の変更")
    u, = b.state["unevaluable"]
    assert u["trigger"] == "p3.fix.declared_files" and "検査用の git の言い分" in u["why"] and "自分の変更" in u["why"]


@pytest.mark.parametrize("broken", ["worktree_tree", "tree_names_between"])
@pytest.mark.parametrize("accept", [None, "自分の変更"])
def test_tree_guard_keeps_the_git_reason_when_content_names_are_unavailable(repo, monkeypatch, broken, accept):
    """道具つきの役の突合で中身の差の名前が取れない回は、名前を黙って空にしない——拒む文と記録の行に git の言い分が載る"""
    inst = guarded()
    b = Board({inst["id"]: inst})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    git_fails(monkeypatch, broken)
    if accept is None:
        with pytest.raises(Reject, match="検査用の git の言い分"):
            commands._tree_guard(b, inst["id"], inst, None)
    else:
        commands._tree_guard(b, inst["id"], inst, accept)
        row, = b.state["git_mismatches"]
        assert row["content"] == [] and "検査用の git の言い分" in row["content_unavailable"] and row["accepted"] == accept


def test_refuse_touched_and_emit_keep_the_git_reason(repo, monkeypatch):
    """起こし直しの確かめ（relaunch --if-untouched）と、節を出す時の木（Board.worktree_tree）も git の言い分を捨てない"""
    from engine import board as boardmod
    monkeypatch.setattr(commands, "stop_marks", lambda marks: [])
    git_fails(monkeypatch, "worktree_tree")
    prev = {"tree_before_id": "t" * 40, "launch_head": list(commands._own_git_marks())}
    with pytest.raises(Reject, match="検査用の git の言い分"):
        commands._refuse_touched(prev, [])
    monkeypatch.setattr(boardmod.util, "worktree_tree", lambda why=None: (why.append("fatal: 出す時の言い分"), None)[1])
    b = boardmod.Board.__new__(boardmod.Board)
    said = []
    assert b.worktree_tree(said) is None and said == ["fatal: 出す時の言い分"]
    again = []
    assert b.worktree_tree(again) is None and again == said   # 1 プロセスの中では取り直さず、言い分も同じ物を返す


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


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="SKIP read-permission: 権限 000 の段は POSIX の一般の利用者でだけ読めない")
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


def test_board_name_escapes_non_utf8_names():
    """UTF-8 でない名前（PEP 383 の孤立サロゲート）は \\xNN に逃がす——盤面の保存（UTF-8 の JSON）を落とさない"""
    assert commands._board_name("a\udce3.txt") == "a\\xe3.txt" and commands._board_name("日本語.txt") == "日本語.txt"


def test_child_tmp_row_with_a_non_utf8_name_can_be_saved(tmp_path, monkeypatch):
    """UTF-8 でない名前（Linux の os.walk が孤立サロゲートで返す）も逃がしてから行の sample に入れる——行は UTF-8 の JSON に書ける。
    APFS・NTFS はその名前のファイルを作れないので、名前を返す所（os.walk）とファイルの確かめだけを置き換える"""
    import json
    b = Board({})
    on_board(monkeypatch, b)
    tmp = tmp_path / "gl-w-n"
    tmp.mkdir()
    real_walk = os.walk   # commands.os は os そのもの——shutil.rmtree（Windows は os.walk(topdown=False) で消す）には本物を渡す
    monkeypatch.setattr(commands.os, "walk", lambda top, onerror=None, **k: real_walk(top, onerror=onerror, **k) if k
                        else iter([(str(tmp), [], ["caf\udce9.txt"])]))
    monkeypatch.setattr(pathlib.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: True)
    monkeypatch.setattr(pathlib.Path, "stat", lambda self, **k: os.stat_result((0,) * 6 + (1,) + (0,) * 3))
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, None)
    row, = b.state["git_mismatches"]
    assert row["sample"] == ["caf\\xe9.txt"] and row["measured"] is True
    json.dumps(row, ensure_ascii=False).encode("utf-8")


class ProbeBoard:
    """launch_one が盤面を読み書きする所（Board(d)・_board_update）だけの偽物。state と instance は全部の開き直しで共有する"""
    state = {}
    rd = {"instances": {}}

    def __init__(self, d):
        self.round = 1

    def save(self):
        pass


SANDBOX_FAILED = "Sandbox is required but failed to initialize: EPERM: operation not permitted, listen /tmp/srt-mux-1.sock"


def probe_launch(tmp_path, monkeypatch, probe_says):
    """確かめの子が probe_says の形で終わる run_role を置き、launch_one を呼ぶ関数と呼び出しの一覧を返す。形は 'made'（両方のファイル）・
    'ran'（作業ディレクトリのファイルだけ——専用の置き場が書けない版）・'silent'（何も作らずに終わった——Bash を呼ばなかった）・
    'failed'（子が落ちた）・'sandbox'（返答に sandbox の初期化の失敗の文）。書く子は、起こされた時点で盤面に専用の置き場の記録
    （child_tmp）が在ったかを覚える"""
    ProbeBoard.state = {"round": 1}
    monkeypatch.delenv("CLAUDE_CODE_TMPDIR", raising=False)   # engine 自身が claude の子として走る場は親の値を持つ——拾わない
    monkeypatch.setattr(commands, "Board", ProbeBoard)
    monkeypatch.setattr(commands, "launch_refusal", lambda inst, cwd, d: None)
    calls = []

    def fake_run_role(argv, prompt, out_path, **kw):
        env, meta = kw.get("env") or {}, kw.get("meta") or {}
        calls.append({"argv": argv, "env": env, "cwd": kw.get("cwd"), "probe": meta.get("probe"),
                      "recorded": (ProbeBoard.rd["instances"]["p3.fix"].get("child_tmp") or {}).get("dir")})
        if meta.get("probe"):
            if probe_says == "made":
                pathlib.Path(env["TMPDIR"], commands.PROBE_FILE).write_text("", encoding="utf-8")
            if probe_says in ("made", "ran"):
                pathlib.Path(kw["cwd"], commands.PROBE_RAN).write_text("", encoding="utf-8")
            if probe_says == "sandbox":
                pathlib.Path(out_path).write_text(json.dumps({"made": False, "error": SANDBOX_FAILED}), encoding="utf-8")
            return {"ok": probe_says != "failed", "why": "rate limit" if probe_says == "failed" else None, "session_id": "p",
                    "superseded": False, "runs": [], "rejections": []}
        if env.get("CLAUDE_CODE_TMPDIR"):
            pathlib.Path(env["TMPDIR"], "made-by-child.txt").write_text("x", encoding="utf-8")
        return {"ok": True, "why": None, "session_id": "s", "superseded": False, "runs": [], "rejections": []}
    monkeypatch.setattr(commands, "run_role", fake_run_role)
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    inst = {"id": "p3.fix", "node": "p3.fix", "out_path": str(tmp_path / "o.json"),
            "launch": {"kind": "runner", "edits": True, "stdin": str(prompt),
                       "argv": ["claude", "-p", "--model", "opus", "--effort", "high", "--output-format", "json"]}}
    ProbeBoard.rd = {"instances": {"p3.fix": dict(inst)}}
    return (lambda: commands.launch_one(str(tmp_path), inst, 0, cwd=str(tmp_path))), calls


@pytest.mark.parametrize("probe_says, writable", [("made", True), ("ran", False)])
def test_launch_one_probes_once_and_falls_back_to_the_shared_tmp(tmp_path, monkeypatch, probe_says, writable):
    """書き換える子の専用の一時の置き場は、決まった結果が出るまで確かめの子（いちばん安いモデル・作業ツリーの外・役の前置きなし）で
    書けるかを測り、書けなければ共有の置き場で起こして、測れていないことを痕跡に残す（人の関所の条件 2）。Bash が走った印（作業
    ディレクトリのファイル）が在れば sandbox は立つと決まる。専用の置き場は子を起こす前に盤面に書き、数えた後に消す（先に書く記録）"""
    launch, calls = probe_launch(tmp_path, monkeypatch, probe_says)
    for _ in range(2):
        launch()
    probes, writers = [c for c in calls if c["probe"]], [c for c in calls if not c["probe"]]
    assert len(probes) == 1 and len(writers) == 2
    assert probes[0]["argv"] == ["claude", "-p", "--model", commands.PROBE_MODEL, "--output-format", "json"]
    assert probes[0]["cwd"] != str(tmp_path)
    assert ProbeBoard.state["child_tmp_probe"]["writable"] is writable and ProbeBoard.state["child_tmp_probe"]["sandbox"] is True
    rows = ProbeBoard.state["git_mismatches"]
    if writable:
        assert all(w["env"].get("CLAUDE_CODE_TMPDIR") == w["env"]["TMPDIR"] == w["recorded"] for w in writers)
        assert [(r["measured"], r["files"]) for r in rows] == [(True, 1), (True, 1)]
    else:
        assert not any(w["env"].get("CLAUDE_CODE_TMPDIR") or w["recorded"] for w in writers)
        assert [r["measured"] for r in rows] == [False, False] and "書けない版" in rows[0]["note"]
        assert ProbeBoard.state["unevaluable"][0]["trigger"] == "child_tmp_probe"
    assert "child_tmp" not in ProbeBoard.rd["instances"]["p3.fix"]


@pytest.mark.parametrize("probe_says, said", [("failed", "rate limit"), ("silent", "Bash が走った印も")])
def test_an_undecided_probe_is_not_fixed_and_is_retried_up_to_the_limit(tmp_path, monkeypatch, probe_says, said):
    """確かめの子が落ちた回・Bash を呼ばずに終わった回は『書けない版』とも『sandbox が立たない』とも固めず、次の launch で確かめ直す。
    run で PROBE_TRIES 回決まらなければ、決まらないまま固めて共有の置き場で起こす（人の関所 3 周目の条件 4・round 2 の条件 1）。
    痕跡は『確かめられない』で、『書けない版』と取り違えない。書く子は止めずに起こす"""
    launch, calls = probe_launch(tmp_path, monkeypatch, probe_says)
    for _ in range(commands.PROBE_TRIES + 1):
        assert launch()["ok"] is True
    assert len([c for c in calls if c["probe"]]) == commands.PROBE_TRIES
    got = ProbeBoard.state["child_tmp_probe"]
    assert got["writable"] is None and got["sandbox"] is None and got["tries"] == commands.PROBE_TRIES
    notes = [r["note"] for r in ProbeBoard.state["git_mismatches"]]
    assert all("確かめられない" in n and said in n and "書けない版" not in n for n in notes)


def test_a_probe_that_sees_the_sandbox_init_failure_hands_the_writer_back(tmp_path, monkeypatch):
    """確かめの子の返答に sandbox の初期化の失敗の文が在れば、入れ子の sandbox（子の Bash が走らない場）と固め、書く子を起こさずに
    会話に返す（handback——launch の締めが attempt_log に handback を書く）。理由は外し方を名指す。固めた後の launch は確かめ直さない"""
    launch, calls = probe_launch(tmp_path, monkeypatch, "sandbox")
    for _ in range(2):
        got = launch()
        assert got["ok"] is False and got["handback"] is True and "excludedCommands" in got["why"] and "--reprobe" in got["why"]
    assert [c["probe"] for c in calls] == ["child_tmp"]                     # 書く子は起こさない・確かめは 1 回
    rec = ProbeBoard.state["child_tmp_probe"]
    assert rec["sandbox"] is False and "初期化で落ちた" in rec["why"]


def test_old_board_probe_record_keeps_what_it_proved(tmp_path, monkeypatch):
    """旧い盤面の記録（sandbox の鍵が無い）は、専用の置き場に書けた（Bash が走った）ときだけ決まった物と読み、ほかは確かめ直す"""
    launch, calls = probe_launch(tmp_path, monkeypatch, "made")
    ProbeBoard.state["child_tmp_probe"] = {"writable": True, "at": "t", "why": None, "tries": 1}
    launch()
    assert not [c for c in calls if c["probe"]]
    ProbeBoard.state["child_tmp_probe"] = {"writable": False, "at": "t", "why": "旧い版の『書けない版』", "tries": 1}
    launch()
    assert len([c for c in calls if c["probe"]]) == 1 and ProbeBoard.state["child_tmp_probe"]["sandbox"] is True


def test_probe_that_cannot_make_its_places_is_undecided_not_a_crash(monkeypatch):
    """確かめの子の置き場を作れない回は、launch を落とさずに『確かめられない』（固めない側）で返す"""
    def refuse(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(commands.tempfile, "mkdtemp", refuse)
    got = commands._probe_child_tmp("d", {"id": "p3.fix", "node": "p3.fix", "launch": {"argv": ["claude"]}})
    assert got["writable"] is None and "No space left" in got["why"]


def test_relaunch_counts_the_child_tmp_a_crashed_launch_left(repo, tmp_path, monkeypatch):
    """launch が締めずに居なくなった（落ちた）回の専用の置き場は、盤面の先に書いた記録から、relaunch が前の試行の子を止め切った後に
    数えて消す——起こし直しは記録を引き継ぎ、前の試行の置き場を別の試行の物と取り違えない"""
    left = tmp_path / "gl-w-left"
    left.mkdir()
    (left / "x.txt").write_text("落ちた子の Bash", encoding="utf-8")
    prev = {"id": "p3.fix", "node": "p3.fix", "status": "pending", "out_path": str(tmp_path / "o.json"), "emitted_at": T1,
            "launch": {"kind": "runner", "edits": True}, "child_tmp": {"dir": str(left), "at": T1}}
    b = Board({"p3.fix": prev})
    on_board(monkeypatch, b)
    monkeypatch.setattr(commands, "resolve_dir", lambda a: "d")
    monkeypatch.setattr(commands, "Board", lambda d: b)
    monkeypatch.setattr(commands, "probe_marks", lambda *a: None)
    monkeypatch.setattr(commands, "stop_marks", lambda marks: [])
    monkeypatch.setattr(commands, "retire_out", lambda *a: None)
    monkeypatch.setattr(commands, "reissue", lambda b_, p, why: b_.rd["instances"].__setitem__(
        "p3.fix", {**p, "attempts": 2, "out_path": p["out_path"] + ".a2", "child_tmp": p["child_tmp"]}) or b_.rd["instances"]["p3.fix"])
    b.trace = lambda *a, **k: None
    b.is_runner = lambda n: True
    b.nodes = {"p3.fix": {}}
    commands.cmd_relaunch(argparse.Namespace(node="p3.fix", reason="落ちた", if_untouched=False))
    row, = b.state["git_mismatches"]
    assert (row["instance"], row["kind"], row["files"], row["sample"]) == ("p3.fix", "outside_tmp", 1, ["x.txt"])
    assert "締めずに終わった" in row["note"] and not left.exists() and "child_tmp" not in b.rd["instances"]["p3.fix"]


def test_note_child_tmp_leaves_another_attempts_record(tmp_path, monkeypatch):
    """古い試行の締めは、同じ id の新しい試行が書いた別の置き場の記録を消さない"""
    mine, theirs = tmp_path / "gl-w-old", tmp_path / "gl-w-new"
    mine.mkdir()
    theirs.mkdir()
    b = Board({"p3.fix": {"id": "p3.fix", "child_tmp": {"dir": str(theirs), "at": T2}}})
    on_board(monkeypatch, b)
    commands._note_child_tmp("d", {"id": "p3.fix"}, mine, None)
    assert b.rd["instances"]["p3.fix"]["child_tmp"]["dir"] == str(theirs) and not mine.exists() and theirs.exists()


def test_note_child_tmp_clears_the_record_of_a_place_already_gone(tmp_path, monkeypatch):
    """置き場が既に無い（別の手が片付けた）回は数えずに、盤面の記録だけ消す——起こし直しのたびに消えた置き場の記録を運び続けない"""
    gone = tmp_path / "gl-w-gone"
    b = Board({"p3.fix": {"id": "p3.fix", "child_tmp": {"dir": str(gone), "at": T1}}})
    on_board(monkeypatch, b)
    commands._note_child_tmp("d", {"id": "p3.fix"}, gone, None)
    assert "child_tmp" not in b.rd["instances"]["p3.fix"] and "git_mismatches" not in b.state


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
