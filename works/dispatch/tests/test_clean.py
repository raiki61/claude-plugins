"""片付け（clean ノードと dispatch.py --clean）。消してよいのは、PR が閉じていて、会話が無く、手元にしか無い変更も無い clone だけ。"""

import contextlib
import io
import pathlib
import subprocess
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakeHerdr, FakePorts, make_cfg
from .test_provision import git
import dispatch
import gitx
from config import Repo
from nodes import clean

REPO = Repo("o/r", "s", "/src/r", "/clones", ())


def folders(*names):
    return [f"/clones/{n}" for n in names]


class Candidates(unittest.TestCase):
    def rows(self, names, states, open_cwds=(), dirty=(), unpushed=()):
        return clean.candidates(REPO, folders(*names), lambda n: states[n], set(open_cwds),
                                lambda p: p not in dirty, lambda p: p in unpushed)

    def test_only_pr_folders_of_this_repo_are_looked_at(self):
        rows = self.rows(["r-pr-1", "other-pr-2", "r-pr-x", "r"], {1: "MERGED"})
        self.assertEqual([r["number"] for r in rows], [1])

    def test_closed_or_merged_without_session_or_local_work_is_removable(self):
        rows = self.rows(["r-pr-1", "r-pr-2"], {1: "MERGED", 2: "CLOSED"})
        self.assertEqual([r["removable"] for r in rows], [True, True])

    def test_open_pr_is_kept(self):
        row = self.rows(["r-pr-1"], {1: "OPEN"})[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "pr_open"))

    def test_folder_with_a_conversation_is_kept(self):
        row = self.rows(["r-pr-1"], {1: "MERGED"}, open_cwds=["/clones/r-pr-1/backend"])[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "session"))

    def test_uncommitted_or_unpushed_work_is_kept(self):
        self.assertEqual(self.rows(["r-pr-1"], {1: "MERGED"}, dirty=["/clones/r-pr-1"])[0]["reason"], "dirty")
        self.assertEqual(self.rows(["r-pr-1"], {1: "MERGED"}, unpushed=["/clones/r-pr-1"])[0]["reason"], "unpushed")

    def test_unknown_pr_state_is_kept(self):
        row = self.rows(["r-pr-1"], {1: None})[0]
        self.assertEqual((row["removable"], row["reason"]), (False, "pr_state_unknown"))


class Unpushed(unittest.TestCase):
    def test_commit_only_here_counts(self):
        from .test_provision import make_world
        src, root = make_world()
        path = str(pathlib.Path(root, "r-pr-1"))
        git("clone", "-q", src, path)
        self.assertFalse(gitx.unpushed(path))
        git("-C", path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "local")
        self.assertTrue(gitx.unpushed(path))


class Main(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()
        for n in (1, 2):
            git("clone", "-q", str(pathlib.Path(self.root).parent / "o" / "r.git"), str(pathlib.Path(self.root, f"r-pr-{n}")))

    def run_clean(self, argv, ports):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dispatch.main(["--config", self.cfg, *argv], ports=ports)
        return rc, buf.getvalue()

    def ports(self, herdr=None):
        p = FakePorts([], herdr=herdr)
        p.pr_state = lambda repo, n: {1: "MERGED", 2: "OPEN"}[n]
        return p

    def test_clean_without_apply_removes_nothing(self):
        rc, out = self.run_clean(["--clean"], self.ports())
        self.assertEqual(rc, 0)
        self.assertTrue(pathlib.Path(self.root, "r-pr-1").exists())
        self.assertIn("r-pr-1", out)
        self.assertIn("--apply", out)

    def test_apply_removes_only_candidates_and_closes_their_empty_workspace(self):
        h = FakeHerdr()
        h.create_workspace(str(pathlib.Path(self.root, "r-pr-1")), "r-pr-1")
        h.writes.clear()
        rc, out = self.run_clean(["--clean", "--apply"], self.ports(herdr=h))
        self.assertEqual(rc, 0)
        self.assertFalse(pathlib.Path(self.root, "r-pr-1").exists())
        self.assertTrue(pathlib.Path(self.root, "r-pr-2").exists())
        self.assertEqual(h.writes, [("close_workspace", "W0")])

    def test_apply_does_not_close_a_workspace_whose_pane_has_a_conversation(self):
        h = FakeHerdr()
        h.create_workspace(str(pathlib.Path(self.root, "r-pr-1")), "r-pr-1")
        h._panes[0]["agent"] = "claude"
        h.writes.clear()
        self.run_clean(["--clean", "--apply"], self.ports(herdr=h))
        self.assertEqual(h.writes, [])


if __name__ == "__main__":
    unittest.main()
