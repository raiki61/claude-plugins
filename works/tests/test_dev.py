"""works/dev/ の開発の殻（固定した版の Archon を隔離して回す・使い捨ての対象を作る）の骨組みの検査。

archon 本体のダウンロードやネットワークは伴わない範囲だけを見る:
- mktarget.sh が作る使い捨ての対象に、pack が dev 用ファイル抜き・ゴミファイル抜きで入り、
  全部 commit 済みで、仕込んだバグのせいでテストが赤になること。
- archon.sh が、キャッシュにある実行ファイルの sha256 が違えばネットワークに出ずに拒むこと。
- archon.sh が Archon を UV_NO_CONFIG=1 で起こすこと（script の節の uv に対象の uv の設定を読ませない）。
- archon.sh の認証に既定の口座が無いこと: CLAUDE_CODE_OAUTH_TOKEN があればそれ、無ければ
  WORKS_KEYCHAIN_ITEM の名の keychain の項目（ここでは偽物に差し替える。本物には触らない）を
  HOME を隔離する前の元の HOME で読み、どちらも無ければ 1 行の案内で止まること（Ruling R20）。
- archon.sh・mktarget.sh・real-run.sh が、WORKS_DEV_HOME・対象・origin が Claude Code の一時フォルダ
  （/private/tmp/claude-* か /tmp/claude-*。サンドボックスの Bash がそこへ書ける穴）の下に解けるとき、
  何も作らずに 1 行の理由で終了コード 2 で止まること（symlink を辿った先で見る）。
- check.sh が works 自身の工程（works/<d>/<d>.yaml）だけを 1 本ずつ validate し、`workflow test works` を回し
  （どちらも認証を読ませない）、
  どれか 1 つでも赤なら終了コード 1 になること（Archon は偽物の記録係に差し替える。Ruling R10）。
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"


def git(cwd, *args):
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def run_tests(cwd):
    """対象リポジトリの中身（target-seed の写し）を unittest discover で回す。"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


