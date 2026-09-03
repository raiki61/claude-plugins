#!/usr/bin/env python3
"""catchup.py の --switch（該当ブランチへ移る）を、一時の git リポジトリで実際に動かして確かめる。

GitHub には触らない。PR の node は固定の材料（headRefName・headRepository・head の oid）で、git だけ本物。
「読むより動かす」——guard（追跡の未コミットで止まる・別 worktree で止まる・ignored を上書きしない）は、
git 自身が止めない状態で組んで、guard を消したら赤くなる形にする（枝で中身が違うファイルで汚すと、guard を
消しても git が拒んで緑のまま＝恒真）。合否は行の文言だけでなく git の状態（branch --show-current・
status --porcelain・for-each-ref）で見る。

網の外: main の配線（fetch の後・render の前に呼ぶ、this と --switch 無しでは呼ばない、地図は移った後の
HEAD で描く）。数行なのでレビューで読む。run.sh は --help に --switch が出ることだけ固定する。
status-none（git status が読めない）は git を決定的に失敗させる方法が無いので、純関数 tree_blocker で見る。

Windows では作業場を消せないことがあるので ignore_cleanup_errors=True。cwd は変えず、path を渡す
（chdir を忘れた検査が run.sh からこのリポジトリ本体に git switch を打つのを防ぐ）。"""

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "catchup", ROOT / "attention" / "scripts" / "catchup.py")
catchup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catchup)

GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
       "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false"]
HEAD_REF = "feat/1569-x"
NUM = 1569


