"""目的の文（graph の節 p0.purpose）の受け付け。blk-purpose の節のスクリプトが呼ぶ。Archon を知らない関数だけを出す。

- check_constraints: 前提の実測（blk-premises が置く p0.premises の返答 {"constraints": [...]}）を、写しの graph の
                     p0.premises の型と post_check に通す（目的の役が読む前提を、graphloops の record.process.constraints と
                     同じ受け付けを通った物に限る）
- check_purpose:     目的の役の返答を受け付ける。通れば盤面の purpose.json（graph の writes: process.purpose ← $）
- read_purpose:      盤面の purpose.json を読み、型に通して返す（collect）

check_purpose は dict を返し、例外で拒まない（accept.py の check_* と同じ）。check_constraints・read_purpose は Reject を投げる。
型は accept.role_schema（写しの graph の schema。注記を落とす）、post_check は写しの graph の節が名指す物を rules の
POST_CHECKS から引く——ここで写し直さない（写し直しで graph に post_check が足されても、ここを直さずに効く）。
"""
import copy
import json
import pathlib
import sys

sys.dont_write_bytecode = True   # accept.py と同じ（下で import する物の .pyc を止める）

from accept import (SNAPSHOT_SCHEMA, _Board, _graph, _guard, _in_repo, _read_board, _rev, _rules,  # noqa: E402
                    _type_errors, _write_board, role_schema, snapshot_tree, _git)
from engine.util import Reject  # noqa: E402

NODE = "p0.purpose"
PREMISES_NODE = "p0.premises"
PURPOSE_FILE = "purpose.json"             # 受け付けた目的の返答（graph の process.purpose と同じ中身）
SNAPSHOT_FILE = "purpose-snapshot.json"   # 目的の役を起こす前（intake の時）の作業ツリー。形は accept.SNAPSHOT_SCHEMA


def _post_check(nid, out, b):
    """写しの graph の節 nid が post_check を名指していれば、rules の POST_CHECKS のそれを当てる（無ければ何もしない）"""
    name = _graph()["nodes"][nid].get("post_check")
    if name:
        _rules().POST_CHECKS[name](b, nid, out, None)


def refuse_if_frozen(board):
    """盤面に目的の文が既に在れば Reject。graph の p0.purpose は once——最初の修正の前に 1 度だけ固め、以降変えない
    （事前登録。後から書き直せると、実装に合わせて目的を狭める道が開く）"""
    p = pathlib.Path(board) / PURPOSE_FILE
    if p.exists():
        raise Reject(f"盤面に目的の文 {PURPOSE_FILE} が既に在る（{p}）——目的は最初の修正の前に 1 度だけ固め、"
                     "以降は変えない（graph の p0.purpose の once）")


def check_constraints(obj, board) -> None:
    """前提の実測（p0.premises の返答）を写しの型と post_check（measured_needs_output）に通す。拒めば Reject"""
    _type_errors(obj, role_schema(PREMISES_NODE), "前提の実測（p0.premises の返答）")
    _post_check(PREMISES_NODE, copy.deepcopy(obj), _Board(board, ""))


def _tree_unchanged(repo, board):
    """目的の役が作業ツリーを変えていないか。盤面に purpose-snapshot.json（intake の時の写し）が在れば今と比べ、
    無ければ作業ツリーが綺麗であることを求める（accept.py の判定役の確かめと同じ形）。違えば Reject"""
    snap = _read_board(board, SNAPSHOT_FILE)
    if snap is None:
        dirty = _git(repo, "status", "--porcelain").splitlines()
        if dirty:
            raise Reject("作業ツリーに変更が在る——目的の役は読むだけの役で、作業ツリーを変えてはいけない"
                         f"（git status --porcelain: {dirty[:5]}{' ほか' if len(dirty) > 5 else ''}）")
        return
    _type_errors(snap, SNAPSHOT_SCHEMA, f"盤面の {SNAPSHOT_FILE} ")
    now = snapshot_tree(repo)
    if now != {k: snap[k] for k in ("porcelain", "diff_sha256")}:
        raise Reject("intake の後から作業ツリーが変わった——目的の役は読むだけの役で、作業ツリーを変えてはいけない"
                     f"（git status --porcelain: intake の時 {snap['porcelain'].splitlines()[:5]} / 今 {now['porcelain'].splitlines()[:5]}）")


