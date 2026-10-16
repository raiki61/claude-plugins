"""git への口。dispatch で git を呼ぶのはこの 1 か所だけ。

作業場は元の clone の git worktree（作る・消すは herdr の口。herdr.py）。worktree は中身（objects・refs・stash）を元の clone と
共有するので、手元の作業の判定は「その worktree の HEAD とその枝」に絞る（ほかの枝や元の clone の作業を数えない）。

部署の属性（役・アカウント・上役など）は、部署（worktree）ごとの git の設定 `company.<名前>` に置く（worktree_attrs・
enable_worktree_config・set_worktree_attr）。値は元の clone の `.git/worktrees/<部署>/config.worktree` に入り、ほかの部署と元の clone に
混ざらず、commit されず、`git worktree remove` で一緒に消える（会社の形の設計 4.2）。

書く関数は fetch・fast_forward・reset_keep・delete_branch・enable_worktree_config・set_worktree_attr・unset_worktree_attr・exclude の 8 つで、呼んでよいノードは柵（tests/fences.py の D4 の表 WRITES）が構文木で見る。
"""

import os
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


def reset_keep(cwd, branch, runner=_default_runner):
    """その枝を開いている worktree（cwd）を、origin/<枝> へ `git reset --keep` で揃える。書く口。
    作者が force-push して、手元の HEAD が origin の祖先でなくなったときだけ使う（呼ぶ側が、HEAD が前に送った時の head と同じで、
    場所がきれいなことを確かめてから）。--keep は、未コミットの変更と重なるなら git が断る（変更は消さない）。"""
    _must(["git", "-C", cwd, "reset", "--quiet", "--keep", f"refs/remotes/origin/{branch}"], runner)


def is_main_worktree(cwd, runner=_default_runner):
    """cwd が、linked worktree でなく本体の checkout か（`git rev-parse` の git-dir と git-common-dir が同じ）。読めなければ None。"""
    out = _git(cwd, ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"], runner)
    lines = (out or "").splitlines()
    if len(lines) != 2:
        return None
    return os.path.realpath(lines[0]) == os.path.realpath(lines[1])


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


def common_dir(cwd, runner=_default_runner):
    """cwd の属するリポジトリの共通の .git の場所（linked worktree でも元の clone の .git）。git でなければ None。"""
    out = _git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"], runner)
    return os.path.normpath(out) if out else None


def git_dir(cwd, runner=_default_runner):
    """cwd の worktree の .git の場所（linked worktree なら元の clone の .git/worktrees/<名前>）。commit されず、git worktree remove で
    消える。git でなければ None。"""
    out = _git(cwd, ["rev-parse", "--path-format=absolute", "--git-dir"], runner)
    return os.path.normpath(out) if out else None


def root_of(common):
    """共通の .git の場所から、元の clone の根。ふつうは .git の親。bare など .git で終わらなければ、その場所そのもの。"""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


ATTR = "company."


def worktree_attrs(cwd, runner=_default_runner):
    """その worktree の git の設定 company.<名前> を {名前: 値} で（名前は git が小文字にそろえる）。
    extensions.worktreeConfig が入っていない・属性が無い・読めないときは空。"""
    out = _git(cwd, ["config", "--worktree", "--get-regexp", r"^company\."], runner)
    attrs = {}
    for line in (out or "").splitlines():
        key, _, value = line.partition(" ")
        if key.startswith(ATTR):
            attrs[key[len(ATTR):]] = value
    return attrs


def enable_worktree_config(source, runner=_default_runner):
    """元の clone に extensions.worktreeConfig = true を入れる（部署ごとの設定を使う前提）。書く口。
    already（もう入っている）・enabled（入れた）のどちらか。git の文書は、入れる前に共通の設定の core.bare と core.worktree を
    元の clone の config.worktree へ移すよう求めている。そのどちらかが共通の設定に在れば入れずに GitError（移すのは持ち主）。"""
    if (_git(source, ["config", "--local", "--type=bool", "--get", "extensions.worktreeConfig"], runner) or "") == "true":
        return "already"
    moved = [k for k in ("core.bare", "core.worktree")
             if _git(source, ["config", "--local", "--get", k], runner) not in (None, "false")]
    if moved:
        raise GitError(f"{source} の共通の設定に {', '.join(moved)} が有るので extensions.worktreeConfig を入れない"
                       "（git help worktree の CONFIGURATION FILE の節のとおり、先に元の clone の config.worktree へ移す）")
    _must(["git", "-C", source, "config", "--local", "extensions.worktreeConfig", "true"], runner)
    return "enabled"


def exclude(source, pattern, runner=_default_runner):
    """元の clone の .git/info/exclude（commit されない、手元だけの無視の決まり。worktree と共有）に pattern の行が無ければ足す。書く口。
    added（足した）・already（もう有る）。勤め先のリポジトリの .gitignore を触らずに、Claude Code が作る .claude/ を隠すのに使う。"""
    common = common_dir(source, runner)
    if not common:
        raise GitError(f"{source} が git でない")
    path = os.path.join(common, "info", "exclude")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    if pattern in (line.strip() for line in text.splitlines()):
        return "already"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + pattern + "\n")
    return "added"


def is_merged(cwd, target, runner=_default_runner):
    """その場所の HEAD が target（例: refs/remotes/origin/main）に入っているか。読めなければ偽（消さない側に倒す）。"""
    return _is_ancestor(cwd, "HEAD", target, runner)


def unset_worktree_attr(cwd, name, runner=_default_runner):
    """その worktree の git の設定 company.<名前> を消す。書く口。もともと無ければ何もしない（git config は終了の値 5 を返す）。"""
    argv = ["git", "-C", cwd, "config", "--worktree", "--unset", f"{ATTR}{name}"]
    p = runner(argv)
    if p.returncode not in (0, 5):
        raise GitError(f"{' '.join(argv[:4])}: {(p.stderr or p.stdout).strip()[:300]}")


def set_worktree_attr(cwd, name, value, runner=_default_runner):
    """その worktree の git の設定 company.<名前> に値を書く（同じ値なら同じ結果）。書く口。"""
    _must(["git", "-C", cwd, "config", "--worktree", f"{ATTR}{name}", value], runner)
