"""使用率の控え（limits.py）。控えの形は ~/.cache/claude-limits/<アカウント名>.json で、
{"five_hour": {used_percentage, resets_at, updated_at}, "seven_day": {...}, "updated_at", "source"?}。
アカウントの数と名前は dispatch の設定から読み、1 つでも 7 つでも同じに動く。API と Keychain は偽物にする。"""

import ast
import json
import pathlib
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest

from . import DISPATCH
import config
import limits

NOW = 1_800_000_000


def win(p, reset, at=NOW):
    return {"used_percentage": p, "resets_at": reset, "updated_at": at}


HEADERS = """HTTP/2 200\r
anthropic-ratelimit-unified-5h-utilization: 0.38\r
anthropic-ratelimit-unified-5h-reset: 1800003840\r
anthropic-ratelimit-unified-7d-utilization: 0.32\r
Anthropic-Ratelimit-Unified-7d-Reset: 1800187200\r
anthropic-ratelimit-unified-status: allowed\r
"""


class Headers(unittest.TestCase):
    def test_reads_both_windows_as_percent(self):
        snap = limits.from_headers(HEADERS, NOW)
        self.assertEqual(snap["five_hour"], win(38.0, 1800003840))
        self.assertEqual(snap["seven_day"], win(32.0, 1800187200))
        self.assertEqual(snap["source"], "probe")

    def test_rejected_window_without_its_own_header_is_full(self):
        text = ("anthropic-ratelimit-unified-status: rejected\n"
                "anthropic-ratelimit-unified-representative-claim: five_hour\n"
                "anthropic-ratelimit-unified-reset: 1800000900\n")
        snap = limits.from_headers(text, NOW)
        self.assertEqual(snap["five_hour"], win(100, 1800000900))
        self.assertIsNone(snap["seven_day"])

    def test_no_ratelimit_headers_is_none(self):
        self.assertIsNone(limits.from_headers("HTTP/2 401\r\n", NOW))


class NeedProbe(unittest.TestCase):
    def test_missing_or_partial_snapshot_needs_probe(self):
        self.assertTrue(limits.need_probe(None, NOW))
        self.assertTrue(limits.need_probe({"five_hour": win(1, NOW + 60), "seven_day": None}, NOW))

    def test_passed_reset_needs_probe(self):
        self.assertTrue(limits.need_probe({"five_hour": win(1, NOW - 1), "seven_day": win(1, NOW + 60)}, NOW))

    def test_fresh_snapshot_does_not(self):
        self.assertFalse(limits.need_probe({"five_hour": win(1, NOW + 60), "seven_day": win(1, NOW + 60)}, NOW))

    def test_stale_seven_day_needs_probe_sooner_than_five_hour(self):
        snap = {"five_hour": win(1, NOW + 9999, NOW - 20 * 60), "seven_day": win(1, NOW + 9999, NOW - 20 * 60)}
        self.assertTrue(limits.need_probe(snap, NOW))
        snap["seven_day"]["updated_at"] = NOW
        self.assertFalse(limits.need_probe(snap, NOW))

    def test_full_window_is_not_probed_while_it_lasts(self):
        snap = {"five_hour": win(100, NOW + 600, NOW - 9999), "seven_day": win(50, NOW + 9999, NOW - 9999)}
        self.assertFalse(limits.need_probe(snap, NOW))


class Render(unittest.TestCase):
    def test_one_line_per_account(self):
        snap = {"five_hour": win(38.2, NOW + 3840), "seven_day": win(32, NOW + 187200)}
        self.assertEqual(limits.render("p1", snap, NOW), "p1 5h 38% 1h4m  7d 32% 2d4h")

    def test_high_usage_is_marked_and_passed_reset_reads_zero(self):
        snap = {"five_hour": win(85, NOW - 5), "seven_day": win(91, NOW + 120)}
        self.assertEqual(limits.render("a", snap, NOW), "a 5h 0%  7d 91%! 2m")

    def test_no_snapshot_is_empty(self):
        self.assertEqual(limits.render("a", None, NOW), "")


