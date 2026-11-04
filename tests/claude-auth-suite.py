"""共通の認証の部品 scripts/claude_auth.py のうち、アカウントの OAuth トークンを探す口（account_token）の試験。
Keychain（security）と資格情報のファイルは偽物にする。

アカウントの持ち方は人で違う。次の 3 つを同じ口で扱う。
- `claude` をそのまま使う人: Claude Code 自身が Keychain の項目（値は JSON）か、設定のフォルダの .credentials.json に置く
- 設定のフォルダを分け、自分で Keychain に項目を作る人: 項目の値はトークンそのもの
- 項目の名前を自分で決めている人: 設定で名前を渡す
"""

import datetime
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import claude_auth  # noqa: E402

TOK = "sk-ant-oat01-" + "x" * 20


def keychain(items):
    """items: {サービス名: 値}。security find-generic-password -s <名> -w の偽物"""
    asked = []

    def run(args, **kw):
        svc = args[args.index("-s") + 1]
        asked.append(svc)
        val = items.get(svc)
        return subprocess.CompletedProcess(args, 0 if val else 44, stdout=(val or ""), stderr="")
    run.asked = asked
    return run


class ConfigDir(unittest.TestCase):
    def test_default_folder_is_under_the_given_home(self):
        # 渡した環境の HOME を使う（account_token と同じ）。呼ぶ側が別の利用者や試験の家を渡せる
        self.assertEqual(claude_auth.config_dir({"HOME": "/h"}), str(pathlib.Path("/h", ".claude")))
        self.assertEqual(claude_auth.config_dir({"HOME": "/h", "CLAUDE_CONFIG_DIR": "/x"}), "/x")


