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
- archon.sh が、認証を使う実行のたびに隔離した Archon の設定へ模型（WORKS_DEV_MODEL。既定は dev/guard.sh の WORKS_DEV_MODEL_DEFAULT）を書き、
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
import sys
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
    # 既定の家の根（XDG_STATE_HOME）も試験の一時の置き場に向ける（test_use の use と同じ）。殻の子が利用者の本物の
    # ~/.local/state の控えを読み書きしないように、子が継ぐ os.environ を 1 か所で差し替える
    _saved["xdg"] = tempfile.mkdtemp(prefix="xdg-state-")
    _saved["xdg_environ"] = mock.patch.dict(os.environ, {"XDG_STATE_HOME": _saved["xdg"]})
    _saved["xdg_environ"].start()


def tearDownModule():
    base = _saved.pop("base", None)
    environ = _saved.pop("environ", None)
    _saved.pop("xdg_environ").stop()
    shutil.rmtree(_saved.pop("xdg"), ignore_errors=True)
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


MARK_HOME = "/tmp/works-dev-test-original-home"   # 隔離の前の利用者の HOME の印（実在しなくてよい）
OWN_LOGIN = '{"claudeAiOauth": {"accessToken": "sk-ant-oat01-dummy-token-for-test"}}'   # Claude Code 自身の項目の中身


