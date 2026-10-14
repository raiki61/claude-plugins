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
slots = [
  {{ workspace = "work0", path = "{d}/r0" }},
  {{ workspace = "work1", path = "{d}/r1" }},
]
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
        self.assertEqual(repo.slots, (config.Slot("work0", f"{self.d}/r0"), config.Slot("work1", f"{self.d}/r1")))

    def test_defaults_without_accounts_or_limits(self):
        body = f'[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "{self.d}/second.md"\nslots = []\n'
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.accounts, (config.Account("default", "claude", None),))
        self.assertEqual(cfg.limit_percent, 95)
        self.assertEqual(cfg.limits_dir, os.path.expanduser("~/.cache/claude-limits"))

    def test_tilde_is_expanded(self):
        body = ('[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "%s/second.md"\n'
                'slots = [{ workspace = "w", path = "~/x" }]\n') % self.d
        cfg = config.load(write(self.d, "c.toml", body), env={})
        self.assertEqual(cfg.repos[0].slots[0].path, os.path.expanduser("~/x"))

    def test_missing_second_prompt_file_names_the_path(self):
        body = '[[repos]]\nrepo = "o/r"\nsecond_prompt_file = "/nope/second.md"\nslots = []\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        self.assertIn("/nope/second.md", str(e.exception))

    def test_every_problem_is_listed_at_once(self):
        body = '[[repos]]\nslots = "x"\n'
        with self.assertRaises(config.ConfigError) as e:
            config.load(write(self.d, "c.toml", body), env={})
        msg = str(e.exception)
        for word in ("repo", "second_prompt_file", "slots"):
            self.assertIn(word, msg)

    def test_env_var_is_used_without_argument(self):
        path = write(self.d, "c.toml", FULL.format(d=self.d))
        cfg = config.load(env={"WORKS_DISPATCH_CONFIG": path})
        self.assertEqual(cfg.repos[0].repo, "o/r")

    def test_missing_file_is_a_config_error(self):
        with self.assertRaises(config.ConfigError) as e:
            config.load(f"{self.d}/none.toml", env={})
        self.assertIn("none.toml", str(e.exception))


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
