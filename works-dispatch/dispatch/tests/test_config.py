"""設定の読み（config.load）と JSON の入出力（jsonio）。"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

from . import DISPATCH  # noqa: F401 — import の道を整える
import config
import jsonio
from . import schemacheck


def write(dirpath, name, body):
    p = pathlib.Path(dirpath) / name
    p.write_text(body, encoding="utf-8")
    return str(p)


FULL = """
limit_percent = 95
limits_dir = '{d}/limits'
accounts = [
  {{ name = "main", command = "claude",   config_dir = '{d}/c0' }},
  {{ name = "a1",   command = "claude-a", config_dir = '{d}/c1' }},
]

[[repos]]
repo = "o/r"
second_prompt_file = '{d}/second.md'
source = '{d}/src'
copy_files = ["frontend/.env.local", "deploy/local/secrets.local.yaml"]
copy_from = '{d}/keep'
gh_user = "me-at-work"
"""


class Load(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        write(self.d, "second.md", "1. 深掘りして\n2. 世の中の解と照合して\n")

    def test_full_config(self):
        cfg = config.load(write(self.d, "c.toml", FULL.format(d=self.d)), env={})
        self.assertEqual(cfg.limit_percent, 95)
        self.assertEqual(cfg.limits_dir, f"{self.d}/limits")
        self.assertEqual(cfg.accounts, (
            config.Account("main", "claude", f"{self.d}/c0"),
            config.Account("a1", "claude-a", f"{self.d}/c1"),
        ))
        repo = cfg.repos[0]
        self.assertEqual(repo.repo, "o/r")
        self.assertEqual(repo.second_prompt, "1. 深掘りして\n2. 世の中の解と照合して\n")
        self.assertEqual(repo.source, f"{self.d}/src")
        self.assertEqual(repo.copy_files, ("frontend/.env.local", "deploy/local/secrets.local.yaml"))
        self.assertEqual(repo.copy_from, f"{self.d}/keep")
        self.assertEqual(repo.gh_user, "me-at-work")
        self.assertEqual(cfg.notes, ())
        self.assertEqual(config.copy_root(repo), f"{self.d}/keep")

    def test_task_cwd_is_ignored_with_a_note(self):
        # サブエージェントは自分の作業場で起動する（会社の形の設計 4.1）。書かれていても止めず、注記を出して無視する（形が違っても止めない）
        for value in ("'~/notes'", "3"):
            with self.subTest(value=value):
                cfg = config.load(write(self.d, "c.toml", FULL.format(d=self.d) + f"task_cwd = {value}\n"), env={})
                self.assertFalse(hasattr(cfg.repos[0], "task_cwd"))
                [note] = cfg.notes
                self.assertIn("task_cwd は使わなくなったので無視した", note)

    def test_pick_repo_by_name_or_by_the_source_clone_path(self):
        cfg = config.load(write(self.d, "c.toml", FULL.format(d=self.d)), env={})
        self.assertEqual(config.pick_repo(cfg, "o/r").repo, "o/r")
        os.makedirs(f"{self.d}/src", exist_ok=True)
        self.assertEqual(config.pick_repo(cfg, f"{self.d}/src/").repo, "o/r")
        with self.assertRaises(config.ConfigError):
            config.pick_repo(cfg, f"{self.d}/elsewhere")

    def test_defaults_without_accounts_or_limits(self):
        body = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n'
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.accounts, (config.Account("default", "claude", None),))
        self.assertEqual(cfg.repos[0].copy_files, ())
        # copy_from を書かなければ、元の clone から写す
        self.assertIsNone(cfg.repos[0].copy_from)
        # gh_user を書かなければ、gh はその人の今の設定（有効なアカウントか GH_TOKEN）で動く
        self.assertIsNone(cfg.repos[0].gh_user)
        self.assertEqual(config.copy_root(cfg.repos[0]), cfg.repos[0].source)
        self.assertEqual(cfg.limit_percent, 95)
        self.assertEqual(cfg.limits_dir, os.path.expanduser("~/.cache/claude-limits"))
        self.assertEqual(cfg.reset_soon_hours, 24)

    def test_reset_soon_hours_is_read_and_checked(self):
        body = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n'
        self.assertEqual(config.load(write(self.d, "c.toml", "reset_soon_hours = 6.5\n" + body), env={}).reset_soon_hours, 6.5)
        for bad in ('"24"', "-1", "true"):
            with self.assertRaises(config.ConfigError) as e:
                config.load(write(self.d, "c.toml", f"reset_soon_hours = {bad}\n" + body), env={})
            self.assertIn("reset_soon_hours", str(e.exception))

    def test_move_early_values_are_read_and_checked(self):
        body = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n'
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual((cfg.early_percent, cfg.early_reset_hours), (90, 1.0))
        cfg = config.load(write(self.d, "c.toml", "move_early_percent = 80\nmove_early_reset_hours = 2\n" + body), env={})
        self.assertEqual((cfg.early_percent, cfg.early_reset_hours), (80, 2))
        for key, bad in (("move_early_percent", '"90"'), ("move_early_percent", "true"), ("move_early_reset_hours", "-1")):
            with self.assertRaises(config.ConfigError) as e:
                config.load(write(self.d, "c.toml", f"{key} = {bad}\n" + body), env={})
            self.assertIn(key, str(e.exception))

    def test_account_kinds(self):
        # アカウントの持ち方は人で違う。claude そのまま／設定のフォルダ＋自分で作った Keychain の項目／使用率の枠の無いもの（Ollama・Foundry など）
        body = (f'accounts = [\n'
                f'  {{ name = "main", command = "claude" }},\n'
                f'  {{ name = "w", command = "claude-w", config_dir = \'{self.d}/w\', keychain_service = "my-item" }},\n'
                f'  {{ name = "local", command = "claude-ollama", limits = false }},\n'
                f']\n[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n')
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.accounts, (
            config.Account("main", "claude"),
            config.Account("w", "claude-w", f"{self.d}/w", "my-item"),
            config.Account("local", "claude-ollama", None, None, False),
        ))
        self.assertTrue(cfg.accounts[0].limits)

    def test_account_field_types_are_checked(self):
        body = ('accounts = [{ name = "a", command = "c", keychain_service = 1, limits = "no" }]\n'
                f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n')
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        self.assertIn("keychain_service", str(e.exception))
        self.assertIn("limits", str(e.exception))

    def test_plan_is_told_per_account(self):
        # ログインの記録からプランが読めないアカウント（setup-token の鍵だけで動く物）に、持ち主が教えたプランを書く
        repo = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\nsource = "s"\n'
        body = 'accounts = [{ name = "p2", command = "claude-p2", plan = "default_claude_max_20x" }]\n' + repo
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.accounts[0].plan, "default_claude_max_20x")
        for bad, word in (('plan = ""', "plan"), ("plan = 20", "plan"), ('plan = "Max 20x"', "default_claude_max_20x"), ('plan = "x", limits = false', "limits = false")):
            with self.subTest(bad=bad):
                body = f'accounts = [{{ name = "a", command = "c", {bad} }}]\n' + repo
                with self.assertRaises(config.ConfigError) as e:
                    config.load(write(self.d, "c.toml", body), env={})
                self.assertIn(word, str(e.exception))

    def test_tilde_is_expanded(self):
        body = ('[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'%s/second.md\'\n'
                'source = "~/x"\ncopy_from = "~/y"\n') % self.d
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual((cfg.repos[0].source, cfg.repos[0].copy_from),
                         (os.path.expanduser("~/x"), os.path.expanduser("~/y")))

    def test_clone_root_left_from_the_previous_version_is_ignored(self):
        # 前の版は PR ごとの clone を <clone_root>/<名前>-pr-<番号> に作った。今は herdr の worktree の置き場に任せるので読まない。
        # 知らない鍵はほかと同じく読み飛ばす（止めない）
        body = (f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = \'{self.d}/second.md\'\n'
                'source = "s"\nclone_root = "~/src"\n')
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertFalse(hasattr(cfg.repos[0], "clone_root"))

    def test_missing_second_prompt_file_names_the_path(self):
        body = '[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "/nope/second.md"\nsource = "s"\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        self.assertIn("/nope/second.md", str(e.exception))

    def test_every_problem_is_listed_at_once(self):
        body = '[[repos]]\ncopy_files = "x"\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        msg = str(e.exception)
        for word in ("repo", "source", "copy_files"):
            self.assertIn(word, msg)

    def test_env_var_is_used_without_argument(self):
        path = write(self.d, "c.toml", FULL.format(d=self.d))
        cfg = config.load(env={"WORKS_DISPATCH_CONFIG": path})
        self.assertEqual(cfg.repos[0].repo, "o/r")

    def test_missing_file_is_a_config_error(self):
        with self.assertRaises(config.ConfigError) as e:
            config.load(f"{self.d}/none.toml", env={})
        self.assertIn("none.toml", str(e.exception))


class EffectiveConfigDir(unittest.TestCase):
    def test_named_dir_wins(self):
        self.assertEqual(config.effective_config_dir(config.Account("a", "c", "/d"), {"CLAUDE_CONFIG_DIR": "/x"}), "/d")

    def test_unset_follows_the_repository_common_rule(self):
        # 決め方の正本はリポジトリ直下の scripts/claude_auth.py の config_dir（写しは vendor/claude_auth.py）
        from vendor import claude_auth
        acct = config.Account("default", "claude", None)
        for env in ({"CLAUDE_CONFIG_DIR": "/x"}, {}):
            with self.subTest(env=env):
                self.assertEqual(config.effective_config_dir(acct, env), claude_auth.config_dir(env))


class PickRepo(unittest.TestCase):
    def test_first_repo_by_default_and_named_repo(self):
        d = tempfile.mkdtemp()
        write(d, "second.md", "x")
        body = "".join(f'[[repos]]\nrepo = "{r}"\nsecond_prompt_file = \'{d}/second.md\'\nsource = "s"\n'
                       for r in ("o/a", "o/b"))
        cfg = config.load(write(d, "c.toml", body), env={})
        self.assertEqual(config.pick_repo(cfg, None).repo, "o/a")
        self.assertEqual(config.pick_repo(cfg, "o/b").repo, "o/b")
        with self.assertRaises(config.ConfigError):
            config.pick_repo(cfg, "o/z")


class JsonIO(unittest.TestCase):
    def test_dump_adds_schema_and_load_reads_it(self):
        d = tempfile.mkdtemp()
        out = f"{d}/x.json"
        jsonio.dump({"items": []}, out)
        self.assertEqual(jsonio.load(out), {"schema": 1, "items": []})

    def test_dump_to_stdout(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            jsonio.dump({"a": "日本"}, None)
        self.assertEqual(json.loads(buf.getvalue()), {"schema": 1, "a": "日本"})

    def test_unknown_schema_version_stops(self):
        d = tempfile.mkdtemp()
        write(d, "x.json", json.dumps({"schema": 2}))
        with self.assertRaises(jsonio.SchemaVersionError):
            jsonio.load(f"{d}/x.json")


class SchemaCheck(unittest.TestCase):
    S = {"type": "object", "required": ["schema", "items"], "properties": {
        "schema": {"type": "integer"},
        "items": {"type": "array", "items": {"type": "object", "required": ["k"],
                                             "properties": {"k": {"type": "string", "enum": ["a", "b"]}}}}}}

    def test_ok(self):
        self.assertEqual(schemacheck.check({"schema": 1, "items": [{"k": "a"}]}, self.S), [])

    def test_finds_missing_wrong_type_and_enum(self):
        errs = schemacheck.check({"schema": "1", "items": [{"k": "c"}, {}]}, self.S)
        self.assertEqual(len(errs), 3, errs)


if __name__ == "__main__":
    unittest.main()
