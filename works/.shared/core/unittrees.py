"""修正の単位ごとの小さい git worktree（単位の worktree）。層 L1（works の物を何も知らない）。標準ライブラリと git だけ。

修正の工程が直す単位ごとに worktree を切り、流れの道具の fan_out で同時に直させ、差分を run の作業ツリーへ順に当てる土台。
run の作業ツリー（repo）の本物の index・HEAD・枝はどの口も動かさない（index を使う手は全部一時の GIT_INDEX_FILE で回す）。

- snapshot(repo) -> sha: run の作業ツリーの今の姿（未 commit の tracked の変更と、git が無視しない untracked を含む）を、
  親を HEAD にした commit にして sha を返す。参照 base-<sha> で守る（worktree を切る前に gc に拾われない）
- add(repo, base_sha, place) -> path: `git worktree add --detach <place> <base_sha>`。単位の参照 u-<place の印> で base を守る
- diff(path, base_sha) -> str: 単位の worktree の今の姿（untracked を含む）と base の差分（`--binary`。改名は削除と追加で書く）
- apply(repo, patch) -> (ok, why): run の作業ツリーへ当てる。一時の index で `git apply --cached --3way` を試し、食い違いが
  無い時だけ、その結果と今の姿の差分を作業ツリーへ当てる（index を汚さない）。当たらなければ作業ツリーを変えずに (False, 理由)
- remove(repo, path): 単位の worktree とその参照を消す（消えた置き場は prune で片付ける）
- sweep(repo) -> [path]: この作業ツリーから切った単位の worktree と参照の全部を消す（止まった run の残りの片付け）
- applied(repo, patch) -> bool: patch が作業ツリーに既に当たっているか（逆向きに当たるか。作業ツリーを変えない）

diff・apply は objects（書ける一時のフォルダ）を受ける。渡せば新しい object をそこに書き、元の objects は代わりの置き場として
読む（GIT_OBJECT_DIRECTORY と GIT_ALTERNATE_OBJECT_DIRECTORIES）。共通の .git が書けない所（役の sandbox）から回すための口で、
diff と apply に同じ objects を渡す（diff が書いた木を apply が読む）。

守りの参照は refs/works/units/<作業ツリーの印>/ の下に置く（印は作業ツリーの根の実パスの sha256 の頭 12 字）。参照は同じ
リポジトリの worktree の間で共有なので、作業ツリーごとに分けて、同じリポジトリの別の run の単位を sweep が消さない。
apply は同時に呼ばない前提（呼び手が単位の差分を 1 つずつ当てる。2 つが同時に作業ツリーを書くと後の方が当たらずに返る）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile

REF_ROOT = "refs/works/units"
# 外から継いだ git の居場所の変数は落とす（hook や節の中から呼ばれても、渡した repo・path だけを見る）
_GIT_PLACE = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_COMMON_DIR", "GIT_PREFIX")
# 利用者の設定に左右されない差分の形（apply が読める a/・b/ の頭・外の diff と textconv なし）
_DIFF = ["-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "diff", "--binary", "--no-renames", "--no-ext-diff",
         "--no-textconv", "--no-color", "--src-prefix=a/", "--dst-prefix=b/"]
_WHO = {"GIT_AUTHOR_NAME": "works", "GIT_AUTHOR_EMAIL": "works@localhost",
        "GIT_COMMITTER_NAME": "works", "GIT_COMMITTER_EMAIL": "works@localhost"}


class UnitTreeError(RuntimeError):
    """git が落ちた（どのコマンドかと標準エラーを文に載せる）"""


def _env(index: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_PLACE}
    if index is not None:
        env["GIT_INDEX_FILE"] = index
    return env


def _git(cwd, *args, index: str | None = None, data: bytes | None = None, env: dict | None = None,
         check: bool = True, objects: str | None = None) -> subprocess.CompletedProcess:
    """cwd で git を起こす（バイトのまま）。check なら落ちた時に UnitTreeError。objects は新しい object の置き場（頭の注記）"""
    extra = dict(env or {})
    if objects is not None:
        real = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                              capture_output=True, env=_env()).stdout.decode("utf-8", "replace").strip()
        extra.update({"GIT_OBJECT_DIRECTORY": str(objects), "GIT_ALTERNATE_OBJECT_DIRECTORIES": real})
    r = subprocess.run(["git", "-C", str(cwd), *args], input=data, capture_output=True,
                       env={**_env(index), **extra})
    if check and r.returncode != 0:
        raise UnitTreeError(f"git {' '.join(args[:3])} が落ちた（{cwd}）: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r


def _out(cwd, *args, **kw) -> str:
    return _git(cwd, *args, **kw).stdout.decode("utf-8", "replace").strip()


def _mark(path) -> str:
    return hashlib.sha256(os.path.realpath(str(path)).encode("utf-8")).hexdigest()[:12]


def _top(repo) -> str:
    return os.path.realpath(_out(repo, "rev-parse", "--show-toplevel"))


def _prefix(repo) -> str:
    """repo の作業ツリーの守りの参照の頭（refs/works/units/<作業ツリーの印>/）"""
    return f"{REF_ROOT}/{_mark(_top(repo))}/"


def _tree_now(tree, tmp: str, objects: str | None = None) -> str:
    """tree の作業ツリーの今の姿の木（一時の index に本物の index を写して add -A。本物の index は動かさない）"""
    index = os.path.join(tmp, "index")
    real = _out(tree, "rev-parse", "--path-format=absolute", "--git-path", "index")
    if os.path.isfile(real):   # 写すと stat の控えが効き、変わったファイルだけを読み直す。写しの mtime は本物に揃える
        # （git は index の mtime と同じ秒に書かれたファイルを stat で信じずに中身を読む。写しの mtime が今になると、
        # 同じ秒・同じ大きさで書き換えたファイルを変わっていないと読み、直しを落とす）
        shutil.copy2(real, index)
    _git(tree, "add", "-A", index=index, objects=objects)
    return _out(tree, "write-tree", index=index, objects=objects)


def snapshot(repo) -> str:
    """run の作業ツリーの今の姿を、親を HEAD にした commit にして sha を返す（本物の index・HEAD・枝は動かさない）。
    commit は参照 refs/works/units/<作業ツリーの印>/base-<sha> で守る（sweep で消える）"""
    with tempfile.TemporaryDirectory(prefix="works-unit-") as tmp:
        tree = _tree_now(repo, tmp)
    head = _out(repo, "rev-parse", "--verify", "HEAD^{commit}")
    sha = _out(repo, "commit-tree", tree, "-p", head, "-m", "works: 単位の worktree の base（run の作業ツリーの今の姿）",
               env=_WHO)
    _git(repo, "update-ref", _prefix(repo) + f"base-{sha}", sha)
    return sha


def add(repo, base_sha: str, place) -> pathlib.Path:
    """place に base_sha の単位の worktree を切る（HEAD は切り離し。枝を作らない）。参照 u-<place の印> で base を守る"""
    place = pathlib.Path(place)
    place.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", "--quiet", str(place), base_sha)
    _git(repo, "update-ref", _prefix(repo) + f"u-{_mark(place)}", base_sha)
    return place


def diff(path, base_sha: str, objects: str | None = None) -> str:
    """単位の worktree path の今の姿（未 commit・untracked を含む。単位が commit した物も今の姿に入る）と base_sha の差分"""
    with tempfile.TemporaryDirectory(prefix="works-unit-") as tmp:
        tree = _tree_now(path, tmp, objects)
    return _git(path, *_DIFF, base_sha, tree, objects=objects).stdout.decode("utf-8", "surrogateescape")


def apply(repo, patch: str, objects: str | None = None) -> tuple[bool, str]:
    """patch を run の作業ツリー repo へ 3 方向で当てる。(True, "") か、作業ツリーを変えずに (False, 理由)。
    一時の index（作業ツリーの今の姿）で `git apply --cached --3way` を試し、食い違い（未解決の段）が残れば当てない。
    通れば、今の姿とその結果の木の差分を作業ツリーへそのまま当てる（git apply は全部か無しか。本物の index は読まない）"""
    if not patch.strip():
        return True, ""
    data = patch.encode("utf-8", "surrogateescape")
    with tempfile.TemporaryDirectory(prefix="works-unit-") as tmp:
        before = _tree_now(repo, tmp, objects)
        index = os.path.join(tmp, "index")
        r = _git(repo, "apply", "--cached", "--3way", "--whitespace=nowarn", index=index, data=data, check=False,
                 objects=objects)
        if r.returncode != 0 or _out(repo, "ls-files", "-u", index=index, objects=objects):
            return False, (r.stderr.decode("utf-8", "replace").strip() or "3 方向で当てると食い違いが残る")
        after = _out(repo, "write-tree", index=index, objects=objects)
        if after == before:
            return True, ""
        step = _git(repo, *_DIFF, before, after, objects=objects).stdout
    r = _git(repo, "apply", "--whitespace=nowarn", data=step, check=False)
    if r.returncode != 0:   # 試してから当てるまでの間に作業ツリーが変わった
        return False, r.stderr.decode("utf-8", "replace").strip()
    return True, ""


def applied(repo, patch: str) -> bool:
    """patch が run の作業ツリー repo に既に当たっているか（逆向きに当たるか。`git apply -R --check`。作業ツリーも index も
    変えない）。空の patch は真"""
    if not patch.strip():
        return True
    r = _git(repo, "apply", "-R", "--check", "--whitespace=nowarn", data=patch.encode("utf-8", "surrogateescape"),
             check=False)
    return r.returncode == 0


def remove(repo, path) -> None:
    """単位の worktree path と守りの参照 u-<path の印> を消す（置き場が消えていれば prune で登録を片付ける）"""
    ref = _prefix(repo) + f"u-{_mark(path)}"   # 消す前に印を取る（実パスは在る間に解く）
    if pathlib.Path(path).exists():
        _git(repo, "worktree", "remove", "--force", str(path))
    _git(repo, "worktree", "prune")
    _git(repo, "update-ref", "-d", ref, check=False)


def _refs(repo) -> list[str]:
    return _out(repo, "for-each-ref", "--format=%(refname)", _prefix(repo)).splitlines()


def sweep(repo) -> list[str]:
    """repo の作業ツリーから切った単位の worktree（守りの参照 u-<印> を持つ物）を全部消し、この作業ツリーの守りの参照を
    全部消す。消した worktree の実パスを返す。同じリポジトリのほかの作業ツリーの単位には触らない"""
    prefix = _prefix(repo)
    refs = set(_refs(repo))
    gone = []
    for line in _out(repo, "worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        path = line[len("worktree "):]
        if prefix + f"u-{_mark(path)}" in refs:
            if pathlib.Path(path).exists():
                _git(repo, "worktree", "remove", "--force", path)
            gone.append(os.path.realpath(path))
    _git(repo, "worktree", "prune")
    for ref in refs:
        _git(repo, "update-ref", "-d", ref, check=False)
    return gone
