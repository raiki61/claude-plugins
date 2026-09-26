"""works/dev/ の開発の殻（固定した版の Archon を隔離して回す・使い捨ての対象を作る）の骨組みの検査。

archon 本体のダウンロードやネットワークは伴わない範囲だけを見る:
- mktarget.sh が作る使い捨ての対象に、pack が dev 用ファイル抜き・ゴミファイル抜きで入り、
  全部 commit 済みで、仕込んだバグのせいでテストが赤になること。
- archon.sh が、キャッシュにある実行ファイルの sha256 が違えばネットワークに出ずに拒み、
  そのファイルを消せば取り直すと 1 行で案内すること（消すのは人。archon.sh は消さない）。
- archon.sh の認証に既定の口座が無いこと: CLAUDE_CODE_OAUTH_TOKEN があればそれ、無ければ
  WORKS_KEYCHAIN_ITEM の名の keychain の項目（ここでは偽物に差し替える。本物には触らない）を
  HOME を隔離する前の元の HOME で読み、どちらも無ければ 1 行の案内で止まること（Ruling R20）。
- archon.sh が、認証を使う実行のたびに隔離した Archon の設定へ模型（WORKS_DEV_MODEL。既定 opus）を書き、
  TITLE_GENERATION_MODEL も（設定していなければ）同じにすること。WORKS_DEV_NO_AUTH=1 では書かないこと
  （偽の shasum で確かめを通し、偽の実行ファイルまで exec させて見る）。
- archon.sh・mktarget.sh・real-run.sh が、WORKS_DEV_HOME・対象・origin が Claude Code の一時フォルダ
  （/private/tmp/claude-* か /tmp/claude-*。サンドボックスの Bash がそこへ書ける穴）の下に解けるとき、
  何も作らずに 1 行の理由で終了コード 2 で止まること（symlink を辿った先で見る）。
- dogfood.sh（このリポジトリ自身を対象にラインを回す）が、今の HEAD を clone して pack を枝 dogfood-base に commit し、
  <dir>/origin.git を origin（既定の枝は dogfood-base）にして、clone の中で Archon（偽物）を正しい引数で呼ぶこと。
  認証が無い・置き場が Claude Code の一時フォルダの下のときは何も作らずに止まること。
- check.sh が works 自身の工程（works/<d>/<d>.yaml）だけを 1 本ずつ validate し、`workflow test works` を回し
  （どちらも認証を読ませない）、
  どれか 1 つでも赤なら終了コード 1 になること（Archon は偽物の記録係に差し替える。Ruling R10）。
  validate する工程が 0 本（名前の合わない YAML だけ・YAML 無し）の時も、glob の型の文字列を
  validate に渡さずに終了コード 1 になること。

試験の一時フォルダの基は setUpModule が 1 か所で決める。TMPDIR（tempfile の既定）が Claude Code の一時フォルダの
下なら、そのままでは置き場が全部 guard.sh に拒まれて殻の振る舞いまで届かないので、リポジトリの根の
.works-test-tmp/（gitignore。works/ の中は _dogfood が自分を写し込むので避ける）へ移す。guard.sh は緩めない。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"

# guard.sh の works_dev_refuse_claude_tmp が拒む所（realpath で見る）
CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")
BASETEMP_PARENT = ROOT.parent / ".works-test-tmp"
_saved = {}


def in_claude_tmp(path):
    return os.path.realpath(path).startswith(CLAUDE_TMP)


def setUpModule():
    """試験の一時フォルダ（TemporaryDirectory() の既定と、子へ渡す TMPDIR）を Claude Code の一時フォルダの外に置く。"""
    _saved["tempdir"] = tempfile.tempdir
    _saved["origin"] = tempfile.gettempdir()
    if in_claude_tmp(_saved["origin"]):
        BASETEMP_PARENT.mkdir(exist_ok=True)
        _saved["base"] = tempfile.mkdtemp(prefix="run-", dir=str(BASETEMP_PARENT))   # 同時に回る別の run と分ける
        tempfile.tempdir = _saved["base"]


def tearDownModule():
    base = _saved.pop("base", None)
    tempfile.tempdir = _saved.get("tempdir")
    if base:
        shutil.rmtree(base, ignore_errors=True)
        try:
            BASETEMP_PARENT.rmdir()   # 空の時だけ消える
        except OSError:
            pass


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
        """壊れたキャッシュは 1 行で拒み、消せば取り直すと案内する。消すのは人（黙って消さない）。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            dev_home = pathlib.Path(tmp_str)
            bin_dir = dev_home / "bin"
            bin_dir.mkdir(parents=True)
            cached = bin_dir / "archon-darwin-arm64"
            cached.write_bytes(b"not the real archon binary")

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
            lines = result.stderr.strip().splitlines()
            self.assertEqual(len(lines), 1, result.stderr)
            self.assertIn("sha256", lines[0])
            self.assertIn(str(cached), lines[0])
            self.assertIn("消して", lines[0])
            self.assertIn("取り直す", lines[0])
            self.assertEqual(cached.read_bytes(), b"not the real archon binary")   # 消さない

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

    def _exec_archon_sh(self, **overrides):
        """偽の shasum（固定の sha256 を出す）で確かめを通し、キャッシュの偽の実行ファイル（受けた
        TITLE_GENERATION_MODEL と引数を記録する）まで exec させる。本物の Archon もネットワークも要らない。
        戻り値は (結果, 隔離した Archon の config.yaml の中身か None, 偽の実行ファイルが記録した行)。"""
        expected = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"', (DEV / "archon.sh").read_text(), re.M).group(1)
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            seen = tmp / "seen.txt"
            fake_archon = dev_home / "bin" / "archon-darwin-arm64"
            fake_archon.write_text(
                "#!/bin/sh\n"
                f'printf \'%s\\n\' "${{TITLE_GENERATION_MODEL-(unset)}}" "$*" > "{seen}"\n'
            )
            fake_bin = tmp / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{expected}  $3"\n')
            (fake_bin / "shasum").chmod(0o755)
            env = dict(os.environ)
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH",
                         "WORKS_DEV_MODEL", "TITLE_GENERATION_MODEL"):
                env.pop(name, None)
            env.update(WORKS_DEV_HOME=str(dev_home), PATH=str(fake_bin) + os.pathsep + env.get("PATH", ""))
            env.update(overrides)
            result = subprocess.run(["sh", str(DEV / "archon.sh"), "workflow", "run", "x"],
                                    capture_output=True, text=True, env=env)
            config = dev_home / "archon-home" / "config.yaml"
            self.assertNotIn("dummy-token-for-test", result.stdout + result.stderr)
            return (result, config.read_text() if config.exists() else None,
                    seen.read_text().splitlines() if seen.exists() else None)

    def test_archon_sh_pins_model_when_using_auth(self):
        """認証を使う実行は毎回、隔離した Archon の設定に模型（既定 opus）を書き、題の生成の模型も揃える。
        書かないと Claude CLI の既定の模型で黙って回る（real-run.sh を通さず archon.sh を直に打った時）。"""
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("assistants:\n  claude:\n    model: opus\n", config)
        self.assertEqual(seen, ["opus", "workflow run x"])

    def test_archon_sh_model_follows_works_dev_model(self):
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                                                    WORKS_DEV_MODEL="sonnet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: sonnet\n", config)
        self.assertEqual(seen[0], "sonnet")

    def test_archon_sh_keeps_title_generation_model_if_set(self):
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                                                    TITLE_GENERATION_MODEL="haiku")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    model: opus\n", config)
        self.assertEqual(seen[0], "haiku")

    def test_archon_sh_no_auth_does_not_pin_model(self):
        """認証の要らない道（テスト・validate・workflow test）は変えない: 設定を書かず、模型も要らない。"""
        result, config, seen = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(config)
        self.assertEqual(seen, ["(unset)", "workflow run x"])

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

    def _run_check(self, fail_on="", works_layout=None):
        """check.sh を偽の Archon（引数と cwd を記録し、引数に fail_on を含めば終了コード 1）で回す。

        works_layout を渡せば、works/dev を TMPDIR の下の works/dev に写し、works/ の下に
        {相対パス: 中身} の物だけを置いた写しの check.sh を回す。
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            check = DEV / "check.sh"
            if works_layout is not None:
                works = tmp / "works"
                shutil.copytree(DEV, works / "dev")
                for rel, text in works_layout.items():
                    (works / rel).parent.mkdir(parents=True, exist_ok=True)
                    (works / rel).write_text(text)
                check = works / "dev" / "check.sh"
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
            result = subprocess.run(["sh", str(check)], capture_output=True, text=True, env=env)
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

    def test_check_fails_when_no_workflow_is_validated(self):
        # 何も確かめずに緑を返さない（名前の合わない YAML だけ／YAML 無し）
        for label, layout in (("name-mismatch", {"blk-x/other.yaml": "name: other\n"}), ("no-yaml", {})):
            with self.subTest(label):
                result, calls = self._run_check(works_layout=layout)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("validate する工程が見つからない", result.stderr)
                args = [c[2] for c in calls]
                self.assertFalse([a for a in args if a.startswith("validate workflows")], args)
                self.assertIn("workflow test works", args)   # 赤でも残りは回す

    # ---- dogfood.sh（works 自身のリポジトリを対象にラインを回す）。AI の要らない所だけを偽の Archon で見る
    GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

    def _dogfood(self, tmp, *args, working_path="/wt/run-1", output_root="/out", runs_json=None, **env_kw):
        """TMPDIR の下に works/ を写した git の元（src）を作り、その写しの dogfood.sh を偽の Archon で回す。
        src には commit していない物（根の未追跡・works/ の中の書き換えと未追跡）を残す。
        偽の Archon は cwd・WORKS_DEV_NO_AUTH・引数（1 つずつ）をタブ区切りで記録し、`workflow runs --json` には
        runs_json（省略時は working_path・output_root の止まった run を 1 本）を返す。
        戻り値は (結果, 元のリポジトリ, 呼び出しの記録)。"""
        src = tmp / "src"
        shutil.copytree(ROOT, src / "works", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(src), *self.GIT_ID, "commit", "-q", "-m", "base"], check=True)
        # commit していない物は clone にも pack にも入らない
        (src / "uncommitted.txt").write_text("手元だけの変更\n")
        with (src / "works" / "archon-plugin.json").open("a") as f:
            f.write("手元だけの書き換え\n")
        (src / "works" / "darkfactory" / "scratch-untracked.txt").write_text("手元だけの未追跡\n")
        log = tmp / "calls.txt"
        fake = tmp / "fake-archon.sh"
        runs = runs_json or json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                  "working_path": str(working_path),
                                                  "output_root": str(output_root)}]})
        (tmp / "runs.json").write_text(runs)
        fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "$@"; echo; }} >> "{log}"\n'
            f'case "$*" in "workflow runs --json") cat "{tmp / 'runs.json'}" ;; esac\n'
            "exit 0\n"
        )
        env = self._env(TMPDIR=str(tmp), WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake),
                        CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true")
        env.pop("WORKS_DEV_NO_AUTH", None)
        for name, value in env_kw.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        result = subprocess.run(["sh", str(src / "works" / "dev" / "dogfood.sh"), *args],
                                capture_output=True, text=True, env=env)
        self.assertNotIn("dummy-token-for-test", result.stdout + result.stderr)
        calls = [line.rstrip("\t").split("\t") for line in log.read_text().splitlines()] if log.exists() else []
        return result, src, calls

    def test_dogfood_clones_head_commits_pack_and_runs_line(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            request = tmp / "req.json"
            request.write_text('[{"where": "x", "text": "y"}]\n')
            result, src, calls = self._dogfood(tmp, str(request), "python3 -m unittest -q", str(tmp / "dog"))
            self.assertEqual(result.returncode, 0, result.stderr)
            dog = (tmp / "dog").resolve()
            repo = dog / "repo"

            # 元の HEAD の上に、pack を置いた commit が 1 本だけ乗った枝 dogfood-base
            self.assertEqual(git(repo, "rev-parse", "--abbrev-ref", "HEAD"), "dogfood-base")
            self.assertEqual(git(repo, "rev-parse", "HEAD~1"), git(src, "rev-parse", "HEAD"))
            self.assertEqual(git(repo, "status", "--porcelain"), "")
            self.assertFalse((repo / "uncommitted.txt").exists())
            pack = repo / ".archon" / "workflows" / "works"
            # pack は clone した HEAD から写す（手元の works/ の書き換え・未追跡は入らない）
            self.assertEqual((pack / "archon-plugin.json").read_text(), (ROOT / "archon-plugin.json").read_text())
            self.assertFalse((pack / "darkfactory" / "scratch-untracked.txt").exists())
            self.assertTrue((pack / "archon-plugin.json").exists())
            self.assertTrue((pack / "darkfactory" / "darkfactory.yaml").exists())
            for d in ("tests", "dev", "docs"):
                self.assertFalse((pack / d).exists(), d)
            self.assertEqual(list(pack.rglob("__pycache__")), [])
            self.assertEqual(sorted(git(repo, "diff", "--name-only", "HEAD~1").splitlines()),
                             sorted(str(p.relative_to(repo)) for p in pack.rglob("*") if p.is_file()))

            # origin は <dir>/origin.git の裸のリポジトリで、既定の枝は dogfood-base（元のリポジトリの枝は持たない）
            self.assertEqual(pathlib.Path(git(repo, "remote", "get-url", "origin")).resolve(), dog / "origin.git")
            self.assertEqual(git(repo, "symbolic-ref", "refs/remotes/origin/HEAD"), "refs/remotes/origin/dogfood-base")
            self.assertEqual(git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/"),
                             "refs/remotes/origin/HEAD\nrefs/remotes/origin/dogfood-base")
            self.assertEqual(git(dog / "origin.git", "symbolic-ref", "HEAD"), "refs/heads/dogfood-base")
            self.assertEqual(git(dog / "origin.git", "rev-parse", "dogfood-base"), git(repo, "rev-parse", "HEAD"))

            # 依頼は <dir>/request.json に写し、その絶対パスを渡す。ラインは clone の中で認証付きで回し、
            # run の問い合わせは認証を読ませずに回す
            self.assertEqual((dog / "request.json").read_text(), request.read_text())
            self.assertEqual(calls, [
                [str(repo), "", "workflow", "run", "darkfactory",
                 "--input", f"request={dog / 'request.json'}", "--input", "test_cmd=python3 -m unittest -q"],
                [str(repo), "1", "workflow", "runs", "--json"],
            ])

            out = result.stdout
            self.assertIn("run id: run-1", out)
            self.assertIn("状態: paused", out)
            self.assertIn("/wt/run-1", out)
            for verb in ("approve", "reject", "resume"):
                self.assertIn(f"workflow {verb} run-1", out)
            self.assertIn("WORKS_DEV_MODEL=opus", out)
            self.assertIn(f"git -C {src.resolve()} apply /out/artifacts/runs/run-1/board/fix.diff", out)
            self.assertNotIn("注意", out)   # 差分も worktree も .archon/ に触れていない

    def test_dogfood_warns_when_fix_touches_pack_copy(self):
        """修正が works/ でなく pack の写し（.archon/workflows/works）を書き換えたら、取り込まないよう 1 行で注意する。
        関所では worktree の変更で、審査の後は fix.diff で見る。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            wt = tmp / "wt"
            (wt / ".archon" / "workflows" / "works").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(wt)], check=True)
            (wt / ".archon" / "workflows" / "works" / "a.yaml").write_text("x\n")
            subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(wt), *self.GIT_ID, "commit", "-q", "-m", "base"], check=True)
            board = tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
            board.mkdir(parents=True)
            cases = {
                "worktree（関所で止まっている間）": ("wt", None),
                "fix.diff（審査の後）": (None, "diff --git a/.archon/workflows/works/a.yaml b/.archon/workflows/works/a.yaml\n"),
            }
            for why, (touch_wt, diff) in cases.items():
                with self.subTest(why):
                    (wt / ".archon" / "workflows" / "works" / "a.yaml").write_text("y\n" if touch_wt else "x\n")
                    (board / "fix.diff").unlink(missing_ok=True)
                    if diff:
                        (board / "fix.diff").write_text(diff)
                    shutil.rmtree(tmp / "src", ignore_errors=True)
                    result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / why),
                                                       working_path=wt, output_root=tmp / "out")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    notes = [l for l in result.stdout.splitlines() if "注意" in l]
                    self.assertEqual(len(notes), 1, result.stdout)
                    self.assertIn(".archon/", notes[0])

    def test_dogfood_refuses_used_dir(self):
        """<dir> に前の回の clone か依頼が在れば、何も書かずに 1 行で止まる（前の回の依頼を上書きしない）。"""
        for used in ("repo", "request.json", "origin.git"):
            with self.subTest(used), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                (tmp / "req.json").write_text("[]\n")
                dog = tmp / "dog"
                dog.mkdir()
                if used == "request.json":
                    (dog / used).write_text("前の回の依頼\n")
                else:
                    (dog / used).mkdir()
                result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(dog))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
                self.assertIn(used, result.stderr)
                self.assertEqual(sorted(p.name for p in dog.iterdir()), [used])
                if used == "request.json":
                    self.assertEqual((dog / used).read_text(), "前の回の依頼\n")
                self.assertEqual(calls, [])

    def test_dogfood_names_itself_when_run_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               runs_json='{"runs": []}')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dogfood.sh: darkfactory の run が見つからない", result.stderr)

    def test_dogfood_default_dir_is_under_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true")
            self.assertEqual(result.returncode, 0, result.stderr)
            made = list(tmp.glob("works-dogfood.*"))
            self.assertEqual(len(made), 1, made)
            self.assertEqual(calls[0][0], str((made[0] / "repo").resolve()))

    def test_dogfood_stops_without_auth_before_cloning(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               CLAUDE_CODE_OAUTH_TOKEN=None)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
            self.assertIn("WORKS_KEYCHAIN_ITEM", result.stderr)
            self.assertFalse((tmp / "dog").exists())
            self.assertEqual(calls, [])

    def test_dogfood_refuses_claude_tmp(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            cases = {
                "置き場": ([self.HOLE], {}),
                "WORKS_DEV_HOME": ([str(tmp / "dog")], {"WORKS_DEV_HOME": self.HOLE}),
                "既定の置き場（TMPDIR）": ([], {"TMPDIR": "/private/tmp/claude-works-guard-test-0"}),
            }
            for why, (dir_arg, env) in cases.items():
                with self.subTest(why):
                    result, src, calls = self._dogfood(tmp / why, str(tmp / "req.json"), "true", *dir_arg, **env)
                    self.assert_guarded(result, tmp / "dog", "/private/tmp/claude-works-guard-test-0")
                    self.assertEqual(calls, [])

    def test_dogfood_usage(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            result, src, calls = self._dogfood(tmp, "only-one-arg")
            self.assertEqual(result.returncode, 2)
            self.assertIn("usage: dogfood.sh", result.stderr)
            self.assertEqual(calls, [])

    def test_positive_path_reaches_shell_when_tmpdir_in_claude_tmp(self):
        """TMPDIR が Claude Code の一時フォルダの下でも、正の道の試験が guard.sh に拒まれず緑になる。"""
        origin = _saved["origin"]
        try:
            if in_claude_tmp(origin):
                hole = tempfile.mkdtemp(prefix="works-tmpdir-", dir=origin)
            else:
                hole = tempfile.mkdtemp(prefix="claude-works-tmpdir-", dir="/private/tmp")
        except OSError as e:
            self.skipTest(f"Claude Code の一時フォルダの下に試しのフォルダを作れない（{e}）")
        try:
            self.assertTrue(in_claude_tmp(hole), hole)
            r = subprocess.run(
                ["python3", "-m", "unittest", "test_dev.TestDevShell.test_mktarget_places_pack_without_dev_files"],
                cwd=str(pathlib.Path(__file__).resolve().parent), capture_output=True, text=True,
                env=dict(os.environ, TMPDIR=hole, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("OK", r.stderr)
        finally:
            shutil.rmtree(hole, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
