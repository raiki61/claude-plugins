"""VM のディスク（/）を部署の作業場と一時の置き場で埋めないための部品（頼み 96620c）。部署の会話の Bash の TMPDIR（role_hook.put_tmpdir）・
部署を立てる前の空きの確かめ（provision.room_need・room_short と --task）・サブエージェントの作業場の片付け（clean.agent_rows・remove_agent）・
一時の置き場の写しで写さない物（clean.keep_tmp）。"""

import os
import pathlib
import subprocess
import time
import unittest

from . import DISPATCH, fakegit  # noqa: F401
from .test_dispatch import FakePorts, fake_cfg, run_main
from . import scratch
import gitx
import role_hook
from nodes import clean, provision

GIB = 1024 ** 3


class TmpDir(unittest.TestCase):
    def setUp(self):
        self.job = scratch()
        self.env_file = os.path.join(scratch(), "env.sh")
        self.env = {"CLAUDE_ENV_FILE": self.env_file, "CLAUDE_JOB_DIR": self.job}

    def lines(self):
        return pathlib.Path(self.env_file).read_text(encoding="utf-8").splitlines()

    def test_department_bash_gets_tmpdir_under_the_job_folder_once(self):
        where = role_hook.put_tmpdir({"role": "担当"}, self.env, posix=True)
        self.assertEqual(where, os.path.join(self.job, "tmp", clean.TMPDIR_NAME))
        self.assertTrue(os.path.isdir(where))
        role_hook.put_tmpdir({"role": "担当"}, self.env, posix=True)   # やり直しの SessionStart でも 1 行のまま
        self.assertEqual(self.lines(), [f"export TMPDIR={where}"])

    def test_nothing_is_added_outside_a_background_department(self):
        self.assertIsNone(role_hook.put_tmpdir({}, self.env, posix=True))   # 部署でない
        self.assertIsNone(role_hook.put_tmpdir({"role": "担当"}, {"CLAUDE_ENV_FILE": self.env_file}, posix=True))   # 裏の会話でない
        self.assertIsNone(role_hook.put_tmpdir({"role": "担当"}, self.env, posix=False))   # Windows
        self.assertFalse(os.path.exists(self.env_file))

    def test_a_path_with_a_space_is_quoted_for_the_shell(self):
        job = os.path.join(scratch(), "a b")
        where = role_hook.put_tmpdir({"role": "担当"}, {**self.env, "CLAUDE_JOB_DIR": job}, posix=True)
        self.assertEqual(self.lines(), [f"export TMPDIR='{where}'"])


class Room(unittest.TestCase):
    def test_need_is_the_reserve_and_the_checkout(self):
        self.assertEqual(provision.room_need(GIB), provision.ROOM_RESERVE + GIB)
        self.assertEqual(provision.room_need(None), provision.ROOM_RESERVE + provision.ROOM_FALLBACK)

    def test_short_only_when_free_is_known_and_below_the_need(self):
        self.assertIsNone(provision.room_short(None, GIB))   # 読めないときは止めない
        self.assertIsNone(provision.room_short(2 * GIB, 2 * GIB))
        said = provision.room_short(GIB, 6 * GIB)
        self.assertIn("ディスクの空きが足りない（空き 1.0 GB・要る空き 6.0 GB）", said)
        self.assertIn("--clean --apply", said)

    def test_tree_bytes_sums_the_size_column_and_skips_submodules(self):
        out = ("100644 blob aaa      12\ta.txt\n"
               "160000 commit bbb       -\tsub\n"
               "100644 blob ccc       30\tdir/b b.txt\n")
        got = gitx.tree_bytes("/x", runner=lambda argv: subprocess.CompletedProcess(argv, 0, out, ""))
        self.assertEqual(got, 42)
        self.assertIsNone(gitx.tree_bytes("/x", runner=lambda argv: subprocess.CompletedProcess(argv, 128, "", "bad")))


