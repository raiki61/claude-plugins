#!/usr/bin/env python3
"""clean ノード: 枝ごとの場所（元の clone の linked worktree）のうち、消してよいものを選び、消す（設計書 3 節の片付け）。外に書く。

見るのは、元の clone の linked worktree だけ（元の clone 自身は、herdr が linked と返しても見ない）。並びは herdr アダプタの
worktrees が返す、元の clone と中身を共有する worktree なので、関係ないリポジトリの場所は並びにも入らない。
消してよいのは、次の全部を満たす場所だけ。
- 枝に居る（枝に乗っていない checkout は消さない）
- その枝の PR が閉じている（MERGED か CLOSED）。PR の無い枝（issue から始めて PR をまだ作っていないもの）は消さない。
  PR が読めなければ消さない
- その場所かその下を作業フォルダにする会話が、どのアカウントにも無い（入口は、閉じた PR の会話が手すきで手元の作業も無ければ、
  先に会話を終え（turn.close_session）、会話の一覧を取り直して無いことを確かめてから消す）
- 未コミットの変更も、git にまだ足していない新しいファイルも、その枝の上の stash も無い
- 手元の枝の先頭が PR の head の commit と同じ（手元にしか無い commit が無い）
- 設定の copy_files に書いたファイルのうち、写し元と中身が違うもの（その場所で書き換えた手元だけのファイル）が無い
git が追わないファイルのうち、それ以外（依存・生成物など）は場所と一緒に捨ててよい（作り直せる）。
パスはリンクを辿った実際のパスで比べる（会話の作業フォルダを見落とさない）。
消す時は herdr の worktree の口で checkout と作業場を消し（--force は付けない）、消えたことを読み戻してから、手元の枝も消す
（先頭が PR の head と同じときだけ）。前の版の PR ごとの clone（<リポジトリの名前>-pr-<番号>）は扱わない。

部署（入口の --task が立て、属性 company.session を持つ linked worktree）は、別の決まりで選ぶ（departments・retire）。
- 都度の部署である（属性 company.residency が resident の常設の部署は畳まない。属性が無ければ都度とみなす。会社の形の設計 4.10 の 1）
- 部署の会話が終わっている（state が done・stopped・failed）か、会話の一覧にもう無い
- 未コミットの変更も git に足していないファイルも、手元にしか無い commit や stash も無い
- 部署の枝の先頭が本流（origin の既定の枝の手元の控え）に入っている
消す時は、会話を `claude rm` で消し（会話の worktree は下回りが作ったので、rm は worktree を残す）、続けて上と同じく herdr の
worktree の口で場所と作業場（attach の窓）を消し、手元の枝も消す。本流に入れる方法は会社ごとに決める（設計の 8 章）ので、
ここは「入っていれば消す」だけを持つ。

常設の部署は作業場を残したまま、頼みごとに枝を切り替える。入れ終えた前の枝は手元に残るので、--land が入れた枝とその commit を
属性 company.landed-branches（JSON の 枝 → commit）に書き、--clean --apply と次の --land が sweep_landed で消す。消すのは、
どの worktree も開いていない枝で、先頭がまだ入れた commit と同じ物だけ（入れた後に commit を積んだ枝は消さず、記録から外す）。
部署の会話に「切り替えるときに前の枝を消す」と任せず機械で消すのは、会話は前の枝を消し忘れても止まらず、消してよいかの見極め
（入れた commit と同じか）を機械が確かに持つため。

使い方は入口から: python3 dispatch.py --clean [--apply]
"""

import filecmp
import json
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


def _same(a, b):
    return os.path.realpath(a or "") == os.path.realpath(b or "")


class Unknown(Exception):
    """PR が読めない（pr_for_branch が投げる）。その場所は消さない。"""


def changed_copies(path, copy_root, copy_files):
    """copy_files のうち、場所に在って、写し元（copy_root）と中身が違うもの（写し元が無いものも含む）。"""
    out = []
    for rel in copy_files:
        here, there = os.path.join(path, rel), os.path.join(copy_root, rel)
        if os.path.isfile(here) and not (os.path.isfile(there) and filecmp.cmp(here, there, shallow=False)):
            out.append(rel)
    return out


def candidates(places, pr_for_branch, open_cwds, is_clean, stashed, head_sha, source=None, changed=lambda p: []):
    """places は herdr.worktrees の並び。pr_for_branch(枝) は {number, state, head_sha}・None（PR が無い）・Unknown を投げる。
    changed(場所) は、写し元と中身の違う copy_files の並び（changed_copies）。
    返す 1 行は {path, branch, number, state, pr_head, removable, reason, files}。"""
    rows = []
    for place in sorted((p for p in places if p.get("linked")), key=lambda p: p.get("path") or ""):
        path, branch = place["path"], place.get("branch")
        if source and _same(path, source):
            continue
        row = {"path": path, "branch": branch, "number": None, "state": None, "pr_head": None,
               "removable": False, "reason": None, "files": []}
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
            row["files"] = changed(path)
            if row["files"]:
                row["reason"] = "local_files"
            else:
                row["removable"] = True
    return rows