class Record(unittest.TestCase):
    def test_five_hour_takes_the_newer_or_higher_value(self):
        old = {"five_hour": win(10, NOW + 100, NOW - 50), "seven_day": win(30, NOW + 999, NOW - 50)}
        got = limits.merge_statusline(old, {"five_hour": {"used_percentage": 12, "resets_at": NOW + 100}}, NOW)
        self.assertEqual(got["five_hour"], win(12, NOW + 100))
        self.assertEqual(got["seven_day"], old["seven_day"])

    def test_seven_day_is_written_only_when_its_window_moves_or_is_missing(self):
        old = {"five_hour": None, "seven_day": win(30, NOW + 999, NOW - 50)}
        same = limits.merge_statusline(old, {"seven_day": {"used_percentage": 62, "resets_at": NOW + 999}}, NOW)
        self.assertIsNone(same)  # 7d を大きさで採らない（放置ペインの古い高い値が今の値を潰すため）。変わらなければ書かない
        moved = limits.merge_statusline(old, {"seven_day": {"used_percentage": 2, "resets_at": NOW + 5000}}, NOW)
        self.assertEqual(moved["seven_day"], win(2, NOW + 5000))
        first = limits.merge_statusline(None, {"seven_day": {"used_percentage": 5, "resets_at": NOW + 5000}}, NOW)
        self.assertEqual(first["seven_day"], win(5, NOW + 5000))

    def test_name_follows_the_account_whose_folder_runs_the_statusline(self):
        accts = (config.Account("main", "claude", None), config.Account("w7", "claude-w7", "/h/.claude-w7"))
        self.assertEqual(limits.account_for(accts, {"CLAUDE_CONFIG_DIR": "/h/.claude-w7", "HOME": "/h"}), "w7")
        self.assertEqual(limits.account_for(accts, {"HOME": "/h"}), "main")
        self.assertIsNone(limits.account_for(accts, {"CLAUDE_CONFIG_DIR": "/h/.claude-x", "HOME": "/h"}))


def accounts(n):
    return tuple(config.Account(f"a{i}", f"claude-a{i}", f"/h/.claude-a{i}") for i in range(n))


