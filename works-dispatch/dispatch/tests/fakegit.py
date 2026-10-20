"""dispatch の判断の筋を本物の git を起動せずに試すための、git の偽物（ports.git や、g を受け取るノードに渡す。gitx と同じ名前の口を持つ）。

commit・ブランチ・origin・worktree・部署の属性を辞書で持つ。持つのは --land（landing.py・nodes/land.py）と、部署の流れ（--ask・--deliver・
--task・--move・--retire など）が判断に使う口だけで、git の出す字の形（diff -U0・blame・worktree list・config --show-origin など）と、git
そのものの振る舞い（リベース・push の断り・作業ツリーの書きかけ・worktree add が属性を写すこと）は、本物の git の試験（境目の試験。
test_land の GitBoundary・test_ports の GitWorktree・test_company の Attrs など）が確かめる。偽物の振る舞いは、その境目の試験が確かめた
gitx の返しに合わせる。読み方の決まり（写しの属性を空と読む・前の版の寿命の読み替え）は gitx.shape_attrs をそのまま使う。
場所（元の clone と worktree）は本物のフォルダを作る（受付箱など、製品のコードがファイルとして書く物を置く）。共通の .git と worktree の
管理の場所（.git/worktrees/<id>）もフォルダだけ作り、git の中身は置かない。
偽物で書かない試験: ぶつかりはファイルの単位で決める（本物の git は同じファイルの別の hunk ならマージする）ので、同じファイルの
別の行を両側で変える試験。commit とリベースは作業ツリーのファイルを書き換えない（--land が作業ツリーから読む CI の定義や
CHANGELOG は materialize で置く）ので、リベースで作業ツリーのファイルが替わることに頼る試験。どちらも本物の git の試験で書く。
"""

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
import traceback
from unittest import mock

import gitx


