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
  head に揃えてから渡す）。祖先でなくても、HEAD が前に送った時の head（行の sent_head）のままで場所がきれいなら、作者の
  force-push なので `git reset --keep` で origin に揃える。それ以外（手元にしか無い commit が有る）は動かさず、注記に書く。
- fork の PR（head が別のリポジトリ）は origin に枝が無いので作らず provision_failed。
- 最後に、herdr の worktree の並びにその枝の場所が在り、作業場が開いていて、checkout がその枝に居ることを読み戻してから返す。

作業役（入口の --task）の場所は prepare_task が用意する。違いはその関数の説明に書いた。部署の属性（役・アカウント・会話の名前・
上役）は mark が、その場所の git の設定 company.<名前> に書く（会社の形の設計 4.2）。

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
            sent_head = row.get("sent_head")
            if sent_head and g.head_sha(made["path"]) == sent_head and g.is_clean(made["path"]):
                # 手元の HEAD が前に送った時の head のまま（手元で積んだ commit ではない）で、origin の祖先でなくなった:
                # 作者が force-push した。場所がきれいなら origin に揃える（--keep は未コミットの変更と重なれば断る）
                g.reset_keep(made["path"], branch)
                notes.append(f"枝 {branch} は前に送った後に origin で書き換えられていた（force-push）ので、origin の head に揃えた")
            else:
                notes.append(f"枝 {branch} に手元にしか無い commit が有るので、origin の head へ早送りしなかった")
        seen = find(h.worktrees(repo.source), branch)
    except (gitx.GitError, h.HerdrError, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out
    return _read_back(out, made, seen, branch, notes, g)


def _read_back(out, made, seen, branch, notes, g):
    """作った・開いた場所を、herdr の worktree の並び（seen）と git から読み戻して、out を ready にするか、外れを detail に書く。"""
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


def prepare_task(row, repo, default_branch, h=herdr, g=gitx):
    """作業役（入口の --task）の場所を用意する。row は {head: 枝, label: 作業の名前}。PR の場所と同じく、枝の場所が在れば開き直し、
    無ければ herdr に作らせる（置き場は herdr の worktrees.directory）。元の clone 自身がその枝を開いていれば branch_busy。

    PR と違い、枝は origin に無くてよい（作業はこれから始める）。作るときの元は、origin にその枝が在れば origin/<枝>、無ければ
    origin の既定の枝（default_branch）。手元に同じ名前の枝が在れば、herdr はそれを開く。在る場所は git で動かさない
    （作業役の枝は手元で積む物なので、origin へ早送りしない）。作業場の名前（herdr の label）は作業の名前にする。"""
    branch, name = row.get("head"), row.get("label")
    out = {"number": None, "branch": branch, "path": None, "pane": None, "workspace": None,
           "created": False, "status": "provision_failed", "detail": None}
    if not branch:
        out["detail"] = "枝が決まっていない"
        return out
    notes = []
    try:
        places = h.worktrees(repo.source)
        if source_holds(places, branch):
            out.update(status="branch_busy", detail=f"元の clone {repo.source} が枝 {branch} を開いている（枝を替えない。"
                                                     "元の clone を別の枝へ移すか、別の枝の名前で頼む）")
            return out
        place = find(places, branch)
        if place is None:
            try:
                g.fetch(repo.source, branch)
                base = f"origin/{branch}"
            except gitx.GitError:
                g.fetch(repo.source, default_branch)
                base = f"origin/{default_branch}"
            made = h.create_worktree(repo.source, branch, base, name)
            out["created"] = True
            notes += _copy(repo, made["path"])
        else:
            made = h.open_worktree(repo.source, place["path"], name)
        seen = find(h.worktrees(repo.source), branch)
    except (gitx.GitError, h.HerdrError, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out
    return _read_back(out, made, seen, branch, notes, g)


def mark(path, source, attrs, g=gitx):
    """部署の属性を、その場所（worktree）の git の設定 company.<名前> に書く。値が None（か空）の属性は、前の回の値が残っていれば消す
    （使い直した場所に、前の回の gh のアカウントや設定の場所が残って効き続けないように）。書けなければ GitError。
    元の clone に extensions.worktreeConfig が無ければ先に入れる（部署ごとの設定は、これが無いと書けない）。"""
    g.enable_worktree_config(source)
    for name, value in attrs.items():
        if value:
            g.set_worktree_attr(path, name, value)
        else:
            g.unset_worktree_attr(path, name)


def hide_claude_dir(source, g=gitx):
    """元の clone の .git/info/exclude に .claude/ を足す（無ければ）。部署の会話が元の clone に作る .claude/（許可の記録など）を、
    勤め先のリポジトリの .gitignore を触らずに git status から隠す（会社の形の設計 9.1 で確かめた）。"""
    return g.exclude(source, ".claude/")


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
