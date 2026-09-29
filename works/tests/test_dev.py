"""works/dev/ の開発の殻（固定した版の Archon を隔離して回す・使い捨ての対象を作る）の骨組みの検査。

archon 本体のダウンロードやネットワークは伴わない範囲だけを見る:
- mktarget.sh が作る使い捨ての対象に、pack が dev 用ファイル抜き・ゴミファイル抜きで入り、
  全部 commit 済みで、仕込んだバグのせいでテストが赤になること。
- archon.sh が、キャッシュにある実行ファイルの sha256 が違えばネットワークに出ずに拒み、
  そのファイルを消せば取り直すと 1 行で案内すること（消すのは人。archon.sh は消さない）。
- archon.sh の認証が利用者自身の物だけを拾うこと（順は起こし役 .shared/core/auth_launch.py の 1 か所）: 名指しの
  WORKS_KEYCHAIN_ITEM の keychain の項目があればそれ、無ければ本流の claude_auth.auth_env の順（受け継いだ認証・
  CLAUDE_KEYCHAIN_SERVICE・設定の置き場から導いた claude-code-oauth-<名>）、それでも足せなければ CLAUDE_CONFIG_DIR から導いた
  Claude Code 自身の keychain の項目（どれも偽物に差し替える。本物には触らない）を HOME を隔離する前の元の HOME で読み、
  拾った出どころの名だけを出し（値は出さない）、どれも無ければ 1 行の案内で止まること（Ruling R20 の「黙ってどこかの口座で回さない」）。
- archon.sh が、認証を使う実行のたびに隔離した Archon の設定へ模型（WORKS_DEV_MODEL。既定 opus）を書き、
  TITLE_GENERATION_MODEL も（設定していなければ）同じにすること。WORKS_DEV_NO_AUTH=1 では書かないこと
  （偽の shasum で確かめを通し、偽の実行ファイルまで exec させて見る）。
- archon.sh が、認証を使う実行で対象（cwd）の根を利用者の mise が信頼済みの時だけ（偽の mise の trust --show を隔離の前の
  HOME で読む）、run の worktree の置き場を MISE_TRUSTED_CONFIG_PATHS に足すこと（前の値は残す）。
- lib.sh works_dev_show_run の差分が、周の中の commit で入った .gitignore に当たる追跡ファイルを足した行として載せること。
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
下か（guard.sh の works_dev_refuse_claude_tmp を正本として呼んで決める）なら、そのままでは置き場が全部 guard.sh に
拒まれて殻の振る舞いまで届かないので、リポジトリの根の .works-test-tmp/（gitignore。works/ の中は _dogfood が
自分を写し込むので避ける）へ移す。移す時は tempfile.tempdir と、子が継ぐ os.environ の TMPDIR を揃えて差し替え、
tearDownModule で両方を戻す。guard.sh は緩めない。
"""
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gitkit import GIT_ID, committed_copy, git
import hermetic  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"

BASETEMP_PARENT = ROOT.parent / ".works-test-tmp"
_saved = {}


def in_claude_tmp(path):
    """path を guard.sh の works_dev_refuse_claude_tmp が拒むか（正本を呼び、終了コード 2 なら真）。"""
    r = subprocess.run(
        ["sh", "-c", '. "$1"; works_dev_refuse_claude_tmp in_claude_tmp path "$2"', "_", str(DEV / "guard.sh"), str(path)],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 2):
        raise RuntimeError(f"guard.sh の判定が終了コード {r.returncode} で終わった: {r.stderr}")
    return r.returncode == 2


def claude_tmp_dir(prefix):
    """Claude Code の一時フォルダの綴り（/private/tmp/claude-・/tmp/claude-）のうち、この OS で作れる方に試しのフォルダを作る。
    /private/tmp は macOS にしか無い"""
    errs = []
    for base in ("/private/tmp", "/tmp"):
        try:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
        except OSError as e:
            errs.append(f"{base}: {e}")
    raise unittest.SkipTest(f"SKIP claude-tmp: Claude Code の一時フォルダの下に試しのフォルダを作れない（{'; '.join(errs)}）")


def setUpModule():
    """試験の一時フォルダ（TemporaryDirectory() の既定と、子へ渡す TMPDIR）を Claude Code の一時フォルダの外に置く。"""
    _saved["tempdir"] = tempfile.tempdir
    _saved["origin"] = tempfile.gettempdir()
    if in_claude_tmp(_saved["origin"]):
        BASETEMP_PARENT.mkdir(exist_ok=True)
        _saved["base"] = tempfile.mkdtemp(prefix="run-", dir=str(BASETEMP_PARENT))   # 同時に回る別の run と分ける
        tempfile.tempdir = _saved["base"]
        _saved["environ"] = mock.patch.dict(os.environ, {"TMPDIR": _saved["base"]})   # 子が継ぐ TMPDIR も揃える
        _saved["environ"].start()


def tearDownModule():
    base = _saved.pop("base", None)
    environ = _saved.pop("environ", None)
    if environ:
        environ.stop()
    tempfile.tempdir = _saved.get("tempdir")
    if base:
        shutil.rmtree(base, ignore_errors=True)
        try:
            BASETEMP_PARENT.rmdir()   # 空の時だけ消える
        except OSError:
            pass


def run_tests(cwd):
    """対象リポジトリの中身（target-seed の写し）を unittest discover で回す。"""
    env = hermetic.child_env(PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
        cwd=str(cwd),
        capture_output=True,
        text=True, encoding="utf-8",
        env=env,
    )