class FakeGit:
    GitError = gitx.GitError
    AttrError = gitx.AttrError
    OWN_ID = gitx.OWN_ID
    MAIN_ID = gitx.MAIN_ID
    PERSISTENT, EPHEMERAL = gitx.PERSISTENT, gitx.EPHEMERAL
    FORMER_RESIDENCY = gitx.FORMER_RESIDENCY
    CONFIG_TRIES, CONFIG_PAUSE = gitx.CONFIG_TRIES, gitx.CONFIG_PAUSE
    # git を起動しない関数はそのまま使う
    root_of = staticmethod(gitx.root_of)
    lifecycle_attrs = staticmethod(gitx.lifecycle_attrs)
    former_names = staticmethod(gitx.former_names)

    def __init__(self, source, files, url=None, branches=()):
        """source は元の clone の場所、files は最初の commit の中身、url は origin の URL（origin_repo の元。既定は <source の親>/o/r.git、空なら origin が無い）、
        branches は origin に最初の commit で置くほかのブランチの名前。"""
        self.source = os.path.realpath(source)
        os.makedirs(os.path.join(self.source, ".git"), exist_ok=True)
        self.url = os.path.join(os.path.dirname(self.source), "o", "r.git") if url is None else url
        self.commits = {}   # id → {"parent", "files", "subject"}
        root = self._new(None, dict(files), "init")
        self.origin = {"main": root, **{b: root for b in branches}}      # origin のブランチ
        self.tracking = dict(self.origin)    # 手元の refs/remotes/origin/*
        self.local = {"main": root}       # 手元の refs/heads/*（worktree の間で共有）
        self.heads = {self.source: "main"}   # worktree の場所 → 開いているブランチ（ブランチに居なければ None）
        self.detached = {}   # ブランチに居ない worktree の場所 → 先頭の commit
        self.ids = {self.source: gitx.MAIN_ID}   # worktree の場所 → worktree の id（管理の場所 .git/worktrees/<id> の <id>）
        self.locks = {}      # worktree の場所 → 鍵の訳
        self.attrs = {}      # worktree の場所 → 部署の属性 company.*（書いた worktree の id OWN_ID も、読む前の形で持つ）
        self.worktree_config = False   # 元の clone に extensions.worktreeConfig が入っているか
        self.stashes = []    # stash の記録（「WIP on <ブランチ>: …」の形の字）
        self.ignored = {}    # 場所 → .gitignore に当たるファイルの並び
        self.has_origin_head = True    # 手元の origin/HEAD が在るか
        self.excludes = set()
        self.dirty = set()   # 未コミットの変更が有る場所
        self.rebases = {}    # リベースの途中の場所 → (ブランチ, 元の先頭, 解けていないファイル)

    # 試験が世界を作る口

    def _new(self, parent, files, subject):
        sha = hashlib.sha1(f"{len(self.commits)} {parent} {subject}".encode()).hexdigest()
        self.commits[sha] = {"parent": parent, "files": files, "subject": subject}
        return sha

    def add_worktree(self, path, branch, start=None, creator=None):
        """git -C <creator> worktree add [-b branch] path start の形。branch が手元に在れば start は要らない。作った場所を返す。
        本物の git と同じく、extensions.worktreeConfig が入っていれば、作った元の worktree（creator。既定は元の clone）の属性を写す
        （読む側は、書いた worktree の id が違うので写しと見て空と読む）。"""
        path = os.path.realpath(path)
        if path in self.heads:
            raise gitx.GitError(f"fatal: '{path}' already exists")
        if branch in self.heads.values():
            raise gitx.GitError(f"fatal: '{branch}' is already used by worktree")
        if branch not in self.local:
            self.local[branch] = self._resolve(self.source, start)
        self.heads[path] = branch
        self._admin(path)
        os.makedirs(path, exist_ok=True)
        if self.worktree_config:
            got = self.attrs.get(os.path.realpath(creator or self.source))
            if got:
                self.attrs[path] = dict(got)
        return path

    def _admin(self, path):
        """linked の worktree の id を決め、管理の場所のフォルダと、場所の .git のファイルを作る（同じ名前が在れば本物の git と同じく数字を足す）。"""
        base, n = os.path.basename(path), 0
        taken = set(self.ids.values())
        wid = base
        while wid in taken:
            n += 1
            wid = f"{base}{n}"
        self.ids[path] = wid
        os.makedirs(os.path.join(self.source, ".git", "worktrees", wid), exist_ok=True)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, ".git"), "w", encoding="utf-8") as f:   # 本物と同じく場所の .git のファイル（git を呼ばずに場所のルートを決める windows.place_of が見る）
            f.write(f"gitdir: {os.path.join(self.source, '.git', 'worktrees', wid)}\n")

    def remove_worktree(self, path, force=False):
        """git worktree remove。書きかけが有れば（force でなければ）断る。場所のフォルダも消す。"""
        path = os.path.realpath(path)
        if path not in self.heads or path == self.source:
            raise gitx.GitError(f"fatal: '{path}' is not a working tree")
        if not force and path in self.dirty:
            raise gitx.GitError(f"fatal: '{path}' contains modified or untracked files, use --force to delete it")
        self._forget(path)
        shutil.rmtree(path, ignore_errors=True)

    def _forget(self, path):
        wid = self.ids.pop(path, None)
        for table in (self.heads, self.detached, self.locks, self.attrs):
            table.pop(path, None)
        self.dirty.discard(path)
        if wid:
            shutil.rmtree(os.path.join(self.source, ".git", "worktrees", wid), ignore_errors=True)

    def commit(self, path, changes, subject):
        """場所 path の今のブランチに、changes（名前 → 中身。None は消す）を足した commit を作る。"""
        branch = self.heads[os.path.realpath(path)]
        parent = self.local[branch]
        files = {**self.commits[parent]["files"], **changes}
        self.local[branch] = self._new(parent, {k: v for k, v in files.items() if v is not None}, subject)
        return self.local[branch]

    def push_origin(self, branch, changes, subject):
        """ほかの clone が origin の branch に commit を足した形（手元の ref は動かさない）。"""
        parent = self.origin[branch]
        files = {**self.commits[parent]["files"], **changes}
        self.origin[branch] = self._new(parent, {k: v for k, v in files.items() if v is not None}, subject)
        return self.origin[branch]

    def files(self, ref, cwd=None):
        return dict(self.commits[self._resolve(cwd or self.source, ref)]["files"])

    def snapshot(self):
        return (dict(self.origin), dict(self.tracking), dict(self.local), dict(self.heads),
                {k: dict(v) for k, v in self.attrs.items()})

    # 読む口

    def _resolve(self, cwd, ref):
        cwd = os.path.realpath(cwd)
        if ref == "HEAD":
            place = self._place(cwd)
            return self.detached.get(place) or self.local.get(self.heads.get(place))
        for prefix, table in (("refs/heads/", self.local), ("refs/remotes/origin/", self.tracking), ("origin/", self.tracking)):
            if ref.startswith(prefix):
                return table.get(ref[len(prefix):])
        if ref in self.commits:   # まだ fetch していない commit の id は、本物の rev-parse と同じく引けない
            return ref if ref in self._reachable() else None
        return self.local.get(ref)

    def _reachable(self):
        return {s for sha in (*self.local.values(), *self.tracking.values()) for s in self._line(sha)}

    def _line(self, sha):
        out = []
        while sha:
            out.append(sha)
            sha = self.commits[sha]["parent"]
        return out

    def rev(self, cwd, ref):
        return self._resolve(cwd, ref)

    def is_ancestor(self, cwd, a, b):
        a, b = self._resolve(cwd, a), self._resolve(cwd, b)
        return bool(a and b) and a in self._line(b)

    def remote_rev(self, cwd, branch):
        return self.origin.get(branch)

    def subjects(self, cwd, a, b):
        seen = set(self._line(self._resolve(cwd, a)))
        return [f"{s[:7]} {self.commits[s]['subject']}" for s in self._line(self._resolve(cwd, b)) if s not in seen]

    def forked_paths(self, cwd, base, branch):
        b, h = self._resolve(cwd, base), self._resolve(cwd, branch)
        if not (b and h):
            raise gitx.GitError(f"{base}...{branch} を引けない")
        seen = set(self._line(b))
        fork = next((s for s in self._line(h) if s in seen), None)
        old, new = (self.commits[fork]["files"] if fork else {}), self.commits[h]["files"]
        return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))

    def origin_head(self, cwd):
        return "origin/main" if self.has_origin_head and self._place(cwd) else None

    def default_branch(self, cwd):
        if self.has_origin_head or "main" in self.origin:
            return "main"
        raise gitx.GitError(f"{cwd}: origin の既定のブランチを決められない")

    def file_at(self, cwd, commit, path):
        sha = self._resolve(cwd, commit)
        return self.commits[sha]["files"].get(path) if sha else None

    def _place(self, cwd):
        """cwd を含む worktree の場所（一番深い物）。どの worktree にも入っていなければ None（git でない場所）。"""
        if not cwd:
            return None
        cwd = os.path.realpath(cwd)
        best = None
        for p in self.heads:
            if (cwd == p or cwd.startswith(p.rstrip(os.sep) + os.sep)) and (best is None or len(p) > len(best)):
                best = p
        return best

    def common_dir(self, cwd):
        if self._place(cwd) is None:
            return None
        d = os.path.join(self.source, ".git")
        os.makedirs(d, exist_ok=True)
        return d

    def git_dir(self, cwd):
        place = self._place(cwd)
        if place is None:
            return None
        if place == self.source:
            return self.common_dir(cwd)
        d = os.path.join(self.source, ".git", "worktrees", self.ids[place])
        os.makedirs(d, exist_ok=True)
        return d

    def toplevel(self, cwd):
        return self._place(cwd)

    def is_main_worktree(self, cwd):
        place = self._place(cwd)
        return None if place is None else place == self.source

    def branch(self, cwd):
        place = self._place(cwd)
        return self.heads.get(place) if place else None

    def head_sha(self, cwd):
        place = self._place(cwd)
        if place is None:
            return None
        return self.detached.get(place) or self.local.get(self.heads.get(place))

    def origin_url(self, cwd):
        return self.url if self._place(cwd) and self.url else None

    def origin_repo(self, cwd):
        url = self.origin_url(cwd)
        m = gitx._REPO.search(url) if url else None
        return f"{m.group(1)}/{m.group(2)}" if m else None

    def untracked(self, cwd):
        return set()

    def ignored_files(self, cwd):
        return sorted(self.ignored.get(self._place(cwd), []))

    def is_clean(self, cwd):
        place = self._place(cwd)
        return place is not None and place not in self.dirty

    def stashed(self, cwd, branch):
        return any(x.startswith((f"WIP on {branch}: ", f"On {branch}: ")) for x in self.stashes)

    def unpushed(self, cwd, landed=None):
        """HEAD の上に、どの origin のブランチ（手元の控え）にも入っていない commit が有るか、今のブランチの stash が有るか。"""
        head = self.head_sha(cwd)
        if head is None:
            return True
        remote = {s for sha in self.tracking.values() for s in self._line(sha)}
        if head not in remote and not (landed and landed()):
            return True
        return self.stashed(cwd, self.branch(cwd) or "(no branch)")

    def is_merged(self, cwd, target):
        return self.is_ancestor(cwd, "HEAD", target)

    def worktree_attrs(self, cwd, former=True, copies=False):
        place = self._place(cwd)
        if place is None:
            return {}
        return gitx.shape_attrs(self.attrs.get(place, {}), self.ids.get(place) if self.attrs.get(place) else None,
                                former=former, copies=copies)

    def worktree_id(self, cwd):
        place = self._place(cwd)
        return self.ids.get(place) if place else None

    def listed_worktrees(self, source):
        out = []
        for p in sorted(self.heads, key=lambda p: (p != self.source, p)):
            out.append({"path": p, "head": self.head_sha(p), "branch": self.heads[p], "locked": self.locks.get(p)})
        return out

    # 書く口

    def exclude(self, source, pattern):
        if pattern in self.excludes:
            return "already"
        self.excludes.add(pattern)
        return "added"

    def enable_worktree_config(self, source):
        if self.worktree_config:
            return "already"
        self.worktree_config = True
        return "enabled"

    def _attr_place(self, cwd):
        place = self._place(cwd)
        if place is None:
            raise gitx.GitError(f"fatal: not in a git directory: {cwd}")
        return place

    def drop_copied_attrs(self, cwd):
        place = self._attr_place(cwd)
        got = self.attrs.get(place) or {}
        if not gitx._copy_of(got, self.ids[place] if got else None):
            return False
        self.attrs.pop(place, None)
        return True

    def set_worktree_attr(self, cwd, name, value):
        self.attrs.setdefault(self._attr_place(cwd), {})[name.lower()] = value

    def unset_worktree_attr(self, cwd, name):
        self.attrs.get(self._attr_place(cwd), {}).pop(name.lower(), None)

    def fetch(self, cwd, branch):
        if branch not in self.origin:
            raise gitx.GitError(f"fatal: couldn't find remote ref {branch}")
        self.tracking[branch] = self.origin[branch]

    def push(self, cwd, sha, ref, force=False):
        sha = self._resolve(cwd, sha)
        if not force and ref in self.origin and self.origin[ref] not in self._line(sha):
            raise gitx.GitError(f"! [rejected] {ref} (non-fast-forward)")
        self.origin[ref] = self.tracking[ref] = sha   # git の push は手元の origin/<ref> も書き換える

    def push_rebased(self, cwd, branch, old, new):
        if (self.origin.get(branch) or "") != old:
            raise gitx.GitError(f"! [rejected] {branch} (stale info)")
        self.origin[branch] = self.tracking[branch] = new

    def drop_remote(self, cwd, ref):
        if ref not in self.origin:
            return "absent"
        del self.origin[ref]
        self.tracking.pop(ref, None)
        return "deleted"

    def advance_branch(self, source, branch, sha):
        old = self.local.get(branch)
        if old is None:
            return "absent"
        if old == sha:
            return "current"
        if old not in self._line(sha):
            return "local_only"
        # 書きかけとぶつかる「dirty」は返さない（代表の clone の書きかけは本物の git の試験で確かめる）
        self.local[branch] = sha
        return "updated"

    def fast_forward_to(self, cwd, ref):
        """今のブランチを ref の先頭まで fast-forward だけする（current・updated・local_only）。未コミットの変更と重なって git が断る形は
        持たない（本物の git の試験で確かめる）。"""
        target, head = self._resolve(cwd, ref), self._resolve(cwd, "HEAD")
        if target is None:
            raise gitx.GitError(f"{cwd}: {ref} が無い")
        if target in self._line(head):
            return "current"
        if head not in self._line(target):
            return "local_only"
        self.local[self.heads[self._place(cwd)]] = target
        return "updated"

    def fast_forward(self, cwd, branch):
        """手元のブランチが origin/<branch> の祖先なら fast-forward だけする（current・updated・local_only）。"""
        target, head = self.tracking.get(branch), self._resolve(cwd, "HEAD")
        if head == target:
            return "current"
        if target is None or head not in self._line(target):   # 手元が先に進んでいる・分かれた・origin/<branch> が読めない
            return "local_only"
        self.local[self.heads[self._place(cwd)]] = target
        return "updated"

    def reset_keep(self, cwd, branch):
        """origin/<branch> へ `git reset --keep` で揃える。未コミットの変更と重なって git が断る形は持たない（本物の git の試験で確かめる）。"""
        if branch not in self.tracking:
            raise gitx.GitError(f"{cwd}: origin/{branch} が無い")
        self.local[self.heads[self._place(cwd)]] = self.tracking[branch]

    def changed_paths(self, cwd, since, path):
        """since から HEAD までに中身の替わったファイル（path の下。cwd はリポジトリのルートと見る）。"""
        a, b = (self.commits[self._resolve(cwd, r)]["files"] for r in (since, "HEAD"))
        prefix = "" if path in ("", ".") else path.rstrip("/") + "/"
        return sorted(k for k in {*a, *b} if a.get(k) != b.get(k) and k.startswith(prefix))

    def rebase(self, cwd, onto):
        """git の 3 方向のマージと同じ決め方で、ブランチの commit を 1 つずつ onto の上へリベースする。ぶつかれば途中のまま返す。"""
        cwd = os.path.realpath(cwd)
        branch = self.heads[cwd]
        head, cur = self.local[branch], self._resolve(cwd, onto)
        base = set(self._line(cur))
        own = [s for s in self._line(head) if s not in base][::-1]
        for sha in own:
            before, after, now = (self.commits[self.commits[sha]["parent"]]["files"], self.commits[sha]["files"],
                                  self.commits[cur]["files"])
            changed = {f for f in {*before, *after} if before.get(f) != after.get(f)}
            clash = sorted(f for f in changed if now.get(f) != before.get(f) and now.get(f) != after.get(f))
            if clash:
                self.rebases[cwd] = (branch, head, clash)
                return False, clash
            files = {**now, **{f: after.get(f) for f in changed}}
            cur = self._new(cur, {k: v for k, v in files.items() if v is not None}, self.commits[sha]["subject"])
        self.local[branch] = cur
        return True, []

    def rebase_continue(self, cwd):
        raise gitx.GitError("偽物の git はぶつかりを解いた後のリベースを続けない（本物の git の試験で確かめる）")

    def rebase_abort(self, cwd):
        branch, head, _ = self.rebases.pop(os.path.realpath(cwd))
        self.local[branch] = head

    def rebasing(self, cwd):
        return os.path.realpath(cwd) in self.rebases

    def conflicted(self, cwd):
        return list(self.rebases.get(os.path.realpath(cwd), (None, None, []))[2])

    def add_path(self, cwd, path):
        pass

    def add_detached(self, source, path, sha, lock=None):
        """ブランチに乗らない一時の worktree。commit の中身を本物のファイルとして出す（ツールの台本を走らせる場所）。"""
        path = os.path.realpath(path)
        sha = self._resolve(source, sha)
        self.heads[path] = None
        self.detached[path] = sha
        self._admin(path)
        if lock is not None:
            self.locks[path] = lock
        os.makedirs(path, exist_ok=True)
        materialize(path, self.commits[sha]["files"])
        if self.worktree_config and self.attrs.get(self.source):   # 本物と同じく元の clone の属性を写す（add_worktree と同じ）
            self.attrs[path] = dict(self.attrs[self.source])

    def remove_detached(self, source, path):
        path = os.path.realpath(path)
        if path not in self.heads:
            raise gitx.GitError(f"fatal: '{path}' is not a working tree")
        self._forget(path)
        shutil.rmtree(path, ignore_errors=True)

    def keep_commit(self, source, ref, sha):
        self.kept = {**getattr(self, "kept", {}), ref: sha}

    def on_some_ref(self, source, sha, prefixes=("refs/heads", "refs/remotes", "refs/company")):
        refs = [*self.local.values(), *self.tracking.values(), *getattr(self, "kept", {}).values()]
        return any(sha in self._line(r) for r in refs if r)

    def delete_branch(self, source, branch, expected_sha):
        now = self.local.get(branch)
        if not now:
            return "absent"
        if now != expected_sha:
            return "moved"
        if branch in self.heads.values():
            raise gitx.GitError(f"error: cannot delete branch '{branch}' used by worktree")
        del self.local[branch]
        return "deleted"


