"""包みの切符（.shared/core/ticket.py）の検査。

- 守る場所: 共通の .git・この worktree の gitdir の実体・ほかの worktree と元の作業ツリー・盤面・包みの家（home()）・
  Archon の家の設定と DB など（ARCHON_FILES）が入り、
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
        env = {"HOME": str(fake_home)}
        with mock.patch.dict(os.environ, env):
            for name in ("XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR"):
                os.environ.pop(name, None)
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(self.real(ROOT), got)
        names = (".gitconfig", ".config/git", ".config/gh", ".bashrc", ".bash_profile", ".bash_login",
                 ".zshrc", ".zshenv", ".zprofile", ".profile", ".claude", ".claude.json")
        self.assertEqual(sorted(ticket.HOME_FILES), sorted(names), "一覧はデータで持ち、試験の名前と同じ")
        for name in names:
            with self.subTest(name=name):
                self.assertIn(str(fake_home / name), got)

    def test_protected_has_archon_home_entries(self):
        """Archon の家（ARCHON_HOME、無ければ ~/.archon）の設定・DB・env・家の workflows/commands/scripts を守る（再審査 N3）。
        設定の claudeBinaryPath を書き換えられると次の run から包みが外れる。家そのものは守らない（run の worktree が
        家の workspaces・worktrees の下に在るので、塞ぐと役が自分の worktree に書けない）"""
        names = ("config.yaml", "archon.db", "archon.db-wal", "archon.db-shm", "archon.db-journal", ".env", "workflows",
                 "commands", "scripts", "credential-key", "install.json", ".archon")
        self.assertEqual(sorted(ticket.ARCHON_FILES), sorted(names), "一覧はデータで持ち、試験の名前と同じ")
        ah = self.tmp / "archon-home"
        with mock.patch.dict(os.environ, {"ARCHON_HOME": str(ah)}):
            got = ticket.protected_paths(self.wt1, self.board)
        for name in names:
            with self.subTest(name=name):
                self.assertIn(self.real(ah / name), got)
        self.assertNotIn(self.real(ah), got)
        fake_home = self.tmp / "user2"
        fake_home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(fake_home), "ARCHON_HOME": ""}):
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(str(fake_home / ".archon" / "config.yaml"), got)
        self.assertIn(str(fake_home / ".archon" / "archon.db"), got)
        # ARCHON_HOME の頭の ~ は Archon と同じく HOME に開く
        with mock.patch.dict(os.environ, {"HOME": str(fake_home), "ARCHON_HOME": "~/ah"}):
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(str(fake_home / "ah" / "config.yaml"), got)

    def test_worktree_under_archon_home_is_fine(self):
        """Archon の run の worktree（<家>/workspaces/<owner>/<repo>/worktrees/…）でも切符を書ける（家の中身を名指しで守るので
        入れ子の拒否に掛からない）"""
        ah = self.tmp / "archon-home"
        wt = ah / "workspaces" / "o" / "r" / "worktrees" / "wt3"
        wt.parent.mkdir(parents=True)
        git(self.main, "worktree", "add", "-q", "-b", "b3", str(wt))
        self.addCleanup(git, self.main, "worktree", "remove", "--force", str(wt))
        with mock.patch.dict(os.environ, {"ARCHON_HOME": str(ah)}):
            got = ticket.protected_paths(wt, self.board)
        self.assertIn(self.real(ah / "config.yaml"), got)
        self.assertNotIn(self.real(wt), got)

    def test_protected_has_own_dot_git_file(self):
        # linked worktree の .git は gitdir を指す 1 行のファイル。書き換えると後の git が別のリポジトリを見る
        self.assertTrue((self.wt1 / ".git").is_file())
        got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(self.real(self.wt1 / ".git"), got)
        got = ticket.protected_paths(self.main, self.board)
        self.assertIn(self.real(self.main / ".git"), got)

    def test_protected_follows_config_env(self):
        # 設定の置き場を環境変数で替えている時は、その先も守る
        xdg = self.tmp / "xdg"
        claude = self.tmp / "claude-conf"
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg), "CLAUDE_CONFIG_DIR": str(claude)}):
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertIn(str(xdg / "git"), got)
        self.assertIn(str(xdg / "gh"), got)
        self.assertIn(str(claude), got)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "CLAUDE_CONFIG_DIR": ""}):
            got = ticket.protected_paths(self.wt1, self.board)
        self.assertNotIn(str(xdg / "git"), got)
        self.assertNotIn(str(claude), got)

    def test_git_local_env_is_stripped(self):
        # git の「リポジトリに固有」の環境変数が外から漏れても、答えは cwd の worktree のもの
        other = self.tmp / "other"
        other.mkdir()
        git(other, "init", "-q")
        clean = ticket.protected_paths(self.wt1, self.board)
        leak = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other),
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": str(other)}
        with mock.patch.dict(os.environ, leak):
            self.assertEqual(ticket.protected_paths(self.wt1, self.board), clean)
        names = ticket._local_env_vars()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS",
                     "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY"):
            self.assertIn(name, names)

    def test_git_local_env_fallback(self):
        # git rev-parse --local-env-vars が引けない時は、既定の 4 つを外す
        with mock.patch.object(ticket.subprocess, "run", side_effect=OSError("no git")):
            self.assertEqual(set(ticket._local_env_vars()), set(ticket.GIT_ENV_FALLBACK))
        self.assertEqual(set(ticket.GIT_ENV_FALLBACK), {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"})

    def test_nested_worktree_raises(self):
        # 役の worktree が守る場所（ここでは元の作業ツリー）の中に入れ子なら、黙って塞がずに理由 1 行で止める
        repo = self.tmp / "nest"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a\n")
        git(repo, "add", "a.txt")
        git(repo, "commit", "-q", "-m", "init")
        inner = repo / ".worktrees" / "wt"
        git(repo, "worktree", "add", "-q", "-b", "in", str(inner))
        with self.assertRaises(ticket.TicketError) as cm:
            ticket.protected_paths(inner, self.board)
        self.assertNotIn("\n", str(cm.exception))
        self.assertIn(os.path.realpath(repo), str(cm.exception))
        # 盤面が役の worktree を含む時も同じ
        with self.assertRaises(ticket.TicketError):
            ticket.protected_paths(self.wt1, self.repo_tmp)

    def test_spellings_private_prefix(self):
        # macOS の /var・/tmp・/etc は /private の下への symlink。どちらの綴りも同じ場所なら両方を返す
        if os.path.realpath("/var") != "/private/var":
            self.skipTest("/var が /private/var への symlink でない")
        for spelled in ("/private/var/folders/x/y", "/var/folders/x/y", "/private/tmp/z", "/tmp/z"):
            with self.subTest(spelled=spelled):
                got = ticket._spellings(spelled)
                bare = spelled[len("/private"):] if spelled.startswith("/private/") else spelled
                self.assertEqual(got, {bare, "/private" + bare})
        self.assertEqual(ticket._spellings("/Users/u/x"), {"/Users/u/x"})
        self.assertEqual(ticket._spellings("/private/nope/x"), {"/private/nope/x"}, "実在の symlink でない /private は足さない")

    def test_git_derived_paths_have_both_spellings(self):
        # git は realpath（/private/var/...）で返すが、/var/... の綴りも入る
        if not str(self.repo_tmp).startswith(("/var/", "/tmp/")) or self.real(self.repo_tmp) == str(self.repo_tmp):
            self.skipTest("使い捨てのリポジトリが /var・/tmp の綴りの下にない")
        got = ticket.protected_paths(self.wt1, self.board)
        for p in (self.wt2, self.main, self.main / ".git", self.main / ".git" / "worktrees" / "wt1", self.wt1 / ".git"):
            with self.subTest(p=str(p)):
                self.assertIn(str(p), got)
                self.assertIn(self.real(p), got)

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
