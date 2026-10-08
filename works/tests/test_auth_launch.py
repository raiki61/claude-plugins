"""殻の認証の起こし役（.shared/core/auth_launch.py）の柵。

- 順の真ん中は本流の写し claude_auth.auth_env を丸ごと呼ぶ（部品を並べ直すと写しの柵はバイト同一のまま緑なので、ここで縛る）
- 名指し（WORKS_KEYCHAIN_ITEM）は受け継いだ認証より先に効き、取れなければ次へ進まない（設計 2.6 順の形 1）
- python3 -I で起こした check は起こし役のフォルダ（試験の持つ写し）に __pycache__ を作らない（-I は PYTHONDONTWRITEBYTECODE を
  見ず、__pycache__ は .gitignore に隠れて git status に出ない）。tree_run.py の CLI と run_tests.py（とその import）の分は
  test_tree_run.py と test_blk_tests_delta.py が各々の写しで見る。共有の works/ はどの試験も見ない（別の実行の残り物で揺れる）。
  試験自身の import の分は各試験の頭の sys.dont_write_bytecode に任せ、試験では縛らない
- Context7 はやめた（持ち主 2026-10-09）: 前の版が読んだ鍵の項目の名（WORKS_CONTEXT7_KEYCHAIN_ITEM）が env に残っていても、
  その項目を読まず、子の環境に CONTEXT7_API_KEY を置かない
security は偽の runner に差し替え、本物の keychain には触らない。
"""
import os
import pathlib
import shutil
import subprocess
import sys
import types
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import auth_launch  # noqa: E402
import claude_auth  # noqa: E402
import hermetic  # noqa: E402

TOKEN = "sk-ant-oat01-fake-for-test"


def keychain(items):
    """-s の名ごとに items の値を返す偽の security（呼ばれた名は calls に残る）"""
    calls = []

    def run(args, **kw):
        service = args[args.index("-s") + 1]
        calls.append(service)
        return types.SimpleNamespace(stdout=items.get(service, ""), returncode=0 if service in items else 44)
    run.calls = calls
    return run


