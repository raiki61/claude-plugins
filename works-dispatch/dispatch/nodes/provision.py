#!/usr/bin/env python3
"""provision ノード: 枝ごとの作業場（元の clone の git worktree と herdr の作業場）を、無ければ作り、有れば使い直す（設計書 3 節）。外に書く。

場所の鍵は枝。作る・並べる・開くは herdr アダプタ（herdr.py の worktrees・create_worktree・open_worktree）に任せ、ここは
「枝の場所を探す・作る・開く」の言葉だけで書く。
- 場所を探す: 元の clone の worktree のうち、その枝を開いている linked worktree。フォルダの名前では探さない。
  元の clone 自身がその枝を開いていれば、作らずに branch_busy（元の clone の枝を勝手に替えない）。
- 無ければ作る: origin のその枝を取ってから、origin/<枝> を元に worktree を作り、copy_files（git が追わない手元だけのファイル）を写す。
  置き場は herdr の既定に任せる。依存は入れない。
- 有れば使い直す: origin のその枝を取り、作業場が開いていなければ開く。
- どちらでも、手元の枝が origin の枝の祖先なら早送りだけする（/catchup は枝を移るときも pull・merge をしないので、origin の今の
  head に揃えてから渡す）。手元にしか無い commit が有れば動かさず、注記に書く。
- fork の PR（head が別のリポジトリ）は origin に枝が無いので作らず provision_failed。
- 最後に、herdr の worktree の並びにその枝の場所が在り、作業場が開いていて、checkout がその枝に居ることを読み戻してから返す。

issue から始めるとき（入口の --issue）に、issue に結んだ枝がまだ無ければ、link_branch が GitHub に枝を作って issue に結ぶ
（gh issue develop。書く口）。作った後に issue に結んだ枝を読み戻して返す。

使い方: python3 nodes/provision.py --plan <plan の JSON> --number <番号> [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import jsonio  # noqa: E402


def label(repo, branch):
    """herdr の作業場の名前: <リポジトリの名前>/<枝>。人が見るためだけで、探すのには使わない。
    リポジトリの名前で始めるのは、issue の番号で始まる枝でも、数字で始まらないようにするため（設計書 3 節）。"""
    return f"{repo.repo.split('/')[-1]}/{branch}"


def find(places, branch):
    """worktree の並び（herdr.worktrees）から、その枝の場所（linked worktree）を 1 つ。無ければ None。"""
    return next((p for p in places if p.get("linked") and p.get("branch") == branch and not p.get("prunable")), None)


def source_holds(places, branch):
    """元の clone 自身がその枝を開いているか。"""
    return any(not p.get("linked") and p.get("branch") == branch for p in places)


def would(row, places):
    """--dry-run の報告用: create（作る）・reuse（使い直す）・branch_busy・provision_failed（fork の PR）のどれか。
    issue でまだ枝が無い行（head が None）は create。"""
    if row.get("fork"):
        return "provision_failed"
    branch = row.get("head")
    if branch is None:
        return "create"
    if source_holds(places, branch):
        return "branch_busy"
    return "reuse" if find(places, branch) else "create"


def link_branch(repo, number, base, gh=ghx, env=None):
    """issue に枝を結ぶ（GitHub に base から枝を作る）。作った後に読み戻した、issue に結んだ枝の並びを返す。"""
    gh.issue_develop(repo.repo, number, base, env=env)
    return gh.issue_branches(repo.repo, number, env=env)


def _copy(repo, path):
    notes = []
    for rel in repo.copy_files:
        src = os.path.join(config.copy_root(repo), rel)
        if not os.path.isfile(src):
            notes.append(f"写すファイルが {config.copy_root(repo)} に無い: {rel}")
            continue
        dst = os.path.join(path, rel)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return notes


def prepare(row, repo, h=herdr, g=gitx):
    branch = row.get("head")
    out = {"number": row["number"], "branch": branch, "path": None, "pane": None, "workspace": None,
           "created": False, "status": "provision_failed", "detail": None}
    if row.get("fork"):
        out["detail"] = "fork の PR（head が別のリポジトリ）なので、origin に枝が無く、作業場を作らない"
        return out
    if not branch:
        out["detail"] = "枝が決まっていない"
        return out
    notes = []
    try:
        g.fetch(repo.source, branch)
        places = h.worktrees(repo.source)
        if source_holds(places, branch):
            out.update(status="branch_busy", detail=f"元の clone {repo.source} が枝 {branch} を開いている（枝を替えない。"
                                                     "元の clone を別の枝へ移すか、そこで作業する）")
            return out
        place = find(places, branch)
        if place is None:
            made = h.create_worktree(repo.source, branch, f"origin/{branch}", label(repo, branch))
            out["created"] = True
            notes += _copy(repo, made["path"])
        else:
            made = h.open_worktree(repo.source, place["path"], label(repo, branch))
        moved = g.fast_forward(made["path"], branch)
        if moved == "local_only":
            notes.append(f"枝 {branch} に手元にしか無い commit が有るので、origin の head へ早送りしなかった")
        seen = find(h.worktrees(repo.source), branch)
    except (gitx.GitError, h.HerdrError, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out

    misses = []
    if seen is None or not seen.get("workspace"):
        misses.append(f"作った後の読み戻しで、枝 {branch} の場所の作業場が herdr に見えない")
    elif os.path.realpath(seen["path"]) != os.path.realpath(made["path"]):
        misses.append(f"作った後の読み戻しで、枝 {branch} の場所が {seen['path']}（{made['path']} のはず）")
    elif g.branch(made["path"]) != branch:
        misses.append(f"作った後の読み戻しで、{made['path']} の枝が {g.branch(made['path'])}（{branch} のはず）")
    if misses or not made.get("pane_id"):
        out["detail"] = "／".join(notes + (misses or ["作業場のペインが返らなかった"]))
        return out
    out.update(path=made["path"], pane=made["pane_id"], workspace=seen["workspace"], status="ready",
               detail="／".join(notes) or None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    repo = config.pick_repo(config.load(a.config, os.environ), a.repo)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"provision": prepare(row, repo)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