class TestDevShell(unittest.TestCase):
    def test_mktarget_places_pack_without_dev_files(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            out = subprocess.run(
                ["sh", str(DEV / "mktarget.sh"), str(tmp)],
                capture_output=True,
                text=True,
                check=True,
            )
            printed = pathlib.Path(out.stdout.strip())
            self.assertEqual(printed.resolve(), tmp.resolve())

            pack = tmp / ".archon" / "workflows" / "works"
            self.assertTrue((pack / "archon-plugin.json").exists())
            self.assertTrue((pack / ".shared" / "core" / "COPIED_FROM").exists())
            for d in ("tests", "dev", "docs"):
                self.assertFalse((pack / d).exists())
            self.assertEqual(list(pack.rglob("__pycache__")), [])
            self.assertEqual(list(pack.rglob(".DS_Store")), [])
            self.assertEqual(git(tmp, "status", "--porcelain"), "")  # 全部 commit 済み
            self.assertEqual(run_tests(tmp).returncode, 1)  # 仕込んだバグで赤

    def test_archon_sh_refuses_wrong_checksum(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            dev_home = pathlib.Path(tmp_str)
            bin_dir = dev_home / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "archon-darwin-arm64").write_bytes(b"not the real archon binary")

            env = dict(os.environ)
            env["WORKS_DEV_HOME"] = str(dev_home)
            env["WORKS_DEV_NO_AUTH"] = "1"

            result = subprocess.run(
                ["sh", str(DEV / "archon.sh"), "version"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("sha256", result.stderr)

    def test_archon_sh_runs_archon_with_uv_no_config(self):
        # script の節の uv に対象の [tool.uv]・uv.toml を読ませない（tests/test_script_headers.py。README）。
        # 偽の shasum が固定した sha256 を返し、偽の実行ファイルが受け取った環境を書き出す（本物の実行ファイルは要らない）
        pinned = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"$', (DEV / "archon.sh").read_text(), re.M).group(1)
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            dump = tmp / "env.txt"
            (dev_home / "bin" / "archon-darwin-arm64").write_text(f'#!/bin/sh\nenv > "{dump}"\n')
            fake_bin = tmp / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{pinned}  $3"\n')
            (fake_bin / "shasum").chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k not in ("UV_NO_CONFIG", "CLAUDE_CODE_OAUTH_TOKEN")}
            env.update(WORKS_DEV_HOME=str(dev_home), WORKS_DEV_NO_AUTH="1",
                       PATH=str(fake_bin) + os.pathsep + env.get("PATH", ""))
            r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True, env=env,
                               cwd=tmp_str)
            self.assertEqual(r.returncode, 0, r.stderr)
            seen = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line)
            self.assertEqual(seen.get("UV_NO_CONFIG"), "1")

    def _run_archon_sh_with_fake_security(self, fake_token="dummy-token-for-test", **overrides):
        """偽の `security`（呼ばれた時の $HOME と引数を記録し、偽のトークンを出す）を PATH の先頭に置いて archon.sh を回す。

        本物の keychain には一切触れない。実行ファイルの中身は意図的に違うものにしてあるので、
        認証の段を抜ければ sha256 の確かめで exit 1 になる（本物の 77MB の実行ファイルは要らない）。
        overrides の値が None の変数は環境から外す。戻り値は (結果, 呼ばれた時の $HOME, 引数) で、
        security が呼ばれなければ後ろ 2 つは None。
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)

            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            (dev_home / "bin" / "archon-darwin-arm64").write_bytes(b"not the real archon binary")

            fake_bin = tmp / "fake-bin"
            fake_bin.mkdir()
            home_file = tmp / "security-home.txt"
            args_file = tmp / "security-args.txt"
            security_script = fake_bin / "security"
            security_script.write_text(
                "#!/bin/sh\n"
                f'echo "$HOME" > "{home_file}"\n'
                f'echo "$*" > "{args_file}"\n'
                f"echo '{fake_token}'\n"
            )
            security_script.chmod(0o755)

            env = dict(os.environ)
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)
            env["HOME"] = "/tmp/works-dev-test-original-home"  # 実在しなくてよい、印の値
            env["WORKS_DEV_HOME"] = str(dev_home)
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            for name, value in overrides.items():
                if value is None:
                    env.pop(name, None)
                else:
                    env[name] = value

            result = subprocess.run(
                ["sh", str(DEV / "archon.sh"), "version"],
                capture_output=True,
                text=True,
                env=env,
            )
            home = home_file.read_text().strip() if home_file.exists() else None
            args = args_file.read_text().strip() if args_file.exists() else None
            # トークンは画面にも記録にも出さない。
            self.assertNotIn("dummy-token-for-test", result.stdout + result.stderr)
            return result, home, args

    def test_archon_sh_reads_named_keychain_item_before_home_is_isolated(self):
        """WORKS_KEYCHAIN_ITEM の名の keychain の項目（偽物）を、HOME を隔離する前の元の HOME で読むこと。"""
        result, home, args = self._run_archon_sh_with_fake_security(WORKS_KEYCHAIN_ITEM="some-item-for-test")
        self.assertEqual(home, "/tmp/works-dev-test-original-home")
        self.assertEqual(args, "find-generic-password -s some-item-for-test -w")
        # 中身の違う実行ファイルなので、keychain を読んだ後の sha256 の確かめで落ちる。
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def test_archon_sh_prefers_token_env_over_keychain(self):
        result, home, args = self._run_archon_sh_with_fake_security(
            CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", WORKS_KEYCHAIN_ITEM="some-item-for-test"
        )
        self.assertIsNone(args)  # keychain は読まない
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def test_archon_sh_has_no_default_account(self):
        """トークンも keychain の項目名も無ければ、既定の口座を読まずに 1 行の案内で止まること。"""
        result, home, args = self._run_archon_sh_with_fake_security()
        self.assertIsNone(args)  # 既定の項目名で keychain を読みに行かない
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("sha256", result.stderr)  # 実行ファイルの確かめより前で止まる
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        for word in ("CLAUDE_CODE_OAUTH_TOKEN", "claude setup-token", "WORKS_KEYCHAIN_ITEM"):
            self.assertIn(word, lines[0])

    def test_archon_sh_stops_when_keychain_item_is_empty(self):
        """keychain の項目が空の値を返したら、空のトークンを渡さずに同じ 1 行の案内で止まること。"""
        result, home, args = self._run_archon_sh_with_fake_security(
            fake_token="", WORKS_KEYCHAIN_ITEM="some-item-for-test"
        )
        self.assertEqual(args, "find-generic-password -s some-item-for-test -w")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("sha256", result.stderr)  # 実行ファイルの確かめより前で止まる
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        for word in ("CLAUDE_CODE_OAUTH_TOKEN", "claude setup-token", "WORKS_KEYCHAIN_ITEM"):
            self.assertIn(word, lines[0])

    def test_archon_sh_no_auth_skips_auth(self):
        result, home, args = self._run_archon_sh_with_fake_security(WORKS_DEV_NO_AUTH="1")
        self.assertIsNone(args)
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def test_real_run_stops_without_auth_before_making_target(self):
        """real-run.sh（費用の掛かる実走）は、認証が無ければ対象を作る前に 1 行の案内で止まること。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            env = dict(os.environ, WORKS_DEV_HOME=str(tmp / "dev-home"))
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)
            result = subprocess.run(
                ["sh", str(DEV / "real-run.sh"), str(tmp / "target")],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
            self.assertIn("WORKS_KEYCHAIN_ITEM", result.stderr)
            self.assertFalse((tmp / "target").exists())
            self.assertFalse((tmp / "dev-home").exists())   # 設定も書かない

    # ---- Claude Code の一時フォルダの下を拒む（サンドボックスの穴。設計書 7 節）
    HOLE = "/private/tmp/claude-works-guard-test-0/x"   # 作らない（拒むのは作る前）

    def assert_guarded(self, result, *made):
        self.assertEqual(result.returncode, 2, result.stderr)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertIn("/private/tmp/claude-", lines[0])
        self.assertNotIn("sha256", result.stderr)
        for p in made:
            self.assertFalse(pathlib.Path(p).exists(), p)

    def _env(self, **kw):
        env = dict(os.environ)
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM"):
            env.pop(name, None)
        env.update(kw)
        return env

    def test_archon_sh_refuses_dev_home_in_claude_tmp(self):
        for home in (self.HOLE, "/tmp/claude-works-guard-test-0/x"):   # /tmp は macOS では /private/tmp への symlink
            with self.subTest(home):
                r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True,
                                   env=self._env(WORKS_DEV_HOME=home, WORKS_DEV_NO_AUTH="1"))
                self.assert_guarded(r, "/private/tmp/claude-works-guard-test-0")

    def test_archon_sh_refuses_dev_home_through_symlink(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            link = pathlib.Path(tmp_str) / "link"
            link.symlink_to("/private/tmp")
            r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True,
                               env=self._env(WORKS_DEV_HOME=str(link / "claude-works-guard-test-0" / "x"),
                                             WORKS_DEV_NO_AUTH="1"))
            self.assert_guarded(r, "/private/tmp/claude-works-guard-test-0")

    def test_archon_sh_refuses_cwd_in_claude_tmp(self):
        try:
            cwd = tempfile.mkdtemp(prefix="claude-works-guard-", dir="/private/tmp")
        except OSError as e:
            self.skipTest(f"/private/tmp に試しのフォルダを作れない（{e}）")
        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True, cwd=cwd,
                                   env=self._env(WORKS_DEV_HOME=str(pathlib.Path(tmp_str) / "dev-home"),
                                                 WORKS_DEV_NO_AUTH="1"))
                self.assert_guarded(r, pathlib.Path(tmp_str) / "dev-home")
        finally:
            shutil.rmtree(cwd)

    def test_mktarget_refuses_target_in_claude_tmp(self):
        r = subprocess.run(["sh", str(DEV / "mktarget.sh"), self.HOLE], capture_output=True, text=True,
                           env=self._env())
        self.assert_guarded(r, "/private/tmp/claude-works-guard-test-0")

    def test_real_run_refuses_claude_tmp(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            link = tmp / "link"
            link.symlink_to("/private/tmp")
            cases = {
                "WORKS_DEV_HOME": ([str(tmp / "target")], {"WORKS_DEV_HOME": self.HOLE}),
                "対象": ([self.HOLE], {"WORKS_DEV_HOME": str(tmp / "dev-home")}),
                "対象（symlink の先）": ([str(link / "claude-works-guard-test-0" / "t")],
                                        {"WORKS_DEV_HOME": str(tmp / "dev-home")}),
                "既定の対象（TMPDIR）": ([], {"WORKS_DEV_HOME": str(tmp / "dev-home"),
                                           "TMPDIR": "/private/tmp/claude-works-guard-test-0"}),
            }
            for why, (args, env) in cases.items():
                with self.subTest(why):
                    # 認証が在っても（偽のトークン）、拒むのは認証の確かめと対象を作るより前
                    r = subprocess.run(["sh", str(DEV / "real-run.sh"), *args], capture_output=True, text=True,
                                       env=self._env(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", **env))
                    self.assert_guarded(r, tmp / "target", tmp / "dev-home", "/private/tmp/claude-works-guard-test-0")
                    self.assertNotIn("dummy-token-for-test", r.stdout + r.stderr)

    def test_real_run_refuses_origin_in_claude_tmp(self):
        # 対象は穴の外でも、origin（<対象>.origin.git）が穴の下の symlink に解けるなら拒む
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "t.origin.git").symlink_to("/private/tmp/claude-works-guard-test-0")
            r = subprocess.run(["sh", str(DEV / "real-run.sh"), str(tmp / "t")], capture_output=True, text=True,
                               env=self._env(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                                             WORKS_DEV_HOME=str(tmp / "dev-home")))
            self.assert_guarded(r, tmp / "t", tmp / "dev-home")

    def _run_check(self, fail_on=""):
        """check.sh を偽の Archon（引数と cwd を記録し、引数に fail_on を含めば終了コード 1）で回す"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            log = tmp / "calls.txt"
            fake = tmp / "fake-archon.sh"
            fake.write_text(
                "#!/bin/sh\n"
                f'printf \'%s|%s|%s\\n\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "$*" >> "{log}"\n'
                f'case "$*" in *"{fail_on or "@@never@@"}"*) exit 1 ;; esac\n'
                "exit 0\n"
            )
            # 偽物を使わず本物の archon.sh へ落ちても、ネットワークに出ずに sha256 で止まるようにしておく
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            (dev_home / "bin" / "archon-darwin-arm64").write_bytes(b"not the real archon binary")
            env = dict(os.environ, WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp), WORKS_DEV_HOME=str(dev_home))
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)   # 認証が無くても回ること
            result = subprocess.run(["sh", str(DEV / "check.sh")], capture_output=True, text=True, env=env)
            calls = [line.split("|", 2) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_check_validates_only_works_workflows(self):
        ours = sorted(p.parent.name for p in ROOT.glob("*/*.yaml") if p.stem == p.parent.name)
        self.assertIn("blk-judge", ours)
        result, calls = self._run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = [c[2] for c in calls]
        self.assertEqual(args, [f"validate workflows {n}" for n in ours] + ["workflow test works"])
        for cwd, no_auth, a in calls:
            with self.subTest(a):
                self.assertIn("works-check", cwd)   # 使い捨ての対象の中で回す
                self.assertEqual(no_auth, "1")   # validate も workflow test（dry-run）も provider に触れない

    def test_check_fails_when_one_workflow_is_red(self):
        result, calls = self._run_check(fail_on="validate workflows blk-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("workflow test works", [c[2] for c in calls])   # 赤でも残りは回す


if __name__ == "__main__":
    unittest.main()
