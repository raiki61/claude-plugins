"""包みの切符（.shared/core/ticket.py）の検査。

- 守る場所: 共通の .git・この worktree の gitdir の実体・ほかの worktree と元の作業ツリー・盤面・包みの家（home()）が入り、
  役の cwd の worktree 自身は入らない
- 綴りと realpath が違う場所（symlink を通した綴り。macOS の /var と /private/var と同じ形）は両方が入る
- 書く → 読むで同じ中身が返り、置き場は home()/tickets/<cwd の realpath の sha256 の先頭 16 桁>.json
- 壊れた切符・無い切符は None。git でない cwd は TicketError
使い捨てのリポジトリは tempfile の下に作る。包みの家は WORKS_ADAPTER_HOME で使い捨ての場所へ向ける（本物の家に書かない）。
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(CORE))

import ticket  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def git(cwd, *args):
    subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], check=True, capture_output=True)


class TicketCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 元の作業ツリー main と、その worktree 2 つ（wt1 が役の cwd）。試験は読むだけなので 1 度だけ作る
        cls._repo_tmp = tempfile.TemporaryDirectory()
        cls.repo_tmp = pathlib.Path(cls._repo_tmp.name)
        cls.main = cls.repo_tmp / "main"
        cls.main.mkdir()
        git(cls.main, "init", "-q", "-b", "main")
        (cls.main / "a.txt").write_text("a\n")
        git(cls.main, "add", "a.txt")
        git(cls.main, "commit", "-q", "-m", "init")
        cls.wt1 = cls.repo_tmp / "wt1"
        cls.wt2 = cls.repo_tmp / "wt2"
        git(cls.main, "worktree", "add", "-q", "-b", "b1", str(cls.wt1))
        git(cls.main, "worktree", "add", "-q", "-b", "b2", str(cls.wt2))

    @classmethod
    def tearDownClass(cls):
        cls._repo_tmp.cleanup()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.home = self.tmp / "adapter-home"
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.home),
                                           "GIT_CEILING_DIRECTORIES": str(self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        self.board = self.tmp / "artifacts" / "board"
        self.board.mkdir(parents=True)

    def real(self, p):
        return os.path.realpath(p)

    def test_protected_excludes_own_worktree(self):
        got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(self.real(self.main), got)
        self.assertIn(self.real(self.wt2), got)
        self.assertNotIn(self.real(self.wt1), got)
        self.assertNotIn(str(self.wt1), got)
        self.assertEqual(got, sorted(set(got)), "重複なし・並べて返す")

    def test_protected_from_main_excludes_main(self):
        # 役の cwd が元の作業ツリーのときは元を除き、worktree 2 つは入る
        got = ticket.protected_paths(self.main, self.board)
        self.assertNotIn(self.real(self.main), got)
        self.assertIn(self.real(self.wt1), got)
        self.assertIn(self.real(self.wt2), got)

    def test_protected_has_git_dirs_and_board(self):
        got = ticket.protected_paths(self.wt1, self.board)
        common = subprocess.run(["git", "-C", str(self.wt1), "rev-parse", "--git-common-dir"],
                                check=True, capture_output=True, text=True).stdout.strip()
        common = os.path.join(str(self.wt1), common) if not os.path.isabs(common) else common
        gitdir = subprocess.run(["git", "-C", str(self.wt1), "rev-parse", "--absolute-git-dir"],
                                check=True, capture_output=True, text=True).stdout.strip()
        self.assertIn(self.real(common), got)
        self.assertEqual(self.real(common), self.real(self.main / ".git"))
        self.assertIn(self.real(gitdir), got)
        self.assertNotEqual(self.real(gitdir), self.real(common), "worktree の gitdir は共通の .git と別の場所")
        self.assertIn(self.real(self.board), got)
        self.assertIn(str(self.board), got)
        self.assertIn(str(ticket.home()), got)
        self.assertEqual(ticket.home(), self.home)

    def test_protected_has_pack_and_settings(self):
        fake_home = self.tmp / "user"
        fake_home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(fake_home)}):
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(self.real(ROOT), got)
        for name in (".gitconfig", ".config/git", ".bashrc", ".zshrc", ".profile", ".claude"):
            with self.subTest(name=name):
                self.assertIn(str(fake_home / name), got)

    def test_protected_both_spellings(self):
        # 綴り（symlink を通した道）と realpath が違う場所は両方。/var と /private/var と同じ形を自分で作る
        real_dir = self.tmp / "real"
        real_dir.mkdir()
        link = self.tmp / "link"
        link.symlink_to(real_dir)
        board = link / "board"
        board.mkdir()
        got = ticket.protected_paths(self.wt1, board)
        self.assertIn(str(board), got)
        self.assertIn(self.real(board), got)
        self.assertNotEqual(str(board), self.real(board))
        # 役の cwd を symlink の綴りで渡しても、自分の worktree はどちらの綴りでも入らない
        wt_link = self.tmp / "wtlink"
        wt_link.symlink_to(self.wt1)
        got = ticket.protected_paths(wt_link, self.board)
        self.assertNotIn(self.real(self.wt1), got)
        self.assertNotIn(str(wt_link), got)
        self.assertIn(self.real(self.wt2), got)

    def test_write_read_roundtrip(self):
        path = ticket.write(self.board, self.wt1, "run-123")
        digest = hashlib.sha256(self.real(self.wt1).encode("utf-8")).hexdigest()[:16]
        self.assertEqual(path, self.home / "tickets" / f"{digest}.json")
        self.assertEqual(ticket.ticket_path(self.wt1), path)
        got = ticket.read(self.wt1)
        self.assertEqual(got, json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(set(got), {"run_id", "board", "cwd", "protected", "written_at"})
        self.assertEqual(got["run_id"], "run-123")
        self.assertEqual(got["board"], str(self.board))
        self.assertEqual(got["cwd"], str(self.wt1))
        self.assertEqual(got["protected"], ticket.protected_paths(self.wt1, self.board))
        self.assertTrue(got["written_at"])
        # cwd を symlink の綴りで引いても同じ切符（名前は realpath から）
        wt_link = self.tmp / "wtlink"
        wt_link.symlink_to(self.wt1)
        self.assertEqual(ticket.ticket_path(wt_link), path)
        self.assertEqual(ticket.read(wt_link), got)
        # 一時ファイルを残さない
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name])

    def test_write_overwrites(self):
        ticket.write(self.board, self.wt1, "run-1")
        ticket.write(self.board, self.wt1, "run-2")
        self.assertEqual(ticket.read(self.wt1)["run_id"], "run-2")

    def test_read_missing_is_none(self):
        self.assertIsNone(ticket.read(self.wt1))

    def test_read_broken_is_none(self):
        path = ticket.ticket_path(self.wt1)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(ticket.read(self.wt1))
        path.write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(ticket.read(self.wt1), "オブジェクトでない JSON も壊れた扱い")

    def test_not_git_raises(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(ticket.TicketError):
            ticket.protected_paths(plain, self.board)
        with self.assertRaises(ticket.TicketError):
            ticket.write(self.board, plain, "run-x")
        self.assertIsNone(ticket.read(plain))

    def test_home_default(self):
        with mock.patch.dict(os.environ, {"HOME": "/h", "XDG_STATE_HOME": "/xs"}):
            os.environ.pop("WORKS_ADAPTER_HOME")
            self.assertEqual(ticket.home(), pathlib.Path("/xs/works/adapter"))
            os.environ.pop("XDG_STATE_HOME")
            self.assertEqual(ticket.home(), pathlib.Path("/h/.local/state/works/adapter"))
            os.environ["XDG_STATE_HOME"] = ""
            os.environ["WORKS_ADAPTER_HOME"] = ""
            self.assertEqual(ticket.home(), pathlib.Path("/h/.local/state/works/adapter"), "空は無いと同じ（${:-}）")


if __name__ == "__main__":
    unittest.main()
