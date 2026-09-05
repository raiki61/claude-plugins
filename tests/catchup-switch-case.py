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


def make_origin(tmp, repo, owner="o", name="r"):
    """origin を、その場に作った bare リポジトリに向ける（path の末尾が owner/name.git なので origin_is が
    通る）。手元に無い枝を fetch する検査用——GitHub には触らない。戻り値は bare の path。"""
    bare = os.path.join(tmp, owner, f"{name}.git")
    os.makedirs(os.path.dirname(bare), exist_ok=True)
    git(tmp, "init", "-q", "--bare", bare)
    git(repo, "remote", "set-url", "origin", bare)
    return bare


def new_commit(repo, parent, msg):
    """parent の子 commit を、木はそのままで作る（枝は動かさない）。"""
    return git(repo, "commit-tree", git(repo, "write-tree"), "-p", parent, "-m", msg)


def node(repo, **over):
    """PR の node。実物の GraphQL と同じ形で、state・既定ブランチ・maintainerCanModify も持つ。"""
    n = {"__typename": "PullRequest", "headRefName": HEAD_REF, "state": "OPEN",
         "headRepository": {"nameWithOwner": "o/r"}, "maintainerCanModify": False,
         "baseRepository": {"defaultBranchRef": {"name": "main"}},
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
    """origin にだけある枝は、その 1 本を fetch して作り、移る（名前・追跡先は gh pr checkout と同じ）。手元の
    origin/<枝> の追跡 ref が古くても、fetch した先端で作る（fetch せずに手元の ref から作ると古い枝になる）。
    手元にある枝（main・feat）は動かない。"""
    repo = make_repo(tmp)
    make_origin(tmp, repo)
    # 追跡先は --track で明示的に付ける（既定の autoSetupMerge が付けるのに頼らない）。origin のタグは取らない
    git(repo, "config", "branch.autoSetupMerge", "false")
    old = git(repo, "rev-parse", "HEAD")
    new = new_commit(repo, old, "pushed-from-elsewhere")
    git(repo, "push", "-q", "origin", f"{new}:refs/heads/pr-head", f"{new}:refs/tags/v9")
    git(repo, "update-ref", "refs/remotes/origin/pr-head", old)  # 手元の追跡 ref は古い
    git(repo, "update-ref", "refs/heads/origin/pr-head", old)  # 短縮名 origin/pr-head を曖昧にする同名の枝
    write(repo, "stray.txt", "u\n")
    out, on = call(repo, node(repo, headRefName="pr-head", head={"nodes": [{"commit": {"oid": new}}]}))
    return verdict({"line": "ブランチ pr-head: 手元に無かったので origin/pr-head から作って main から移った"
                    "（未追跡 1 件は持ち越した）" in out and "gh pr checkout" not in out,
                    "branch": current(repo) == "pr-head", "on": on == "pr-head",
                    "tip": git(repo, "rev-parse", "HEAD") == new,
                    # 同名の枝で短縮名が曖昧なので完全名で見る（--abbrev-ref は remotes/origin/pr-head に伸びる）
                    "upstream": git(repo, "rev-parse", "--symbolic-full-name", "pr-head@{upstream}")
                    == "refs/remotes/origin/pr-head",
                    "no_tags": git(repo, "tag", "-l") == "",
                    "others_kept": git(repo, "rev-parse", "main") == old
                    and git(repo, "rev-parse", HEAD_REF) == old}, out)


@case("remote-dirty")
def _remote_dirty(tmp):
    """手元に無い枝でも guard は先——追跡ファイルに未コミットがあれば fetch もせず止まる（古い追跡 ref が
    そのまま＝fetch していない証拠）。枝は作らない。止まった行に今どこに居るかが添う。"""
    repo = make_repo(tmp)
    make_origin(tmp, repo)
    old = git(repo, "rev-parse", "HEAD")
    new = new_commit(repo, old, "pushed-from-elsewhere")
    git(repo, "push", "-q", "origin", f"{new}:refs/heads/pr-head")
    git(repo, "update-ref", "refs/remotes/origin/pr-head", old)
    write(repo, "same.txt", "same\nedited\n")
    out, on = call(repo, node(repo, headRefName="pr-head", head={"nodes": [{"commit": {"oid": new}}]}))
    # 片付けた後の一手は「もう一度 /catchup」——git switch pr-head は枝が無いので失敗するか、古い追跡 ref から作る
    return verdict({"line": "未コミットの変更 1 件" in out and "（手元は main のまま）" in out
                    and f"→ もう一度 /catchup {NUM}" in out and "git switch pr-head" not in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "no_new_branch": "refs/heads/pr-head" not in heads(repo),
                    "no_fetch": git(repo, "rev-parse", "refs/remotes/origin/pr-head") == old}, out)


@case("remote-ignored")
def _remote_ignored(tmp):
    """origin から作るときも ignored の file を上書きしない（switch -c にも --no-overwrite-ignore）。拒まれたら
    枝は作られず、手元の file もそのまま。"""
    repo = make_repo(tmp)
    make_origin(tmp, repo)
    git(repo, "switch", "-q", HEAD_REF)
    write(repo, ".vscode/settings.json", "TRACKED\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "vscode")
    git(repo, "push", "-q", "origin", f"{HEAD_REF}:refs/heads/vs-branch")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    with open(os.path.join(repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
        f.write(".vscode/\n")
    write(repo, ".vscode/settings.json", "PRIVATE\n")
    out, on = call(repo, node(repo, headRefName="vs-branch", head={"nodes": [{"commit": {"oid": head}}]}))
    return verdict({"line": "作れなかった" in out and "settings.json" in out and "（手元は main のまま）" in out,
                    "branch": current(repo) == "main", "not_on": not on,
                    "no_new_branch": "refs/heads/vs-branch" not in heads(repo),
                    "kept": read(repo, ".vscode/settings.json").strip() == "PRIVATE"}, out)


@case("none")
def _none(tmp):
    """手元にも origin にも無ければそう言い、枝は作らない——merge 済みで枝が削除された PR ならその旨と、
    refs/pull/N/head からの取り方。origin に届かなければ（認証・URL 違い）git の言い分を添える。どちらも
    手元の origin/<枝> の古い ref からは作らない。"""
    repo = make_repo(tmp)
    make_origin(tmp, repo)
    git(repo, "update-ref", "refs/remotes/origin/nope", "HEAD")  # 古い追跡 ref だけ残っている
    out, on = call(repo, node(repo, headRefName="nope", state="MERGED"))
    git(repo, "remote", "set-url", "origin", os.path.join(tmp, "nowhere", "o", "r.git"))
    out2, on2 = call(repo, node(repo, headRefName="nope"))
    # 応答が無ければ FETCH_TIMEOUT 秒で切る（ssh を sleep する script に差し替えて再現。Windows は sh が無いことがある）。
    # 待つのは検査の実時間なので、切る秒数は縮めて借りる（timeout は float を受ける）
    short = 0.2
    out3 = f"origin から取れなかった（{short} 秒で応答が無い）"
    if os.name != "nt":
        git(repo, "remote", "set-url", "origin", "ssh://nowhere.invalid/o/r.git")
        slow = write(tmp, "slow-ssh", "#!/bin/sh\nsleep 5\n")
        os.chmod(slow, 0o755)
        os.environ["GIT_SSH_COMMAND"] = slow
        saved, catchup.FETCH_TIMEOUT = catchup.FETCH_TIMEOUT, short
        out3, on3 = call(repo, node(repo, headRefName="nope"))
        catchup.FETCH_TIMEOUT = saved
        del os.environ["GIT_SSH_COMMAND"]
    return verdict({"gone": "origin にももう無い（PR は merge 済みで、枝は削除済み）" in out
                    and f"git fetch origin refs/pull/{NUM}/head" in out and "（手元は main のまま）" in out,
                    "unreachable": "origin から取れなかった（git fetch が失敗）" in out2
                    and "does not appear to be a git repository" in out2,
                    "timeout": f"origin から取れなかった（{short} 秒で応答が無い）" in out3,
                    "branch": current(repo) == "main", "not_on": not on and not on2,
                    "no_new_branch": "refs/heads/nope" not in heads(repo)}, "\n".join((out, out2, out3)))


@case("fork-remote")
def _fork_remote(tmp):
    """fork の PR の枝が手元に無ければ origin の refs/pull/N/head から作って移る。追跡先は gh pr checkout と
    同じ——既定は origin の refs/pull/N/head（pull は効き、push は上流名が違うので git が拒む）、PR が
    maintainer の push を許していれば fork の URL の refs/heads/<head>。"""
    repo = make_repo(tmp)
    bare = make_origin(tmp, repo)
    head = new_commit(repo, "main", "on-fork")
    git(repo, "push", "-q", "origin", f"{head}:refs/pull/{NUM}/head")
    n = node(repo, headRefName="fork-feat", headRepository={"nameWithOwner": "other/r"},
             head={"nodes": [{"commit": {"oid": head}}]})
    def again(over=None):
        """main に戻して枝を消してから、もう一度呼ぶ（毎回「手元に無い」状態から始める）。"""
        git(repo, "switch", "-q", "main")
        git(repo, "branch", "-q", "-D", "fork-feat")
        return call(repo, dict(n, **over) if over else n)

    def cfg():
        return tuple(git(repo, "config", "--get", f"branch.fork-feat.{k}")
                     for k in ("remote", "pushRemote", "merge"))

    out1, on1 = call(repo, n)
    moved1 = current(repo) == "fork-feat" and git(repo, "rev-parse", "HEAD") == head
    cfg1 = cfg()
    out2, on2 = again({"maintainerCanModify": True})
    moved2 = current(repo) == "fork-feat" and git(repo, "rev-parse", "HEAD") == head
    cfg2 = cfg()
    fork_bare = bare.replace(os.path.join(tmp, "o", "r.git"), os.path.join(tmp, "other", "r.git"))
    # 消えた fork（headRepository null）は maintainerCanModify でも fork の URL が無いので origin の refs/pull へ
    out3, on3 = again({"headRepository": None, "maintainerCanModify": True})
    cfg3 = cfg()
    # 追跡先が書けなければ（他のセッションが .git/config を書いている最中 = config.lock）移った上で注釈
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-q", "-D", "fork-feat")
    lock = write(repo, os.path.join(".git", "config.lock"), "")
    out4, on4 = call(repo, n)
    os.remove(lock)
    return verdict({
        "line": f"ブランチ fork-feat: 手元に無かったので PR の head（origin の refs/pull/{NUM}/head。fork other/r）"
                "から作って main から移った" in out1,
        "moved": moved1 and on1 == "fork-feat" and moved2 and on2 == "fork-feat",
        "track_pull_ref": cfg1 == ("origin", "origin", f"refs/pull/{NUM}/head"),
        "track_fork": cfg2 == (fork_bare, fork_bare, "refs/heads/fork-feat"),
        "gone_fork": "消えた fork）から作って" in out3 and on3 == "fork-feat"
        and cfg3 == ("origin", "origin", f"refs/pull/{NUM}/head"),
        "config_lock": on4 == "fork-feat" and current(repo) == "fork-feat"
        and "追跡先を書けなかった（branch.fork-feat.remote / pushRemote / merge）" in out4,
        "main_kept": git(repo, "rev-parse", "main") != head,
    }, "\n".join((out1, out2, out3, out4)))


@case("origin-mismatch")
def _origin_mismatch(tmp):
    """origin が別のリポジトリなら移らない。origin が無くてもその旨。"""
    repo = make_repo(tmp)
    git(repo, "remote", "set-url", "origin", "https://github.com/x/y.git")
    out1, on1 = call(repo)
    git(repo, "remote", "remove", "origin")
    out2, on2 = call(repo)
    # 別のリポジトリで呼ぶのは普通に起きるので、この行にも今どこに居るかが要る
    return verdict({"mismatch": "origin が o/r でない" in out1 and "x/y" in out1 and not on1,
                    "no_origin": "origin が無い" in out2 and not on2,
                    "where": out1.endswith("（手元は main のまま）") and out2.endswith("（手元は main のまま）"),
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
    # 手元の feat を main より 1 commit 先にする（head = main の先端。手元が head を含む）
    git(repo, "update-ref", f"refs/heads/{HEAD_REF}", new_commit(repo, base, "ahead"))
    out_ahead, on_ahead = call(repo, node(repo, headRepository=fork))
    moved = current(repo) == HEAD_REF
    git(repo, "switch", "-q", "main")
    # head が手元の feat の子（手元が古い）。逆向きの判定なら移ってしまう
    child = new_commit(repo, HEAD_REF, "newer-on-fork")
    out_old, on_old = call(repo, node(repo, headRepository=fork, head={"nodes": [{"commit": {"oid": child}}]}))
    orphan = git(repo, "commit-tree", git(repo, "write-tree"), "-m", "orphan")  # 親が無いので new_commit では作れない
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
    """head が main の fork PR: 手元の main は候補にしない（base 側の枝で、fork の main とは別物）。gh pr checkout が
    付ける <fork の owner>/main の名前が手元に無ければ refs/pull/N/head からその名前で作って移り、あればそれに
    移る。既定ブランチ名が node に無ければ（取れなかったとき）従来どおり手元の main を照合して「含まない」で
    止まる。fork が消えている（headRepository null）PR は名前だけでは移らず、head が既定ブランチ名なら作る名前を
    決められないと言う。"""
    repo = make_repo(tmp)
    make_origin(tmp, repo)
    fork = {"nameWithOwner": "other/r"}
    base = git(repo, "rev-parse", "main")
    head = new_commit(repo, "main", "on-fork-main")
    git(repo, "push", "-q", "origin", f"{head}:refs/pull/{NUM}/head")
    n = node(repo, headRefName="main", headRepository=fork, head={"nodes": [{"commit": {"oid": head}}]})
    out_nodef, on_nodef = call(repo, dict(n, baseRepository=None))
    stayed = current(repo) == "main"
    out_made, on_made = call(repo, n)
    made = current(repo) == "other/main" and git(repo, "rev-parse", "HEAD") == head
    git(repo, "switch", "-q", "main")
    out_pref, on_pref = call(repo, n)
    moved = current(repo) == "other/main"
    git(repo, "switch", "-q", "main")
    out_null, on_null = call(repo, node(repo, headRepository=None, head={"nodes": [{"commit": {"oid": head}}]}))
    out_null_main, on_null_main = call(repo, node(repo, headRefName="main", headRepository=None,
                                                  head={"nodes": [{"commit": {"oid": head}}]}))
    return verdict({
        "no_default_stays": "既に居る" not in out_nodef and "含まない" in out_nodef and not on_nodef and stayed,
        "made": "ブランチ other/main: 手元に無かったので PR の head" in out_made and on_made == "other/main"
        and made and git(repo, "rev-parse", "main") == base,
        "prefixed": "ブランチ other/main: main から移った" in out_pref and on_pref == "other/main" and moved,
        "gone_default": "作る名前を決められない" in out_null_main and f"refs/pull/{NUM}/head" in out_null_main
        and not on_null_main,
        "gone_fork": "消えた fork" in out_null and "含まない" in out_null and not on_null,
        "still": current(repo) == "main",
    }, "\n".join((out_nodef, out_made, out_pref, out_null, out_null_main)))


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
    write(repo, "same.txt", "same\nedited\n")
    out_stay, on_stay = call(repo)  # 止まった行の末尾は、枝名が無いので detached HEAD と書く
    git(repo, "checkout", "-q", "--", "same.txt")
    out, on = call(repo)
    return verdict({"stay": out_stay.endswith("（手元は detached HEAD のまま）") and not on_stay,
                    "line": "（detached） から移った" in out, "warn": "leaving 1 commit behind" in out,
                    "branch": current(repo) == HEAD_REF, "on": on}, out_stay + "\n" + out)


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
