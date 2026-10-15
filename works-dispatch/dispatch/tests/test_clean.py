"""片付け（clean ノードと dispatch.py --clean）。消してよいのは、元の clone の linked worktree のうち、枝の PR が閉じていて、会話が無く、
手元の作業も無く、手元の枝の先頭が PR の head と同じ場所だけ。"""

import contextlib
import io
import os
import pathlib
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakeHerdr, FakePorts, gitx_source, make_cfg
from .test_provision import git, make_world
import dispatch
import gitx
from nodes import clean


def place(path, branch, linked=True):
    return {"path": path, "branch": branch, "linked": linked, "workspace": None, "prunable": False}


SHA = "a" * 40


class Candidates(unittest.TestCase):
    def rows(self, places, prs, open_cwds=(), dirty=(), stashed=(), heads=None):
        def pr_for(branch):
            got = prs.get(branch)
            if got == "unknown":
                raise clean.Unknown("x")
            return got
        return clean.candidates(places, pr_for, set(open_cwds), lambda p: p not in dirty,
                                lambda p, b: p in stashed, lambda p: (heads or {}).get(p, SHA))

    def merged(self, n=1, state="MERGED"):
        return {"number": n, "state": state, "head_sha": SHA}

    def test_only_linked_worktrees_are_looked_at(self):
        rows = self.rows([place("/s", "main", linked=False), place("/w/a", "a")], {"a": self.merged(), "main": self.merged()})
        self.assertEqual([r["path"] for r in rows], ["/w/a"])

    def test_closed_or_merged_without_session_or_local_work_is_removable(self):
        rows = self.rows([place("/w/a", "a"), place("/w/b", "b")], {"a": self.merged(1), "b": self.merged(2, "CLOSED")})
        self.assertEqual([(r["number"], r["removable"]) for r in rows], [(1, True), (2, True)])

    def test_branch_without_a_pr_is_kept(self):
        # issue から始めて PR をまだ作っていない枝は消さない
        row = self.rows([place("/w/12-fix", "12-fix")], {})[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "no_pr"))

    def test_detached_checkout_is_kept(self):
        self.assertEqual(self.rows([place("/w/x", None)], {})[0]["reason"], "no_branch")

    def test_open_pr_is_kept(self):
        row = self.rows([place("/w/a", "a")], {"a": self.merged(state="OPEN")})[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "pr_open"))

    def test_folder_with_a_conversation_is_kept(self):
        row = self.rows([place("/w/a", "a")], {"a": self.merged()}, open_cwds=["/w/a/backend"])[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "session"))

    def test_uncommitted_stashed_or_moved_work_is_kept(self):
        pr = {"a": self.merged()}
        self.assertEqual(self.rows([place("/w/a", "a")], pr, dirty=["/w/a"])[0]["reason"], "dirty")
        self.assertEqual(self.rows([place("/w/a", "a")], pr, stashed=["/w/a"])[0]["reason"], "unpushed")
        self.assertEqual(self.rows([place("/w/a", "a")], pr, heads={"/w/a": "b" * 40})[0]["reason"], "unpushed")

    def test_unknown_pr_is_kept(self):
        row = self.rows([place("/w/a", "a")], {"a": "unknown"})[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "pr_state_unknown"))

    def test_conversation_behind_a_symlink_still_keeps_the_place(self):
        real = pathlib.Path(tempfile.mkdtemp()).resolve()
        (real / "a").mkdir()
        link = pathlib.Path(tempfile.mkdtemp()) / "w"
        os.symlink(real, link)
        rows = self.rows([place(str(link / "a"), "a")], {"a": self.merged()}, open_cwds=[str(real / "a")])
        self.assertEqual(rows[0]["reason"], "session")


