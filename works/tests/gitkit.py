"""試験の使い捨ての git リポジトリを、1 回だけ作った型の写しで配る道具（テストのモジュールではない。test_*.py に当たらない）。

どの試験も「種（dev/target-seed/ など）を写して git init・add・commit」を毎回やっていて、1 回に git を 3〜4 本起こす。
committed_copy は、同じ種の 2 回目からは、テストのプロセスで 1 回だけ作った型（.git ごと）を写し、git は 1 本だけ起こす。
試験が git を呼ぶ時の GIT_ID（hook・署名・名前を切る -c）と git() もここに 1 つだけ置く。
写しは型と同じ中身・同じ commit（版の名前も同じ）で、試験ごとに別のフォルダなので、試験が書き換えても他に漏れない。
型は tempfile の既定の置き場に作り、プロセスの終わりに消す。置き場ごと消された（test_dev の tearDownModule）ら作り直す。
型は src を最初に呼ばれた時の姿で写す（回っている間に src を書き換えても、型の写しには入らない）。

写した .git の index は型のファイルの stat（ino・ctime）を持ち、そのままでは index の stat を信じる plumbing
（diff-files・diff-index）が全部のファイルを変わったと見る。写すたびに update-index --refresh を 1 回起こして
（git を 1 本）、git init から作った時と同じ綺麗な index にする。
"""
import atexit
import pathlib
import shutil
import subprocess
import tempfile

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

_made = {}   # (src, sub, ignore) → (型の根, HEAD の版)


def git(repo, *args):
    """repo で git を起こし、標準出力（前後の空白を落とす）を返す。失敗は CalledProcessError。hook・署名・利用者の名前に左右されない"""
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _build(src, sub, ignore):
    home = pathlib.Path(tempfile.mkdtemp(prefix="works-gitkit-"))
    atexit.register(shutil.rmtree, home, True)
    repo = home / "repo"
    shutil.copytree(src, repo / sub, ignore=shutil.ignore_patterns(*ignore) if ignore else None)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    return repo, git(repo, "rev-parse", "HEAD")


def committed_copy(dest, src, sub=".", ignore=()):
    """src の中身を dest/sub に写し、dest を根に全部を 1 本の commit にした git リポジトリを置く。HEAD の版を返す。
    dest はまだ無いこと。ignore は写さない名前の型（shutil.ignore_patterns に渡す物）。"""
    key = (str(pathlib.Path(src).resolve()), sub, tuple(ignore))
    if key not in _made or not _made[key][0].is_dir():
        _made[key] = _build(src, sub, ignore)
    repo, head = _made[key]
    shutil.copytree(repo, dest, symlinks=True)
    git(dest, "update-index", "-q", "--refresh")   # index の stat を写しのファイルに合わせる（test_gitkit）
    return head
