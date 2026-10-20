"""--land の判断の筋を本物の git を起動せずに試すための、git の偽物（ports.git に渡す。gitx と同じ名前の口を持つ）。

commit・ブランチ・origin・worktree・部署の属性を辞書で持つ。持つのは --land（landing.py・nodes/land.py）が判断に使う口だけで、
git の出す字の形（diff -U0・blame・worktree list など）と、git そのものの振る舞い（リベース・push の断り・作業ツリーの書きかけ）は
test_land の本物の git の試験（境目の試験）が確かめる。偽物の振る舞いは、その境目の試験が確かめた gitx の返しに合わせる。
"""

import hashlib
import os
import pathlib

import gitx


class FakeGit:
    GitError = gitx.GitError
    AttrError = gitx.AttrError
    OWN_ID = gitx.OWN_ID

    def __init__(self, source, files):
        self.source = os.path.realpath(source)
        self.commits = {}   # id → {"parent", "files", "subject"}
        root = self._new(None, dict(files), "init")
        self.origin = {"main": root}      # origin のブランチ
        self.tracking = {"main": root}    # 手元の refs/remotes/origin/*
        self.local = {"main": root}       # 手元の refs/heads/*（worktree の間で共有）
        self.heads = {self.source: "main"}   # worktree の場所 → 開いているブランチ
        self.attrs = {}      # worktree の場所 → 部署の属性 company.*
        self.excludes = set()
        self.dirty = set()   # 未コミットの変更が有る場所
        self.drafts = {}     # 場所 → 書きかけのファイルの名前の集まり（advance_branch が「dirty」を返すかを決める）
        self.rebases = {}    # リベースの途中の場所 → (ブランチ, 元の先頭, 解けていないファイル)

    # 試験が世界を作る口

    def _new(self, parent, files, subject):
        sha = hashlib.sha1(f"{len(self.commits)} {parent} {subject}".encode()).hexdigest()
        self.commits[sha] = {"parent": parent, "files": files, "subject": subject}
        return sha

    def add_worktree(self, path, branch, start):
        path = os.path.realpath(path)
        self.local[branch] = self._resolve(self.source, start)
        self.heads[path] = branch
        return path

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
            return self.local.get(self.heads.get(cwd))
        for prefix, table in (("refs/heads/", self.local), ("refs/remotes/origin/", self.tracking), ("origin/", self.tracking)):
            if ref.startswith(prefix):
                return table.get(ref[len(prefix):])
        if ref in self.commits:
            return ref
        return self.local.get(ref)

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

    def origin_head(self, cwd):
        return "origin/main"

    def file_at(self, cwd, commit, path):
        sha = self._resolve(cwd, commit)
        return self.commits[sha]["files"].get(path) if sha else None

    def common_dir(self, cwd):
        d = os.path.join(self.source, ".git")
        os.makedirs(d, exist_ok=True)
        return d

    def untracked(self, cwd):
        return set()

    def is_clean(self, cwd):
        return os.path.realpath(cwd) not in self.dirty

    def worktree_attrs(self, cwd, former=True, copies=False):
        return dict(self.attrs.get(os.path.realpath(cwd), {}))

    def worktree_id(self, cwd):
        return os.path.basename(cwd)

    # 書く口

    def exclude(self, source, pattern):
        if pattern in self.excludes:
            return "already"
        self.excludes.add(pattern)
        return "added"

    def enable_worktree_config(self, source):
        pass

    def drop_copied_attrs(self, cwd):
        return False

    def set_worktree_attr(self, cwd, name, value):
        self.attrs.setdefault(os.path.realpath(cwd), {})[name] = value

    def unset_worktree_attr(self, cwd, name):
        self.attrs.get(os.path.realpath(cwd), {}).pop(name, None)

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
        holder = next((p for p, b in self.heads.items() if b == branch), None)
        a, b = self.commits[old]["files"], self.commits[sha]["files"]
        if self.drafts.get(holder, set()) & {f for f in {*a, *b} if a.get(f) != b.get(f)}:
            return "dirty"
        self.local[branch] = sha
        return "updated"

    def rebase(self, cwd, onto):
        """git の 3 方向のマージと同じ決め方で、ブランチの commit を onto の上に 1 つずつ載せ直す。ぶつかれば途中のまま返す。"""
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


def materialize(path, files):
    """場所 path に files の中身を書く（--land がファイルとして読む物。ゲートの CI の定義〔land.ci_on〕など）。"""
    for rel, text in files.items():
        p = pathlib.Path(path, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
