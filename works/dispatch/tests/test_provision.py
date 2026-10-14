"""provision ノード: PR ごとの clone と herdr の作業場を、無ければ作り、有れば使い直す（設計書 3 節）。

git は本物を使う。一時のフォルダに、GitHub に見立てた裸のリポジトリ `<tmp>/o/r.git` と、それを origin にした元の clone を作る。
herdr だけ偽物にする。
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
import gitx
import config
from config import Repo
from nodes import provision


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_world():
    """(元の clone のパス, clone_root) を返す。元の clone には追跡しないファイル frontend/.env.local がある。"""
    t = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-prov-"))
    remote = t / "o" / "r.git"
    remote.parent.mkdir()
    git("init", "--bare", "-q", str(remote))
    src = t / "src"
    git("clone", "-q", str(remote), str(src))
    git("-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    git("-C", str(src), "push", "-q", "origin", "HEAD")
    (src / "frontend").mkdir()
    (src / "frontend" / ".env.local").write_text("SECRET=1\n")
    (src / ".gitignore").write_text("frontend/.env.local\n")
    root = t / "clones"
    root.mkdir()
    return str(src), str(root)


class FakeHerdr:
    HerdrError = Exception

    def __init__(self, panes=None):
        self._panes = list(panes or [])
        self.created = []

    def panes(self):
        return list(self._panes)

    def create_workspace(self, cwd, label):
        self.created.append((cwd, label))
        pane = {"pane_id": f"N{len(self.created)}:p1", "workspace_id": f"N{len(self.created)}", "cwd": cwd, "agent": None}
        self._panes.append(pane)
        return {"workspace_id": pane["workspace_id"], "pane_id": pane["pane_id"]}


class Prepare(unittest.TestCase):
    def setUp(self):
        self.src, self.root = make_world()
        self.repo = Repo("o/r", "second", self.src, self.root, ("frontend/.env.local", "deploy/missing.yaml"))
        self.row = {"number": 7, "clone_path": config.clone_path(self.repo, 7)}

    def test_clone_path_is_repo_name_pr_number(self):
        self.assertEqual(self.row["clone_path"], os.path.join(self.root, "r-pr-7"))

    def test_creates_clone_with_github_origin_copies_files_and_opens_workspace(self):
        h = FakeHerdr()
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertTrue(got["created"])
        path = self.row["clone_path"]
        self.assertEqual(gitx.origin_url(path), gitx.origin_url(self.src))
        self.assertEqual(gitx.origin_repo(path), "o/r")
        self.assertEqual((pathlib.Path(path) / "frontend" / ".env.local").read_text(), "SECRET=1\n")
        self.assertEqual(h.created, [(path, "r-pr-7")])
        self.assertEqual(got["pane"], "N1:p1")
        self.assertIn("deploy/missing.yaml", got["detail"])

    def test_second_time_reuses_clone_and_existing_pane(self):
        h = FakeHerdr()
        provision.prepare(self.row, self.repo, h, gitx)
        got = provision.prepare(self.row, self.repo, h, gitx)
        self.assertEqual((got["status"], got["created"], got["pane"]), ("ready", False, "N1:p1"))
        self.assertEqual(len(h.created), 1)

    def test_existing_folder_of_another_repo_is_not_touched(self):
        path = pathlib.Path(self.row["clone_path"])
        path.mkdir()
        (path / "mine.txt").write_text("keep")
        got = provision.prepare(self.row, self.repo, FakeHerdr(), gitx)
        self.assertEqual(got["status"], "provision_failed")
        self.assertEqual(sorted(p.name for p in path.iterdir()), ["mine.txt"])

    def test_output_matches_schema(self):
        out = {"schema": 1, "provision": provision.prepare(self.row, self.repo, FakeHerdr(), gitx)}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("provision")), [])


class Plan(unittest.TestCase):
    def test_dry_run_plan_says_create_or_reuse(self):
        src, root = make_world()
        repo = Repo("o/r", "s", src, root, ())
        pathlib.Path(root, "r-pr-8").mkdir()
        self.assertEqual(provision.would(repo, 7), "create")
        self.assertEqual(provision.would(repo, 8), "reuse")


if __name__ == "__main__":
    unittest.main()