class LocalWork(unittest.TestCase):
    """worktree は枝と stash を元の clone と共有する。判定はその場所の HEAD とその枝に絞る。"""

    def world(self):
        src, root = make_world()
        path = str(pathlib.Path(root, "feat-1"))
        git("-C", src, "worktree", "add", "-q", "-b", "feat/1", path, "origin/feat/1")
        return src, path

    def commit(self, cwd, msg="local"):
        git("-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", msg)

    def test_commit_only_here_counts(self):
        src, path = self.world()
        self.assertFalse(gitx.unpushed(path))
        self.commit(path)
        self.assertTrue(gitx.unpushed(path))

    def test_local_commits_in_the_source_clone_do_not_count_here(self):
        src, path = self.world()
        self.commit(src)   # 元の clone の main にだけ手元の commit
        self.assertFalse(gitx.unpushed(path))

    def test_new_file_not_yet_added_is_not_clean(self):
        src, path = self.world()
        self.assertTrue(gitx.is_clean(path))
        pathlib.Path(path, "new.py").write_text("x = 1\n")
        self.assertFalse(gitx.is_clean(path))

    def test_ignored_file_alone_stays_clean(self):
        src, path = self.world()
        pathlib.Path(path, "frontend").mkdir()
        pathlib.Path(path, "frontend", ".env.local").write_text("A=1\n")
        self.assertTrue(gitx.is_clean(path))

    def test_stash_counts_only_on_its_own_branch(self):
        src, path = self.world()
        pathlib.Path(path, "draft.py").write_text("x = 1\n")
        git("-C", path, "-c", "user.name=t", "-c", "user.email=t@t", "stash", "push", "-q", "--include-untracked")
        self.assertTrue(gitx.is_clean(path))
        self.assertTrue(gitx.unpushed(path))
        self.assertTrue(gitx.stashed(path, "feat/1"))
        self.assertFalse(gitx.stashed(src, "main"))   # stash は共有だが、別の枝の物は数えない
        self.assertFalse(gitx.unpushed(src))

    def test_commit_on_a_detached_head_counts_as_unpushed(self):
        src, path = self.world()
        git("-C", path, "checkout", "-q", "--detach")
        self.commit(path, "loose")
        self.assertTrue(gitx.unpushed(path))


class Remove(unittest.TestCase):
    def setUp(self):
        self.src, self.root = make_world()
        self.h = FakeHerdr(root=self.root)
        self.path = self.h.create_worktree(self.src, "feat/1", "origin/feat/1", "r/feat/1")["path"]
        self.h.writes.clear()

    def row(self, head=None):
        return {"path": self.path, "branch": "feat/1", "pr_head": head or gitx.head_sha(self.path)}

    def test_removes_the_place_its_workspace_and_the_local_branch(self):
        got = clean.remove(self.row(), self.src, "r/feat/1", self.h, gitx)
        self.assertEqual((got["removed"], got["branch_deleted"], got["detail"]), (True, True, None))
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.h.panes(), [])
        self.assertEqual(git("-C", self.src, "branch", "--list", "feat/1"), "")

    def test_branch_whose_tip_moved_is_kept(self):
        got = clean.remove(self.row("b" * 40), self.src, "r/feat/1", self.h, gitx)
        self.assertTrue(got["removed"])
        self.assertFalse(got["branch_deleted"])
        self.assertIn("feat/1", git("-C", self.src, "branch", "--list", "feat/1"))

    def test_dirty_place_is_not_forced(self):
        pathlib.Path(self.path, "new.py").write_text("x\n")
        got = clean.remove(self.row(), self.src, "r/feat/1", self.h, gitx)
        self.assertFalse(got["removed"])
        self.assertIn("dirty_worktree_requires_force", got["detail"])
        self.assertTrue(os.path.exists(self.path))
        self.assertIn("feat/1", git("-C", self.src, "branch", "--list", "feat/1"))

    def test_release_closes_only_the_worktrees_own_workspace(self):
        # 持ち主の別の作業場のペインが、その場所に cd しているだけなら、その作業場は閉じない
        other = self.h.open_at(self.path, worktree=False)
        self.h.open_at(os.path.join(self.path, "sub"), worktree=False)
        got = clean.release(self.src, self.path, self.h)
        self.assertEqual((got["status"], got["workspace"]), ("closed", "W0"))
        self.assertEqual(self.h.writes, [("close_workspace", "W0")])
        self.assertIn(other, self.h.panes())

    def test_release_keeps_a_workspace_with_any_pane_that_is_not_a_shell(self):
        # 1 つの作業場に複数のペイン。どれか 1 つでも前がシェルでなければ（dev server など）、作業場を閉じない
        extra = self.h.add_pane("W0", self.path)
        self.h.busy.add(extra["pane_id"])
        got = clean.release(self.src, self.path, self.h)
        self.assertEqual(got["status"], "close_failed")
        self.assertIn(extra["pane_id"], got["detail"])
        self.assertEqual(self.h.writes, [])

    def test_release_of_a_place_without_an_open_workspace_closes_nothing(self):
        self.h.close_workspace("W0")
        self.h.writes.clear()
        self.h.open_at(self.path, worktree=False)   # cd しただけのペインはその場所の作業場ではない
        self.assertEqual(clean.release(self.src, self.path, self.h)["status"], "none")
        self.assertEqual(self.h.writes, [])