class AccountToken(unittest.TestCase):
    def test_named_item_comes_first(self):
        run = keychain({"my-item": TOK})
        self.assertEqual(claude_auth.account_token("/h/.claude-a", {}, "my-item", "darwin", run), (TOK, "keychain(my-item)"))

    def test_item_named_from_the_folder(self):
        run = keychain({"claude-code-oauth-p1": TOK})
        tok, note = claude_auth.account_token("/h/.claude-p1", {}, None, "darwin", run)
        self.assertEqual((tok, note), (TOK, "keychain(claude-code-oauth-p1)"))

    def test_claude_codes_own_item_holds_json(self):
        login = json.dumps({"claudeAiOauth": {"accessToken": TOK, "refreshToken": "r"}})
        own = claude_auth.claude_code_items("/h/.claude-w")[0]
        run = keychain({own: login})
        tok, note = claude_auth.account_token("/h/.claude-w", {}, None, "darwin", run)
        self.assertEqual((tok, note), (TOK, f"keychain({own})"))

    def test_default_folder_uses_the_plain_item(self):
        # CLAUDE_CONFIG_DIR を入れずに起動する claude は、名前に足し書きの無い項目を使う
        self.assertEqual(claude_auth.claude_code_items(None), ["Claude Code-credentials"])
        # 既定のフォルダを名指したときだけ、足し書きの無い項目も試す
        self.assertEqual(claude_auth.claude_code_items("/h/.claude", home="/h")[1:], ["Claude Code-credentials"])

    def test_other_folder_never_falls_back_to_the_default_accounts_item(self):
        # 足し書きの無い項目は既定のアカウントの物。別のフォルダのアカウントがそれを読むと、別のアカウントの鍵で動く
        items = claude_auth.claude_code_items("/h/.claude-x", home="/h")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].startswith("Claude Code-credentials-"))
        login = json.dumps({"claudeAiOauth": {"accessToken": TOK}})
        tok, note = claude_auth.account_token("/h/.claude-x", {"HOME": "/h"}, None, "darwin",
                                              keychain({"Claude Code-credentials": login}))
        self.assertIsNone(tok)

    def test_credentials_file_when_there_is_no_keychain(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": TOK}}))
        tok, note = claude_auth.account_token(str(d), {}, None, "linux", keychain({}))
        self.assertEqual((tok, note), (TOK, "file(.credentials.json)"))

    def test_malformed_credentials_file_is_named_not_dropped(self):
        # 形の違う値は渡さないが、捨てたことは探した所の並びに出す（無いのと同じに見せない）
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-other-x"}}))
        tok, note = claude_auth.account_token(str(d), {}, None, "linux", keychain({}))
        self.assertIsNone(tok)
        self.assertIn(".credentials.json:file-malformed", note)
        (d / ".credentials.json").write_text("{}")   # 在るのにトークンが無い物も、無いのと同じに見せない
        self.assertIn(":file-malformed", claude_auth.account_token(str(d), {}, None, "linux", keychain({}))[1])
        (d / ".credentials.json").write_text("not json")
        self.assertIn(":file-malformed", claude_auth.account_token(str(d), {}, None, "linux", keychain({}))[1])
        e = pathlib.Path(tempfile.mkdtemp())
        self.assertIn(":file-miss", claude_auth.account_token(str(e), {}, None, "linux", keychain({}))[1])

    def test_nothing_found_names_where_it_looked(self):
        tok, note = claude_auth.account_token("/nowhere/.claude-z", {}, None, "darwin", keychain({}))
        self.assertIsNone(tok)
        self.assertIn("claude-code-oauth-z", note)
        self.assertIn("Claude Code-credentials", note)


def helper(values, code=0):
    """利用者の窓口（CLAUDE_TOKEN_HELPER）の偽物。values: {設定のフォルダ: 出す値}。security の問いが来たら赤にする"""
    asked = []

    def run(args, **kw):
        assert args[0] == "/bin/tok", "窓口でない物を起動した: %r" % (args,)
        asked.append(args)
        val = values.get(args[1], "")
        return subprocess.CompletedProcess(args, code if val else 1, stdout=val, stderr="")
    run.asked = asked
    return run


HELPER = {"CLAUDE_TOKEN_HELPER": "/bin/tok"}


class TokenHelper(unittest.TestCase):
    """鍵の置き場を利用者の側の 1 か所（窓口）だけが知る人の口。窓口には設定のフォルダだけを渡し、トークンを受け取る"""

    def test_helper_gets_the_folder_and_its_token_is_used_on_any_os(self):
        for platform in ("linux", "darwin", "win32"):
            run = helper({"/h/.claude-p2": TOK + "\n"})
            self.assertEqual(claude_auth.account_token("/h/.claude-p2", HELPER, None, platform, run), (TOK, "helper"))
            self.assertEqual(run.asked, [["/bin/tok", "/h/.claude-p2"]])

    def test_default_account_passes_the_default_folder(self):
        run = helper({"/h/.claude": TOK})
        self.assertEqual(claude_auth.account_token(None, dict(HELPER, HOME="/h"), None, "linux", run)[0], TOK)
        self.assertEqual(run.asked[0][1], str(pathlib.Path("/h", ".claude")))

    def test_empty_or_failing_helper_falls_back_and_says_so(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": TOK}}))
        self.assertEqual(claude_auth.account_token(str(d), HELPER, None, "linux", helper({})),
                         (TOK, "file(.credentials.json)"))
        tok, note = claude_auth.account_token("/nowhere/.claude-z", HELPER, None, "linux", helper({}))
        self.assertIsNone(tok)
        self.assertIn("helper-miss", note)

    def test_malformed_value_is_not_passed_and_not_shown(self):
        tok, note = claude_auth.account_token("/h/.claude-p2", HELPER, None, "linux", helper({"/h/.claude-p2": "oops-secret"}))
        self.assertIsNone(tok)
        self.assertIn("helper-malformed", note)
        self.assertNotIn("oops-secret", note)

    def test_helper_that_cannot_start_falls_back(self):
        def boom(args, **kw):
            raise FileNotFoundError(args[0])
        tok, note = claude_auth.account_token("/h/.claude-p2", HELPER, None, "linux", boom)
        self.assertIsNone(tok)
        self.assertIn("helper-error(FileNotFoundError)", note)

    def test_named_keychain_item_wins_over_the_helper(self):
        # 呼ぶ側が項目を名指したら、その項目を読む（窓口には頼まない）
        run = keychain({"my-item": TOK})
        self.assertEqual(claude_auth.account_token("/h/.claude-a", HELPER, "my-item", "darwin", run), (TOK, "keychain(my-item)"))

    def test_auth_env_adds_the_helpers_token(self):
        out, note = claude_auth.auth_env(dict(HELPER, CLAUDE_CONFIG_DIR="/h/.claude-p2"), "linux",
                                         helper({"/h/.claude-p2": TOK}))
        self.assertEqual((out["CLAUDE_CODE_OAUTH_TOKEN"], note), (TOK, "helper"))
        self.assertTrue(claude_auth.added(note))

    def test_auth_env_keeps_the_inherited_route(self):
        env = dict(HELPER, CLAUDE_CONFIG_DIR="/h/.claude-p2", ANTHROPIC_API_KEY="k")
        out, note = claude_auth.auth_env(env, "linux", helper({"/h/.claude-p2": TOK}))
        self.assertEqual(note, "inherited(ANTHROPIC_API_KEY)")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", out)

    def test_auth_env_without_helper_is_unchanged(self):
        self.assertEqual(claude_auth.auth_env({"CLAUDE_CONFIG_DIR": "/h/.claude-p2"}, "linux", helper({}))[1], "none")


# security find-generic-password -s <名>（-w なし）の実物の出力の形（2026-10-19 に macOS 26 で採った。値は替えてある）
ATTRS = """keychain: "/h/Library/Keychains/login.keychain-db"
version: 512
class: "genp"
attributes:
    "acct"<blob>="x"
    "cdat"<timedate>=0x32303236303931373030353934345A00  "20260917005944Z\\000"
    "mdat"<timedate>=0x32303236303931373030353934345A00  "20260917005944Z\\000"
    "svce"<blob>="claude-code-oauth-p3"
"""


def attrs(text, code=0):
    asked = []

    def run(args, **kw):
        asked.append(args)
        return subprocess.CompletedProcess(args, code, stdout=text, stderr="")
    run.asked = asked
    return run


def day(y, m, d):
    """その日の UTC の 12 時（ATTRS の書き換えた時刻 00:59 から、日の数が日付の差と同じになる時刻）"""
    return datetime.datetime(y, m, d, 12, tzinfo=datetime.timezone.utc)


class Expiry(unittest.TestCase):
    def test_age_is_counted_from_the_last_write_without_reading_the_token(self):
        run = attrs(ATTRS)
        self.assertEqual(claude_auth.keychain_age_days("claude-code-oauth-p3", run, day(2026, 10, 19)), 32)
        self.assertNotIn("-w", run.asked[0])   # 値（トークン）は読まない

    def test_missing_or_unreadable_item_has_no_age(self):
        self.assertIsNone(claude_auth.keychain_age_days("x", attrs("", 44)))
        self.assertIsNone(claude_auth.keychain_age_days("x", attrs("attributes:\n")))

        def boom(args, **kw):
            raise FileNotFoundError("security")
        self.assertIsNone(claude_auth.keychain_age_days("x", boom))

    def test_note_starts_before_the_one_year_lifetime_ends(self):
        self.assertIsNone(claude_auth.expiry_note("s", attrs(ATTRS), day(2027, 8, 17)))   # 334 日
        self.assertIn("30 日後に切れる見込み", claude_auth.expiry_note("s", attrs(ATTRS), day(2027, 8, 18)))   # 335 日
        self.assertIn("今日切れる見込み", claude_auth.expiry_note("s", attrs(ATTRS), day(2027, 9, 17)))   # 365 日
        near = claude_auth.expiry_note("s", attrs(ATTRS), day(2027, 9, 1))
        self.assertIn("16 日後に切れる見込み", near)
        self.assertIn("claude setup-token", near)
        self.assertIn("切れた見込み", claude_auth.expiry_note("s", attrs(ATTRS), day(2027, 10, 1)))
        self.assertIsNone(claude_auth.expiry_note("s", attrs("", 44), day(2027, 10, 1)))


class AuthFailed(unittest.TestCase):
    def test_short_non_json_line_is_an_auth_failure(self):
        # 実測 2026-09-15: 認証切れの子は、この 1 行を標準出力に出して終了コード 0 で返った
        self.assertTrue(claude_auth.auth_failed("Failed to authenticate: OAuth session expired and could not be refreshed\n"))
        self.assertTrue(claude_auth.auth_failed(b"Invalid API key \xc2\xb7 Please run /login"))

    def test_json_error_result_naming_auth_is_an_auth_failure(self):
        self.assertTrue(claude_auth.auth_failed(json.dumps({"type": "result", "is_error": True,
                                                            "result": "Failed to authenticate. API Error: 401"})))
        self.assertTrue(claude_auth.auth_failed(json.dumps({"is_error": True, "result": "Login expired · Please run /login"})))
        self.assertFalse(claude_auth.auth_failed(json.dumps({"is_error": True, "result": "Prompt is too long"})))

    def test_json_empty_long_or_many_lines_are_not(self):
        self.assertFalse(claude_auth.auth_failed('{"type": "result", "is_error": false}'))
        self.assertFalse(claude_auth.auth_failed(""))
        self.assertFalse(claude_auth.auth_failed("x" * (claude_auth.AUTH_FAILURE_MAX_BYTES + 1)))
        self.assertFalse(claude_auth.auth_failed("一行目\n二行目"))


if __name__ == "__main__":
    unittest.main()
