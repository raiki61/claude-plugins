"""git への口。dispatch で git を呼ぶのはこの 1 か所だけ。

書く関数は clone・set_origin・fetch の 3 つで、呼んでよいのは provision のノードだけ（D4。柵が構文木で見る）。
"""

import re
import subprocess

# git@host:o/r.git・ssh://git@host/o/r.git・https://host/o/r(.git) の末尾 2 つを OWNER/NAME として取る
_REPO = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class GitError(Exception):
    pass


def _git(cwd, args, runner):
    p = runner(["git", "-C", cwd, *args])
    return p.stdout.strip() if p.returncode == 0 else None


def branch(cwd, runner=_default_runner):
    """今の枝の名前。枝に居ない（detached）・git でない時は None。"""
    return _git(cwd, ["branch", "--show-current"], runner) or None


def is_clean(cwd, runner=_default_runner):
    """追跡しているファイルに未コミットの変更が無いか。追跡していないファイルは見ない（/catchup が枝を移る条件と同じ）。"""
    out = _git(cwd, ["status", "--porcelain", "--untracked-files=no"], runner)
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


def clone(source, path, runner=_default_runner):
    """手元の clone から clone する。手元のパスからの clone は、中身（.git/objects/）をハードリンクで共有する（git-clone の --local）。"""
    _must(["git", "clone", "--quiet", source, path], runner)


def set_origin(path, url, runner=_default_runner):
    _must(["git", "-C", path, "remote", "set-url", "origin", url], runner)


def fetch(path, runner=_default_runner):
    _must(["git", "-C", path, "fetch", "--quiet", "origin"], runner)


def unpushed(cwd, runner=_default_runner):
    """手元にしか無い commit（どの remote の枝にも入っていない commit）があるか。読めない時は、有るとみなす（消さない側に倒す）。"""
    out = _git(cwd, ["log", "--branches", "--not", "--remotes", "--oneline"], runner)
    return out is None or out != ""


def ignored_files(cwd, runner=_default_runner):
    """git が追わないファイル（.gitignore に当たるもの）。丸ごと無視したフォルダ（node_modules など）は中を数えない。"""
    out = _git(cwd, ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory"], runner)
    return sorted(line for line in (out or "").splitlines() if line and not line.endswith("/"))
