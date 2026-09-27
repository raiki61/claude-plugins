"""engine が子の書いた物を測る口——道具つきの役の前後の突合（中身の木の id）・書き換える節の申告の両方向の突合・書き換える子の
専用の一時の置き場の数え・外から来た JSON と引数の孤立サロゲートの検め。本物の git の使い捨てのリポジトリの上で直に呼ぶ"""
import argparse
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


def guarded(iid="r1.inv", run_by="investigator"):
    return {"id": iid, "node": iid, "status": "pending", "run_by": run_by, "tree_before": util.porcelain(),
            "tree_before_id": util.worktree_tree()}


# ---------------------------------------------------------------- 道具つきの役の前後の突合
def test_rewriting_an_already_modified_file_is_caught_by_the_tree_id(repo):
    """既に ' M' のファイルの中身だけを書き換えても porcelain は同じ——木の id で拒む"""
    inst = guarded()
    b = Board({inst["id"]: inst}, {inst["id"]: {}})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    assert util.porcelain() == inst["tree_before"]
    with pytest.raises(Reject, match="中身 a.py"):
        commands._tree_guard(b, inst["id"], inst, None)


def test_content_change_with_a_writer_in_the_wave_is_recorded_not_refused(repo):
    """同じ波に作業ツリーへ書きうる手（回す側の節・engine が走らせる節）が居るなら、中身の書き換えの帰属を断定せず記録だけ残す"""
    inst = guarded()
    other = {"id": "p0.local_checks", "node": "p0.local_checks", "status": "pending", "run_by": "tester"}
    b = Board({inst["id"]: inst, other["id"]: other}, {inst["id"]: {}, other["id"]: {"engine_run": True}})
    (repo / "a.py").write_text("一式の副産物\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    row = b.state["git_mismatches"][0]
    assert row["content"] == ["a.py"] and row["concurrent_writers"] == ["p0.local_checks"] and "断定しない" in row["accepted"]


def test_new_file_is_refused_even_with_a_writer_in_the_wave(repo):
    """状態コードとパスの並びが変わった形は、今までどおり拒む（書く手が居ても通さない）"""
    inst = guarded()
    other = {"id": "p3.fix", "node": "p3.fix", "status": "pending", "run_by": "writer"}
    b = Board({inst["id"]: inst, other["id"]: other}, {inst["id"]: {}, other["id"]: {}})
    (repo / "new.py").write_text("x\n", encoding="utf-8")
    with pytest.raises(Reject, match="new.py"):
        commands._tree_guard(b, inst["id"], inst, None)


def test_instance_without_tree_id_is_compared_by_names_with_a_trace(repo):
    """前の版の engine が出した instance（木の id が無い）は並びだけで比べ、測れなかった痕跡を残して通す"""
    inst = guarded()
    del inst["tree_before_id"]
    b = Board({inst["id"]: inst}, {inst["id"]: {}})
    (repo / "a.py").write_text("役が書き換えた\n", encoding="utf-8")
    commands._tree_guard(b, inst["id"], inst, None)
    assert b.state["unevaluable"][0]["trigger"] == "r1.inv.tree_before_id"


# ---------------------------------------------------------------- 書き換える節の申告の両方向の突合
def fix_board(repo, round_base=None):
    inst = {"id": "p3.fix", "node": "p3.fix", "status": "pending", "run_by": "writer", "tree_before_id": util.worktree_tree()}
    b = Board({"p3.fix": inst}, {"p3.fix": {"declared_files": "changes[].files"}})
    b.rd["tree_base"] = {"p3.fix": round_base or inst["tree_before_id"]}
    return b, inst


def out(*files):
    return {"changes": [{"files": list(files)}]}


def test_declared_files_must_match_what_changed_in_both_directions(repo):
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    (repo / "made.txt").write_text("テストが作った\n", encoding="utf-8")
    with pytest.raises(AnswerReject, match=r"書いたのに申告に無い: \['made.txt'\]"):
        commands._declared_guard(b, "p3.fix", inst, "changes[].files", out("keep.py"), None)
    with pytest.raises(AnswerReject, match=r"申告したのに変わっていない: \['a.py'\]"):
        commands._declared_guard(b, "p3.fix", inst, "changes[].files", out("keep.py", "made.txt", "a.py"), None)
    # 綴りの揺れ（./・絶対パス）はリポジトリの根からの相対にそろえてから比べる
    commands._declared_guard(b, "p3.fix", inst, "changes[].files", out("./keep.py", str(repo / "made.txt")), None)


def test_accept_tree_change_leaves_a_declared_trace(repo):
    b, inst = fix_board(repo)
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    commands._declared_guard(b, "p3.fix", inst, "changes[].files", out(), "テストの副産物を消し忘れた")
    row = b.state["git_mismatches"][0]
    assert row["kind"] == "declared" and row["undeclared"] == ["keep.py"] and row["unwritten"] == []


def test_renamed_file_counts_as_written_under_its_old_name(repo):
    """差の名前に改名の古い側が出ない設定（diff.renames）でも、消えた古い側の申告を『変わっていない』にしない"""
    b, inst = fix_board(repo)
    git(repo, "mv", "old.py", "new_name.py")
    commands._declared_guard(b, "p3.fix", inst, "changes[].files", out("old.py", "new_name.py"), None)


def test_retried_instance_declares_the_round_total(repo):
    """差し戻しで出し直した instance は、周の基準（最初に出した時点）から申告の累計を突き合わせる——前の試行の分を申告してよく、
    前の試行と今の試行の間に機械の節が作った物（一式の副産物）は今の試行の区間の外"""
    first = util.worktree_tree()
    (repo / "keep.py").write_text("前の試行が直した\n", encoding="utf-8")
    (repo / "suite_made.txt").write_text("緑の確認の副産物\n", encoding="utf-8")
    b, inst = fix_board(repo, round_base=first)
    (repo / "a.py").write_text("今の試行が直した\n", encoding="utf-8")
    commands._declared_guard(b, "p3.fix", inst, "changes[].files", out("keep.py", "a.py"), None)


def test_instance_without_tree_id_skips_the_declared_check_with_a_trace(repo):
    b, inst = fix_board(repo)
    del inst["tree_before_id"]
    b.rd.pop("tree_base")
    (repo / "keep.py").write_text("直した\n", encoding="utf-8")
    commands._declared_guard(b, "p3.fix", inst, "changes[].files", out(), None)
    assert b.state["unevaluable"][0]["trigger"] == "p3.fix.declared_files"


# ---------------------------------------------------------------- 書き換える子の専用の一時の置き場
def test_child_tmp_is_counted_without_the_childs_session_and_removed(tmp_path, monkeypatch):
    b = Board({}, {})
    monkeypatch.setattr(commands, "_board_update", lambda d, fn, allow_halted=False: fn(b))
    tmp = tmp_path / "gl-w-x"
    (tmp / "-repo" / "sess-1" / "tasks").mkdir(parents=True)
    (tmp / "-repo" / "sess-1" / "tasks" / "t.json").write_text("claude 自身", encoding="utf-8")
    (tmp / "pytest-of-u").mkdir()
    (tmp / "pytest-of-u" / "x.txt").write_text("子の Bash", encoding="utf-8")
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, "sess-1")
    row = b.state["git_mismatches"][0]
    assert (row["kind"], row["measured"], row["files"], row["sample"]) == ("outside_tmp", True, 1, ["pytest-of-u/x.txt"])
    assert not tmp.exists()


def test_empty_child_tmp_says_it_could_not_measure(tmp_path, monkeypatch):
    """専用の置き場が空＝CLAUDE_CODE_TMPDIR が効いた印が無い。『書いていない』と『測れていない』を同じ 0 にしない"""
    b = Board({}, {})
    monkeypatch.setattr(commands, "_board_update", lambda d, fn, allow_halted=False: fn(b))
    tmp = tmp_path / "gl-w-y"
    tmp.mkdir()
    commands._note_child_tmp("d", {"id": "p3.fix"}, tmp, None)
    row = b.state["git_mismatches"][0]
    assert row["measured"] is False and "測れていない" in row["note"]


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
    """loop.py の文字列の引数は全部検める——外すのは PATH_ONLY_ARGS だけ（引数を足しても既定で検めの中に入る）"""
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