class TestDevShell(unittest.TestCase):
    def test_mktarget_places_pack_without_dev_files(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            out = subprocess.run(
                ["sh", str(DEV / "mktarget.sh"), str(tmp)],
                capture_output=True,
                text=True, encoding="utf-8",
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
            # 出どころの控え（run ごとの版の控え versions.json が読む）: 写した元の works の commit と手元の書き換えの有無
            src = json.loads((pack / ".works-source.json").read_text(encoding="utf-8"))
            self.assertEqual(src["rev"], git(ROOT, "rev-parse", "HEAD"))
            self.assertEqual(src["dirty"], git(ROOT, "status", "--porcelain", "--", ".") != "")
            self.assertEqual(src["from"], str(ROOT))
            self.assertEqual(src["version"], json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"])
            self.assertEqual(git(tmp, "status", "--porcelain"), "")  # 全部 commit 済み
            self.assertEqual(run_tests(tmp).returncode, 1)  # 仕込んだバグで赤

    def _copy_pack_source(self, works_copy: pathlib.Path) -> tuple:
        """works_copy から works_dev_copy_pack で pack を写し、(出どころの控え, 写した pack の直下の名) を返す"""
        pack = works_copy.parent / "pack"
        subprocess.run(["sh", "-c", '. "$1" && works_dev_copy_pack "$2" "$3"', "_", str(DEV / "lib.sh"),
                        str(works_copy), str(pack)], check=True, capture_output=True, text=True, encoding="utf-8")
        return (json.loads((pack / ".works-source.json").read_text(encoding="utf-8")),
                sorted(p.name for p in pack.iterdir()))

    def test_copy_pack_from_plugin_cache_copy_is_honest(self):
        """works/ だけを写した置き場（Claude Code のプラグインのキャッシュの形。git の外・.in_use/ と .orphaned_at の印つき）から
        pack を写すと、出どころの控えは rev・dirty が null（分からない物を埋めない）で、版は plugin.json の version。
        キャッシュが別の git のリポジトリの中（設定の置き場を git で持つ人）でも、その commit を works の版と偽らない。
        Claude Code の印は pack に写さない"""
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
        for inside_repo in (False, True):
            with self.subTest(inside_repo=inside_repo), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                if inside_repo:
                    git(tmp, "init", "-q")
                    (tmp / "dotfile").write_text("x\n", encoding="utf-8")
                    git(tmp, "add", "dotfile")
                    git(tmp, "commit", "-q", "-m", "dotfiles")
                copy = tmp / "cache" / "raiki61" / "works" / version
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("tests", "__pycache__", ".git"))
                (copy / ".in_use").mkdir()
                (copy / ".in_use" / "12345").write_text("{}", encoding="utf-8")
                (copy / ".orphaned_at").write_text("1790054446372", encoding="utf-8")
                src, names = self._copy_pack_source(copy)
                self.assertEqual(src, {"rev": None, "dirty": None, "from": str(copy), "version": version})
                self.assertNotIn(".in_use", names)
                self.assertNotIn(".orphaned_at", names)
                self.assertIn(".shared", names)

    def test_archon_sh_refuses_wrong_checksum(self):
        """壊れたキャッシュは 1 行で拒み、消せば取り直すと案内する。消すのは人（黙って消さない）。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            dev_home = pathlib.Path(tmp_str)
            bin_dir = dev_home / "bin"
            bin_dir.mkdir(parents=True)
            cached = bin_dir / "archon-darwin-arm64"
            cached.write_bytes(b"not the real archon binary")

            env = hermetic.child_env()
            env["WORKS_DEV_HOME"] = str(dev_home)
            env["WORKS_DEV_NO_AUTH"] = "1"

            result = subprocess.run(
                ["sh", str(DEV / "archon.sh"), "version"],
                capture_output=True,
                text=True, encoding="utf-8",
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

            env = hermetic.child_env()
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
                text=True, encoding="utf-8",
                env=env,
            )
            home = home_file.read_text().strip() if home_file.exists() else None
            args = args_file.read_text().strip() if args_file.exists() else None
            # トークンは画面にも記録にも出さない。
            self.assertNotIn("dummy-token-for-test", result.stdout + result.stderr)
            return result, home, args

    def test_archon_sh_reads_named_keychain_item_before_home_is_isolated(self):
        """WORKS_KEYCHAIN_ITEM の名の keychain の項目（偽物）を、HOME を隔離する前の元の HOME で読むこと。"""
        result, home, args = self._run_archon_sh_with_fake_security(
            fake_token="sk-ant-oat01-dummy-token-for-test", WORKS_KEYCHAIN_ITEM="some-item-for-test")
        self.assertEqual(home, "/tmp/works-dev-test-original-home")
        self.assertEqual(args, "find-generic-password -s some-item-for-test -w")
        # 中身の違う実行ファイルなので、keychain を読んだ後の sha256 の確かめで落ちる。
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def test_archon_sh_named_keychain_item_beats_token_env(self):
        """名指し（WORKS_KEYCHAIN_ITEM）はその起動で利用者が明示した物なので、受け継いだ CLAUDE_CODE_OAUTH_TOKEN より先に
        読む（設計 2.6 順の形 1）。元の HOME で名指しの項目を読んでから sha256 の確かめへ進む"""
        result, home, args = self._run_archon_sh_with_fake_security(
            fake_token="sk-ant-oat01-dummy-token-for-test",
            CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", WORKS_KEYCHAIN_ITEM="some-item-for-test"
        )
        self.assertEqual(home, "/tmp/works-dev-test-original-home")
        self.assertEqual(args, "find-generic-password -s some-item-for-test -w")
        self.assertIn("WORKS_KEYCHAIN_ITEM", result.stderr)
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def test_archon_sh_reads_claude_codes_own_keychain_item(self):
        """トークンも名指しの項目も無く、本流の段（導いた claude-code-oauth-<名>）でも足せなければ、CLAUDE_CONFIG_DIR から導いた
        Claude Code 自身の項目を隔離の前の HOME で読み、拾えたら出どころの名だけを出す。それも空なら 1 行の案内で止まること。"""
        import hashlib
        cfg = "/tmp/works-dev-test-claude-config"
        own = "Claude Code-credentials-" + hashlib.sha256(cfg.encode("utf-8")).hexdigest()[:8]
        login = '{"claudeAiOauth": {"accessToken": "sk-ant-oat01-dummy-token-for-test"}}'
        result, home, args = self._run_archon_sh_with_fake_security(fake_token=login, CLAUDE_CONFIG_DIR=cfg)
        self.assertEqual(home, "/tmp/works-dev-test-original-home")
        self.assertEqual(args, f"find-generic-password -s {own} -w")
        self.assertEqual(result.returncode, 1)   # 拾えたので、実行ファイルの sha256 の確かめまで進む
        self.assertIn("sha256", result.stderr)
        self.assertIn(f"Claude Code の keychain の項目 {own}", result.stderr)
        result, home, args = self._run_archon_sh_with_fake_security(fake_token=login, CLAUDE_CONFIG_DIR=None)
        self.assertEqual(args, "find-generic-password -s Claude Code-credentials -w")
        self.assertIn("sha256", result.stderr)
        result, home, args = self._run_archon_sh_with_fake_security(fake_token="", CLAUDE_CONFIG_DIR=cfg)
        self.assertEqual(args, "find-generic-password -s Claude Code-credentials -w")   # 導いた 2 つを試した最後
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("sha256", result.stderr)  # 実行ファイルの確かめより前で止まる
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        for word in ("CLAUDE_CODE_OAUTH_TOKEN", "claude setup-token", "WORKS_KEYCHAIN_ITEM", own):
            self.assertIn(word, lines[0])
        result, home, args = self._run_archon_sh_with_fake_security(fake_token="not-a-claude-token", CLAUDE_CONFIG_DIR=cfg)
        self.assertNotEqual(result.returncode, 0)   # 形の違う値は渡さない
        self.assertNotIn("sha256", result.stderr)

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

    def test_no_auth_howto_names_existing_items_before_new_token(self):
        """認証が無い時の 1 行の案内は、keychain に既に在る項目を名指す口（WORKS_KEYCHAIN_ITEM・CLAUDE_KEYCHAIN_SERVICE）を、
        トークンを新しく作る案内（claude setup-token）より先に出す"""
        result, home, args = self._run_archon_sh_with_fake_security(fake_token="", CLAUDE_CONFIG_DIR=None)
        self.assertNotEqual(result.returncode, 0)
        lines = result.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        line = lines[0]
        for word in ("WORKS_KEYCHAIN_ITEM", "CLAUDE_KEYCHAIN_SERVICE", "claude setup-token"):
            self.assertIn(word, line)
        self.assertLess(line.index("WORKS_KEYCHAIN_ITEM"), line.index("claude setup-token"), line)
        self.assertLess(line.index("CLAUDE_KEYCHAIN_SERVICE"), line.index("claude setup-token"), line)

    def test_archon_sh_no_auth_skips_auth(self):
        result, home, args = self._run_archon_sh_with_fake_security(WORKS_DEV_NO_AUTH="1")
        self.assertIsNone(args)
        self.assertEqual(result.returncode, 1)
        self.assertIn("sha256", result.stderr)

    def _exec_archon_sh(self, prepare=None, cwd_in_tmp=None, **overrides):
        """偽の shasum（固定の sha256 を出す）で確かめを通し、キャッシュの偽の実行ファイル（受けた
        TITLE_GENERATION_MODEL と引数を記録する）まで exec させる。本物の Archon もネットワークも要らない。
        戻り値は (結果, 隔離した Archon の config.yaml の中身か None, 偽の実行ファイルが記録した行)。"""
        expected = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"', (DEV / "archon.sh").read_text(), re.M).group(1)
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            if prepare:
                prepare(dev_home)
            seen = tmp / "seen.txt"
            fake_archon = dev_home / "bin" / "archon-darwin-arm64"
            skills_seen = tmp / "skills.txt"
            settings_seen = tmp / "settings.txt"
            env_seen = tmp / "env.txt"
            mise_seen = tmp / "mise.txt"
            fake_archon.write_text(
                "#!/bin/sh\n"
                f'printf \'%s\\n\' "${{TITLE_GENERATION_MODEL-(unset)}}" "$*" > "{seen}"\n'
                f'ls "$CLAUDE_CONFIG_DIR/skills" > "{skills_seen}" 2>&1\n'
                f'cat "$CLAUDE_CONFIG_DIR/settings.json" > "{settings_seen}" 2>/dev/null || true\n'
                f'printf \'%s\\n\' "${{WORKS_ARCHON_VERSION-(unset)}}" "${{WORKS_CLAUDE_VERSION-(unset)}}" > "{env_seen}"\n'
                f'printf \'%s\\n\' "${{MISE_TRUSTED_CONFIG_PATHS-(unset)}}" > "{mise_seen}"\n'
            )
            fake_bin = tmp / "fake-bin"
            # 隔離した設定に coldwrite を入れる claude（dev/toolset.py が PATH から引く）は偽物（本物は起こさない）
            from test_toolset import make_user_config, write_fake_claude
            write_fake_claude(fake_bin)
            # mise も偽物（本物の利用者の信頼の控えは読まない）。trust --show は実物の mise 2026.9 と同じ
            # `<dir>: trusted|untrusted` の形で cwd を FAKE_MISE_TRUST の状態として出し（空なら何も出さない）、呼ばれた時の HOME を記録する
            mise_calls = tmp / "mise-calls.txt"
            (fake_bin / "mise").write_text(
                "#!/bin/sh\n"
                f'printf \'%s|%s\\n\' "$*" "$HOME" >> "{mise_calls}"\n'
                '[ "$1 $2" = "trust --show" ] && [ -n "${FAKE_MISE_TRUST:-}" ] && printf \'%s: %s\\n\' "$(pwd -P)" "$FAKE_MISE_TRUST"\n'
                "exit 0\n")
            (fake_bin / "mise").chmod(0o755)
            # 借りる物を取る利用者の設定（隔離の前の CLAUDE_CONFIG_DIR）も偽物（本物の利用者の設定は読まない）
            user_cfg = make_user_config(tmp / "user-claude-config")
            claude_calls = tmp / "claude-calls.jsonl"
            (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{expected}  $3"\n')
            (fake_bin / "shasum").chmod(0o755)
            env = hermetic.child_env()
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH",
                         "WORKS_DEV_MODEL", "TITLE_GENERATION_MODEL", "WORKS_REAL_CLAUDE", "CLAUDE_BIN_PATH",
                         "WORKS_DEV_ADAPTER", "MISE_TRUSTED_CONFIG_PATHS", "FAKE_MISE_TRUST",
                         "WORKS_CLAUDE_VERSION", "WORKS_ARCHON_VERSION"):
                env.pop(name, None)
            env.update(WORKS_DEV_HOME=str(dev_home), PATH=str(fake_bin) + os.pathsep + env.get("PATH", ""),
                       FAKE_CLAUDE_LOG=str(claude_calls), CLAUDE_CONFIG_DIR=str(user_cfg))
            env.update(overrides)
            result = subprocess.run(["sh", str(DEV / "archon.sh"), "workflow", "run", "x"],
                                    capture_output=True, text=True, encoding="utf-8", env=env,
                                    cwd=None if cwd_in_tmp is None else tmp / cwd_in_tmp)
            config = dev_home / "archon-home" / "config.yaml"
            self.assertNotIn("dummy-token-for-test", result.stdout + result.stderr)
            # exec した時の隔離した CLAUDE_CONFIG_DIR/skills の中身（test_archon_sh_installs_borrowed_skills が見る）
            self.skills_seen = skills_seen.read_text().split() if skills_seen.exists() else None
            self.settings_seen = (json.loads(settings_seen.read_text())
                                  if settings_seen.exists() and settings_seen.read_text() else None)
            self.env_seen = env_seen.read_text().splitlines() if env_seen.exists() else None
            self.mise_seen = mise_seen.read_text().strip() if mise_seen.exists() else None
            self.mise_calls = mise_calls.read_text().splitlines() if mise_calls.exists() else []
            self.workspaces = str((dev_home / "archon-home").resolve() / "workspaces")
            record = dev_home / "claude-config" / ".works-toolset.json"
            self.toolset_rec = json.loads(record.read_text()) if record.exists() else None
            self.user_cfg = user_cfg
            self.claude_calls = ([json.loads(ln)["argv"] for ln in claude_calls.read_text().splitlines()]
                                 if claude_calls.exists() else [])
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

    def test_archon_sh_trusts_run_worktrees_for_mise_only_when_target_root_is_trusted(self):
        """mise の信頼はパスに結び付き、run の worktree は隔離した家の下の新しいパス。対象（cwd）の根を利用者の mise が信頼済みの
        時だけ、隔離の前の HOME で読んで、run の worktree の置き場（<家>/archon-home/workspaces）を MISE_TRUSTED_CONFIG_PATHS に
        足す（前の値は残す）。未信頼・mise が何も出さない・認証の要らない道では足さない"""
        def target(dev_home):
            (dev_home.parent / "target").mkdir()
        auth = {"CLAUDE_CODE_OAUTH_TOKEN": "dummy-token-for-test"}
        result, _, _ = self._exec_archon_sh(prepare=target, cwd_in_tmp="target", FAKE_MISE_TRUST="trusted", **auth)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mise_seen, self.workspaces)
        self.assertEqual([c.split("|")[0] for c in self.mise_calls], ["trust --show"])
        self.assertEqual(self.mise_calls[0].split("|")[1], os.environ.get("HOME", ""))   # 隔離の前の HOME
        result, _, _ = self._exec_archon_sh(prepare=target, cwd_in_tmp="target", FAKE_MISE_TRUST="trusted",
                                            MISE_TRUSTED_CONFIG_PATHS="/somewhere", **auth)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mise_seen, "/somewhere:" + self.workspaces)
        for trust in ("untrusted", ""):
            result, _, _ = self._exec_archon_sh(prepare=target, cwd_in_tmp="target", FAKE_MISE_TRUST=trust, **auth)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.mise_seen, "(unset)", trust)
        result, _, _ = self._exec_archon_sh(prepare=target, cwd_in_tmp="target", FAKE_MISE_TRUST="trusted",
                                            WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mise_seen, "(unset)")
        self.assertEqual(self.mise_calls, [])

    def test_show_run_diff_keeps_ignored_tracked_file_committed_in_round(self):
        """lib.sh works_dev_show_run の差分は、一時の index を run の worktree の今の HEAD から組む。周の中の commit（周の頭の版
        base より後）で入った .gitignore に当たる追跡ファイルも、足した行として差分に載り、消す行にも抜けにもならない
        （base の木から組むと載らず、空の index から組むと base に在る追跡ファイルが消す行になる）"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            wt = tmp / "wt"
            committed_copy(wt, DEV / "target-seed")
            base = git(wt, "rev-parse", "HEAD")
            (wt / ".gitignore").write_text(".env*\n")
            (wt / ".env.example").write_text("KEY=\n")
            git(wt, "add", ".gitignore")
            git(wt, "add", "-f", ".env.example")
            git(wt, "commit", "-q", "-m", "周の中の commit")
            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
            board = tmp / "out" / "artifacts" / "runs" / "run-1" / "board" / "r1"
            board.mkdir(parents=True)
            (board / "start.json").write_text(json.dumps({"base_rev": base}))
            runs = tmp / "runs.json"
            runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                  "working_path": str(wt), "output_root": str(tmp / "out")}]}))
            fake = tmp / "archon.sh"
            fake.write_text(f'cat "{runs}"\n')
            diffs = tmp / "diffs"
            diffs.mkdir()
            r = subprocess.run(["sh", "-c", '. "$1"; works_dev_show_run t "$2" "$3" "$3" "$4"', "_",
                                str(DEV / "lib.sh"), str(fake), str(wt), str(diffs)],
                               capture_output=True, text=True, encoding="utf-8",
                               env={**{k: v for k, v in os.environ.items() if k not in ("WORKS_RUN_ID", "HERDR_ENV")},
                                    "WORKS_DEV_MODEL": "opus", "CLAUDE_BIN_PATH": "/usr/bin/true"})
            self.assertEqual(r.returncode, 0, r.stderr)
            body = (diffs / "run-run-1.diff").read_text()
            self.assertIn("+# 直した", body)
            self.assertIn("+KEY=", body)
            self.assertNotIn("deleted file", body)
            self.assertNotIn("取り込むと消えるファイル", r.stdout)

    def _show_run(self, tmp, wt, *, redo="", rc="0"):
        """偽の Archon（run の一覧には run-1、ほかの呼び出しは FAKE_RC で終わる）で works_dev_show_run を回す。差分は tmp/diffs"""
        (tmp / "runs.json").write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                             "working_path": str(wt), "output_root": str(tmp / "out")}]}))
        fake = tmp / "archon.sh"
        fake.write_text(f'case "$*" in "workflow runs --json") cat "{tmp / "runs.json"}" ;; *) exit "${{FAKE_RC:-0}}" ;; esac\n')
        (tmp / "diffs").mkdir(exist_ok=True)
        env = {**{k: v for k, v in os.environ.items() if k not in ("WORKS_RUN_ID", "HERDR_ENV", "WORKS_DEV_SHOW_CMD")},
               "WORKS_DEV_HOME": str(tmp / "dev-home"), "WORKS_DEV_MODEL": "opus", "CLAUDE_BIN_PATH": "/usr/bin/true",
               "FAKE_RC": rc}
        if redo:
            env["WORKS_DEV_SHOW_CMD"] = redo
        return subprocess.run(["sh", "-c", '. "$1"; works_dev_show_run t "$2" "$3" "$3" "$4"', "_",
                               str(DEV / "lib.sh"), str(fake), str(wt), str(tmp / "diffs")],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def test_show_run_empty_diff_leaves_no_file_then_rewrites_cumulative(self):
        """差分が空（起動の直後の関所）なら run-<id>.diff を書かず、前の同じ名のファイルも消し、取り込む行を出さない。
        worktree が進んだ後に呼び直すと、差分は周の頭の版からの累積（役の commit・手直し・未追跡）になり、周の頭の版に当てると
        worktree の今の姿と一致する"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            wt = tmp / "wt"
            committed_copy(wt, DEV / "target-seed")
            base = git(wt, "rev-parse", "HEAD")
            board = tmp / "out" / "artifacts" / "runs" / "run-1" / "board" / "r1"
            board.mkdir(parents=True)
            (board / "start.json").write_text(json.dumps({"base_rev": base}))
            diff = tmp / "diffs" / "run-run-1.diff"
            (tmp / "diffs").mkdir()
            diff.write_text("前の回の置き物\n")
            r = self._show_run(tmp, wt)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(diff.exists())
            self.assertIn(f"修正の差分: まだ無い（run の worktree と周の頭の版 {base[:12]} の差が空。書く先: {diff}）", r.stdout)
            self.assertNotIn(" apply ", r.stdout)

            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 役が commit した直し\n")
            git(wt, "commit", "-q", "-am", "役の commit")
            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 手直し\n")
            (wt / "new.txt").write_text("未追跡\n")
            r = self._show_run(tmp, wt)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"apply {diff}", r.stdout)
            check = tmp / "check"
            subprocess.run(["git", "clone", "-q", str(wt), str(check)], check=True)
            git(check, "checkout", "-q", base)
            git(check, "apply", str(diff))
            for name in ("stats.py", "new.txt"):
                self.assertEqual((check / name).read_text(), (wt / name).read_text(), name)

    def test_show_run_continue_lines_rewrite_diff(self):
        """WORKS_DEV_SHOW_CMD を渡せば、承認・関所の答え（continue・stop）・続きの行の後ろに同じ前置きでその口と run id を付ける
        （止める reject・取り消す cancel には付けない）。行の終了は、続きが落ちればその値、通れば書き直しの値。渡さなければ付けない"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            wt = tmp / "wt"
            wt.mkdir()
            redo = tmp / "redo.sh"
            redo.write_text(f'printf "%s|%s\\n" "$1" "$WORKS_DEV_HOME" >> "{tmp / "redo.log"}"\nexit "${{REDO_RC:-0}}"\n')
            r = self._show_run(tmp, wt, redo=f"sh {redo}")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = {l.split(": ", 1)[0]: l.split(": ", 1)[1] for l in r.stdout.splitlines() if ": " in l}
            tail = f"; works_rc=$?; cd {wt} && "
            for label, verb in (("進める（承認するとその場で続きを回す）", "approve run-1"),
                                ("関所に一言で答えて進める", "respond run-1 continue"),
                                ("関所で止める（報告は出る）", "respond run-1 stop"),
                                ("失敗や中断から続ける", "resume run-1")):
                with self.subTest(verb):
                    self.assertIn(f"workflow {verb}", lines[label])
                    self.assertIn(tail, lines[label])
                    self.assertTrue(lines[label].endswith(f"sh {redo} run-1; (exit $((works_rc ? works_rc : $?)))"),
                                    lines[label])
            for label in ("止める", "取り消す（走っている run を Archon の cancel で止める。報告は report.sh で組む）"):
                self.assertNotIn("works_rc", lines[label])
            self.assertTrue(lines["差分だけを書き直す（Archon の生のコマンドで続けた後）"].endswith(f"sh {redo} run-1"))

            # 前置きは export の無い殻でも書き直しの口に届く。終了は続きが落ちればその値、通れば書き直しの値
            clean = {k: v for k, v in os.environ.items() if not k.startswith(("WORKS_", "CLAUDE_"))}
            for archon_rc, redo_rc, want in (("0", "0", 0), ("3", "0", 3), ("0", "5", 5), ("3", "5", 3)):
                with self.subTest(archon=archon_rc, redo=redo_rc):
                    (tmp / "redo.log").unlink(missing_ok=True)
                    ran = subprocess.run(["sh", "-c", lines["失敗や中断から続ける"]], capture_output=True, text=True,
                                         encoding="utf-8", env={**clean, "FAKE_RC": archon_rc, "REDO_RC": redo_rc})
                    self.assertEqual(ran.returncode, want, ran.stderr)
                    self.assertEqual((tmp / "redo.log").read_text(), f"run-1|{tmp / 'dev-home'}\n")

            r = self._show_run(tmp, wt)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("works_rc", r.stdout)
            self.assertNotIn("差分だけを書き直す", r.stdout)

    def test_archon_sh_installs_borrowed_skills(self):
        """archon.sh は exec の前に、選んだ物だけの設定を隔離した CLAUDE_CONFIG_DIR に組む（dev/toolset.py）。
        superpowers の 5 つのスキルは両方の道で skills/ へ写す（Archon の validate も同じ置き場でスキルを探す）。
        coldwrite・pr-review-toolkit は認証を使う道だけで、PATH の claude（ここでは偽物）の plugin の CLI で入れる。認証の要らない道は claude を起こさない"""
        from test_sp_skills import BORROW
        result, _, _ = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(self.skills_seen), sorted(BORROW))
        self.assertEqual(self.settings_seen["enabledPlugins"],
                         {"coldwrite@works-local": True, "pr-review-toolkit@works-local": True})
        self.assertEqual([c[:3] for c in self.claude_calls],
                         [["plugin", "marketplace", "add"], ["plugin", "install", "coldwrite@works-local"],
                          ["plugin", "install", "pr-review-toolkit@works-local"], ["--version"]])
        result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(self.skills_seen), sorted(BORROW))
        self.assertIsNone(self.settings_seen)
        self.assertEqual(self.claude_calls, [])

    def test_archon_sh_passes_versions_to_run(self):
        """run ごとの版の控え（versions.json。線の start が書く）へ、Archon の版と本物の claude の --version を env で渡す。
        認証の要らない道は claude を起こさない"""
        result, _, _ = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        want = re.search(r'^ARCHON_VERSION="([^"]+)"', (DEV / "archon.sh").read_text(), re.M).group(1)
        self.assertEqual(self.env_seen, [want, "9.9.9 (Claude Code)"])
        result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_seen, [want, "(unset)"])
        self.assertEqual(self.claude_calls, [])

    def test_archon_sh_takes_borrowed_tools_from_the_users_config(self):
        """借りる物は、隔離の前の利用者の設定（CLAUDE_CONFIG_DIR、無ければ $HOME/.claude）に入れたプラグインから取る
        （隔離した後の CLAUDE_CONFIG_DIR は選んだ物だけの設定で、利用者の物ではない）。記録の source がそこを指す"""
        from test_toolset import make_user_config
        result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("superpowers", "coldwrite", "pr-review-toolkit"):
            self.assertTrue(self.toolset_rec[name]["source"].startswith(str(self.user_cfg) + os.sep), self.toolset_rec[name])
        with tempfile.TemporaryDirectory() as home:
            dot = make_user_config(pathlib.Path(home) / ".claude")
            result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1", CLAUDE_CONFIG_DIR="", HOME=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.toolset_rec["coldwrite"]["source"].startswith(str(dot) + os.sep), self.toolset_rec)

    def test_archon_sh_resolves_relative_user_config_before_passing_it(self):
        """相対の CLAUDE_CONFIG_DIR は、殻を起こした所から絶対パスに直して toolset.py へ渡す（toolset.py は絶対だけを受ける）。
        記録の source は利用者の設定の中の絶対パス"""
        result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1", CLAUDE_CONFIG_DIR="../user-claude-config",
                                            cwd_in_tmp="dev-home")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("superpowers", "coldwrite", "pr-review-toolkit"):
            src = self.toolset_rec[name]["source"]
            self.assertTrue(os.path.isabs(src), self.toolset_rec[name])
            self.assertTrue(os.path.realpath(src).startswith(os.path.realpath(self.user_cfg) + os.sep), self.toolset_rec[name])

    def test_archon_sh_stops_when_borrowed_tools_are_not_installed(self):
        """借りる物が利用者の設定に入っていなければ、1 物 1 行の理由と入れるコマンドを出して終了コード 2 で止まり、
        Archon を起こさない（use.sh check・start も同じ所で止まる）"""
        with tempfile.TemporaryDirectory() as empty:
            result, _, seen = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1", CLAUDE_CONFIG_DIR=empty)
        self.assertEqual(result.returncode, 2, result.stderr)
        for cmd in ("claude plugin install superpowers@superpowers-marketplace", "claude plugin install coldwrite@raiki61",
                    "claude plugin install pr-review-toolkit@claude-plugins-official"):
            self.assertIn(cmd, result.stderr)
        self.assertIsNone(seen, "止めるべき所で Archon を起こした")

    def test_archon_sh_stops_when_isolated_config_leaks_into_user_scope(self):
        """隔離した CLAUDE_CONFIG_DIR に CLAUDE.md（や一覧の外の設定・スキル・プラグイン）が在れば、toolset.py の柵が
        名前を出して終了コード 2 で止め、archon.sh は Archon を起こさない（settingSources: [user] の節に読ませない）"""
        def put_claude_md(home):
            (home / "claude-config").mkdir()
            (home / "claude-config" / "CLAUDE.md").write_text("# 文体の決まり\n", encoding="utf-8")
        result, _, seen = self._exec_archon_sh(prepare=put_claude_md, WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("CLAUDE.md", result.stderr)
        self.assertIsNone(seen, "止めるべき所で Archon を起こした")

    def test_real_run_stops_without_auth_before_making_target(self):
        """real-run.sh（費用の掛かる実走）は、認証が無ければ対象を作る前に 1 行の案内で止まること。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"))
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)
            result = subprocess.run(
                ["sh", str(DEV / "real-run.sh"), str(tmp / "target")],
                capture_output=True, text=True, encoding="utf-8", env=env,
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
        env = hermetic.child_env()
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM"):
            env.pop(name, None)
        env.update(kw)
        return env

    def test_archon_sh_refuses_dev_home_in_claude_tmp(self):
        for home in (self.HOLE, "/tmp/claude-works-guard-test-0/x"):   # /tmp は macOS では /private/tmp への symlink
            with self.subTest(home):
                r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True, encoding="utf-8",
                                   env=self._env(WORKS_DEV_HOME=home, WORKS_DEV_NO_AUTH="1"))
                self.assert_guarded(r, "/private/tmp/claude-works-guard-test-0")

    def test_archon_sh_refuses_dev_home_through_symlink(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            link = pathlib.Path(tmp_str) / "link"
            link.symlink_to("/private/tmp")
            r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True, encoding="utf-8",
                               env=self._env(WORKS_DEV_HOME=str(link / "claude-works-guard-test-0" / "x"),
                                             WORKS_DEV_NO_AUTH="1"))
            self.assert_guarded(r, "/private/tmp/claude-works-guard-test-0")

    def test_archon_sh_refuses_cwd_in_claude_tmp(self):
        cwd = claude_tmp_dir("claude-works-guard-")
        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                r = subprocess.run(["sh", str(DEV / "archon.sh"), "version"], capture_output=True, text=True, encoding="utf-8", cwd=cwd,
                                   env=self._env(WORKS_DEV_HOME=str(pathlib.Path(tmp_str) / "dev-home"),
                                                 WORKS_DEV_NO_AUTH="1"))
                self.assert_guarded(r, pathlib.Path(tmp_str) / "dev-home")
        finally:
            shutil.rmtree(cwd)

    def test_mktarget_refuses_target_in_claude_tmp(self):
        r = subprocess.run(["sh", str(DEV / "mktarget.sh"), self.HOLE], capture_output=True, text=True, encoding="utf-8",
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
                    r = subprocess.run(["sh", str(DEV / "real-run.sh"), *args], capture_output=True, text=True, encoding="utf-8",
                                       env=self._env(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", **env))
                    self.assert_guarded(r, tmp / "target", tmp / "dev-home", "/private/tmp/claude-works-guard-test-0")
                    self.assertNotIn("dummy-token-for-test", r.stdout + r.stderr)

    def test_real_run_refuses_origin_in_claude_tmp(self):
        # 対象は穴の外でも、origin（<対象>.origin.git）が穴の下の symlink に解けるなら拒む
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "t.origin.git").symlink_to("/private/tmp/claude-works-guard-test-0")
            r = subprocess.run(["sh", str(DEV / "real-run.sh"), str(tmp / "t")], capture_output=True, text=True, encoding="utf-8",
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
            env = hermetic.child_env(WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp), WORKS_DEV_HOME=str(dev_home))
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)   # 認証が無くても回ること
            result = subprocess.run(["sh", str(check)], capture_output=True, text=True, encoding="utf-8", env=env)
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
    def _dogfood(self, tmp, *args, working_path="/wt/run-1", output_root="/out", runs_json=None, **env_kw):
        """TMPDIR の下に works/ を写した git の元（src）を作り、その写しの dogfood.sh を偽の Archon で回す。
        src には commit していない物（根の未追跡・works/ の中の書き換えと未追跡）を残す。
        偽の Archon は cwd・WORKS_DEV_NO_AUTH・引数（1 つずつ）をタブ区切りで記録し、`workflow runs --json` には
        runs_json（省略時は working_path・output_root の止まった run を 1 本）を返す。
        戻り値は (結果, 元のリポジトリ, 呼び出しの記録)。"""
        src = tmp / "src"
        # works/ を src/works に写して commit した git（型の写し。gitkit）
        committed_copy(src, ROOT, sub="works", ignore=("__pycache__", "*.pyc", ".DS_Store"))
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
            f'case "$1 $2" in "workflow run") printf \'%s\\n\' "${{WORKS_DEV_ADAPTER-(unset)}}" > "{tmp / 'adapter-env.txt'}" ;; esac\n'
            f'case "$*" in "workflow runs --json") cat "{tmp / 'runs.json'}" ;; esac\n'
            "exit 0\n"
        )
        env = self._env(TMPDIR=str(tmp), WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake),
                        CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true")
        env.pop("WORKS_DEV_NO_AUTH", None)
        env.pop("WORKS_DEV_ADAPTER", None)   # 既定（包みを通す）を見る。試験ごとに env_kw で渡す
        for name, value in env_kw.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        result = subprocess.run(["sh", str(src / "works" / "dev" / "dogfood.sh"), *args],
                                capture_output=True, text=True, encoding="utf-8", env=env)
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
                 "--input", f"request={dog / 'request.json'}", "--input", "test_cmd=python3 -m unittest -q",
                 "--input", "tdd_suite=works/dev/tdd-suite.sh", "--input", "adapter=", "--input", "final_gate=always"],
                [str(repo), "1", "workflow", "runs", "--json"],
            ])
            # 既定は包みを通す（持ち主 2026-09-28）: archon.sh に WORKS_DEV_ADAPTER=1 を渡し、ラインには adapter=（包みを求める）
            self.assertEqual((tmp / "adapter-env.txt").read_text(), "1\n")

            out = result.stdout
            self.assertIn("run id: run-1", out)
            self.assertIn("状態: paused", out)
            self.assertIn("/wt/run-1", out)
            for verb in ("approve", "reject", "resume"):
                self.assertIn(f"workflow {verb} run-1", out)
            # 模型を明示しなかった run の続きは空の指定で起こす（既定の opus を明示にしない。解くのは archon.sh）
            self.assertIn("WORKS_DEV_MODEL= WORKS_MODEL_PINNED=", out)
            self.assertNotIn("WORKS_DEV_MODEL=opus", out)
            for verb in ("approve", "resume"):   # 続きのコマンドも包みを通す（archon.sh は打つたびに設定を書き直す）
                self.assertRegex(out, rf"WORKS_DEV_ADAPTER=1 sh [^\n]* workflow {verb} run-1")
                # その場で回る残りの工程が関所の文の答えの行を組めるよう、答えの頭（隔離した archon.sh の respond）を載せる
                self.assertRegex(out, rf"WORKS_ANSWER_CMD='cd [^'\n]* workflow respond' [^\n]* workflow {verb} run-1")
            # 差分は run の worktree の git diff --binary <周の頭の版>（P1 Task 29）。worktree が無ければ書かずに知らせる
            self.assertIn(f"git -C {src.resolve()} apply {dog / 'run-run-1.diff'}", out)
            self.assertIn("run の worktree（/wt/run-1）が無いので書いていない", out)
            self.assertNotIn("注意", out)   # 差分も worktree も .archon/ に触れていない

    def test_dogfood_adapter_switch_falls_back_to_optional(self):
        """WORKS_DEV_ADAPTER=0（か空）で包みを外し、ラインには adapter=optional を渡す（包みの無い run を h-judge が止めない）。
        1 は既定と同じ。ほかの値は archon.sh が拒む（ここでは偽の Archon なので値がそのまま届くことだけを見る）"""
        for value, want_env, want_input in (("0", "0", "adapter=optional"), ("", "", "adapter=optional"),
                                            ("1", "1", "adapter=")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                (tmp / "req.json").write_text("[]\n")
                result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                                   WORKS_DEV_ADAPTER=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(want_input, calls[0])
                self.assertEqual((tmp / "adapter-env.txt").read_text(), want_env + "\n")
                self.assertEqual("WORKS_DEV_ADAPTER=1 " in result.stdout, value == "1")

    def test_dogfood_warns_when_fix_touches_pack_copy(self):
        """修正が works/ でなく pack の写し（.archon/workflows/works）を書き換えたら、取り込まないよう 1 行で注意する。
        差分は run の worktree と周の頭の版（盤面の r1/start.json の base_rev）の差で、役が commit した変更も未追跡も入る。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            wt = tmp / "wt"
            (wt / ".archon" / "workflows" / "works").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(wt)], check=True)
            (wt / ".archon" / "workflows" / "works" / "a.yaml").write_text("x\n")
            subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(wt), *GIT_ID, "commit", "-q", "-m", "base"], check=True)
            board = tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
            (board / "r1").mkdir(parents=True)
            base = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8").stdout.strip()
            (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
            cases = {"worktree の書き換え（commit していない）": False, "役が commit した変更（HEAD が動いた）": True}
            for why, commit in cases.items():
                with self.subTest(why):
                    (wt / ".archon" / "workflows" / "works" / "a.yaml").write_text(f"{why}\n")
                    if commit:
                        subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
                        subprocess.run(["git", "-C", str(wt), *GIT_ID, "commit", "-q", "-m", "moved"], check=True)
                    shutil.rmtree(tmp / "src", ignore_errors=True)
                    result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / why),
                                                       working_path=wt, output_root=tmp / "out")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    notes = [l for l in result.stdout.splitlines() if "注意" in l]
                    self.assertEqual(len(notes), 1, result.stdout)
                    self.assertIn(".archon/", notes[0])

    def test_dogfood_next_commands_carry_keychain_item(self):
        """README どおり WORKS_KEYCHAIN_ITEM を 1 コマンドの前置で渡して起こしたら、出た承認・拒否・続きの行は
        項目名を cd の後・sh の直前に載せ、認証の変数を export していない殻でそのまま打って Archon に認証が届くこと。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_KEYCHAIN_ITEM="item for test")
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = {verb: [l for l in result.stdout.splitlines() if f"workflow {verb} run-1" in l]
                     for verb in ("approve", "reject", "resume")}
            for verb, found in lines.items():
                with self.subTest(verb):
                    self.assertEqual(len(found), 1, result.stdout)
                    # 行は lib.sh の works_dev_go が shlex.quote で組むので、同じ字句の規則で読む（値の中の && は 1 語）
                    words = shlex.split(found[0].split(": ", 1)[1])
                    self.assertEqual((words[0], words[2], words[3]), ("cd", "&&", "WORKS_KEYCHAIN_ITEM=item for test"))
                    self.assertIn("sh", words, found[0])
                    for word in words[3:words.index("sh")]:
                        self.assertRegex(word, r"^[A-Z_][A-Z0-9_]*=", found[0])
            self.assertNotIn("export", result.stdout)
            # 出た行を、認証の変数の無い殻で打つ。偽の Archon は届いた項目名と cwd を書き、run の一覧には run-1（worktree は
            # <dog>/repo。承認の後に修正が在る）を返す。行の後ろの口が承認の後に差分を書き直す
            repo = (tmp / "dog" / "repo").resolve()
            (tmp / "runs.json").write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory",
                                                                 "status": "paused", "working_path": str(repo),
                                                                 "output_root": str(tmp / "out")}]}))
            (repo / "fixed.txt").write_text("承認の後の修正\n")
            (tmp / "fake-archon.sh").write_text(
                f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{tmp / "runs.json"}" ;;\n'
                '*) printf "%s|%s|%s\\n" "${WORKS_KEYCHAIN_ITEM:-}" "$(pwd -P)" "$*" ;; esac\n')
            cmd = lines["approve"][0].split(": ", 1)[1]
            ran = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, encoding="utf-8", env=self._env())
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(ran.stdout.splitlines()[0], f"item for test|{repo}|workflow approve run-1")
            diff = (tmp / "dog").resolve() / "run-run-1.diff"
            self.assertIn(f"修正の差分（run の worktree と周の頭の版 {git(repo, 'rev-parse', 'HEAD')[:12]} の差", ran.stdout)
            self.assertIn("+承認の後の修正", diff.read_text())

    def test_dogfood_show_rewrites_diff_in_dir(self):
        """起動の直後（修正がまだ無い）は <dir>/run-<id>.diff を書かない。出た「差分だけを書き直す」の行を認証も WORKS_* も
        export していない殻で打つと、dogfood.sh --show が前置きの家・偽の Archon で run を引き、今の worktree の累積の差分を書く"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            wt = tmp / "wt"
            committed_copy(wt, DEV / "target-seed")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               working_path=wt, output_root=tmp / "out")
            self.assertEqual(result.returncode, 0, result.stderr)
            diff = (tmp / "dog").resolve() / "run-run-1.diff"
            self.assertFalse(diff.exists())
            self.assertIn("修正の差分: まだ無い", result.stdout)
            self.assertNotIn(" apply ", result.stdout)
            redo = next(l for l in result.stdout.splitlines() if l.startswith("差分だけを書き直す")).split(": ", 1)[1]
            self.assertIn(f"dogfood.sh --show {(tmp / 'dog').resolve()} run-1", redo)

            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 関所の後の直し\n")
            clean = {k: v for k, v in os.environ.items() if not k.startswith(("WORKS_", "CLAUDE_"))}
            ran = subprocess.run(["sh", "-c", redo], capture_output=True, text=True, encoding="utf-8", env=clean)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertIn("+# 関所の後の直し", diff.read_text())
            self.assertIn(f"git -C {src.resolve()} apply {diff}", ran.stdout)
            self.assertIn(redo, ran.stdout)   # 出し直した行も同じ口を持つ
            after = [l.rstrip("\t").split("\t") for l in (tmp / "calls.txt").read_text().splitlines()][len(calls):]
            self.assertEqual(after, [[str((tmp / "dog" / "repo").resolve()), "1", "workflow", "runs", "--json"]])

    def test_dogfood_show_usage(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            for args in (["--show", str(tmp)], ["--show", str(tmp / "nothing"), "run-1"]):
                with self.subTest(args=args):
                    shutil.rmtree(tmp / "src", ignore_errors=True)
                    result, src, calls = self._dogfood(tmp, *args)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("--show", result.stderr)
                    self.assertEqual(calls, [])

    def test_dogfood_token_only_names_variable_without_value(self):
        """トークンだけで起こしたら、値は出さずに CLAUDE_CODE_OAUTH_TOKEN を export した殻で打つよう案内すること。"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"))
            self.assertEqual(result.returncode, 0, result.stderr)
            notes = [l for l in result.stdout.splitlines() if l.startswith("認証:")]
            self.assertEqual(len(notes), 1, result.stdout)
            self.assertIn("CLAUDE_CODE_OAUTH_TOKEN を export した殻で打つ", notes[0])
            self.assertNotIn("WORKS_KEYCHAIN_ITEM=", result.stdout.replace("WORKS_KEYCHAIN_ITEM=<項目名>", ""))

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

    def test_inherited_tmpdir_is_outside_claude_tmp(self):
        """TMPDIR を継ぐ子の置き場（${TMPDIR}/works-dev など）も guard.sh に拒まれない。"""
        r = subprocess.run(["sh", "-c", 'printf %s "${TMPDIR:-/tmp}"'], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertFalse(in_claude_tmp(r.stdout), r.stdout)
        self.assertEqual(os.path.realpath(r.stdout), os.path.realpath(tempfile.gettempdir()))

    def test_positive_path_reaches_shell_when_tmpdir_in_claude_tmp(self):
        """TMPDIR が Claude Code の一時フォルダの下でも、正の道の試験が guard.sh に拒まれず緑になる。"""
        origin = _saved["origin"]
        if in_claude_tmp(origin):
            try:
                hole = tempfile.mkdtemp(prefix="works-tmpdir-", dir=origin)
            except OSError as e:
                self.skipTest(f"SKIP claude-tmp: Claude Code の一時フォルダの下に試しのフォルダを作れない（{e}）")
        else:
            hole = claude_tmp_dir("claude-works-tmpdir-")
        try:
            self.assertTrue(in_claude_tmp(hole), hole)
            r = subprocess.run(
                ["python3", "-m", "unittest", "test_dev.TestDevShell.test_mktarget_places_pack_without_dev_files",
                 "test_dev.TestDevShell.test_inherited_tmpdir_is_outside_claude_tmp"],
                cwd=str(pathlib.Path(__file__).resolve().parent), capture_output=True, text=True, encoding="utf-8",
                env=hermetic.child_env(TMPDIR=hole, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("OK", r.stderr)
        finally:
            shutil.rmtree(hole, ignore_errors=True)


class TestDevModelPin(unittest.TestCase):
    def sh(self, script, **env_kw):
        env = hermetic.child_env()
        for name in ("WORKS_DEV_MODEL", "WORKS_MODEL_PINNED", "WORKS_MODEL_FROM", "WORKS_KEYCHAIN_ITEM",
                     "WORKS_DEV_ADAPTER", "WORKS_ANSWER_CMD", "HERDR_ENV"):
            env.pop(name, None)
        env.update(WORKS_DEV_HOME="/h", CLAUDE_BIN_PATH="/c", **env_kw)
        r = subprocess.run(["sh", "-c", f'set -eu; . "{DEV}/guard.sh"; . "{DEV}/lib.sh"; {script}'],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_default_run_continues_with_start_default(self):
        """既定で start した run の続きは、答える殻の模型や既定に替えず、控えの start の時の既定で起こす"""
        runs = hermetic.tmpdir(self)
        self.sh(f'works_dev_save_ledger "{runs}" run-1 /x')
        led = json.loads((runs / "run-1.json").read_text(encoding="utf-8"))
        self.assertEqual((led["model"], led["model_resolved"]["value"]), ("", "opus"))
        self.assertIn("既定", led["model_resolved"]["from"])
        # 控えの既定を釘の名で渡した殻（load_ledger が export する形）では、続きの行も guard.sh を読んだ archon.sh も
        # その値で解き、出どころに釘の名を残す（既定の定数は環境で替えさせない）
        for pinned in (led["model_resolved"]["value"], "haiku"):
            out = self.sh('works_dev_go /a.sh /x; works_dev_model_value; works_dev_model_from',
                          WORKS_DEV_MODEL="", WORKS_MODEL_PINNED=pinned)
            self.assertIn(f"WORKS_DEV_MODEL= WORKS_MODEL_PINNED={pinned} ", out)
            self.assertEqual(out.splitlines()[-2:], [pinned, "start の時の既定（WORKS_MODEL_PINNED）"])
        self.assertEqual(self.sh("works_dev_model_value", WORKS_DEV_MODEL_DEFAULT="sonnet").strip(), "opus")
        # 明示した run の控えも start の時に解いた値を持ち、出どころで既定と見分ける
        explicit = hermetic.tmpdir(self)
        self.sh(f'works_dev_save_ledger "{explicit}" run-1 /x', WORKS_DEV_MODEL="opus")
        exp = json.loads((explicit / "run-1.json").read_text(encoding="utf-8"))
        self.assertEqual((exp["model"], exp["model_resolved"]["value"]), ("opus", "opus"))
        self.assertNotEqual(exp["model_resolved"]["from"], led["model_resolved"]["from"])
        # 明示した run の行は明示の値だけを載せる（既定は添えない）
        out = self.sh("works_dev_go /a.sh /x", WORKS_DEV_MODEL="sonnet")
        self.assertIn("WORKS_DEV_MODEL=sonnet CLAUDE_BIN_PATH=/c ", out)
        self.assertNotIn("WORKS_MODEL_PINNED", out)


if __name__ == "__main__":
    unittest.main()
