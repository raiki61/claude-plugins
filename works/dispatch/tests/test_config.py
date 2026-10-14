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
limits_dir = "{d}/limits"
accounts = [
  {{ name = "main", command = "claude",   config_dir = "{d}/c0" }},
  {{ name = "a1",   command = "claude-a", config_dir = "{d}/c1" }},
]

[[repos]]
repo = "o/r"
second_prompt_file = "{d}/second.md"
source = "{d}/src"
clone_root = "{d}/clones"
copy_files = ["frontend/.env.local", "deploy/local/secrets.local.yaml"]
copy_from = "{d}/keep"
"""


class Load(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        write(self.d, "second.md", "1. 深掘りして\n2. 世の中の解と照らして\n")

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
        self.assertEqual(repo.second_prompt, "1. 深掘りして\n2. 世の中の解と照らして\n")
        self.assertEqual(repo.source, f"{self.d}/src")
        self.assertEqual(repo.clone_root, f"{self.d}/clones")
        self.assertEqual(repo.copy_files, ("frontend/.env.local", "deploy/local/secrets.local.yaml"))
        self.assertEqual(repo.copy_from, f"{self.d}/keep")
        self.assertEqual(config.copy_root(repo), f"{self.d}/keep")

    def test_defaults_without_accounts_or_limits(self):
        body = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "{self.d}/second.md"\nsource = "s"\nclone_root = "c"\n'
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.accounts, (config.Account("default", "claude", None),))
        self.assertEqual(cfg.repos[0].copy_files, ())
        # copy_from を書かなければ、元の clone から写す
        self.assertIsNone(cfg.repos[0].copy_from)
        self.assertEqual(config.copy_root(cfg.repos[0]), cfg.repos[0].source)
        self.assertEqual(cfg.limit_percent, 95)
        self.assertEqual(cfg.limits_dir, os.path.expanduser("~/.cache/claude-limits"))

    def test_tilde_is_expanded(self):
        body = ('[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "%s/second.md"\n'
                'source = "~/x"\nclone_root = "~/y"\n') % self.d
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual((cfg.repos[0].source, cfg.repos[0].clone_root),
                         (os.path.expanduser("~/x"), os.path.expanduser("~/y")))

    def test_missing_second_prompt_file_names_the_path(self):
        body = '[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "/nope/second.md"\nsource = "s"\nclone_root = "c"\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        self.assertIn("/nope/second.md", str(e.exception))

    def test_every_problem_is_listed_at_once(self):
        body = '[[repos]]\ncopy_files = "x"\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        msg = str(e.exception)
        for word in ("repo", "second_prompt_file", "source", "clone_root", "copy_files"):
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
        body = "".join(f'[[repos]]\nrepo = "{r}"\nsecond_prompt_file = "{d}/second.md"\nsource = "s"\nclone_root = "c"\n'
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
