"""git への口。dispatch で git を呼ぶのはこの 1 か所だけ。

作業場は元の clone の git worktree（作る・消すは herdr の口。herdr.py）。worktree は中身（objects・refs・stash）を元の clone と
共有するので、手元の作業の判定は「その worktree の HEAD とその枝」に絞る（ほかの枝や元の clone の作業を数えない）。

部署の属性（役・アカウント・頼み元など）は、部署（worktree）ごとの git の設定 `company.<名前>` に置く（worktree_attrs・
enable_worktree_config・set_worktree_attr）。値は元の clone の `.git/worktrees/<部署>/config.worktree` に入り、ほかの部署と元の clone に
混ざらず、commit されず、`git worktree remove` で一緒に消える（会社の形の設計 4.2）。

書く関数は fetch・fast_forward・reset_keep・delete_branch・enable_worktree_config・set_worktree_attr・unset_worktree_attr・exclude と、
本流に入れる（取り込みの命令）ための push・drop_remote・advance_branch・add_detached・remove_detached・commit_all と、本流が先に
進んだ枝を載せ直すための rebase・rebase_continue・rebase_abort・add_path・push_rebased で、
呼んでよいノードは柵（tests/fences.py の D4 の表 WRITES）が構文木で見る。
"""

import codecs
import json
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


def toplevel(cwd, runner=_default_runner):
    """cwd の worktree の根。git でなければ None。"""
    out = _git(cwd, ["rev-parse", "--show-toplevel"], runner)
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


def former_names(attrs):
    """部署の前の名前の並び（属性 company.former-names。--reorg と --desk が名前を替えたときに JSON の並びで書く）。読めなければ空。"""
    try:
        got = json.loads(attrs.get("former-names") or "[]")
    except ValueError:
        return []
    return [n for n in got if isinstance(n, str) and n] if isinstance(got, list) else []


def untracked(cwd, runner=_default_runner):
    """git にまだ足していないファイルの集合（cwd の worktree の根からの相対。.gitignore に当たる物は入れない）。読めなければ GitError。"""
    out = _must(["git", "-C", cwd, "ls-files", "--others", "--exclude-standard", "-z"], runner)
    return {x for x in out.split("\0") if x}


def enable_worktree_config(source, runner=_default_runner):
    """元の clone に extensions.worktreeConfig = true を入れる（部署ごとの設定を使う前提）。書く口。
    already（もう入っている）・enabled（入れた）のどちらか。git の文書は、入れる前に共通の設定の core.bare と core.worktree を
    元の clone の config.worktree へ移すよう求めている。そのどちらかが共通の設定に在れば入れずに GitError（移すのは持ち主）。"""
    if (_git(source, ["config", "--local", "--type=bool", "--get", "extensions.worktreeConfig"], runner) or "") == "true":
        _rerere(source, runner)
        return "already"
    moved = [k for k in ("core.bare", "core.worktree")
             if _git(source, ["config", "--local", "--get", k], runner) not in (None, "false")]
    if moved:
        raise GitError(f"{source} の共通の設定に {', '.join(moved)} が有るので extensions.worktreeConfig を入れない"
                       "（git help worktree の CONFIGURATION FILE の節のとおり、先に元の clone の config.worktree へ移す）")
    _rerere(source, runner)
    _must(["git", "-C", source, "config", "--local", "extensions.worktreeConfig", "true"], runner)
    return "enabled"


def _rerere(source, runner):
    """前に手で解いたぶつかりを git に覚えさせる（--land の載せ直しが使い直す。git rerere）。持ち主がどこか（local・global・
    system）に値を書いていれば替えない。"""
    for key in ("rerere.enabled", "rerere.autoUpdate"):
        if _git(source, ["config", "--get", key], runner) is None:
            _git(source, ["config", "--local", key, "true"], runner)


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


# 本流に入れる（取り込みの命令 --land。nodes/land.py と nodes/bump.py）ための口


def rev(cwd, ref, runner=_default_runner):
    """ref の commit。無ければ None。"""
    return _git(cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], runner) or None


def is_ancestor(cwd, a, b, runner=_default_runner):
    """a が b の祖先（同じ commit も含む）か。読めなければ偽。"""
    return _is_ancestor(cwd, a, b, runner)


