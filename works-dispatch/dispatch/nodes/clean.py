#!/usr/bin/env python3
"""clean ノード: PR ごとの clone のうち、消してよいものを選び、消す（設計書 3 節の片付け）。外に書く。

消してよいのは、次の全部を満たすフォルダだけ。
- `<clone_root>/<リポジトリの名前>-pr-<番号>` の形の名前で、origin がこのリポジトリである（同じ名前の別のリポジトリの clone に触らない）
- その PR が閉じている（MERGED か CLOSED）。状態が読めなければ消さない
- そのフォルダかその下を作業フォルダにする会話が、どのアカウントにも無い（会話を閉じるのは持ち主だけ）
- 未コミットの変更も、git にまだ足していない新しいファイルも、手元にしか無い commit（枝に乗っていない HEAD の上を含む）も、stash も無い
パスはリンクを辿った実際のパスで比べる（clone_root がリンクでも、会話の作業フォルダを見落とさない）。
消す時は、そのフォルダを作業フォルダにするペインに会話が無ければ、herdr の作業場を先に閉じてからフォルダを消し、消えたことを読み戻す。
会話のあるペインの作業場は閉じない。

使い方は入口から: python3 dispatch.py --clean [--apply]
"""

import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import gitx  # noqa: E402
import herdr  # noqa: E402

FINISHED = ("MERGED", "CLOSED")


def _inside(cwd, path):
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


def candidates(repo, folders, pr_state, open_cwds, is_clean, unpushed, origin=None):
    """origin(path) は clone の origin の OWNER/NAME（None は照らさない）。"""
    pattern = re.compile(rf"^{re.escape(repo.repo.split('/')[-1])}-pr-(\d+)$")
    rows = []
    for path in sorted(folders):
        m = pattern.match(os.path.basename(path))
        if not m:
            continue
        n = int(m.group(1))
        if origin is not None and origin(path) != repo.repo:
            rows.append({"path": path, "number": n, "state": None, "removable": False, "reason": "other_repo"})
            continue
        state = pr_state(n)
        reason = None
        if state is None:
            reason = "pr_state_unknown"
        elif state not in FINISHED:
            reason = "pr_open"
        elif any(_inside(c, path) for c in open_cwds if c):
            reason = "session"
        elif not is_clean(path):
            reason = "dirty"
        elif unpushed(path):
            reason = "unpushed"
        rows.append({"path": path, "number": n, "state": state, "removable": reason is None, "reason": reason})
    return rows


def remove(row, h=herdr):
    path = row["path"]
    out = {"path": path, "removed": False, "closed_workspace": None, "detail": None}
    try:
        for p in h.panes():
            if os.path.realpath(p.get("cwd") or "") == os.path.realpath(path) and not p.get("agent"):
                h.close_workspace(p["workspace_id"])
                out["closed_workspace"] = p["workspace_id"]
                break
        gitx.remove_clone(path)
    except (h.HerdrError, OSError) as e:
        out["detail"] = str(e)
    out["removed"] = not os.path.exists(path)
    return out
