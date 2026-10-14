"""共通の認証の部品 scripts/claude_auth.py のうち、アカウントの OAuth トークンを探す口（account_token）の試験。
Keychain（security）と資格情報のファイルは偽物にする。

アカウントの持ち方は人で違う。次の 3 つを同じ口で扱う。
- `claude` をそのまま使う人: Claude Code 自身が Keychain の項目（値は JSON）か、設定のフォルダの .credentials.json に置く
- 設定のフォルダを分け、自分で Keychain に項目を作る人: 項目の値はトークンそのもの
- 項目の名前を自分で決めている人: 設定で名前を渡す
"""

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
        # CLAUDE_CONFIG_DIR を入れずに起こす claude は、名前に足し書きの無い項目を使う
        self.assertEqual(claude_auth.claude_code_items(None), ["Claude Code-credentials"])
        self.assertEqual(len(claude_auth.claude_code_items("/h/.claude-x")), 2)

    def test_credentials_file_when_there_is_no_keychain(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": TOK}}))
        tok, note = claude_auth.account_token(str(d), {}, None, "linux", keychain({}))
        self.assertEqual((tok, note), (TOK, "file(.credentials.json)"))

    def test_nothing_found_names_where_it_looked(self):
        tok, note = claude_auth.account_token("/nowhere/.claude-z", {}, None, "darwin", keychain({}))
        self.assertIsNone(tok)
        self.assertIn("claude-code-oauth-z", note)
        self.assertIn("Claude Code-credentials", note)


if __name__ == "__main__":
    unittest.main()
