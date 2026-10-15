"""provision ノード: 枝ごとの作業場（元の clone の git worktree と herdr の作業場）を、無ければ作り、有れば使い直す（設計書 3 節）。

git は本物を使う。一時のフォルダに、GitHub に見立てた裸のリポジトリ `<tmp>/o/r.git` と、それを origin にした元の clone を作る。
herdr だけ偽物にする。偽物の worktree の口は、本物の `git worktree` で作り・並べ・消し、herdr アダプタと同じ形（場所の言葉）で返す
（herdr アダプタが herdr の実物の JSON をその形に読むことは、test_ports の試験が実物の写しで縛る）。
"""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
import gitx
import herdr as real_herdr
from config import Repo
from nodes import provision


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


BRANCHES = [f"feat/{n}" for n in range(1, 10)]


_TEMPLATE = []


def _template():
    """make_world の元の形を 1 度だけ作る（git を何度も起こさないため。各試験はこれを写して使う）。"""
    if _TEMPLATE:
        return _TEMPLATE[0]
    t = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-tmpl-")).resolve()
    remote = t / "o" / "r.git"
    remote.parent.mkdir()
    git("init", "--bare", "-q", "-b", "main", str(remote))
    src = t / "src"
    git("clone", "-q", str(remote), str(src))
    git("-C", str(src), "symbolic-ref", "HEAD", "refs/heads/main")
    (src / ".gitignore").write_text("frontend/.env.local\n")
    git("-C", str(src), "add", ".gitignore")
    git("-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git("-C", str(src), "push", "-q", "origin", "HEAD:refs/heads/main", *[f"HEAD:refs/heads/{b}" for b in BRANCHES])
    git("-C", str(src), "fetch", "-q", "origin")
    (src / "frontend").mkdir()
    (src / "frontend" / ".env.local").write_text("SECRET=1\n")
    _TEMPLATE.append(t)
    return t


def make_world():
    """(元の clone のパス, worktree の置き場) を返す。origin には main と feat/1〜feat/9 が在る（どれも最初の commit。.gitignore を持つ）。
    元の clone は main に居て、追跡しないファイル frontend/.env.local がある。"""
    t = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-prov-")).resolve()
    shutil.copytree(_template(), t, dirs_exist_ok=True, symlinks=True)
    src = t / "src"
    git("-C", str(src), "remote", "set-url", "origin", str(t / "o" / "r.git"))
    root = t / "worktrees"
    root.mkdir()
    return str(src), str(root)


def advance(src, branch):
    """origin の枝に、手元に無い commit を 1 つ積む（ほかの人が push した形）。積んだ commit を返す。"""
    git("-C", src, "fetch", "-q", "origin", branch)
    sha = git("-C", src, "-c", "user.name=o", "-c", "user.email=o@o", "commit-tree", f"origin/{branch}^{{tree}}",
              "-p", f"origin/{branch}", "-m", "theirs")
    git("-C", src, "push", "-q", "origin", f"{sha}:refs/heads/{branch}")
    return sha


def _same(a, b):
    return os.path.realpath(a or "") == os.path.realpath(b or "")


class WorktreeHerdr:
    """herdr アダプタの場所の口と作業場の口の偽物。worktree は本物の git worktree で作り、作業場とペインは手元の表で持つ。"""
    HerdrError = real_herdr.HerdrError

    def __init__(self, root=None):
        self.root = root or str(pathlib.Path(tempfile.mkdtemp(prefix="dispatch-wt-")).resolve())
        self._panes = []
        self._n = 0
        self.writes = []

    # 作業場とペイン
    def panes(self):
        return list(self._panes)

    def open_at(self, path, agent=None):
        """試験の下ごしらえ: その場所に作業場を 1 つ開く（herdr の口ではない。writes に残さない）。"""
        pane = {"pane_id": f"P{self._n}", "workspace_id": f"W{self._n}", "cwd": path, "agent": agent}
        self._n += 1
        self._panes.append(pane)
        return pane

    def _ws(self, path):
        return next((p for p in self._panes if _same(p["cwd"], path)), None)

    def close_workspace(self, workspace_id):
        self.writes.append(("close_workspace", workspace_id))
        self._panes = [p for p in self._panes if p["workspace_id"] != workspace_id]

    # 場所（git worktree）
    def worktrees(self, source):
        out, cur = [], None
        for line in git("-C", source, "worktree", "list", "--porcelain").splitlines() + [""]:
            if line.startswith("worktree "):
                cur = {"path": line[len("worktree "):], "branch": None, "prunable": False}
            elif line.startswith("branch refs/heads/") and cur:
                cur["branch"] = line[len("branch refs/heads/"):]
            elif line.startswith("prunable") and cur:
                cur["prunable"] = True
            elif not line and cur:
                cur["linked"] = bool(out)
                ws = self._ws(cur["path"])
                cur["workspace"] = ws["workspace_id"] if ws else None
                out.append(cur)
                cur = None
        return out

    def _open(self, path):
        ws = self._ws(path) or self.open_at(path)
        return {"path": path, "branch": gitx.branch(path), "workspace_id": ws["workspace_id"], "pane_id": ws["pane_id"]}

    def create_worktree(self, source, branch, base, label):
        self.writes.append(("create_worktree", branch, label))
        path = os.path.join(self.root, re.sub(r"[^A-Za-z0-9._-]", "-", branch))
        has = subprocess.run(["git", "-C", source, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                             capture_output=True).returncode == 0
        p = subprocess.run(["git", "-C", source, "worktree", "add", "-q", *([path, branch] if has else ["-b", branch, path, base])],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise real_herdr.HerdrError(["herdr", "worktree", "create"], "worktree_create_failed")
        return self._open(path)

    def open_worktree(self, source, path, label):
        self.writes.append(("open_worktree", path, label))
        if not any(_same(w["path"], path) for w in self.worktrees(source)):
            raise real_herdr.HerdrError(["herdr", "worktree", "open"], "worktree_not_found")
        return self._open(path)

    def remove_worktree(self, source, path, label):
        self.writes.append(("remove_worktree", path))
        ws = self._open(path)["workspace_id"]
        p = subprocess.run(["git", "-C", source, "worktree", "remove", path], capture_output=True, text=True)
        if p.returncode != 0:
            raise real_herdr.HerdrError(["herdr", "worktree", "remove"], "dirty_worktree_requires_force")
        self._panes = [x for x in self._panes if x["workspace_id"] != ws]
        return {"path": path, "workspace_id": ws}


class Prepare(unittest.TestCase):
    def setUp(self):
        self.src, self.root = make_world()
        self.repo = Repo("o/r", "second", self.src, ("frontend/.env.local", "deploy/missing.yaml"))
        self.row = {"number": 7, "head": "feat/7"}

    def test_label_starts_with_the_repo_name(self):
        # herdr は数字で始まる表示名を受け付けなかった、という報告がある（設計書 3 節）。issue の番号で始まる枝でも数字で始めない
        self.assertEqual(provision.label(self.repo, "12-fix-login"), "r/12-fix-login")

    def test_creates_a_worktree_of_the_branch_copies_files_and_opens_it(self):
        h = WorktreeHerdr(self.root)
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertTrue(got["created"])
        path = got["path"]
        self.assertEqual(gitx.branch(path), "feat/7")
        self.assertEqual(gitx.origin_repo(path), "o/r")
        self.assertEqual((pathlib.Path(path) / "frontend" / ".env.local").read_text(), "SECRET=1\n")
        self.assertEqual(h.writes, [("create_worktree", "feat/7", "r/feat/7")])
        self.assertEqual(got["pane"], "P0")
        self.assertIn("deploy/missing.yaml", got["detail"])
        self.assertEqual(gitx.branch(self.src), "main")  # 元の clone の枝は替えない

    def test_copy_from_takes_files_from_that_folder_not_the_source(self):
        keep = pathlib.Path(self.root).parent / "keep"
        (keep / "frontend").mkdir(parents=True)
        (keep / "frontend" / ".env.local").write_text("KEPT=1\n")
        repo = self.repo._replace(copy_from=str(keep))
        got = provision.prepare(self.row, repo, WorktreeHerdr(self.root), gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual((pathlib.Path(got["path"]) / "frontend" / ".env.local").read_text(), "KEPT=1\n")

    def test_second_time_reuses_the_place_and_its_open_workspace(self):
        h = WorktreeHerdr(self.root)
        first = provision.prepare(self.row, self.repo, h, gitx)
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual((got["status"], got["created"], got["path"], got["pane"]), ("ready", False, first["path"], "P0"))
        self.assertEqual([w[0] for w in h.writes], ["create_worktree", "open_worktree"])

    def test_closed_workspace_is_opened_again_on_the_same_place(self):
        h = WorktreeHerdr(self.root)
        first = provision.prepare(self.row, self.repo, h, gitx)
        h.close_workspace(first["workspace"])
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual((got["status"], got["created"], got["path"]), ("ready", False, first["path"]))
        self.assertNotEqual(got["pane"], first["pane"])

    def test_the_place_is_found_by_branch_not_by_folder_name(self):
        # 置き場は herdr の既定に任せ、こちらは名前で探さない。持ち主が別の場所に作った worktree でも、その枝の場所として使う
        elsewhere = str(pathlib.Path(self.root).parent / "hand-made")
        git("-C", self.src, "worktree", "add", "-q", "-b", "feat/7", elsewhere, "origin/feat/7")
        got = provision.prepare(self.row, self.repo, WorktreeHerdr(self.root), gitx)
        self.assertEqual((got["status"], got["created"]), ("ready", False))
        self.assertTrue(_same(got["path"], elsewhere))

    def test_reused_place_is_fast_forwarded_to_origin(self):
        h = WorktreeHerdr(self.root)
        first = provision.prepare(self.row, self.repo, h, gitx)
        theirs = advance(self.src, "feat/7")
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(gitx.head_sha(first["path"]), theirs)

    def test_existing_local_branch_behind_origin_is_fast_forwarded_when_created(self):
        # 前の片付けで場所は消えたが手元の枝が残っている形。herdr は手元の枝を開くので、その後で origin に揃える
        git("-C", self.src, "branch", "-q", "feat/7", "origin/feat/7")
        theirs = advance(self.src, "feat/7")
        got = provision.prepare(self.row, self.repo, WorktreeHerdr(self.root), gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(gitx.head_sha(got["path"]), theirs)

    def test_local_only_commits_are_not_moved_and_are_noted(self):
        h = WorktreeHerdr(self.root)
        first = provision.prepare(self.row, self.repo, h, gitx)
        git("-C", first["path"], "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "mine")
        mine = gitx.head_sha(first["path"])
        advance(self.src, "feat/7")
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(gitx.head_sha(first["path"]), mine)
        self.assertIn("手元にしか無い commit", got["detail"])

    def test_branch_open_in_the_source_clone_is_branch_busy(self):
        git("-C", self.src, "checkout", "-q", "-b", "feat/7", "origin/feat/7")
        h = WorktreeHerdr(self.root)
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual(got["status"], "branch_busy")
        self.assertEqual(h.writes, [])
        self.assertEqual(gitx.branch(self.src), "feat/7")

    def test_fork_pr_is_not_provisioned(self):
        h = WorktreeHerdr(self.root)
        got = provision.prepare({**self.row, "fork": True}, self.repo, h, gitx)
        self.assertEqual(got["status"], "provision_failed")
        self.assertIn("fork", got["detail"])
        self.assertEqual(h.writes, [])

    def test_branch_missing_on_origin_is_provision_failed(self):
        got = provision.prepare({"number": 7, "head": "nowhere"}, self.repo, WorktreeHerdr(self.root), gitx)
        self.assertEqual(got["status"], "provision_failed")
        self.assertIn("fetch", got["detail"])

    def test_output_matches_schema(self):
        out = {"schema": 1, "provision": provision.prepare(self.row, self.repo, WorktreeHerdr(self.root), gitx)}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("provision")), [])


class Would(unittest.TestCase):
    def test_dry_run_says_create_reuse_or_branch_busy(self):
        places = [{"path": "/s", "branch": "main", "linked": False},
                  {"path": "/w/feat-8", "branch": "feat/8", "linked": True}]
        self.assertEqual(provision.would({"head": "feat/7"}, places), "create")
        self.assertEqual(provision.would({"head": "feat/8"}, places), "reuse")
        self.assertEqual(provision.would({"head": "main"}, places), "branch_busy")
        self.assertEqual(provision.would({"head": "feat/8", "fork": True}, places), "provision_failed")
        self.assertEqual(provision.would({"head": None, "kind": "issue"}, places), "create")


class LinkBranch(unittest.TestCase):
    def test_links_then_reads_the_branches_back(self):
        calls = []

        class Gh:
            def issue_develop(self, repo, number, base, env=None):
                calls.append(("develop", repo, number, base, env))

            def issue_branches(self, repo, number, env=None):
                calls.append(("list", repo, number, env))
                return ["12-fix-login"]

        got = provision.link_branch(Repo("o/r", "s", "/s"), 12, "main", Gh(), {"GH_TOKEN": "t"})
        self.assertEqual(got, ["12-fix-login"])
        self.assertEqual(calls, [("develop", "o/r", 12, "main", {"GH_TOKEN": "t"}), ("list", "o/r", 12, {"GH_TOKEN": "t"})])


if __name__ == "__main__":
    unittest.main()