class ResolveOrder(unittest.TestCase):
    def test_middle_stage_follows_the_copys_auth_env(self):
        """真ん中は写しの auth_env の結果にそのまま従う（番兵に差し替えると出どころの名と子に渡す値が変わる）"""
        seen = {}

        def sentinel(env, platform=None, runner=None, service=None):
            seen["env"] = env
            return dict(env, CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-sentinel"), "keychain(sentinel-svc)"
        with mock.patch.object(claude_auth, "auth_env", sentinel):
            got, name, why = auth_launch.resolve({}, "/u", "/u/.claude-p9", platform="darwin", runner=keychain({}))
        self.assertIsNone(why)
        self.assertEqual(got, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-sentinel"})
        self.assertIn("sentinel-svc", name)
        self.assertEqual((seen["env"]["HOME"], seen["env"]["CLAUDE_CONFIG_DIR"]), ("/u", "/u/.claude-p9"))

    def test_back_stage_only_when_the_copy_adds_nothing(self):
        """写しの auth_env が足せなかった時だけ Claude Code 自身の項目を読む。足せた時はその項目を聞きもしない"""
        run = keychain({"Claude Code-credentials": '{"claudeAiOauth": {"accessToken": "%s"}}' % TOKEN})
        with mock.patch.object(claude_auth, "auth_env", lambda env, **kw: (dict(env), "keychain-miss(x)")):
            got, name, _ = auth_launch.resolve({}, "/u", "", platform="darwin", runner=run)
        self.assertEqual((got, name), ({"CLAUDE_CODE_OAUTH_TOKEN": TOKEN}, "Claude Code の keychain の項目 Claude Code-credentials"))
        run2 = keychain({"Claude Code-credentials": TOKEN})
        with mock.patch.object(claude_auth, "auth_env",
                               lambda env, **kw: (dict(env, CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-m"), "keychain(m)")):
            auth_launch.resolve({}, "/u", "", platform="darwin", runner=run2)
        self.assertEqual(run2.calls, [])

    def test_middle_stage_derives_item_from_users_config(self):
        """利用者の設定の置き場（隔離前）から本流の規則で項目を導く: 無ければ ~/.claude → default、~/.claude-p3 → p3"""
        for cfg, service in (("", "claude-code-oauth-default"), ("/u/.claude-p3", "claude-code-oauth-p3")):
            with self.subTest(cfg=cfg):
                run = keychain({service: TOKEN})
                got, name, why = auth_launch.resolve({}, "/u", cfg, platform="darwin", runner=run)
                self.assertIsNone(why)
                self.assertEqual(got, {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN})
                self.assertIn(service, name)
                self.assertEqual(run.calls, [service])

    def test_named_item_beats_inherited_auth(self):
        """WORKS_KEYCHAIN_ITEM は受け継いだ CLAUDE_CODE_OAUTH_TOKEN・ANTHROPIC_API_KEY より先に効く"""
        env = {"WORKS_KEYCHAIN_ITEM": "named", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-env", "ANTHROPIC_API_KEY": "k"}
        run = keychain({"named": TOKEN})
        got, name, why = auth_launch.resolve(env, "/u", "", platform="darwin", runner=run)
        self.assertIsNone(why)
        self.assertEqual(got, {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN})
        self.assertIn("WORKS_KEYCHAIN_ITEM", name)
        self.assertEqual(run.calls, ["named"])

    def test_named_item_empty_or_malformed_stops(self):
        """名指しの項目が空・壊れた値なら次の段（受け継いだ認証・導く項目・Claude Code の項目）へ進まずに止まる"""
        for value in ("", "not-a-token"):
            with self.subTest(value=value):
                run = keychain({"named": value, "claude-code-oauth-default": TOKEN, "Claude Code-credentials": TOKEN})
                got, _name, why = auth_launch.resolve({"WORKS_KEYCHAIN_ITEM": "named", "CLAUDE_CODE_OAUTH_TOKEN": TOKEN},
                                                      "/u", "", platform="darwin", runner=run)
                self.assertIsNone(got)
                self.assertIn("named", why)
                self.assertEqual(run.calls, ["named"])

    def test_user_runner_reads_keychain_with_users_home(self):
        """security はログイン keychain を $HOME 基準で探すので、隔離前の利用者の HOME で起こす"""
        with mock.patch.object(auth_launch.subprocess, "run") as run:
            auth_launch.user_runner("/users-home")(["security"], capture_output=True)
        self.assertEqual(run.call_args.kwargs["env"]["HOME"], "/users-home")


class ChildEnv(unittest.TestCase):
    def test_named_drops_credentials_that_outrank_the_token(self):
        """名指しで決めた時は、Claude Code が CLAUDE_CODE_OAUTH_TOKEN より先に使う資格（写しの INHERITED と FOUNDRY の旗）を外す"""
        env = {"HOME": "/iso", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_USE_FOUNDRY": "1",
               "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_OAUTH_TOKEN": "old"}
        self.assertEqual(auth_launch.child_env(env, {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN}, True),
                         {"HOME": "/iso", "CLAUDE_CODE_OAUTH_TOKEN": TOKEN})
        self.assertEqual(auth_launch.child_env(env, {"ANTHROPIC_API_KEY": "k"}, False), env)


class IsolatedLaunch(unittest.TestCase):
    def fake_security(self, tmp, service):
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "security").write_text(
            '#!/bin/sh\necho "$HOME" > "$0.home"\nprev=\nfor a in "$@"; do\n'
            f'  if [ "$prev" = -s ] && [ "$a" = "{service}" ]; then echo {TOKEN}; exit 0; fi\n'
            '  prev=$a\ndone\nexit 44\n')
        (bin_dir / "security").chmod(0o755)
        return bin_dir

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ")
    def test_exec_hands_the_named_token_only_to_the_child(self):
        """exec は同じプロセスを実行ファイルに置き換え、子の環境にだけ名指しのトークンを置く（上位の資格は外し、隔離した HOME は
        そのまま）。起こし役自身は値を出さず、security は利用者の HOME で起こす"""
        tmp = hermetic.tmpdir(self)
        bin_dir = self.fake_security(tmp, "named")
        probe = ("import os, json; print(json.dumps({k: os.environ.get(k) == %r if k == 'CLAUDE_CODE_OAUTH_TOKEN' "
                 "else os.environ.get(k) for k in ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'HOME')}))" % TOKEN)
        env = hermetic.child_env(HOME=str(tmp / "iso"), PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                                 WORKS_KEYCHAIN_ITEM="named", ANTHROPIC_API_KEY="k", CLAUDE_CODE_OAUTH_TOKEN="inherited")
        r = subprocess.run([sys.executable, "-I", str(CORE / "auth_launch.py"), "exec", "--user-home", str(tmp / "user"),
                            "--", sys.executable, "-I", "-c", probe], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(TOKEN, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), '{"CLAUDE_CODE_OAUTH_TOKEN": true, "ANTHROPIC_API_KEY": null, "HOME": "%s"}'
                         % (tmp / "iso"))
        self.assertEqual((bin_dir / "security.home").read_text().strip(), str(tmp / "user"))

    @unittest.skipUnless(sys.platform == "darwin", "SKIP macos: keychain の段は macOS だけ")
    def test_exec_does_not_read_a_leftover_context7_item(self):
        """Context7 はやめた: 前の版の鍵の項目の名（WORKS_CONTEXT7_KEYCHAIN_ITEM）が env に残っていても、exec はその項目を
        security で読まず、子の環境に CONTEXT7_API_KEY を置かず、その項目の 1 行も出さない"""
        tmp = hermetic.tmpdir(self)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "security").write_text(
            '#!/bin/sh\necho "$@" >> "$0.calls"\nprev=\nfor a in "$@"; do\n'
            f'  if [ "$prev" = -s ] && [ "$a" = named ]; then echo {TOKEN}; exit 0; fi\n'
            '  if [ "$prev" = -s ] && [ "$a" = c7-item ]; then echo ctx7sk-fake; exit 0; fi\n'
            '  prev=$a\ndone\nexit 44\n')
        (bin_dir / "security").chmod(0o755)
        probe = "import os; print(os.environ.get('CONTEXT7_API_KEY'))"
        env = hermetic.child_env(HOME=str(tmp / "iso"), PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                                 WORKS_KEYCHAIN_ITEM="named", WORKS_CONTEXT7_KEYCHAIN_ITEM="c7-item")
        r = subprocess.run([sys.executable, "-I", str(CORE / "auth_launch.py"), "exec", "--for", "archon.sh",
                            "--user-home", str(tmp / "user"), "--", sys.executable, "-I", "-c", probe],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "None")
        self.assertNotIn("c7-item", (bin_dir / "security.calls").read_text() + r.stderr)
        self.assertFalse(hasattr(auth_launch, "context7_env"))

    def test_exec_stops_with_howto_and_does_not_start_the_child(self):
        """認証が無ければ、子を起こさず 1 行の案内（呼び手の名つき）で 2"""
        tmp = hermetic.tmpdir(self)
        bin_dir = self.fake_security(tmp, "nothing-here")
        env = hermetic.child_env(HOME=str(tmp), PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run([sys.executable, "-I", str(CORE / "auth_launch.py"), "exec", "--for", "archon.sh",
                            "--user-home", str(tmp), "--", sys.executable, "-c", "print('started')"],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertTrue(r.stderr.startswith("archon.sh: " + auth_launch.HOWTO), r.stderr)

    def test_shells_do_not_read_the_keychain_themselves(self):
        """認証の順と keychain の読み出しは起こし役だけが持つ。殻に書き戻したら赤（語で見る）"""
        for sh in sorted((ROOT / "dev").glob("*.sh")):
            body = sh.read_text(encoding="utf-8")
            for word in ("security find-generic-password", "works_dev_auth_candidates", 'CLAUDE_CODE_OAUTH_TOKEN="$('):
                with self.subTest(sh=sh.name, word=word):
                    self.assertNotIn(word, body)

    def test_check_prints_only_the_name_and_leaves_no_pycache(self):
        """python3 -I で check を起こす（殻と同じ起こし方）。標準出力は出どころの名だけでトークンを出さず、
        終わった後に起こし役のフォルダの写しの下に __pycache__ が無い"""
        tmp = hermetic.tmpdir(self)
        # 共有の作業ツリーを見ると別の実行が残した __pycache__ を拾うので、この試験だけが持つ写しで起こす。
        # symlink は不可（auth_launch.py は __file__.resolve() の親を sys.path に入れ、本物の CORE に書く）
        core = tmp / "core"
        shutil.copytree(CORE, core, ignore=shutil.ignore_patterns("__pycache__"))
        home = tmp / "home"
        home.mkdir()
        env = hermetic.child_env(CLAUDE_CODE_OAUTH_TOKEN=TOKEN, HOME=str(home))
        r = subprocess.run([sys.executable, "-I", str(core / "auth_launch.py"), "check", "--user-home", str(home)],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "CLAUDE_CODE_OAUTH_TOKEN"), r.stderr)
        self.assertNotIn(TOKEN, r.stdout + r.stderr)
        self.assertEqual(list(core.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
