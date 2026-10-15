#!/usr/bin/env python3
"""clean ノード: 枝ごとの場所（元の clone の linked worktree）のうち、消してよいものを選び、消す（設計書 3 節の片付け）。外に書く。

見るのは、元の clone の linked worktree だけ（元の clone 自身は見ない）。並びは herdr アダプタの worktrees が返す、元の clone と中身を
共有する worktree なので、関係ないリポジトリの場所は並びにも入らない。
消してよいのは、次の全部を満たす場所だけ。
- 枝に居る（枝に乗っていない checkout は消さない）
- その枝の PR が閉じている（MERGED か CLOSED）。PR の無い枝（issue から始めて PR をまだ作っていないもの）は消さない。
  PR が読めなければ消さない
- その場所かその下を作業フォルダにする会話が、どのアカウントにも無い（入口は、閉じた PR の会話が手すきで手元の作業も無ければ、
  先に会話を終えてから（turn.close_session）この候補を読み直す）
- 未コミットの変更も、git にまだ足していない新しいファイルも、その枝の上の stash も無い
- 手元の枝の先頭が PR の head の commit と同じ（手元にしか無い commit が無い）
パスはリンクを辿った実際のパスで比べる（会話の作業フォルダを見落とさない）。
消す時は herdr の worktree の口で checkout と作業場を消し（--force は付けない）、消えたことを読み戻してから、手元の枝も消す
（先頭が PR の head と同じときだけ）。前の版の PR ごとの clone（<リポジトリの名前>-pr-<番号>）は扱わない。

使い方は入口から: python3 dispatch.py --clean [--apply]
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import gitx  # noqa: E402
import herdr  # noqa: E402

FINISHED = ("MERGED", "CLOSED")


def _inside(cwd, path):
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


class Unknown(Exception):
    """PR が読めない（pr_for_branch が投げる）。その場所は消さない。"""


def candidates(places, pr_for_branch, open_cwds, is_clean, stashed, head_sha):
    """places は herdr.worktrees の並び。pr_for_branch(枝) は {number, state, head_sha}・None（PR が無い）・Unknown を投げる。
    返す 1 行は {path, branch, number, state, pr_head, removable, reason}。"""
    rows = []
    for place in sorted((p for p in places if p.get("linked")), key=lambda p: p.get("path") or ""):
        path, branch = place["path"], place.get("branch")
        row = {"path": path, "branch": branch, "number": None, "state": None, "pr_head": None,
               "removable": False, "reason": None}
        rows.append(row)
        if not branch:
            row["reason"] = "no_branch"
            continue
        try:
            pr = pr_for_branch(branch)
        except Unknown:
            row["reason"] = "pr_state_unknown"
            continue
        if pr is None:
            row["reason"] = "no_pr"
            continue
        row.update(number=pr["number"], state=pr["state"], pr_head=pr.get("head_sha"))
        if pr["state"] not in FINISHED:
            row["reason"] = "pr_open"
        elif any(_inside(c, path) for c in open_cwds if c):
            row["reason"] = "session"
        elif not is_clean(path):
            row["reason"] = "dirty"
        elif stashed(path, branch) or not pr.get("head_sha") or head_sha(path) != pr.get("head_sha"):
            row["reason"] = "unpushed"
        else:
            row["removable"] = True
    return rows


def release(path, h=herdr):
    """作業フォルダがちょうど path で、会話の居ないペインの作業場を閉じる（checkout は残す）。閉じた作業場の ID か None。
    送り直す前に古いペインを畳むのに使う。ほかのフォルダのペインには触らない。"""
    for p in h.panes():
        if os.path.realpath(p.get("cwd") or "") == os.path.realpath(path) and not p.get("agent"):
            h.close_workspace(p["workspace_id"])
            return p["workspace_id"]
    return None


def remove(row, source, label, h=herdr, g=gitx):
    """候補の 1 行の場所を消し、手元の枝も消す。{path, branch, removed, branch_deleted, detail}。"""
    path = row["path"]
    out = {"path": path, "branch": row["branch"], "removed": False, "branch_deleted": False, "detail": None}
    try:
        h.remove_worktree(source, path, label)
    except (h.HerdrError, OSError) as e:
        out["detail"] = str(e)
    out["removed"] = not os.path.exists(path) and all(
        os.path.realpath(p.get("path") or "") != os.path.realpath(path) for p in _safe_list(h, source))
    if not out["removed"]:
        out["detail"] = out["detail"] or "消した後の読み戻しで、場所がまだ在る"
        return out
    try:
        out["branch_deleted"] = g.delete_branch(source, row["branch"], row["pr_head"]) in ("deleted", "absent")
    except gitx.GitError as e:
        out["detail"] = f"場所は消したが、手元の枝 {row['branch']} を消せなかった（{e}）"
    if not out["branch_deleted"] and not out["detail"]:
        out["detail"] = f"場所は消したが、手元の枝 {row['branch']} の先頭が PR の head と違うので残した"
    return out


def _safe_list(h, source):
    try:
        return h.worktrees(source)
    except h.HerdrError:
        return []
