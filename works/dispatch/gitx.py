"""git への口。dispatch で git を呼ぶのはこの 1 か所だけ。読むだけで、書かない。"""

import re
import subprocess

# git@host:o/r.git・ssh://git@host/o/r.git・https://host/o/r(.git) の末尾 2 つを OWNER/NAME として取る
_REPO = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


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