class ProbeAll(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def run_probe(self, accts, fetch=None, token=None):
        asked = []

        def fake_fetch(tok):
            asked.append(tok)
            return HEADERS if fetch is None else fetch(tok)
        limits.probe_all(accts, str(self.dir), {"HOME": "/h"}, NOW,
                         token=token or (lambda user_config, explicit: (f"tok-{explicit or user_config}", "keychain")), fetch=fake_fetch)
        return asked

    def test_seven_accounts_are_all_probed_and_written(self):
        asked = self.run_probe(accounts(7))
        self.assertEqual(len(asked), 7)
        for i in range(7):
            snap = json.loads((self.dir / f"a{i}.json").read_text())
            self.assertEqual(snap["five_hour"]["used_percentage"], 38.0)

    def test_one_account_works_the_same(self):
        self.assertEqual(len(self.run_probe(accounts(1))), 1)
        self.assertTrue((self.dir / "a0.json").is_file())

    def test_keychain_service_comes_from_the_config_or_the_shared_rule(self):
        accts = (config.Account("a", "c", "/h/.claude-a", "my-item"), config.Account("b", "c", "/h/.claude-b"))
        asked = self.run_probe(accts)
        # 鍵を探す口（scripts/claude_auth.py の account_token）には、設定のフォルダと項目の名前の上書きをそのまま渡す
        self.assertEqual(asked, ["tok-my-item", "tok-/h/.claude-b"])

    def test_account_without_usage_window_is_not_probed(self):
        accts = accounts(1) + (config.Account("local", "claude-ollama", None, None, False),)
        self.assertEqual(len(self.run_probe(accts)), 1)
        self.assertFalse((self.dir / "local.json").exists())

    def test_force_asks_even_for_fresh_accounts(self):
        # dispatch が始める前と /catchup の後に、今の値を取るために使う。古さと、試み直しの待ちを見ない
        fresh = {"five_hour": win(5, NOW + 3600), "seven_day": win(40, NOW + 86400)}
        (self.dir / "a0.json").write_text(json.dumps(fresh), encoding="utf-8")
        (self.dir / ".probe-a0").write_text(str(NOW), encoding="utf-8")
        asked = []
        limits.probe_all(accounts(1), self.dir, {}, NOW, token=lambda c, e: ("tok", "x"),
                         fetch=lambda tok: asked.append(tok) or HEADERS, force=True)
        self.assertEqual(asked, ["tok"])

    def test_network_failure_is_logged(self):
        def down(tok):
            raise OSError("接続できない")
        self.assertEqual(len(self.run_probe(accounts(1), fetch=down)), 1)
        self.assertIn("接続できない", (self.dir / "probe.log").read_text(encoding="utf-8"))
        self.assertFalse((self.dir / "a0.json").exists())

    def test_shared_keychain_override_does_not_apply_to_every_account(self):
        # CLAUDE_KEYCHAIN_SERVICE はシェル全体に効く上書きで、残すと全アカウントが同じ鍵（同じ使用率）になる。
        # 既定の鍵の探し方（probe_all が account_token に渡す環境）からは外す。アカウントごとの名前は keychain_service で書く
        env = limits.probe_env({"HOME": "/h", "CLAUDE_KEYCHAIN_SERVICE": "one-item"})
        self.assertEqual(env, {"HOME": "/h"})

    def test_http_level_failure_is_logged_and_the_next_account_still_probed(self):
        import http.client
        asked = []

        def flaky(tok):
            asked.append(tok)
            if len(asked) == 1:
                raise http.client.IncompleteRead(b"")
            return HEADERS
        self.run_probe(accounts(2), fetch=flaky)
        self.assertEqual(len(asked), 2)
        self.assertIn("a0", (self.dir / "probe.log").read_text(encoding="utf-8"))
        self.assertTrue((self.dir / "a1.json").is_file())

    def test_fresh_account_is_skipped_and_failure_is_logged_and_waits(self):
        (self.dir / "a0.json").write_text(json.dumps({"five_hour": win(1, NOW + 60), "seven_day": win(1, NOW + 60)}))
        asked = self.run_probe(accounts(2), token=lambda user_config, explicit: (None, "keychain-miss"))
        self.assertEqual(asked, [])
        self.assertIn("a1", (self.dir / "probe.log").read_text(encoding="utf-8"))
        self.assertIn("keychain-miss", (self.dir / "probe.log").read_text(encoding="utf-8"))
        self.assertFalse((self.dir / "a1.json").exists())
        # 失敗の後は、待ちの間は投げ直さない
        again = self.run_probe(accounts(2))
        self.assertEqual(again, [])


class HerdrConfig(unittest.TestCase):
    def test_one_entry_per_account_plus_one_probe(self):
        for n in (1, 7):
            with self.subTest(accounts=n):
                lines = limits.herdr_entries(accounts(n), "/p/limits.py", "/l/accounts.json")
                self.assertEqual(len(lines), n + 1)
                self.assertIn("show a0", lines[0])
                self.assertIn("--accounts /l/accounts.json", lines[0])
                self.assertIn("probe", lines[-1])

    def test_account_without_usage_window_gets_no_entry(self):
        accts = accounts(2) + (config.Account("local", "claude-ollama", None, None, False),)
        lines = limits.herdr_entries(accts, "/p/limits.py", "/l/accounts.json")
        self.assertEqual(len(lines), 3)
        self.assertNotIn("local", "\n".join(lines))

    def test_lines_take_python_from_path_and_do_not_read_the_toml(self):
        # herdr がタブ欄のコマンドに渡す PATH は、ログインのシェルの PATH と違う（macOS では OS に付いてくる 3.9 が先に来た）。
        # 絶対パスはマシンごとに違うので書かず、このリポジトリのフックと同じく PATH の python3 か python を使う。
        # そのため、タブ欄から呼ぶ道は TOML（tomllib は 3.11 から）を読まず、herdr-config が書いた JSON の写しを読む
        for line in limits.herdr_entries(accounts(2), "/p/limits.py", "/l/accounts.json"):
            self.assertIn("command -v python3 || command -v python", line)
            self.assertIn("--accounts /l/accounts.json", line)
            self.assertNotIn("--config", line)

    def test_lines_stay_valid_toml_when_paths_have_backslashes(self):
        # Windows のパスは \ を含む。TOML の "…" の中では \ がエスケープの始まりなので、そのまま埋めると herdr が設定を読めない
        script, snap = r"D:\a\p\limits.py", r"C:\Users\me\lim\accounts.json"
        for line in limits.herdr_entries(accounts(1), script, snap):
            command = tomllib.loads("x = [" + line + "]")["x"][0]["command"]
            self.assertIn(f"{shlex.quote(script)} --accounts {shlex.quote(snap)}", command)

    def test_snapshot_round_trips_what_show_probe_and_record_need(self):
        accts = (config.Account("main", "claude"),
                 config.Account("p1", "claude-p1", "~/.claude-p1", "kc-p1"),
                 config.Account("local", "claude-ollama", None, None, False))
        d = pathlib.Path(tempfile.mkdtemp())
        path = d / "accounts.json"
        limits.write_snapshot(path, accts, "/l")
        got, limits_dir = limits.read_snapshot(path)
        self.assertEqual(limits_dir, "/l")
        self.assertEqual([(a.name, a.config_dir, a.keychain_service, a.limits) for a in got],
                         [("main", None, None, True), ("p1", "~/.claude-p1", "kc-p1", True), ("local", None, None, False)])

    def test_herdr_config_writes_the_snapshot_next_to_the_records(self):
        d = pathlib.Path(tempfile.mkdtemp())
        toml = d / "dispatch.toml"
        toml.write_text(f'limits_dir = \'{d / "lim"}\'\naccounts = [{{ name = "p1", command = "claude-p1", config_dir = "/h/.claude-p1" }}]\n'
                        f'[[repos]]\nrepo = "o/r"\nsource = \'{d}\'\nclone_root = \'{d}\'\nsecond_prompt_file = \'{toml}\'\n', encoding="utf-8")
        out = subprocess.run([sys.executable, str(DISPATCH / "limits.py"), "--config", str(toml), "herdr-config"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        snap = d / "lim" / "accounts.json"
        self.assertEqual([a.name for a in limits.read_snapshot(snap)[0]], ["p1"])
        command = tomllib.loads(out.stdout)["tab_bar_right"][0]["command"]
        self.assertIn(f"--accounts {shlex.quote(str(snap))}", command)

    def test_show_and_probe_run_where_tomllib_is_missing(self):
        d = pathlib.Path(tempfile.mkdtemp())
        limits.write_snapshot(d / "accounts.json", accounts(1), str(d))
        fresh = {"five_hour": win(5, NOW + 3600, NOW), "seven_day": win(40, NOW + 86400, NOW)}
        (d / "a0.json").write_text(json.dumps(fresh), encoding="utf-8")
        code = ("import sys, time; sys.modules['tomllib'] = None; time.time = lambda: %d\n"
                "sys.path.insert(0, %r); import limits\n"
                "assert limits.main(['--accounts', %r, 'show', 'a0']) == 0\n"
                "assert limits.main(['--accounts', %r, 'probe']) == 0\n"
                "assert 'config' not in sys.modules") % (NOW, str(DISPATCH), str(d / "accounts.json"), str(d / "accounts.json"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("a0 5h 5%"), out.stdout)

    def test_tab_bar_path_reads_as_python_3_9(self):
        # macOS に付いてくる python3 は 3.9。タブ欄から呼ぶファイルは、その文法で読めること
        for rel in ("limits.py", "vendor/claude_auth.py"):
            with self.subTest(file=rel):
                ast.parse((DISPATCH / rel).read_text(encoding="utf-8"), feature_version=(3, 9))

    def test_more_than_herdr_allows_is_refused(self):
        # herdr の tab_bar_right は 16 個まで。アカウントの表示と取り直しの 1 個で 15 アカウントまで
        with self.assertRaises(ValueError):
            limits.herdr_entries(accounts(16), "/p/limits.py", "/l/accounts.json")


if __name__ == "__main__":
    unittest.main()