class TaskRoom(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.brief = str(pathlib.Path(self.root).parent / "brief.md")
        pathlib.Path(self.brief).write_text("頼み", encoding="utf-8")

    def run_task(self, ports, *extra):
        return run_main(["--config", self.cfg, "--task", "直し", "--branch", "task/fix", "--brief", self.brief, *extra], ports)

    def test_a_new_department_is_refused_before_the_place_is_made_when_the_disk_is_short(self):
        ports = FakePorts([], git=self.g)
        ports.free = GIB
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 1, out)
        self.assertIn("止めた: ディスクの空きが足りない", out)
        self.assertNotIn("create_worktree", [w[0] for w in ports.term.writes])

    def test_dry_run_tells_the_free_and_needed_room(self):
        ports = FakePorts([], git=self.g)
        ports.free = GIB
        rc, out = self.run_task(ports, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("- ディスクの空き: 空き 1.0 GB", out)
        self.assertIn("足りないので、実際の回は止める", out)


class AgentPlaces(unittest.TestCase):
    def setUp(self):
        self.source = scratch()
        self.base = os.path.join(self.source, ".claude", "worktrees")
        os.makedirs(self.base)
        self.now = time.time()

    def entry(self, name, **kw):
        path = os.path.join(self.base, name)
        os.makedirs(path, exist_ok=True)
        return {"path": path, "branch": f"worktree-{name}", "head": "a" * 40, "locked": None, **kw}

    def rows(self, entries, open_cwds=(), clean_=True, stashed=False, in_main=True, touched=None):
        last = self.now - 2 * clean.AGENT_IDLE_MIN * 60 if touched is None else touched
        return clean.agent_rows(entries, self.source, open_cwds, lambda p: clean_, lambda p, b: stashed,
                                lambda p, sha: in_main, lambda p: last, self.now)

    def reason(self, entries, **kw):
        [row] = self.rows(entries, **kw)
        return row["reason"]

    def test_only_agent_worktrees_under_the_source_are_listed(self):
        other = {"path": os.path.join(self.source, "elsewhere", "agent-x"), "branch": "b", "head": "a" * 40, "locked": None}
        os.makedirs(other["path"])
        named = self.entry("not-agent")
        rows = self.rows([self.entry("agent-a1"), other, named])
        self.assertEqual([r["path"] for r in rows], [os.path.join(self.base, "agent-a1")])
        self.assertTrue(rows[0]["removable"])

    def test_reasons_to_keep(self):
        self.assertEqual(self.reason([self.entry("agent-a", locked="claude agent")]), "locked")
        self.assertEqual(self.reason([self.entry("agent-a")], open_cwds=[os.path.join(self.base, "agent-a", "sub")]), "session")
        self.assertEqual(self.reason([self.entry("agent-a")], clean_=False), "dirty")
        self.assertEqual(self.reason([self.entry("agent-a")], in_main=False), "unpushed")
        self.assertEqual(self.reason([self.entry("agent-a")], stashed=True), "unpushed")
        self.assertEqual(self.reason([self.entry("agent-a", head=None)]), "unpushed")
        self.assertEqual(self.reason([self.entry("agent-a")], touched=self.now - 60), "recent")

    def test_a_missing_folder_is_not_listed(self):
        e = {"path": os.path.join(self.base, "agent-gone"), "branch": "b", "head": "a" * 40, "locked": None}
        self.assertEqual(self.rows([e]), [])

    def test_remove_runs_worktree_remove_without_force_and_deletes_the_branch(self):
        row = {"path": os.path.join(self.base, "agent-a"), "branch": "worktree-agent-a", "head": "a" * 40}
        os.makedirs(row["path"])
        calls = []

        class G:
            @staticmethod
            def remove_worktree(source, path):
                calls.append(("remove", source, path))
                os.rmdir(path)

            @staticmethod
            def delete_branch(source, branch, sha):
                calls.append(("branch", branch, sha))
                return "deleted"

        out = clean.remove_agent(row, self.source, G)
        self.assertEqual(out, {"path": row["path"], "removed": True, "branch_deleted": True, "detail": None})
        self.assertEqual(calls, [("remove", self.source, row["path"]), ("branch", "worktree-agent-a", "a" * 40)])

    def test_remove_keeps_the_branch_when_git_refuses(self):
        row = {"path": os.path.join(self.base, "agent-a"), "branch": "worktree-agent-a", "head": "a" * 40}
        os.makedirs(row["path"])

        class G:
            @staticmethod
            def remove_worktree(source, path):
                raise gitx.GitError("contains modified or untracked files")

            @staticmethod
            def delete_branch(source, branch, sha):
                raise AssertionError("場所を消せなかったらブランチを消さない")

        out = clean.remove_agent(row, self.source, G)
        self.assertFalse(out["removed"])
        self.assertIn("modified or untracked", out["detail"])


class KeptTmpSkips(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(scratch())
        self.common = scratch()

        class G:
            @staticmethod
            def common_dir(source):
                return self.common

        self.g = G

    def test_tmpdir_rebuilt_folders_and_big_files_are_not_copied(self):
        (self.tmp / clean.TMPDIR_NAME / "x").mkdir(parents=True)
        (self.tmp / clean.TMPDIR_NAME / "x" / "f").write_text("tmp", encoding="utf-8")
        (self.tmp / "work" / ".venv" / "lib").mkdir(parents=True)
        (self.tmp / "work" / ".venv" / "lib" / "m.py").write_text("x", encoding="utf-8")
        (self.tmp / "work" / "note.md").write_text("keep", encoding="utf-8")
        with open(self.tmp / "big.bin", "wb") as f:
            f.truncate(clean.KEPT_FILE_LIMIT + 1)
        n, dest = clean.keep_tmp(str(self.tmp), "/src", "s1", self.g)
        self.assertEqual(n, 2)   # work と big.bin（tmpdir は数えない）
        self.assertEqual(pathlib.Path(dest, "work", "note.md").read_text(encoding="utf-8"), "keep")
        self.assertFalse(os.path.exists(os.path.join(dest, clean.TMPDIR_NAME)))
        self.assertFalse(os.path.exists(os.path.join(dest, "work", ".venv")))
        self.assertFalse(os.path.exists(os.path.join(dest, "big.bin")))
        listed = pathlib.Path(dest, clean.SKIPPED).read_text(encoding="utf-8")
        self.assertIn(f"work{os.sep}.venv/\t-", listed)
        self.assertIn(f"big.bin\t{clean.KEPT_FILE_LIMIT + 1}", listed)
        self.assertNotIn(clean.TMPDIR_NAME, listed)

    def test_only_tmpdir_means_nothing_to_copy(self):
        (self.tmp / clean.TMPDIR_NAME).mkdir()
        (self.tmp / clean.TMPDIR_NAME / "f").write_text("tmp", encoding="utf-8")
        self.assertEqual(clean.keep_tmp(str(self.tmp), "/src", "s2", self.g), (0, None))


if __name__ == "__main__":
    unittest.main()