class Copies(unittest.TestCase):
    def test_copied_files_changed_here_or_missing_at_the_source_are_named(self):
        here, there = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp())
        for d in (here, there):
            (d / "a").mkdir()
        (here / "a" / ".env.local").write_text("A=2\n")
        (there / "a" / ".env.local").write_text("A=1\n")
        (here / "same.yaml").write_text("x\n")
        (there / "same.yaml").write_text("x\n")
        (here / "only-here.yaml").write_text("y\n")
        got = clean.changed_copies(str(here), str(there), ("a/.env.local", "same.yaml", "only-here.yaml", "absent.yaml"))
        self.assertEqual(got, ["a/.env.local", "only-here.yaml"])

    def test_place_with_changed_copies_is_kept(self):
        rows = clean.candidates([place("/w/a", "a")], lambda b: {"number": 1, "state": "MERGED", "head_sha": SHA}, set(),
                                lambda p: True, lambda p, b: False, lambda p: SHA, changed=lambda p: [".env.local"])
        self.assertEqual((rows[0]["removable"], rows[0]["reason"], rows[0]["files"]), (False, "local_files", [".env.local"]))

    def test_the_source_clone_is_never_a_candidate_even_if_listed_as_linked(self):
        rows = clean.candidates([place("/s/repo", "a"), place("/w/a", "b")], lambda b: None, set(), lambda p: True,
                                lambda p, b: False, lambda p: SHA, source="/s/repo")
        self.assertEqual([r["path"] for r in rows], ["/w/a"])


class Main(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.h = FakeHerdr(root=self.root)
        self.paths = {n: self.h.create_worktree(self.src, f"feat/{n}", f"origin/feat/{n}", f"r/feat/{n}")["path"]
                      for n in (1, 2, 3)}
        self.h.close_workspace("W0")
        self.h.writes.clear()

    def run_clean(self, argv, ports):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dispatch.main(["--config", self.cfg, *argv], ports=ports)
        return rc, buf.getvalue()

    def ports(self):
        p = FakePorts([], herdr=self.h)
        p.branch_prs = {"feat/1": {"number": 1, "state": "MERGED", "head_sha": gitx.head_sha(self.paths[1])},
                        "feat/2": {"number": 2, "state": "OPEN", "head_sha": gitx.head_sha(self.paths[2])}}
        return p

    def test_clean_without_apply_removes_nothing(self):
        rc, out = self.run_clean(["--clean"], self.ports())
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.paths[1]))
        self.assertIn("#1 feat/1  MERGED  消せる", out)
        self.assertIn("#2 feat/2  OPEN  残す（pr_open）", out)
        self.assertIn("- feat/3  -  残す（no_pr）", out)
        self.assertIn("--apply", out)
        self.assertEqual(self.h.writes, [])

    def test_apply_removes_only_candidates_opening_a_closed_workspace_first(self):
        rc, out = self.run_clean(["--clean", "--apply"], self.ports())
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.paths[1]))
        self.assertTrue(os.path.exists(self.paths[2]))
        self.assertTrue(os.path.exists(self.paths[3]))
        self.assertEqual(self.h.writes, [("remove_worktree", self.paths[1])])
        self.assertTrue(os.path.exists(self.src))

    def test_apply_returns_1_when_a_place_could_not_be_removed(self):
        pathlib.Path(self.paths[1], "new.py").write_text("x\n")
        ports = self.ports()
        ports.is_clean = lambda p: True   # 候補の判定の後に手元の作業が増えた形
        rc, out = self.run_clean(["--clean", "--apply"], ports)
        self.assertEqual(rc, 1)
        self.assertIn("消せなかった", out)
        self.assertTrue(os.path.exists(self.paths[1]))

    def test_copied_file_changed_in_the_place_is_kept_and_named(self):
        pathlib.Path(self.paths[1], "frontend").mkdir()
        pathlib.Path(self.paths[1], "frontend", ".env.local").write_text("CHANGED=1\n")
        rc, out = self.run_clean(["--clean", "--apply"], self.ports())
        self.assertIn("残す（local_files: frontend/.env.local）", out)
        self.assertTrue(os.path.exists(self.paths[1]))

    def test_unreadable_conversations_stop_without_a_traceback(self):
        import claudex
        ports = self.ports()

        def broken(config_dir):
            raise claudex.ClaudeError("claude agents --json（x）: boom")
        ports.list_sessions = broken
        rc, out = self.run_clean(["--clean", "--apply"], ports)
        self.assertEqual(rc, 1)
        self.assertIn("止めた: claude agents --json（x）: boom", out)
        self.assertEqual(self.h.writes, [])

    def test_place_with_a_conversation_is_not_removed(self):
        ports = self.ports()
        ports.agents = [{"cwd": self.paths[1], "status": "idle"}]
        rc, out = self.run_clean(["--clean", "--apply"], ports)
        self.assertIn("残す（session）", out)
        self.assertEqual(self.h.writes, [])


if __name__ == "__main__":
    unittest.main()