def git(repo, *args):
    r = subprocess.run([*GIT, "-C", repo, *args], check=True, capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def read(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as f:
        return f.read()


def make_repo(tmp):
    """main に 2 file の commit、origin は o/r、head の枝 feat/1569-x は main と同じ先端。"""
    repo = os.path.join(tmp, "r")
    os.makedirs(repo)
    git(repo, "init", "-q")
    write(repo, "a.txt", "a\n")
    write(repo, "same.txt", "same\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", "https://github.com/o/r.git")
    git(repo, "branch", HEAD_REF)
    return repo


def node(repo, **over):
    n = {"__typename": "PullRequest", "headRefName": HEAD_REF,
         "headRepository": {"nameWithOwner": "o/r"},
         "head": {"nodes": [{"commit": {"oid": git(repo, "rev-parse", "HEAD")}}]}}
    n.update(over)
    return n


def call(repo, n=None, num=NUM):
    """戻り値は (見出しの行, 居るブランチ名 or None)。"""
    lines, on = catchup.switch_branch("o", "r", num, n if n is not None else node(repo), cwd=repo)
    return "\n".join(lines), on


def current(repo):
    return git(repo, "branch", "--show-current")


def heads(repo):
    return git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/").splitlines()


def verdict(want, out):
    bad = [k for k, v in want.items() if not v]
    return "SWITCH_OK" if not bad else "SWITCH_NG " + ",".join(bad) + "\n" + out


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("moved")
def _moved(tmp):
    """きれいな木なら移る。元のブランチ名が行に残る（git switch - の戻り先）。"""
    repo = make_repo(tmp)
    out, on = call(repo)
    # 行は等値で見る——きれいな木で移ったときは注釈が 0 行（Switched to は落とす）
    return verdict({"line": out == f"ブランチ {HEAD_REF}: main から移った",
                    "branch": current(repo) == HEAD_REF, "on": on == HEAD_REF}, out)


@case("dirty")
def _dirty(tmp):
    """追跡ファイルの未コミット（両枝で中身が同じ file の変更 + staged の追加）では移らず、変更もそのまま。
    枝で中身が違う file だと guard を消しても git が拒んで緑のままなので、同じ file で汚す。"""
    repo = make_repo(tmp)
    write(repo, "same.txt", "same\nedited\n")
    write(repo, "new.txt", "n\n")
    git(repo, "add", "new.txt")
    out, on = call(repo)
    st = git(repo, "status", "--porcelain")
    return verdict({"line": "未コミットの変更 2 件" in out and f"git switch {HEAD_REF}" in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "kept": " M same.txt" in st and "A  new.txt" in st}, out)


@case("untracked")
def _untracked(tmp):
    """未追跡だけなら移り、file は持ち越される（行にその数）。"""
    repo = make_repo(tmp)
    write(repo, "stray.txt", "u\n")
    out, on = call(repo)
    return verdict({"line": "から移った（未追跡 1 件は持ち越した）" in out,
                    "branch": current(repo) == HEAD_REF, "on": on,
                    "kept": "?? stray.txt" in git(repo, "status", "--porcelain")}, out)


@case("ignored")
def _ignored(tmp):
    """ignored の file を対象の枝が追跡していれば、上書きせずに止まる（--no-overwrite-ignore）。
    邪魔している path が行に出る（拒否文の 1 行目は総称で、path は 2 行目以降）。"""
    repo = make_repo(tmp)
    git(repo, "switch", "-q", HEAD_REF)
    write(repo, ".vscode/settings.json", "TRACKED\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "vscode")
    git(repo, "switch", "-q", "main")
    with open(os.path.join(repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
        f.write(".vscode/\n")
    write(repo, ".vscode/settings.json", "PRIVATE\n")
    out, on = call(repo)
    return verdict({"line": "移れなかった" in out and "settings.json" in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "kept": read(repo, ".vscode/settings.json").strip() == "PRIVATE"}, out)


@case("already")
def _already(tmp):
    """既に居れば移らず、居る扱い（手元の節が付く）。"""
    repo = make_repo(tmp)
    git(repo, "switch", "-q", HEAD_REF)
    out, on = call(repo)
    return verdict({"line": "既に居る" in out and "移った" not in out,
                    "branch": current(repo) == HEAD_REF, "on": on == HEAD_REF}, out)


@case("worktree")
def _worktree(tmp):
    """別の worktree に checkout 済みの枝には移らず、機械の言葉でその旨（git の fatal を出さない）。
    その worktree の dir が消えていれば（prune 前）「そこで続ける」とは言わず、prune を案内する。"""
    repo = make_repo(tmp)
    wt = os.path.join(tmp, "wt")
    git(repo, "worktree", "add", "-q", wt, HEAD_REF)
    out, on = call(repo)
    shutil.rmtree(wt)
    out2, on2 = call(repo)
    return verdict({"line": "別の worktree に checkout 済み" in out and "fatal:" not in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "gone": "dir が無い" in out2 and "git worktree prune" in out2 and not on2
                    and "そこで続ける" not in out2,
                    "still": current(repo) == "main"}, out + "\n" + out2)


@case("remote-only")
def _remote_only(tmp):
    """origin にだけある枝は作らない（DWIM を止める）。案内は gh pr checkout。"""
    repo = make_repo(tmp)
    git(repo, "update-ref", "refs/remotes/origin/pr-head", "HEAD")
    out, on = call(repo, node(repo, headRefName="pr-head"))
    return verdict({"line": "origin にはある" in out and f"gh pr checkout {NUM}" in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "no_new_branch": "refs/heads/pr-head" not in heads(repo)}, out)


@case("none")
def _none(tmp):
    """手元にも origin にも無ければそう言う。"""
    repo = make_repo(tmp)
    out, on = call(repo, node(repo, headRefName="nope"))
    return verdict({"line": "手元に無い（origin にも無い）" in out,
                    "branch": current(repo) == "main", "not_on": not on}, out)


@case("origin-mismatch")
def _origin_mismatch(tmp):
    """origin が別のリポジトリなら移らない。origin が無くてもその旨。"""
    repo = make_repo(tmp)
    git(repo, "remote", "set-url", "origin", "https://github.com/x/y.git")
    out1, on1 = call(repo)
    git(repo, "remote", "remove", "origin")
    out2, on2 = call(repo)
    return verdict({"mismatch": "origin が o/r でない" in out1 and "x/y" in out1 and not on1,
                    "no_origin": "origin が無い" in out2 and not on2,
                    "branch": current(repo) == "main"}, out1 + "\n" + out2)


@case("no-git")
def _no_git(tmp):
    """git の checkout でない場所なら移らない（落ちない）。"""
    plain = os.path.join(tmp, "plain")
    os.makedirs(plain)
    lines, on = catchup.switch_branch("o", "r", NUM, {"__typename": "PullRequest",
                                                     "headRefName": HEAD_REF}, cwd=plain)
    out = "\n".join(lines)
    return verdict({"line": "git の checkout が無い" in out, "not_on": not on}, out)


@case("status-none")
def _status_none(tmp):
    """guard の git status が読めなければ（None）止める（空 "" と同じにしない＝fail-open にしない）。
    git status を決定的に失敗させる方法が無いので、判断を持つ純関数 tree_blocker で見る。"""
    none = catchup.tree_blocker(None, "x")
    clean = catchup.tree_blocker("", "x")
    return verdict({"none_blocks": none[0] is not None and "読めない" in none[0],
                    "clean_passes": clean == (None, 0)}, f"{none} {clean}")


@case("fork")
def _fork(tmp):
    """fork の PR は名前だけでは移らない。手元の同名の枝が head の commit を含めば移る（手元が先でも）。
    含まなければ（無関係・手元が head より古い）移らない。head の commit を持っていなければ照合できない。
    逆向きだけ（手元の先端が head の先祖）で移ると、head が main の fork PR で手元の main に移る。"""
    repo = make_repo(tmp)
    fork = {"nameWithOwner": "other/r"}
    base = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "write-tree")
    # 手元の feat を main より 1 commit 先にする（head = main の先端。手元が head を含む）
    git(repo, "update-ref", f"refs/heads/{HEAD_REF}", git(repo, "commit-tree", tree, "-p", base, "-m", "ahead"))
    out_ahead, on_ahead = call(repo, node(repo, headRepository=fork))
    moved = current(repo) == HEAD_REF
    git(repo, "switch", "-q", "main")
    # head が手元の feat の子（手元が古い）。逆向きの判定なら移ってしまう
    child = git(repo, "commit-tree", tree, "-p", HEAD_REF, "-m", "newer-on-fork")
    out_old, on_old = call(repo, node(repo, headRepository=fork, head={"nodes": [{"commit": {"oid": child}}]}))
    orphan = git(repo, "commit-tree", tree, "-m", "orphan")
    out_unrel, on_unrel = call(repo, node(repo, headRepository=fork,
                                          head={"nodes": [{"commit": {"oid": orphan}}]}))
    out_none, on_none = call(repo, node(repo, headRepository=fork,
                                        head={"nodes": [{"commit": {"oid": "0" * 40}}]}))
    still = current(repo) == "main"
    return verdict({
        "ahead_moves": "から移った" in out_ahead and on_ahead == HEAD_REF and moved,
        "older_stays": "含まない" in out_old and "fork other/r のブランチ" in out_old and not on_old,
        "unrelated": "別物" in out_unrel and not on_unrel,
        "no_oid": "照合できない" in out_none and not on_none,
        "hint": all(f"gh pr checkout {NUM}" in o for o in (out_old, out_unrel, out_none)),
        "still": still,
    }, "\n".join((out_ahead, out_old, out_unrel, out_none)))


@case("fork-main")
def _fork_main(tmp):
    """head が main の fork PR: 手元の main には移らない（main は fork の head の先祖）。gh pr checkout が
    付ける <fork の owner>/main の名前があればそれに移る。fork が消えている（headRepository null）PR も
    名前だけでは移らない。"""
    repo = make_repo(tmp)
    fork = {"nameWithOwner": "other/r"}
    tree = git(repo, "write-tree")
    head = git(repo, "commit-tree", tree, "-p", "main", "-m", "on-fork-main")
    n = node(repo, headRefName="main", headRepository=fork, head={"nodes": [{"commit": {"oid": head}}]})
    out_main, on_main = call(repo, n)
    stayed = current(repo) == "main"
    git(repo, "update-ref", "refs/heads/other/main", head)
    out_pref, on_pref = call(repo, n)
    moved = current(repo) == "other/main"
    git(repo, "switch", "-q", "main")
    out_null, on_null = call(repo, node(repo, headRepository=None, head={"nodes": [{"commit": {"oid": head}}]}))
    return verdict({
        "main_stays": "既に居る" not in out_main and "含まない" in out_main and not on_main and stayed,
        "prefixed": "ブランチ other/main: main から移った" in out_pref and on_pref == "other/main" and moved,
        "gone_fork": "消えた fork" in out_null and "含まない" in out_null and not on_null,
        "still": current(repo) == "main",
    }, "\n".join((out_main, out_pref, out_null)))


@case("triangular")
def _triangular(tmp):
    """三角 workflow（origin が自分の fork で、PR の head がその fork）: 手元は head の側なので名前一致で移る。"""
    repo = make_repo(tmp)
    git(repo, "remote", "set-url", "origin", "https://github.com/other/r.git")
    out, on = call(repo, node(repo, headRepository={"nameWithOwner": "other/r"}))
    return verdict({"line": f"ブランチ {HEAD_REF}: main から移った" in out,
                    "branch": current(repo) == HEAD_REF, "on": on == HEAD_REF}, out)


@case("hook")
def _hook(tmp):
    """post-checkout hook が非 0 でも HEAD は移っているので、移った扱い（終了コードで判定しない）。
    hook の言い分は行に添える（Windows は hook の sh が無いことがあるので、そこは見ない。global の
    core.hooksPath は main() で読ませないようにしてある）。"""
    repo = make_repo(tmp)
    os.chmod(write(repo, os.path.join(".git", "hooks", "post-checkout"),
                   "#!/bin/sh\necho hook-said-no >&2\nexit 1\n"), 0o755)
    out, on = call(repo)
    return verdict({"line": f"ブランチ {HEAD_REF}: main から移った" in out,
                    "branch": current(repo) == HEAD_REF, "on": on,
                    "note": os.name == "nt" or "hook-said-no" in out}, out)


@case("lock")
def _lock(tmp):
    """index.lock（他のセッションが git を動かしている最中）なら移れず、その file 名が行に出る。"""
    repo = make_repo(tmp)
    write(repo, os.path.join(".git", "index.lock"), "")
    out, on = call(repo)
    return verdict({"line": "移れなかった" in out and "index.lock" in out,
                    "branch": current(repo) == "main", "not_on": not on}, out)


@case("tag-shadow")
def _tag_shadow(tmp):
    """同名のタグがあっても枝を見失わない（%(refname:short) は heads/x になる）。"""
    repo = make_repo(tmp)
    git(repo, "tag", HEAD_REF)
    out, on = call(repo)
    return verdict({"line": "から移った" in out, "branch": current(repo) == HEAD_REF, "on": on}, out)


@case("dash-name")
def _dash_name(tmp):
    """- で始まる枝名をオプションと取り違えない（--）。"""
    repo = make_repo(tmp)
    git(repo, "update-ref", "refs/heads/-foo", "HEAD")
    out, on = call(repo, node(repo, headRefName="-foo"))
    return verdict({"line": "ブランチ -foo: main から移った" in out,
                    "branch": current(repo) == "-foo", "on": on}, out)


@case("detached")
def _detached(tmp):
    """detached から移れる。置き去りになる commit があれば git の警告を行に添える。"""
    repo = make_repo(tmp)
    git(repo, "switch", "-q", "--detach")
    git(repo, "commit", "-q", "--allow-empty", "-m", "stray")
    out, on = call(repo)
    return verdict({"line": "（detached） から移った" in out, "warn": "leaving 1 commit behind" in out,
                    "branch": current(repo) == HEAD_REF, "on": on}, out)


@case("rebase")
def _rebase(tmp):
    """衝突した rebase の途中なら「途中」と言って移らない（commit か stash の助言は違う）。"""
    repo = make_repo(tmp)
    write(repo, "a.txt", "b\n")
    git(repo, "commit", "-q", "-am", "b")
    git(repo, "switch", "-q", HEAD_REF)
    write(repo, "a.txt", "c\n")
    git(repo, "commit", "-q", "-am", "c")
    subprocess.run([*GIT, "-C", repo, "rebase", "main"], capture_output=True)  # 衝突して止まる
    st = git(repo, "status", "--porcelain")
    out, on = call(repo, node(repo, headRefName="main"))
    return verdict({"setup": "UU a.txt" in st,
                    "line": "rebase / cherry-pick / revert の途中" in out and "commit か stash" not in out,
                    "not_on": not on, "still_conflict": "UU a.txt" in git(repo, "status", "--porcelain")}, out)


@case("merge")
def _merge(tmp):
    """衝突を解決し終えた merge（MERGE_HEAD あり・衝突の行なし）は普通の staged 変更に見えるが、
    「途中」と言って移らない（commit か stash と言うと、stash が MERGE_HEAD を消す）。"""
    repo = make_repo(tmp)
    write(repo, "a.txt", "b\n")
    git(repo, "commit", "-q", "-am", "b")
    git(repo, "switch", "-q", HEAD_REF)
    write(repo, "a.txt", "c\n")
    git(repo, "commit", "-q", "-am", "c")
    subprocess.run([*GIT, "-C", repo, "merge", "main"], capture_output=True)  # 衝突して止まる
    write(repo, "a.txt", "resolved\n")
    git(repo, "add", "a.txt")
    st = git(repo, "status", "--porcelain")
    out, on = call(repo, node(repo, headRefName="main"))
    return verdict({"setup": st.startswith("M ") and "U" not in st[:2],
                    "line": "merge / rebase" in out and "途中" in out and "commit か stash" not in out,
                    "not_on": not on, "branch": current(repo) == HEAD_REF}, out)


@case("issue")
def _issue(tmp):
    """issue は名前に番号を持つ手元の枝が 1 本のときだけ移る。0 本・2 本以上は理由（候補名）を出す。"""
    repo = make_repo(tmp)
    git(repo, "branch", "chore/1513-a")
    issue = {"__typename": "Issue"}
    out1, on1 = call(repo, issue, num=1513)
    moved = current(repo) == "chore/1513-a"
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "fix/1513-b")
    out2, on2 = call(repo, issue, num=1513)
    out0, on0 = call(repo, issue, num=99)
    return verdict({"one": "ブランチ chore/1513-a: main から移った" in out1 and on1 == "chore/1513-a" and moved,
                    "two": "2 本ある（chore/1513-a, fix/1513-b）" in out2 and not on2,
                    "zero": "名前に #99 を持つ手元のブランチは無い" in out0 and not on0,
                    "still": current(repo) == "main"}, "\n".join((out1, out2, out0)))


@case("behind")
def _behind(tmp):
    """手元の節: 手元が PR の head より後ろなら数える。head の commit を持っていなければそう言う。"""
    repo = make_repo(tmp)
    git(repo, "switch", "-q", HEAD_REF)
    git(repo, "commit", "-q", "--allow-empty", "-m", "pushed-elsewhere")
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    out_behind = catchup.render_local(why="x", pr_head=tip, cwd=repo)
    out_none = catchup.render_local(why="x", pr_head="0" * 40, cwd=repo)
    out_same = catchup.render_local(why="x", pr_head=git(repo, "rev-parse", "HEAD"), cwd=repo)
    return verdict({"heading": f"## 手元のブランチ {HEAD_REF}（x）" in out_behind,
                    "behind": f"PR の head {tip[:7]} より 1 commit 後ろ" in out_behind,
                    "none": "を手元に持っていない" in out_none,
                    "same": "後ろ" not in out_same and "持っていない" not in out_same},
                   "\n".join((out_behind, out_none, out_same)))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-switch-case.py <" + "|".join(CASES) + ">")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # 開発者の global / system の git 設定（core.hooksPath・status.showUntrackedFiles・commit.gpgsign）を
        # 読ませない。検査側の git も機械側（changemap.run は環境を継ぐ）も同じ空の設定で動く
        os.environ["GIT_CONFIG_GLOBAL"] = write(tmp, "gitconfig", "")
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        print(CASES[sys.argv[1]](tmp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
