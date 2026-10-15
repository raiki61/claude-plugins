"""git への口。dispatch で git を呼ぶのはこの 1 か所だけ。

作業場は元の clone の git worktree（作る・消すは herdr の口。herdr.py）。worktree は中身（objects・refs・stash）を元の clone と
共有するので、手元の作業の判定は「その worktree の HEAD とその枝」に絞る（ほかの枝や元の clone の作業を数えない）。

書く関数は fetch・fast_forward・delete_branch の 3 つで、呼んでよいノードは柵（tests/fences.py の D4 の表 WRITES）が構文木で見る。
"""

import re
import subprocess

# git@host:o/r.git・ssh://git@host/o/r.git・https://host/o/r(.git)・手元のパス（Windows では C:\…\o\r.git）の末尾 2 つを OWNER/NAME として取る
_REPO = re.compile(r"[:/\\]([^/:\\]+)[/\\]([^/\\]+?)(?:\.git)?[/\\]?$")


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


class GitError(Exception):
    pass


def _git(cwd, args, runner):
    p = runner(["git", "-C", cwd, *args])
    return p.stdout.strip() if p.returncode == 0 else None


def branch(cwd, runner=_default_runner):
    """今の枝の名前。枝に居ない（detached）・git でない時は None。"""
    return _git(cwd, ["branch", "--show-current"], runner) or None


def is_clean(cwd, runner=_default_runner):
    """未コミットの変更も、git にまだ足していない新しいファイルも無いか。読めない時は、汚れているとみなす（消さない側に倒す）。

    .gitignore に当たるファイル（.env.local など、写し元から作り直せる手元だけのファイル）は数えない。
    """
    out = _git(cwd, ["status", "--porcelain"], runner)
    return out == ""


def origin_repo(cwd, runner=_default_runner):
    """origin の OWNER/NAME。origin が無い・git でない時は None。"""
    url = _git(cwd, ["remote", "get-url", "origin"], runner)
    m = _REPO.search(url) if url else None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def origin_url(cwd, runner=_default_runner):
    """origin の URL そのもの。無ければ None。"""
    return _git(cwd, ["remote", "get-url", "origin"], runner)


def _must(argv, runner):
    p = runner(argv)
    if p.returncode != 0:
        raise GitError(f"{' '.join(argv[:4])}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout.strip()


def fetch(cwd, branch, runner=_default_runner):
    """origin のその枝だけを取り、origin/<枝> を今の head に揃える（git fetch の、決まった remote の枝を取る時の
    remote-tracking の枝の更新）。origin に枝が無ければ GitError。書く口。"""
    _must(["git", "-C", cwd, "fetch", "--quiet", "origin", branch], runner)


def _is_ancestor(cwd, a, b, runner):
    return runner(["git", "-C", cwd, "merge-base", "--is-ancestor", a, b]).returncode == 0


def fast_forward(cwd, branch, runner=_default_runner):
    """その枝を開いている worktree（cwd）で、手元の枝が origin/<枝> の祖先なら早送りだけする。書く口。
    current（もう同じ）・updated（早送りした）・local_only（手元にしか無い commit が有るので動かさない）のどれか。
    未コミットの変更と重なって git が断れば GitError（変更は消さない）。"""
    if _git(cwd, ["rev-parse", "HEAD"], runner) == _git(cwd, ["rev-parse", f"refs/remotes/origin/{branch}"], runner):
        return "current"
    if not _is_ancestor(cwd, "HEAD", f"refs/remotes/origin/{branch}", runner):
        return "local_only"
    _must(["git", "-C", cwd, "merge", "--ff-only", "--quiet", f"refs/remotes/origin/{branch}"], runner)
    return "updated"


def head_sha(cwd, runner=_default_runner):
    """その worktree の HEAD の commit。読めなければ None。"""
    return _git(cwd, ["rev-parse", "HEAD"], runner) or None


def delete_branch(source, branch, expected_sha, runner=_default_runner):
    """元の clone の手元の枝を消す。先頭が expected_sha（PR の head）と同じときだけ消す。書く口。
    deleted・moved（先頭が違うので消さない）・absent（もう無い）のどれか。どこかの worktree が開いている枝は git が断る（GitError）。"""
    now = _git(source, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], runner)
    if not now:
        return "absent"
    if now != expected_sha:
        return "moved"
    _must(["git", "-C", source, "branch", "--quiet", "-D", branch], runner)
    return "deleted"


def stashed(cwd, branch, runner=_default_runner):
    """その枝の上で作った stash が有るか。stash は worktree の間で共有なので、stash の記録の「WIP on <枝>:」「On <枝>:」で絞る。
    読めない時は、有るとみなす（消さない側に倒す）。"""
    out = _git(cwd, ["stash", "list", "--format=%gs"], runner)
    if out is None:
        return True
    return any(line.startswith((f"WIP on {branch}: ", f"On {branch}: ")) for line in out.splitlines())


def unpushed(cwd, runner=_default_runner):
    """その worktree に、手元にしか無い作業があるか。読めない時は、有るとみなす（消さない側に倒す）。

    HEAD の上の、どの remote の枝にも入っていない commit（枝に乗っていない HEAD も同じ）と、今の枝の上で作った stash を数える。
    ほかの枝（元の clone の枝など）は数えない。worktree は枝と stash を元の clone と共有するため。
    """
    out = _git(cwd, ["rev-list", "-n", "1", "HEAD", "--not", "--remotes"], runner)
    if out is None or out != "":
        return True
    return stashed(cwd, branch(cwd, runner) or "(no branch)", runner)


def ignored_files(cwd, runner=_default_runner):
    """git が追わないファイル（.gitignore に当たるもの）。丸ごと無視したフォルダ（node_modules など）は中を数えない。"""
    out = _git(cwd, ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory"], runner)
    return sorted(line for line in (out or "").splitlines() if line and not line.endswith("/"))