def remote_rev(cwd, branch, runner=_default_runner):
    """origin のその枝の先頭の commit を origin に問い合わせて読む（git ls-remote）。枝が無ければ None。手元の ref は書かない。"""
    out = _must(["git", "-C", cwd, "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], runner)
    return out.split()[0] if out else None


def subjects(cwd, a, b, runner=_default_runner):
    """a..b の commit の「短い id 件名」を新しい順に。読めなければ GitError。"""
    return _must(["git", "-C", cwd, "log", "--format=%h %s", f"{a}..{b}"], runner).splitlines()


def commits_touching(cwd, path, since=None, runner=_default_runner):
    """path（cwd からの相対）を変えた commit の id を新しい順に。since を渡せば since..HEAD の中だけ。読めなければ GitError。"""
    return _must(["git", "-C", cwd, "log", "--format=%H", *([f"{since}..HEAD"] if since else []), "--", path], runner).split()


def changed_paths(cwd, since, path, runner=_default_runner):
    """since から HEAD までに変わった、path（cwd からの相対）の下のファイルの並び（リポジトリの根からの相対）。読めなければ GitError。"""
    return _must(["git", "-C", cwd, "diff", "--name-only", since, "HEAD", "--", path], runner).splitlines()


def diff_zero(cwd, a, b, runner=_default_runner):
    """a から b への差分を、前後の行を付けずに（-U0）、名前の付け替えを追わずに。読めなければ GitError。"""
    return _must(["git", "-C", cwd, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", a, b], runner)


def blame_line(cwd, rev, path, line, runner=_default_runner):
    """rev の path の line 行目を最後に変えた commit の (id, 件名)。読めなければ (None, None)。"""
    out = _git(cwd, ["blame", "--porcelain", "-L", f"{line},{line}", rev, "--", path], runner) or ""
    lines = out.splitlines()
    sha = lines[0].split()[0] if lines and lines[0].split() else None
    summary = next((x[len("summary "):] for x in lines if x.startswith("summary ")), None)
    return sha, summary


def origin_head(cwd, runner=_default_runner):
    """origin の既定の枝を指す手元の ref（origin/HEAD が指す先。例 origin/main）。origin/HEAD が無い・git でない時は None。
    手元の ref を読むだけで、origin へは問い合わせない（最後に fetch・push した時の形）。"""
    return _git(cwd, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], runner) or None


def default_branch(cwd, runner=_default_runner):
    """origin の既定の枝の名前（本流。例 main）。手元の origin/HEAD を先に、無ければ origin に `git ls-remote --symref origin HEAD`
    で問う（GitHub に限らず、手元の bare リポジトリでも答える）。どちらでも決まらなければ GitError（直し方を添える）。
    本流の枝の名前の元はこれ 1 つにする（会社の形を読む ref の origin/HEAD と同じ物を、部署の枝を作る元と --land の本流にも使う）。"""
    head = origin_head(cwd, runner)
    if head and head.startswith("origin/"):
        return head.split("/", 1)[1]
    out = _git(cwd, ["ls-remote", "--symref", "origin", "HEAD"], runner) or ""
    for line in out.splitlines():
        if line.startswith("ref: refs/heads/") and line.rstrip().endswith("HEAD"):
            return line[len("ref: refs/heads/"):].split("\t")[0].strip()
    raise GitError(f"{cwd}: origin の既定の枝を決められない（手元の origin/HEAD が無く、origin も HEAD を答えない。"
                   f"origin に本流の枝を push してから git -C {cwd} remote set-head origin --auto を打つ）")


def file_at(cwd, commit, path, runner=_default_runner):
    """その commit の path（cwd からの相対）の中身。無ければ None。"""
    return _git(cwd, ["show", f"{commit}:./{path}"], runner)


def push(cwd, sha, ref, force=False, runner=_default_runner):
    """origin の枝 ref を sha にする（git push origin <sha>:refs/heads/<ref>）。書く口。force が偽なら早送りでしか進めず、
    origin が先に進んでいれば git が断る（GitError）。"""
    _must(["git", "-C", cwd, "push", "--quiet", "origin", f"{'+' if force else ''}{sha}:refs/heads/{ref}"], runner)


# 載せ直しで、前に手で解いたぶつかりを git に使い直させる（git rerere。rebase は rerere を自動で呼ぶ）。解いた所は index に足す
# 利用者の設定の autoStash・updateRefs は切る（やめたときに作業場を戻す reset が、載せ直しの間に書かれた字を消さないように。ほかの枝を動かさないように）
REBASE_OPTS = ["-c", "rerere.enabled=true", "-c", "rerere.autoUpdate=true", "-c", "core.editor=true",
               "-c", "rebase.autoStash=false", "-c", "rebase.updateRefs=false"]


def conflicted(cwd, runner=_default_runner):
    """ぶつかって解けていないファイルの並び（作業場の根からの道）。"""
    out = _git(cwd, ["diff", "--name-only", "--diff-filter=U"], runner)
    return [x for x in (out or "").splitlines() if x]


def rebase(cwd, onto, runner=_default_runner):
    """今の枝を onto の上に載せ直す（git rebase）。書く口。(載せ直せたか, 解けていないファイルの並び)。ぶつかったら途中のまま返す
    （rebase_continue か rebase_abort で終える）。"""
    p = runner(["git", "-C", cwd, *REBASE_OPTS, "rebase", "--quiet", onto])
    return (True, []) if p.returncode == 0 else (False, conflicted(cwd, runner))


def rebase_continue(cwd, runner=_default_runner):
    """途中の載せ直しを続ける（ぶつかりを解いて index に足した後）。書く口。返しは rebase と同じ。"""
    p = runner(["git", "-C", cwd, *REBASE_OPTS, "rebase", "--continue"])
    return (True, []) if p.returncode == 0 else (False, conflicted(cwd, runner))


def rebase_abort(cwd, runner=_default_runner):
    """途中の載せ直しをやめて、載せ直す前の枝に戻す。書く口。"""
    _must(["git", "-C", cwd, *REBASE_OPTS, "rebase", "--abort"], runner)   # rerere を有効にして、途中のぶつかりの記録も消させる


def rebasing(cwd, runner=_default_runner):
    """その作業場が載せ直しの途中か（.git の rebase-merge か rebase-apply が在る）。"""
    d = _git(cwd, ["rev-parse", "--git-dir"], runner)
    if not d:
        return False
    d = d if os.path.isabs(d) else os.path.join(cwd, d)
    return any(os.path.isdir(os.path.join(d, n)) for n in ("rebase-merge", "rebase-apply"))


def add_path(cwd, path, runner=_default_runner):
    """解いたファイルを index に足す。書く口。"""
    _must(["git", "-C", cwd, "add", "--", path], runner)


def push_rebased(cwd, branch, old, new, runner=_default_runner):
    """載せ直した枝を origin に出す（origin の枝が old のままのときだけ上書きする。old が空なら、origin に枝が無いときだけ作る。
    --force-with-lease）。書く口。"""
    _must(["git", "-C", cwd, "push", "--quiet", f"--force-with-lease=refs/heads/{branch}:{old}", "origin",
           f"{new}:refs/heads/{branch}"], runner)


def drop_remote(cwd, ref, runner=_default_runner):
    """origin の枝 ref を消す。書く口。もう無ければ何もしない。"""
    if _git(cwd, ["ls-remote", "--exit-code", "--heads", "origin", ref], runner) is None:
        return "absent"
    _must(["git", "-C", cwd, "push", "--quiet", "origin", "--delete", ref], runner)
    return "deleted"


def _holder(source, branch, runner):
    """その枝を開いている worktree の場所（無ければ None）。"""
    path = None
    for line in (_git(source, ["worktree", "list", "--porcelain"], runner) or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            return path
    return None


def advance_branch(source, branch, sha, runner=_default_runner):
    """手元の枝 branch を sha へ早送りだけする。書く口。current（もう同じ）・updated（進めた）・absent（手元に枝が無い）・
    local_only（手元の枝にしか無い commit が有るので動かさない）・dirty（枝を開いている worktree の書きかけが本流の変更とぶつかるので
    動かさない）のどれか。枝を開いている worktree が有れば、そこで git merge --ff-only を打つ（中身もそろえる。書きかけが本流の
    変更に触れなければ進む）。"""
    old = rev(source, f"refs/heads/{branch}", runner)
    if old is None:
        return "absent"
    if old == sha:
        return "current"
    if not _is_ancestor(source, old, sha, runner):
        return "local_only"
    holder = _holder(source, branch, runner)
    if holder is None:
        _must(["git", "-C", source, "update-ref", f"refs/heads/{branch}", sha, old], runner)
        return "updated"
    # 枝を開いている worktree に書きかけ（未コミットの変更・git に足していないファイル）が有っても、早送りを試す。git merge --ff-only は、
    # 本流の変更が書きかけのファイルに触れるときだけ何も変えずに断るので、触れない書きかけ（持ち主の日記など）は壊さずに進む（5d75df）
    # 利用者の設定の autoStash は切る（書きかけを退避して戻すときにぶつかると、印と stash が残る）。無視するファイルも上書きしない
    p = runner(["git", "-C", holder, "-c", "merge.autoStash=false", "merge", "--ff-only", "--no-overwrite-ignore", "--quiet", sha])
    return "updated" if p.returncode == 0 else "dirty"


def add_detached(source, path, sha, runner=_default_runner, lock=None):
    """枝に乗らない一時の worktree を path に sha で作る（取り込みのときに版を上げる commit を作る場所・機械の道具を走らせる場所）。
    lock を渡せば、作ると同時にその訳で鍵を掛ける（git worktree add --lock --reason。後から lock を打つのと違い、鍵の無い間が無い。
    2026-10-18 に git 2.50 で、作っている途中〔post-checkout のフックの中〕から訳の鍵が在るのを見た）。
    書く口。git の worktree add は、extensions.worktreeConfig が入っていると元の worktree の config.worktree を新しい worktree に
    写すので、source が部署（代表の clone の本社など）なら部署の属性 company.* も載り、一時の場所が同じ名前の部署に見える
    （2026-10-17 に my_notes で --call の間、段取りへの --ask が「名前が 2 つ以上ある」で止まった）。作ったらすぐ消す。git は中身を
    出す前に写すので、出し終えるまでは消せない。その間は部署の一覧の側が写しを数えない（tree.copied_from。2026-10-18、受付 596ed5）。
    extensions.worktreeConfig が入っていなければ config --worktree は共通の設定を指すので、そのときは触らない（写しも起きない）。"""
    _must(["git", "-C", source, "worktree", "add", "--quiet", "--detach", *(["--lock", "--reason", lock] if lock else []), path, sha],
          runner)
    if (_git(path, ["config", "--local", "--type=bool", "--get", "extensions.worktreeConfig"], runner) or "") != "true":
        return
    p = runner(["git", "-C", path, "config", "--worktree", "--remove-section", "company"])
    if p.returncode != 0 and worktree_attrs(path, runner):   # 節が無いとき（終了の値 128）は消す物が無い
        runner(["git", "-C", source, "worktree", "remove", "--force", "--force", path])   # 部署に見える場所を残さない
        raise GitError(f"git -C {path} config --worktree --remove-section company: {(p.stderr or p.stdout).strip()[:300]}")


def remove_detached(source, path, runner=_default_runner):
    """add_detached で作った一時の worktree を消す（中の変更ごと。鍵が掛かっていても。場所がもう無ければ git の記録だけを消す）。
    書く口。path は git worktree list の出す形（絶対のパス）で渡す。"""
    _must(["git", "-C", source, "worktree", "remove", "--force", "--force", path], runner)


def _unquote(text):
    """git が引用符で囲んで出した字（日本語や改行を含むと C の書き方で 8 進に直す。core.quotePath）を元に戻す。囲まれていなければそのまま。"""
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return text
    return codecs.escape_decode(text[1:-1].encode("ascii", "backslashreplace"))[0].decode("utf-8", "replace")


def listed_worktrees(source, runner=_default_runner):
    """source のリポジトリの worktree の並び（git worktree list --porcelain。元の clone 自身も入る）。1 件は {path, head, branch, locked}。
    head は先頭の commit、branch は枝の名前（枝に居なければ None）、locked は鍵の訳（鍵が無ければ None、訳の無い鍵は空の字）。
    読めなければ空。"""
    out, cur = [], None
    for line in (_git(source, ["worktree", "list", "--porcelain"], runner) or "").splitlines():
        if line.startswith("worktree "):
            cur = {"path": _unquote(line[len("worktree "):]), "head": None, "branch": None, "locked": None}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/"):]
        elif line == "locked" or line.startswith("locked "):
            cur["locked"] = _unquote(line[len("locked "):]) if line.startswith("locked ") else ""
    return out


def on_some_ref(source, sha, prefixes=("refs/heads", "refs/remotes", "refs/company"), runner=_default_runner):
    """sha が、prefixes の下のどれかの ref から辿れるか（その commit がほかに残っているか）。読めなければ偽（残す側に倒す）。"""
    return bool(_git(source, ["for-each-ref", "--count=1", "--format=%(refname)", f"--contains={sha}", *prefixes], runner))


def keep_commit(source, ref, sha, runner=_default_runner):
    """ref を sha に向けて書く（どの枝にも無い commit を、場所を消した後も辿れるように残す）。書く口。"""
    _must(["git", "-C", source, "update-ref", ref, sha], runner)


def commit_all(cwd, message, runner=_default_runner):
    """cwd の変更を全部足して commit し、その commit の id を返す。書く口。"""
    _must(["git", "-C", cwd, "add", "--all"], runner)
    _must(["git", "-C", cwd, "commit", "--quiet", "-m", message], runner)
    return _git(cwd, ["rev-parse", "HEAD"], runner)