def fake_security(tmp, items=None, default=""):
    """偽の `security` を tmp/fake-bin に置き、殻の env に被せる上書き（PATH の先頭と印の HOME）と、呼ばれた時の
    `$HOME<TAB>引数` を 1 行ずつ足す記録のパスを返す。`-s <項目>` が items に在ればその値、無ければ default を返し、
    どちらも空なら項目の無い keychain と同じく 44 で終わる。偽物を置かない殻の試験は利用者の本物の keychain に届くので、
    認証の前検を通る殻（archon.sh・dogfood.sh・real-run.sh）の試験はこれを通す"""
    fake_bin = tmp / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    log = tmp / "security-calls.txt"
    arms = "".join(f'  *"-s {service} -w") printf \'%s\\n\' {shlex.quote(value)}; exit 0 ;;\n'
                   for service, value in (items or {}).items())
    tail = f"printf '%s\\n' {shlex.quote(default)}; exit 0\n" if default else "exit 44\n"
    (fake_bin / "security").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\t%s\\n\' "$HOME" "$*" >> "{log}"\n'
        f'case "$*" in\n{arms}esac\n' + tail
    )
    (fake_bin / "security").chmod(0o755)
    return {"PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""), "HOME": MARK_HOME}, log


def security_calls(log):
    """fake_security の記録を (HOME, 引数) の並びで読む（呼ばれていなければ空）"""
    return [tuple(line.split("\t", 1)) for line in log.read_text().splitlines()] if log.exists() else []


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

            fake, log = fake_security(tmp, default=fake_token)

            env = hermetic.child_env(**fake)
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH"):
                env.pop(name, None)
            env["WORKS_DEV_HOME"] = str(dev_home)
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
            calls = security_calls(log)
            home, args = calls[-1] if calls else (None, None)   # 最後に呼ばれた時
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
        """認証を使う実行は毎回、隔離した Archon の設定に模型（既定は guard.sh の値）を書き、題の生成の模型も揃える。
        書かないと Claude CLI の既定の模型で黙って回る（real-run.sh を通さず archon.sh を直に打った時）。"""
        default = hermetic.dev_model_default()
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"assistants:\n  claude:\n    model: {default}\n", config)
        self.assertEqual(seen, [default, "workflow run x"])

    def test_archon_sh_model_follows_works_dev_model(self):
        probe = hermetic.other_model()
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                                                    WORKS_DEV_MODEL=probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {probe}\n", config)
        self.assertEqual(seen[0], probe)

    def test_archon_sh_keeps_title_generation_model_if_set(self):
        probe = hermetic.other_model()
        result, config, seen = self._exec_archon_sh(CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test",
                                                    TITLE_GENERATION_MODEL=probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"    model: {hermetic.dev_model_default()}\n", config)
        self.assertEqual(seen[0], probe)

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
        """WORKS_DEV_SHOW_CMD を渡せば、承認・関所の答え（continue・stop）・続き・止める reject・取り消す cancel の行の後ろに
        同じ前置きでその口と run id を付ける。行の終了は、続きが落ちればその値、通れば書き直しの値。渡さなければ付けない"""
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
                                ("失敗や中断から続ける", "resume run-1"),
                                ("止める", "reject run-1"),
                                ("取り消す（走っている run を Archon の cancel で止める。報告は report.sh で組む）", "cancel run-1")):
                with self.subTest(verb):
                    self.assertIn(f"workflow {verb}", lines[label])
                    self.assertIn(tail, lines[label])
                    self.assertTrue(lines[label].endswith(f"sh {redo} run-1; (exit $((works_rc ? works_rc : $?)))"),
                                    lines[label])
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
        （隔離した後の CLAUDE_CONFIG_DIR は選んだ物だけの設定で、利用者の物ではない）。記録の source がそこを指す。
        superpowers は works の写しから入れるので、利用者の設定を指さない"""
        from test_toolset import make_user_config
        result, _, _ = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pin = json.loads((ROOT / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))["superpowers"]["pin"]
        self.assertEqual(os.path.realpath(self.toolset_rec["superpowers"]["source"]),
                         os.path.realpath(ROOT / ".shared" / "borrow" / "superpowers" / pin["version"]), self.toolset_rec)
        for name in ("coldwrite", "pr-review-toolkit"):
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
        for name in ("coldwrite", "pr-review-toolkit"):   # superpowers は works の写しから入れる
            src = self.toolset_rec[name]["source"]
            self.assertTrue(os.path.isabs(src), self.toolset_rec[name])
            self.assertTrue(os.path.realpath(src).startswith(os.path.realpath(self.user_cfg) + os.sep), self.toolset_rec[name])

    def test_archon_sh_stops_when_borrowed_tools_are_not_installed(self):
        """借りる物が利用者の設定に入っていなければ、1 物 1 行の理由と入れるコマンドを出して終了コード 2 で止まり、
        Archon を起こさない（use.sh check・start も同じ所で止まる）。superpowers は works の写しから入れるので、入れるコマンドを
        出さない"""
        with tempfile.TemporaryDirectory() as empty:
            result, _, seen = self._exec_archon_sh(WORKS_DEV_NO_AUTH="1", CLAUDE_CONFIG_DIR=empty)
        self.assertEqual(result.returncode, 2, result.stderr)
        for cmd in ("claude plugin install coldwrite@raiki61", "claude plugin install pr-review-toolkit@claude-plugins-official"):
            self.assertIn(cmd, result.stderr)
        self.assertNotIn("superpowers@superpowers-marketplace", result.stderr)
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
            env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), **fake_security(tmp)[0])
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
    def _dogfood(self, tmp, *args, working_path="/wt/run-1", output_root=None, runs_json=None, keychain=None, run_status=0,
                 **env_kw):
        """TMPDIR の下に works/ を写した git の元（src）を作り、その写しの dogfood.sh を偽の Archon と偽の security
        （keychain の項目名→値。既定は項目の無い keychain。fake_security）で回す。
        src には commit していない物（根の未追跡・works/ の中の書き換えと未追跡）を残す。
        偽の Archon は cwd・WORKS_DEV_NO_AUTH・引数（1 つずつ）をタブ区切りで記録し、`workflow runs --json` には
        runs_json（省略時は working_path・output_root（省略時は <tmp>/out）の止まった run を 1 本）を返す。
        `workflow run` では一覧の run の盤面 r1/start.json の request_file に request= の値を書く（線の start と同じ欄。
        起動の後にこの起動の依頼で run を結ぶ材料）。
        戻り値は (結果, 元のリポジトリ, 呼び出しの記録)。"""
        output_root = tmp / "out" if output_root is None else output_root
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
            # 起動の時に渡された読み出しのファイル（github_reads）の中身を写して残す（start が盤面へ写して消すので、起動の時に見る）
            f'for a in "$@"; do case $a in github_reads=?*) cp "${{a#github_reads=}}" "{tmp / "github-reads-seen.json"}" ;; esac; done\n'
            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
            f'RUNS="{tmp / "runs.json"}" python3 - "$@" <<\'EOF\'\n'
            "import json, os, pathlib, sys\n"
            "req = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('request=')), '')\n"
            "for r in json.loads(pathlib.Path(os.environ['RUNS']).read_text())['runs']:\n"
            "    p = pathlib.Path(r['output_root'], 'artifacts', 'runs', r['id'], 'board', 'r1', 'start.json')\n"
            "    p.parent.mkdir(parents=True, exist_ok=True)\n"
            "    p.write_text(json.dumps(dict(json.loads(p.read_text()) if p.exists() else {}, request_file=req)))\n"
            "EOF\n"
            f'case "$1 $2" in "workflow run") exit {run_status} ;; esac\n'
            "exit 0\n"
        )
        security, self.security_log = fake_security(tmp, keychain)
        # 利用者の設定の置き場は一時の置き場（起動の時の toolset.py newer に利用者の本物の ~/.claude を読ませない）
        env = self._env(TMPDIR=str(tmp), WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake),
                        CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true",
                        CLAUDE_CONFIG_DIR=str(tmp / "user-claude"), **security)
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

            # 依頼は起動ごとの写し <dir>/requests/<日時>-<pid>.json に写し、その絶対パスを渡す。ラインは clone の中で認証付きで回し、
            # run の問い合わせは認証を読ませずに回す
            copies = list((dog / "requests").iterdir()); self.assertEqual(len(copies), 1, copies); copy = copies[0]; self.assertRegex(copy.name, r"^\d{8}-\d{6}-\d+\.json$"); self.assertEqual(copy.read_text(), request.read_text())
            self.assertEqual(calls, [
                [str(repo), "", "workflow", "run", "darkfactory",
                 "--input", f"request={copy}", "--input", "test_cmd=python3 -m unittest -q",
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
            # 模型を明示しなかった run の続きは空の指定で起こす（既定を明示にしない。解くのは archon.sh）
            self.assertIn("WORKS_DEV_MODEL= WORKS_MODEL_PINNED=", out)
            self.assertNotIn(f"WORKS_DEV_MODEL={hermetic.dev_model_default()}", out)
            for verb in ("approve", "resume"):   # 続きのコマンドも包みを通す（archon.sh は打つたびに設定を書き直す）
                self.assertRegex(out, rf"WORKS_DEV_ADAPTER=1 sh [^\n]* workflow {verb} run-1")
                # その場で回る残りの工程が関所の文の答えの行を組めるよう、答えの頭（隔離した archon.sh の respond）を載せる
                self.assertRegex(out, rf"WORKS_ANSWER_CMD='cd [^'\n]* workflow respond' [^\n]* workflow {verb} run-1")
            # 差分は run の worktree の git diff --binary <周の頭の版>（P1 Task 29）。worktree が無ければ書かずに知らせる
            self.assertIn(f"git -C {src.resolve()} apply {dog / 'run-run-1.diff'}", out)
            self.assertIn("run の worktree（/wt/run-1）が無いので書いていない", out)
            self.assertNotIn("注意", out)   # 差分も worktree も .archon/ に触れていない

    def test_dogfood_reused_dir_binds_only_this_launch_run(self):
        """同じ <dir> を使い直して起こし直しても（前の回の物を消して守りを通る道）、依頼の写しは起動ごとに一意の名で、
        一覧に残った前の起動の run（止まった・落ちた・取り消した）と結びの候補が重ならず、この起動の run 1 本に結べる（設計書 2.3）"""
        for prior in ("paused", "failed", "cancelled"):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                request = tmp / "req.json"
                request.write_text('[{"where": "x", "text": "y"}]\n')
                dog = tmp / "dog"
                first_tmp, second_tmp = tmp / "first", tmp / "second"
                first_tmp.mkdir()
                second_tmp.mkdir()
                result, _, calls = self._dogfood(first_tmp, str(request), "true", str(dog))
                self.assertEqual(result.returncode, 0, result.stderr)
                first_request = next(a.split("=", 1)[1] for a in calls[0] if a.startswith("request="))
                # 人が前の回の clone・origin を消して守りを通る（前の run は <dir> の外、Archon の一覧に残る）
                for used in ("repo", "origin.git"):
                    shutil.rmtree(dog / used)
                runs = json.dumps({"runs": [
                    {"id": "run-2", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/run-2",
                     "output_root": str(second_tmp / "out")},
                    # 前の起動の run は、Archon が残した入力（metadata.inputs.request）に前の起動の写しを持つ
                    {"id": "run-1", "workflow_name": "darkfactory", "status": prior, "working_path": "/wt/run-1",
                     "output_root": str(first_tmp / "out"), "metadata": {"inputs": {"request": first_request}}},
                ]})
                result, _, calls = self._dogfood(second_tmp, str(request), "true", str(dog), runs_json=runs)
                second_request = next(a.split("=", 1)[1] for a in calls[0] if a.startswith("request="))
                self.assertNotEqual(os.path.realpath(second_request), os.path.realpath(first_request))
                self.assertTrue(pathlib.Path(first_request).exists())   # 前の起動の写しは消さない（前の run が指す）
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("run id: run-2", result.stdout)
                self.assertTrue((second_tmp / "dev-home" / "runs" / "run-2.json").exists())

    def test_real_run_reused_dir_binds_only_this_launch_run(self):
        """real-run.sh も、同じ <dir> を消して起こし直した時、依頼の写しの名が前の起動と重ならず、一覧に残る前の起動の run
        （止まった・落ちた・取り消した）を候補にせずに、この起動の run 1 本に結べる（設計書 2.3）"""
        for prior in ("paused", "failed", "cancelled"):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                security, _ = fake_security(tmp)
                runs, current, log = tmp / "runs.json", tmp / "current-run", tmp / "calls.txt"
                fake = tmp / "fake-archon.sh"
                # workflow run はこの起動の run（current-run）の盤面 r1/start.json にだけ request= の値を残す
                fake.write_text(f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{runs}" ;; esac\n'
                                'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
                                f'printf \'%s\\n\' "$*" >> "{log}"\n'
                                f'B="{tmp / "out" / "artifacts" / "runs"}/$(cat "{current}")/board/r1"; mkdir -p "$B"\n'
                                'for a in "$@"; do case "$a" in request=*) printf \'{"request_file": "%s"}\' "${a#request=}" > "$B/start.json" ;; esac; done\n'
                                'exit 0\n')
                env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp),
                                         CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true",
                                         **security)
                target = tmp / "target"
                row = lambda i, status: {"id": i, "workflow_name": "darkfactory", "status": status,
                                         "working_path": f"/wt/{i}", "output_root": str(tmp / "out")}
                current.write_text("run-1")
                runs.write_text(json.dumps({"runs": [row("run-1", "paused")]}))
                first = subprocess.run(["sh", str(DEV / "real-run.sh"), str(target)],
                                       capture_output=True, text=True, encoding="utf-8", env=env)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertIn("run id: run-1", first.stdout)
                # 人が前の対象と origin を消して同じ <dir> で起こし直す（前の run は Archon の一覧に残る）
                shutil.rmtree(target)
                shutil.rmtree(tmp / "target.origin.git")
                current.write_text("run-2")
                runs.write_text(json.dumps({"runs": [row("run-2", "paused"), row("run-1", prior)]}))
                second = subprocess.run(["sh", str(DEV / "real-run.sh"), str(target)],
                                        capture_output=True, text=True, encoding="utf-8", env=env)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("run id: run-2", second.stdout)
                requests = [next(a.split("=", 1)[1] for a in line.split() if a.startswith("request="))
                            for line in log.read_text().splitlines()]
                self.assertEqual(len(requests), 2, requests)
                self.assertNotEqual(*requests)
                self.assertTrue((tmp / "dev-home" / "runs" / "run-2.json").exists())

    def test_dogfood_reads_named_pr_and_issue_from_source_before_clone(self):
        """依頼が {findings, pr, issue} で名指せば、clone の前に元のリポジトリ（GitHub を解ける remote を持つ物。clone は origin を
        付け替える）を cwd にして利用者の env のまま 1 回だけ読み、そのファイルを --input github_reads= で渡す"""
        from test_ghreads import GH_ENV, fake_gh, gh_calls
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            request = tmp / "req.json"
            request.write_text(json.dumps({"findings": [{"where": "x", "text": "y"}], "pr": [7], "issue": [9]}))
            bin_, gh_log, login = fake_gh(tmp)
            env = {name: None for name in GH_ENV}
            env.update(PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", GH_CONFIG_DIR=str(login))
            result, src, calls = self._dogfood(tmp, str(request), "true", str(tmp / "dog"), **env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            given = [a for a in calls[0] if a.startswith("github_reads=")]
            self.assertEqual(len(given), 1, calls[0])
            self.assertNotEqual(given[0], "github_reads=", calls[0])
            seen = tmp / "github-reads-seen.json"
            self.assertTrue(seen.exists(), "起動の時に読み出しのファイルが無い")
            doc = json.loads(seen.read_text(encoding="utf-8"))
            self.assertEqual(doc["pr"]["7"]["body"], "非公開の本文")
            self.assertEqual(doc["issue"]["9"]["comments"][0]["body"], "課題のコメント")
            self.assertEqual({cwd for cwd, _ in gh_calls(gh_log)}, {str(src.resolve())})

    def test_dogfood_failed_launch_drops_reads_file(self):
        """Archon の起動が 0 以外で終わった（start まで行かない）時は、隔離の前に読んだ読み出しのファイル（非公開の本文を持つ）を
        <dir> に残さない。起動の終了コードはそのまま返す"""
        from test_ghreads import GH_ENV, fake_gh
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            request = tmp / "req.json"
            request.write_text(json.dumps({"findings": [{"where": "x", "text": "y"}], "pr": [7], "issue": [9]}))
            bin_, _, login = fake_gh(tmp)
            env = {name: None for name in GH_ENV}
            env.update(PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", GH_CONFIG_DIR=str(login))
            result, src, calls = self._dogfood(tmp, str(request), "true", str(tmp / "dog"), run_status=3, **env)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertTrue((tmp / "github-reads-seen.json").exists(), "起動の時に読み出しのファイルが無い")
            self.assertFalse((tmp / "dog" / "github-reads.json").exists())

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

    def test_dogfood_design_only_appends_input_only_when_asked(self):
        """WORKS_DESIGN_ONLY=1 だけがラインの引数の最後に design_only=true を足す（設計だけの run）。
        未設定・空では引数は今と同じ（1 の外の値は test_dogfood_refuses_design_only_outside_one が止める）"""
        base = ["--input", "tdd_suite=works/dev/tdd-suite.sh", "--input", "adapter=optional",
                "--input", "final_gate=always"]
        for value, extra in ((None, []), ("", []), ("1", ["--input", "design_only=true"])):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                (tmp / "req.json").write_text("[]\n")
                result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                                   WORKS_DEV_ADAPTER="0", WORKS_DESIGN_ONLY=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[0][-(len(base) + len(extra)):], base + extra)

    def test_dogfood_refuses_design_only_outside_one(self):
        """WORKS_DESIGN_ONLY は未設定・空・1 だけを受け、ほかの値は <dir> を作らず・clone せず・Archon を呼ばずに止まる
        （黙って捨てると設計だけのつもりの run が修正まで流れる）"""
        for value in ("on", "true", "0"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                (tmp / "req.json").write_text("[]\n")
                result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                                   WORKS_DEV_ADAPTER="0", WORKS_DESIGN_ONLY=value)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                lines = result.stderr.strip().splitlines()
                self.assertEqual(len(lines), 1, result.stderr)
                self.assertTrue(lines[0].startswith("dogfood.sh: "), lines[0])
                self.assertIn("WORKS_DESIGN_ONLY", lines[0])
                self.assertIn(f"受けた値: {value}", lines[0])
                self.assertEqual(calls, [])
                self.assertFalse((tmp / "dog").exists())

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
                                               CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_KEYCHAIN_ITEM="item for test",
                                               keychain={"item for test": "sk-ant-oat01-dummy-token-for-test"})
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

    def _herdr_follows_continue_lines(self, tmp, out, shell):
        """起動の出力 out の続きの行（承認・止める）を、herdr の枠（偽の herdr）の中で WORKS_* の無い殻から打つと、Archon を呼ぶ前に working を
        送り、最後の報告が run の今の状態と合う（paused→blocked・running→working）。差分だけを書き直す行は今の状態で 1 回だけ（completed→release）"""
        lines = {l.split(": ", 1)[0]: l.split(": ", 1)[1] for l in out.splitlines() if ": " in l}
        herdr_log = tmp / "herdr.txt"
        self.assertIn(f"{shell} --show ", lines["差分だけを書き直す（Archon の生のコマンドで続けた後）"])
        # 起動の直後も同じ口で 1 回（関所で待つ run は blocked）
        self.assertEqual(len(herdr_log.read_text().splitlines()), 1)
        self.assertIn("--state blocked", herdr_log.read_text())
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("WORKS_", "CLAUDE_", "HERDR_"))}
        clean.update(PATH=str(tmp / "herdr-bin") + os.pathsep + clean.get("PATH", ""), HERDR_ENV="1", HERDR_PANE_ID="pane-7")
        for label, status, want in (("進める（承認するとその場で続きを回す）", "running", "pane report-agent pane-7 --source works-factory --agent works --state working"),
                                    ("止める", "paused", "pane report-agent pane-7 --source works-factory --agent works --state blocked"),
                                    ("差分だけを書き直す（Archon の生のコマンドで続けた後）", "completed", "pane release-agent pane-7 --source works-factory --agent works")):
            with self.subTest(label=label, status=status):
                doc = json.loads((tmp / "runs.json").read_text())
                doc["runs"][0]["status"] = status
                (tmp / "runs.json").write_text(json.dumps(doc))
                herdr_log.unlink()
                ran = subprocess.run(["sh", "-c", lines[label]], capture_output=True, text=True, encoding="utf-8", env=clean)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                calls = herdr_log.read_text().splitlines()
                self.assertTrue(len(calls) == 1 if label.startswith("差分") else len(calls) >= 2 and calls[0].startswith("pane report-agent pane-7 --source works-factory --agent works --state working"), calls)
                self.assertTrue(calls[-1].startswith(want), calls)

    def test_dogfood_continue_lines_report_run_state_to_herdr_pane(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            fake_bin, _ = hermetic.fake_herdr(tmp)
            (tmp / "fake-bin").mkdir()
            (tmp / "fake-bin" / "herdr").symlink_to(fake_bin / "herdr")   # 偽の security と同じ PATH の頭に置く
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               HERDR_ENV="1", HERDR_PANE_ID="pane-7")
            self.assertEqual(result.returncode, 0, result.stderr)
            self._herdr_follows_continue_lines(tmp, result.stdout, "dogfood.sh")

    def test_real_run_continue_lines_report_run_state_to_herdr_pane(self):
        """real-run.sh も dogfood.sh と同じく、続きの行の後段（real-run.sh --show <dir> <run-id>）で herdr の枠の集計を run に追わせる"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            fake_bin, _ = hermetic.fake_herdr(tmp)
            security, _ = fake_security(tmp)
            (tmp / "fake-bin" / "herdr").symlink_to(fake_bin / "herdr")
            (tmp / "runs.json").write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                                 "working_path": "/wt/run-1", "output_root": str(tmp / "out")}]}))
            fake = tmp / "fake-archon.sh"
            # workflow run は run の盤面 r1/start.json に request= の値を残す（線の start と同じ。起動の後に結ぶ材料）
            fake.write_text(f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{tmp / "runs.json"}" ;; esac\n'
                            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
                            f'B="{tmp / "out" / "artifacts" / "runs" / "run-1" / "board" / "r1"}"; mkdir -p "$B"\n'
                            'for a in "$@"; do case "$a" in request=*) printf \'{"request_file": "%s"}\' "${a#request=}" > "$B/start.json" ;; esac; done\n'
                            'exit 0\n')
            env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp),
                                     CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true",
                                     HERDR_ENV="1", HERDR_PANE_ID="pane-7", **security)
            result = subprocess.run(["sh", str(DEV / "real-run.sh"), str(tmp / "target")],
                                    capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(f"real-run.sh --show {(tmp / 'target').resolve()} run-1", result.stdout)
            self._herdr_follows_continue_lines(tmp, result.stdout, "real-run.sh")

    def test_show_reports_run_state_to_herdr_pane_once(self):
        """dogfood.sh --show・real-run.sh --show は、起動の時の控え（herdr_pane）の枠へ、その run の今の状態で集計を 1 回だけ出し、
        控えは書き直さない（paused→blocked・running→working・completed→release）"""
        for shell in ("dogfood.sh", "real-run.sh"):
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                fake_bin, herdr_log = hermetic.fake_herdr(tmp)
                target = tmp / "dog" / "repo" if shell == "dogfood.sh" else tmp / "target"
                (target / ".git").mkdir(parents=True)
                ledger = tmp / "dev-home" / "runs" / "run-1.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_text(json.dumps({"run_id": "run-1", "target": str(target), "started_at": 1.0,
                                              "herdr_pane": "pane-7"}))
                runs = tmp / "runs.json"
                fake = tmp / "fake-archon.sh"
                fake.write_text(f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{runs}" ;; esac\nexit 0\n')
                env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake),
                                         CLAUDE_BIN_PATH="/usr/bin/true", HERDR_ENV="1", HERDR_PANE_ID="pane-7",
                                         PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
                for status, want in (("paused", "pane report-agent pane-7 --source works-factory --agent works --state blocked"),
                                     ("running", "pane report-agent pane-7 --source works-factory --agent works --state working"),
                                     ("completed", "pane release-agent pane-7 --source works-factory --agent works")):
                    runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": status,
                                                          "working_path": "/wt/run-1", "output_root": str(tmp / "out")}]}))
                    herdr_log.unlink(missing_ok=True)
                    r = subprocess.run(["sh", str(DEV / shell), "--show", str(target.parent if shell == "dogfood.sh" else target),
                                        "run-1"], capture_output=True, text=True, encoding="utf-8", env=env)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn(f"状態: {status}", r.stdout)
                    calls = herdr_log.read_text().splitlines() if herdr_log.exists() else []
                    self.assertEqual(len(calls), 1, (status, calls))
                    self.assertTrue(calls[0].startswith(want), calls)
                self.assertEqual(json.loads(ledger.read_text())["started_at"], 1.0)

    def test_show_exit_and_output_do_not_change_when_herdr_fails(self):
        """herdr が失敗しても（サーバが居ない server_not_running・rc=1）、dogfood.sh --show・real-run.sh --show の終了コードと
        出力は herdr が通る時と同じ（集計の失敗で run を止めない）"""
        for shell in ("dogfood.sh", "real-run.sh"):
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as tmp_str:
                tmp = pathlib.Path(tmp_str)
                target = tmp / "dog" / "repo" if shell == "dogfood.sh" else tmp / "target"
                (target / ".git").mkdir(parents=True)
                ledger = tmp / "dev-home" / "runs" / "run-1.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_text(json.dumps({"run_id": "run-1", "target": str(target), "started_at": 1.0,
                                              "herdr_pane": "pane-7"}))
                runs = tmp / "runs.json"
                runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                      "working_path": "/wt/run-1", "output_root": str(tmp / "out")}]}))
                fake = tmp / "fake-archon.sh"
                fake.write_text(f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{runs}" ;; esac\nexit 0\n')
                got = {}
                for fail in (False, True):
                    (tmp / str(fail)).mkdir()
                    fake_bin, herdr_log = hermetic.fake_herdr(tmp / str(fail), fail=fail)
                    env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake),
                                             CLAUDE_BIN_PATH="/usr/bin/true", HERDR_ENV="1", HERDR_PANE_ID="pane-7",
                                             PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
                    r = subprocess.run(["sh", str(DEV / shell), "--show",
                                        str(target.parent if shell == "dogfood.sh" else target), "run-1"],
                                       capture_output=True, text=True, encoding="utf-8", env=env)
                    self.assertTrue(herdr_log.exists(), f"herdr が呼ばれていない（fail={fail}）")
                    self.assertIn("--state blocked", herdr_log.read_text())
                    got[fail] = (r.returncode, r.stdout)
                self.assertEqual(got[False][0], 0, got[False][1])
                self.assertEqual(got[True], got[False])

    def test_real_run_outside_herdr_pane_never_calls_herdr(self):
        """herdr の枠の外（HERDR_ENV が無い）で起こした run は、herdr が PATH に在っても起動の後にも --show にも herdr を呼ばず、
        控えに枠を残さない。既定の家の根（XDG_STATE_HOME。setUpModule が試験の一時の置き場に向けた）には何も書かない"""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            fake_bin, herdr_log = hermetic.fake_herdr(tmp)
            security, _ = fake_security(tmp)
            (tmp / "fake-bin" / "herdr").symlink_to(fake_bin / "herdr")
            (tmp / "runs.json").write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused",
                                                                 "working_path": "/wt/run-1", "output_root": str(tmp / "out")}]}))
            fake = tmp / "fake-archon.sh"
            # workflow run は run の盤面 r1/start.json に request= の値を残す（線の start と同じ。起動の後に結ぶ材料）
            fake.write_text(f'#!/bin/sh\ncase "$*" in "workflow runs --json") cat "{tmp / "runs.json"}" ;; esac\n'
                            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
                            f'B="{tmp / "out" / "artifacts" / "runs" / "run-1" / "board" / "r1"}"; mkdir -p "$B"\n'
                            'for a in "$@"; do case "$a" in request=*) printf \'{"request_file": "%s"}\' "${a#request=}" > "$B/start.json" ;; esac; done\n'
                            'exit 0\n')
            env = hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"), WORKS_DEV_ARCHON=str(fake), TMPDIR=str(tmp),
                                     CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true",
                                     **security)
            env.pop("HERDR_ENV", None)
            env.pop("HERDR_PANE_ID", None)
            for args in ([str(tmp / "target")], ["--show", str(tmp / "target"), "run-1"]):
                with self.subTest(args=args[0]):
                    r = subprocess.run(["sh", str(DEV / "real-run.sh"), *args],
                                       capture_output=True, text=True, encoding="utf-8", env=env)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertFalse(herdr_log.exists(), herdr_log.read_text() if herdr_log.exists() else "")
            self.assertEqual(json.loads((tmp / "dev-home" / "runs" / "run-1.json").read_text())["herdr_pane"], "")
            self.assertEqual(os.listdir(os.environ["XDG_STATE_HOME"]), [])

    def test_real_run_show_usage(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            for args in (["--show", str(tmp)], ["--show", str(tmp / "nothing"), "run-1"]):
                with self.subTest(args=args):
                    r = subprocess.run(["sh", str(DEV / "real-run.sh"), *args], capture_output=True, text=True,
                                       encoding="utf-8", env=hermetic.child_env(WORKS_DEV_HOME=str(tmp / "dev-home"),
                                                                                CLAUDE_BIN_PATH="/usr/bin/true"))
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn("--show", r.stderr)
                    self.assertFalse((tmp / "dev-home").exists())

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

    # keychain だけの人（トークンも WORKS_KEYCHAIN_ITEM も無い）も、殻の前検を起こし役の check で通ること。
    # 本流の段が設定の置き場から導く項目（~/.claude → claude-code-oauth-default）と、Claude Code 自身の項目の 2 通り
    KEYCHAIN_ONLY = {
        "derived": ("claude-code-oauth-default", "sk-ant-oat01-dummy-token-for-test",
                    "keychain の項目 claude-code-oauth-default"),
        "own": ("Claude Code-credentials", OWN_LOGIN, "Claude Code の keychain の項目 Claude Code-credentials"),
    }

    def _dogfood_keychain_only(self, which):
        service, value, _ = self.KEYCHAIN_ONLY[which]
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            (tmp / "req.json").write_text("[]\n")
            # 導く項目は設定の置き場の既定（~/.claude → default）から作るので、_dogfood の一時の CLAUDE_CONFIG_DIR を外す
            # （HOME は fake_security の印の置き場なので、newer は利用者の本物の ~/.claude を読まない）
            result, src, calls = self._dogfood(tmp, str(tmp / "req.json"), "true", str(tmp / "dog"),
                                               keychain={service: value}, CLAUDE_CODE_OAUTH_TOKEN=None, CLAUDE_CONFIG_DIR=None)
            self.assertNotIn("認証が無い", result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn((MARK_HOME, f"find-generic-password -s {service} -w"), security_calls(self.security_log))
            self.assertTrue(any(c[2:4] == ["workflow", "run"] for c in calls), calls)   # Archon まで届いた

    def _real_run_keychain_only(self, which):
        service, value, source = self.KEYCHAIN_ONLY[which]
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            dev_home = tmp / "dev-home"
            (dev_home / "bin").mkdir(parents=True)
            (dev_home / "bin" / "archon-darwin-arm64").write_bytes(b"not the real archon binary")
            fake, log = fake_security(tmp, {service: value})
            env = hermetic.child_env(WORKS_DEV_HOME=str(dev_home), CLAUDE_BIN_PATH="/usr/bin/true", **fake)
            result = subprocess.run(["sh", str(DEV / "real-run.sh"), str(tmp / "target")],
                                    capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertNotIn("認証が無い", result.stderr)
            self.assertIn((MARK_HOME, f"find-generic-password -s {service} -w"), security_calls(log))
            # 前検を抜けて archon.sh まで届き、出どころの名の 1 行の後、中身の違う実行ファイルの sha256 の確かめで止まる
            self.assertIn(f"認証は {source}", result.stderr)
            self.assertIn("sha256", result.stderr)
            self.assertNotIn("sk-ant-oat01-dummy-token-for-test", result.stdout + result.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ（auth_launch.py）")
    def test_dogfood_runs_with_derived_keychain_item_only(self):
        self._dogfood_keychain_only("derived")

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ（auth_launch.py）")
    def test_dogfood_runs_with_claude_code_keychain_only(self):
        self._dogfood_keychain_only("own")

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ（auth_launch.py）")
    def test_real_run_passes_precheck_with_derived_keychain_item_only(self):
        self._real_run_keychain_only("derived")

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ（auth_launch.py）")
    def test_real_run_passes_precheck_with_claude_code_keychain_only(self):
        self._real_run_keychain_only("own")

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
        # lib.sh は . で読まれ自分の場所を知れないので、控えを書く部品 launch.py の dir を殻と同じく DEV_DIR で渡す
        env.update(WORKS_DEV_HOME="/h", CLAUDE_BIN_PATH="/c", DEV_DIR=str(DEV), **env_kw)
        r = subprocess.run(["sh", "-c", f'set -eu; . "{DEV}/guard.sh"; . "{DEV}/lib.sh"; {script}'],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def save_ledger(self, runs, **env_kw):
        # works_dev_ledger_bind が控えを書く時と同じく、今の殻の模型の値と出どころを部品に渡す
        self.sh(f'works_dev_launch ledger save --dir "{runs}" --run-id run-1 --target /x '
                '--model-value "$(works_dev_model_value)" --model-from "$(works_dev_model_from)"', **env_kw)

    def test_default_run_continues_with_start_default(self):
        """既定で start した run の続きは、答える殻の模型や既定に替えず、控えの start の時の既定で起こす"""
        runs = hermetic.tmpdir(self)
        self.save_ledger(runs)
        led = json.loads((runs / "run-1.json").read_text(encoding="utf-8"))
        default, probe = hermetic.dev_model_default(), hermetic.other_model()
        self.assertEqual((led["model"], led["model_resolved"]["value"]), ("", default))
        self.assertIn("既定", led["model_resolved"]["from"])
        # 控えの既定を釘の名で渡した殻（load_ledger が export する形）では、続きの行も guard.sh を読んだ archon.sh も
        # その値で解き、出どころに釘の名を残す（既定の定数は環境で替えさせない）
        for pinned in (led["model_resolved"]["value"], probe):
            out = self.sh('works_dev_go /a.sh /x; works_dev_model_value; works_dev_model_from',
                          WORKS_DEV_MODEL="", WORKS_MODEL_PINNED=pinned)
            self.assertIn(f"WORKS_DEV_MODEL= WORKS_MODEL_PINNED={pinned} ", out)
            self.assertEqual(out.splitlines()[-2:], [pinned, "start の時の既定（WORKS_MODEL_PINNED）"])
        self.assertEqual(self.sh("works_dev_model_value", WORKS_DEV_MODEL_DEFAULT=probe).strip(), default)
        # 明示した run の控えも start の時に解いた値を持ち、出どころで既定と見分ける（明示の値は既定と同じでも見分ける）
        explicit = hermetic.tmpdir(self)
        self.save_ledger(explicit, WORKS_DEV_MODEL=default)
        exp = json.loads((explicit / "run-1.json").read_text(encoding="utf-8"))
        self.assertEqual((exp["model"], exp["model_resolved"]["value"]), (default, default))
        self.assertNotEqual(exp["model_resolved"]["from"], led["model_resolved"]["from"])
        # 明示した run の行は明示の値だけを載せる（既定は添えない）
        out = self.sh("works_dev_go /a.sh /x", WORKS_DEV_MODEL=probe)
        self.assertIn(f"WORKS_DEV_MODEL={probe} CLAUDE_BIN_PATH=/c ", out)
        self.assertNotIn("WORKS_MODEL_PINNED", out)


class TestHerdrContinue(unittest.TestCase):
    """lib.sh の続きの口 works_dev_continue と、run を起こした枠ごとの集計 works_dev_herdr_sync（偽の herdr・偽の Archon）"""

    def setUp(self):
        self.tmp = hermetic.tmpdir(self)
        self.runs = self.tmp / "home" / "runs"
        self.runs.mkdir(parents=True)
        self.listed = self.tmp / "listed.json"
        self.archon = self.tmp / "archon.sh"
        # 続きの動詞では、呼ばれた時の herdr の控えの行数と続き中の印の有無を書き、ARCHON_RC で終わる
        self.archon.write_text(
            "#!/bin/sh\n"
            f'case "$*" in "workflow runs --json") cat "{self.listed}"; exit 0 ;; esac\n'
            f'printf "%s|%s|%s\\n" "$*" "$(cat "{self.tmp}/herdr.txt" 2>/dev/null | wc -l | tr -d " ")" '
            f'"$(ls "{self.runs}" | grep -c "\\.cont$")" >> "{self.tmp}/archon-calls.txt"\n'
            'sleep "${ARCHON_SLEEP:-0}"\n'
            'exit "${ARCHON_RC:-0}"\n')

    def ledger(self, rid, pane, sock=None):
        doc = {"run_id": rid, "target": "/x", "herdr_pane": pane}
        if sock is not None:
            doc["herdr_socket"] = sock
        (self.runs / f"{rid}.json").write_text(json.dumps(doc))

    def status(self, **by_id):
        self.listed.write_text(json.dumps({"runs": [{"id": k, "status": v} for k, v in by_id.items()]}))

    def sh(self, script, fail=False, **env_kw):
        shutil.rmtree(self.tmp / "herdr-bin", ignore_errors=True)
        herdr_bin, log = hermetic.fake_herdr(self.tmp, fail=fail)
        env = hermetic.child_env(PATH=f"{herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}", DEV_DIR=str(DEV), **env_kw)
        r = subprocess.run(["sh", "-c", f'. "{DEV}/lib.sh"; {script}', "_", str(self.archon), str(self.runs)],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        return r, hermetic.herdr_sockets(log)

    def test_continue_reports_working_before_archon_and_state_after(self):
        """枠の外の殻から続けても、Archon を呼ぶ前に run を起こした枠（控えの枠とサーバ）へ working を送り、Archon の間は続き中の
        印を置き、戻った後に印を外して run の今の状態を送る。終了の値は Archon の値"""
        self.ledger("r1", "pane-7", "/sock-a")
        self.status(r1="paused")
        r, sent = self.sh('works_dev_continue "$1" "$2" r1 workflow approve r1', ARCHON_RC="3")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual((self.tmp / "archon-calls.txt").read_text(), "workflow approve r1|1|1\n")
        self.assertEqual([s for s, _ in sent], ["/sock-a", "/sock-a"], sent)
        self.assertTrue(sent[0][1].startswith("pane report-agent pane-7 --source works-factory --agent works --state working"), sent)
        self.assertTrue(sent[1][1].startswith("pane report-agent pane-7 --source works-factory --agent works --state blocked"), sent)
        self.assertEqual(list(self.runs.glob("*.cont")), [])

    def test_continue_exit_and_output_do_not_change_when_herdr_fails(self):
        self.ledger("r1", "pane-7", "/sock-a")
        self.status(r1="completed")
        got = {}
        for fail in (False, True):
            with self.subTest(fail=fail):
                shutil.rmtree(self.tmp / "herdr-bin", ignore_errors=True)
                r, sent = self.sh('works_dev_continue "$1" "$2" r1 workflow resume r1', fail=fail, ARCHON_RC="4")
                self.assertTrue(sent, "herdr が呼ばれていない")
                got[fail] = (r.returncode, r.stdout, r.stderr)
        self.assertEqual(got[True], got[False])
        self.assertEqual(got[False][0], 4)

    def test_continue_stopped_by_signal_clears_mark_and_reports_state(self):
        """続きを止められても（TERM）、続き中の印を外して run の今の状態を送り直す（working のまま残さない）"""
        import signal
        import time
        self.ledger("r1", "pane-7", "/sock-a")
        self.status(r1="paused")
        herdr_bin, log = hermetic.fake_herdr(self.tmp)
        env = hermetic.child_env(PATH=f"{herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}", ARCHON_SLEEP="30",
                                 DEV_DIR=str(DEV))
        p = subprocess.Popen(["sh", "-c", f'. "{DEV}/lib.sh"; works_dev_continue "$1" "$2" r1 workflow approve r1', "_",
                              str(self.archon), str(self.runs)], env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while not (self.tmp / "archon-calls.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        os.killpg(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=20), 130)
        sent = [a for _, a in hermetic.herdr_sockets(log)]
        self.assertEqual(list(self.runs.glob("*.cont")), [])
        self.assertTrue(sent[0].startswith("pane report-agent pane-7 --source works-factory --agent works --state working"), sent)
        self.assertTrue(sent[-1].startswith("pane report-agent pane-7 --source works-factory --agent works --state blocked"), sent)

    def test_sync_sends_to_each_named_runs_pane_and_socket_with_rising_seq(self):
        """名指した run を起こした枠ごとに、その枠のサーバへ送る。名指しも打った殻の枠でもない枠へは送らない。
        1 回の集計で複数の枠へ送る時も通し番号は送るたびに増える"""
        self.ledger("r1", "pane-7", "/sock-a")
        self.ledger("r2", "pane-8", "/sock-b")
        self.ledger("r3", "pane-5", "/sock-a")
        self.status(r1="paused", r2="completed", r3="running")
        r, sent = self.sh('works_dev_herdr_sync "$1" "$2" r1 r2')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([(s, a.split(" --")[0]) for s, a in sent],
                         [("/sock-a", "pane report-agent pane-7"), ("/sock-b", "pane release-agent pane-8")], sent)
        seqs = [int(a.rsplit("--seq ", 1)[1]) for _, a in sent]
        self.assertLess(seqs[0], seqs[1])

    def test_sync_without_socket_goes_to_default_server_unless_same_pane(self):
        """サーバを残していない控えの枠へは既定のサーバへ送る（打った殻のサーバを継がない）。打った殻と同じ名の枠の時だけ、
        前の作りどおり打った殻のサーバへ"""
        self.ledger("r1", "pane-7")
        self.status(r1="paused")
        _, sent = self.sh('works_dev_herdr_sync "$1" "$2" r1', HERDR_ENV="1", HERDR_PANE_ID="pane-9", HERDR_SOCKET_PATH="/sock-b")
        self.assertEqual([(s, a.split(" --")[0]) for s, a in sent], [("(unset)", "pane report-agent pane-7")], sent)
        (self.tmp / "herdr.txt.socket").unlink()
        _, sent = self.sh('works_dev_herdr_sync "$1" "$2"', HERDR_ENV="1", HERDR_PANE_ID="pane-7", HERDR_SOCKET_PATH="/sock-b")
        self.assertEqual([(s, a.split(" --")[0]) for s, a in sent], [("/sock-b", "pane report-agent pane-7")], sent)

    def test_sync_counts_continuing_run_as_running(self):
        """続き中の印（鍵を誰かが持つ）の在る run は、Archon が paused を返しても走る run と数える。鍵の無い印（持ち手が落ちた
        残り物。中の pid が別の処理に使い回されて居ても）は数えない"""
        import fcntl
        self.ledger("r1", "pane-7", "/sock-a")
        self.status(r1="paused")
        for held, want in ((True, "--state working"), (False, "--state blocked")):
            with self.subTest(held=held), open(self.runs / "r1.cont", "w") as mark:
                mark.write(f"{os.getpid()}\n")
                mark.flush()
                if held:
                    fcntl.flock(mark, fcntl.LOCK_EX)
                shutil.rmtree(self.tmp / "herdr-bin", ignore_errors=True)
                (self.tmp / "herdr.txt.socket").unlink(missing_ok=True)
                _, sent = self.sh('works_dev_herdr_sync "$1" "$2" r1=paused')
                self.assertEqual(len(sent), 1, sent)
                self.assertIn(want, sent[0][1])

    def test_go_tail_passes_continue_entry_when_dev_dir_is_set(self):
        """入口の殻（DEV_DIR を置く）の続きの行は続きの口の入口 continue.sh を通り、Archon の生の語（workflow <動詞>）も残す"""
        env = hermetic.child_env(WORKS_DEV_HOME="/h", CLAUDE_BIN_PATH="/c", WORKS_DEV_MODEL="opus")
        for dev_dir, want in ((str(DEV), f"sh {DEV / 'continue.sh'} /a.sh workflow"), ("", "sh /a.sh workflow")):
            with self.subTest(dev_dir=dev_dir):
                r = subprocess.run(["sh", "-c", f'DEV_DIR="{dev_dir}"; . "{DEV}/guard.sh"; . "{DEV}/lib.sh"; works_dev_go /a.sh /x'],
                                   capture_output=True, text=True, encoding="utf-8", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.rstrip("\n").endswith(" " + want), r.stdout)

    def test_continue_entry_needs_home_and_workflow_words(self):
        for args, env_kw in (([str(self.archon), "workflow", "approve", "r1"], {}),
                             ([str(self.archon), "approve", "r1", "x"], {"WORKS_DEV_HOME": str(self.tmp / "home")})):
            with self.subTest(args=args):
                r = subprocess.run(["sh", str(DEV / "continue.sh"), *args], capture_output=True, text=True, encoding="utf-8",
                                   env=hermetic.child_env(**env_kw))
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("usage: ", r.stderr)
        self.assertFalse((self.tmp / "archon-calls.txt").exists())
        # 家を前置きで受け、その家の控えの置き場で続ける
        self.ledger("r1", "pane-7", "/sock-a")
        self.status(r1="running")
        herdr_bin, log = hermetic.fake_herdr(self.tmp)
        r = subprocess.run(["sh", str(DEV / "continue.sh"), str(self.archon), "workflow", "approve", "r1"],
                           capture_output=True, text=True, encoding="utf-8",
                           env=hermetic.child_env(WORKS_DEV_HOME=str(self.tmp / "home"),
                                                  PATH=f"{herdr_bin}{os.pathsep}{os.environ.get('PATH', '')}"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.tmp / "archon-calls.txt").read_text(), "workflow approve r1|1|1\n")
        self.assertEqual(len(hermetic.herdr_sockets(log)), 2)


if __name__ == "__main__":
    unittest.main()