class Repos:
    """いくつかのリポジトリの偽物（FakeGit）を 1 つの口にまとめる。場所を取る口は、その場所を持つリポジトリの偽物へ渡す
    （どれも持たなければ最初の物。git でない場所の答えを返す）。"""

    def __init__(self, *gits):
        self.gits = list(gits)

    def of(self, cwd):
        return next((g for g in self.gits if g._place(cwd) is not None), self.gits[0])

    def __getattr__(self, name):
        got = getattr(self.gits[0], name)
        if not callable(got) or isinstance(got, type) or name in ("root_of", "lifecycle_attrs", "former_names"):
            return got
        return lambda cwd, *a, **k: getattr(self.of(cwd), name)(cwd, *a, **k)


def materialize(path, files):
    """場所 path に files の中身を書く（--land がファイルとして読む物。ゲートの CI の定義〔land.ci_on〕など）。"""
    for rel, text in files.items():
        p = pathlib.Path(path, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


BRANCHES = [f"feat/{n}" for n in range(1, 10)]


def world():
    """test_provision.make_world と同じ形の世界を偽物の git の上に作る。(git の偽物, 元の clone のパス, worktree の置き場)。
    origin には main と feat/1〜feat/9 が在る（どれも最初の commit。.gitignore を持つ）。元の clone は main に居て、.gitignore に
    当たるファイル frontend/.env.local が本物のファイルとして在る（写すファイルの試験が読む）。"""
    t = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-fake-")).resolve()
    src = t / "src"
    g = FakeGit(str(src), {".gitignore": "frontend/.env.local\n"}, url=str(t / "o" / "r.git"), branches=BRANCHES)
    materialize(g.source, {".gitignore": "frontend/.env.local\n", "frontend/.env.local": "SECRET=1\n"})
    g.ignored[g.source] = ["frontend/.env.local"]
    root = t / "worktrees"
    root.mkdir()
    return g, g.source, str(root)


class _NoGit:
    """gitx の subprocess の代わり。git を起動しようとしたら試験を赤にする（偽物の git の世界で、製品のコードが ports.git を通らずに
    gitx を直に呼んだ所を見つける）。git でないコマンドは本物の subprocess に渡す。"""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def run(self, argv, *args, **kwargs):
        if argv and os.path.basename(str(argv[0])) == "git":
            caller = next((f for f in reversed(traceback.extract_stack()[:-1]) if not f.filename.endswith(("gitx.py", "fakegit.py"))), None)
            where = f"（{os.path.basename(caller.filename)}:{caller.lineno} {caller.name}）" if caller else ""
            raise AssertionError(f"偽物の git の世界で本物の git を起動した{where}: {' '.join(map(str, argv[:6]))}")
        return self._real.run(argv, *args, **kwargs)


def forbid_real_git(case):
    """試験（unittest.TestCase）の間、gitx が git を起動したら赤にする。"""
    patcher = mock.patch.object(gitx, "subprocess", _NoGit(subprocess))
    patcher.start()
    case.addCleanup(patcher.stop)


def wire(case, g, *modules):
    """試験（unittest.TestCase）の間、modules（フックなど単独の入口のモジュール。ports.git を持たず、モジュールの gitx を git の口に使う）
    の gitx を git の偽物 g に替え、本物の git の起動を赤にする（forbid_real_git）。"""
    forbid_real_git(case)
    for m in modules:
        patcher = mock.patch.object(m, "gitx", g)
        patcher.start()
        case.addCleanup(patcher.stop)