def _source_files_errors(files, repo) -> list:
    """source_files のうち、git が出す形の名前（リポジトリ相対・POSIX・`./` や末尾の `/`・重ねた `/`・`.` の段なし・
    索引／ディスクの大小文字のまま）で作業ツリーに在るファイルでない物（works が足す検査）。
    写しの purpose_sources_changed は、前の周の修正が触ったファイル（`git diff --name-only` の名前）と source_files の
    完全一致の積で目的監査を走り直す。絶対パス・リポジトリの外・無い名前・git の出す形でない名前はその積に決して当たらず、
    走り直しが黙って止まる（p0.purpose は once なので、通せば run の全周で凍る）。名前の正本は git に問う——
    pathlib の正規化や is_file（大小文字を区別しない FS では `readme.md` も真）で代えない"""
    root = pathlib.Path(repo).resolve()
    bad, cands = [], []
    for f in files:
        p = pathlib.PurePosixPath(f)
        if not f or str(p) != f or p.is_absolute() or ".." in p.parts:
            bad.append(f)
            continue
        full = (root / f).resolve()
        if not (full.is_relative_to(root) and full.is_file()):
            bad.append(f)
            continue
        cands.append(f)
    if cands:
        # 追跡中と未追跡の新規（_files_changed_since の diff が拾う物と同じ）。パススペックは字のまま・大小文字を区別
        known = set(_git(repo, "--literal-pathspecs", "ls-files", "--cached", "--others", "--exclude-standard",
                         "-z", "--", *cands).split("\0"))
        bad += [f for f in cands if f not in known]
    return [f for f in files if f in bad]


def check_purpose(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """目的の役の返答を受け付ける。凍結（once）→ 作業ツリー（役は読むだけ）→ 型（写しの graph の p0.purpose の schema）
    → 写しの post_check（graph が名指せば）→ source_files（works が足す）。通れば盤面の purpose.json に書く。
    {"ok", "reason", "purpose_file"}"""
    def run():
        repo_p, board_p = pathlib.Path(repo), pathlib.Path(board)
        board_p.mkdir(parents=True, exist_ok=True)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            refuse_if_frozen(board_p)
            _tree_unchanged(repo_p, board_p)
            _type_errors(reply, role_schema(NODE), "目的の返答")
            out = copy.deepcopy(reply)   # post_check が正規化しても返答の元は触らない（engine と同じく正規化の後を書く）
            _post_check(NODE, out, _Board(board_p, rev))
            bad = _source_files_errors(out["source_files"], repo_p)
            if bad:
                raise Reject(f"source_files に git の出す形のリポジトリ相対の名前で作業ツリーに在るファイルでない物が在る: {bad}"
                             "——出典にしたリポジトリの中のファイルを、git が出す形（根からの相対・`./` や末尾の `/`・"
                             "重ねた `/`・`.` の段なし・大小文字もリポジトリのまま）で書け（依頼のファイルなど"
                             "リポジトリの外の物・git が無視するファイルは書かない）")
            path = _write_board(board_p, PURPOSE_FILE, out)
        return {"ok": True, "reason": "", "purpose_file": str(path)}
    return _guard(run, purpose_file="")


def read_purpose(board) -> tuple:
    """盤面の purpose.json を読み、写しの型に通して (パス, 中身) を返す。無い・読めない・型が合わなければ Reject"""
    path = pathlib.Path(board) / PURPOSE_FILE
    if not path.is_file():
        raise Reject(f"盤面に {PURPOSE_FILE} が無い（{path}）——受け付けを通った目的の文が無い")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Reject(f"盤面の {PURPOSE_FILE} が読めない（{path}: {type(e).__name__}: {e}）")
    _type_errors(obj, role_schema(NODE), f"盤面の {PURPOSE_FILE} ")
    return path, obj