def release(source, path, h=herdr):
    """その場所の worktree の作業場（herdr がその場所に返す open_workspace_id）を閉じる（checkout は残す）。
    送り直す前に古い作業場を畳むのに使う。{status, workspace, detail}。status は closed・none（開いていない）・close_failed。
    閉じる前に、その作業場の全部のペインの前がシェルかを確かめ、シェルでない物（会話・エディタ・dev server）が居れば閉じない。
    同じフォルダに cd しただけのほかの作業場には触らない（そのペインを探して閉じると、持ち主の別の作業場ごと閉じてしまう）。"""
    out = {"status": "close_failed", "workspace": None, "detail": None}
    try:
        place = next((p for p in h.worktrees(source) if _same(p.get("path"), path)), None)
        ws = (place or {}).get("workspace")
        if not ws:
            out["status"] = "none"
            return out
        out["workspace"] = ws
        busy = [p["pane_id"] for p in h.panes() if p.get("workspace_id") == ws and not h.shell_in_front(p["pane_id"])]
        if busy:
            out["detail"] = f"作業場 {ws} のペイン {', '.join(busy)} の前でシェルでない物が動いている（閉じない）"
            return out
        h.close_workspace(ws)
    except h.HerdrError as e:
        out["detail"] = str(e)
        return out
    out["status"] = "closed"
    return out


DONE = ("done", "stopped", "failed")


def departments(places, attrs_of, session_of, is_clean, unpushed, merged, head_sha, source=None):
    """部署ごとに、消してよいか。attrs_of(場所) は部署の git の属性。session_of(属性) は会話の 1 件（{id, sessionId, state, …,
    config_dir}）か、一覧に無ければ None。merged(場所) は枝の先頭が本流に入っているか。
    返す 1 行は {path, branch, name, account, session, config_dir, state, pr_head, removable, reason}（pr_head は消す時に
    手元の枝の先頭と比べる commit で、今の先頭）。reason は resident・running・dirty・unpushed・not_merged・no_branch。"""
    rows = []
    for place in sorted((p for p in places if p.get("linked") and not p.get("prunable")), key=lambda p: p.get("path") or ""):
        path, branch = place["path"], place.get("branch")
        if source and _same(path, source):
            continue
        attrs = attrs_of(path)
        if not attrs.get("session"):
            continue
        s = session_of(attrs)
        row = {"path": path, "branch": branch, "name": attrs.get("name"), "account": attrs.get("account"),
               "session": (s or {}).get("id") or (s or {}).get("sessionId"), "config_dir": (s or {}).get("config_dir"),
               "state": (s or {}).get("state") or (s or {}).get("status") or "gone", "pr_head": head_sha(path),
               "removable": False, "reason": None}
        rows.append(row)
        if attrs.get("residency") == "resident":
            row["reason"] = "resident"
        elif s is not None and s.get("state") not in DONE:
            row["reason"] = "running"
        elif not branch:
            row["reason"] = "no_branch"
        elif not is_clean(path):
            row["reason"] = "dirty"
        elif unpushed(path):
            row["reason"] = "unpushed"
        elif not merged(path):
            row["reason"] = "not_merged"
        else:
            row["removable"] = True
    return rows


def retire(row, source, label, h=herdr, g=gitx, c=None):
    """部署の 1 行を消す: 会話が一覧に在れば c.remove_session（claude rm）で消し、続けて remove で場所と窓と手元の枝を消す。
    rm が断れば（未 push の commit など）、場所も消さない。{path, branch, removed, branch_deleted, detail}。"""
    if row.get("session"):
        ok, said = c.remove_session(row["config_dir"], row["session"])
        if not ok:
            return {"path": row["path"], "branch": row["branch"], "removed": False, "branch_deleted": False,
                    "detail": f"claude rm が断った（{said}）"}
    return remove(row, source, label, h, g)


def remove(row, source, label, h=herdr, g=gitx):
    """候補の 1 行の場所を消し、手元の枝も消す。{path, branch, removed, branch_deleted, detail}。"""
    path = row["path"]
    out = {"path": path, "branch": row["branch"], "removed": False, "branch_deleted": False, "detail": None}
    try:
        h.remove_worktree(source, path, label)
    except (h.HerdrError, OSError) as e:
        out["detail"] = str(e)
    out["removed"] = not os.path.exists(path) and all(not _same(p.get("path"), path) for p in _safe_list(h, source))
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


LANDED_BRANCHES = "landed-branches"   # 常設の部署の属性: 入れた枝 → 入れた commit（JSON）


def landed_of(attrs):
    """属性 company.landed-branches の {枝: commit}。読めなければ空。"""
    try:
        got = json.loads(attrs.get(LANDED_BRANCHES) or "{}")
    except ValueError:
        return {}
    return {b: c for b, c in got.items() if isinstance(b, str) and isinstance(c, str)} if isinstance(got, dict) else {}


def sweep_landed(places, attrs_of, source, apply, g=gitx):
    """常設の部署が入れ終えた前の手元の枝を消す（apply が偽なら見立てだけ）。1 行は {path, name, branch, status, keep}。
    status は deleted（消した・もう無い）・open（どこかの worktree が開いている。次に回す）・moved（入れた後に commit が有るので
    消さず、記録から外す）・would（apply が偽で、消せる）・failed（git が断った。次に回す）。keep はその部署の記録に残す {枝: commit}
    （呼んだ側が属性に書き戻す。同じ部署の行は同じ keep を持つ）。"""
    opened = {p.get("branch") for p in places if p.get("branch") and not p.get("prunable")}
    out = []
    for place in places:
        if not place.get("linked") or place.get("prunable"):
            continue
        attrs = attrs_of(place["path"])
        landed = landed_of(attrs)
        if not landed:
            continue
        keep, rows = {}, []
        for branch, sha in sorted(landed.items()):
            if branch in opened:
                status = "open"
            elif not apply:
                status = "would"
            else:
                try:
                    status = {"deleted": "deleted", "absent": "deleted", "moved": "moved"}[g.delete_branch(source, branch, sha)]
                except gitx.GitError:
                    status = "failed"
            if status in ("open", "would", "failed"):
                keep[branch] = sha
            rows.append({"path": place["path"], "name": attrs.get("name"), "branch": branch, "status": status})
        out += [{**r, "keep": keep} for r in rows]
    return out

