"""節の印（.shared/core/node_marker.py）の検査。

役の節の output_format（JSON Schema）の一番上の description に `works-node: <名>[ continue=<名>][ <flag>…]` を置き、
包みが argv の --json-schema だけでどの節の起動かを見分ける（仕様 3.7・5.1、裁定 TA20）。
- mark と parse が往復する。元の description を持つ schema には印を付けない
- 見分けられない物（大文字・空の continue・知らない flag・印でない文）は印でないと見なす
- strip は印を外して元に戻す
- from_argv は `--json-schema <値>` と `--json-schema=<値>` の両方の綴りを読む
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import node_marker  # noqa: E402
from node_marker import from_argv, mark, parse, strip  # noqa: E402

SCHEMA = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean", "description": "内の注記"}}}


class MarkerCase(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual(node_marker.PREFIX, "works-node: ")

    def test_mark_parse_roundtrip(self):
        m = mark(SCHEMA, "rejudge", cont="judge", flags=("no-post",))
        self.assertEqual(m["description"], "works-node: rejudge continue=judge no-post")
        self.assertEqual(parse(m["description"]), {"name": "rejudge", "cont": "judge", "flags": frozenset({"no-post"})})
        self.assertEqual(parse(mark(SCHEMA, "judge")["description"]), {"name": "judge", "cont": None, "flags": frozenset()})
        self.assertNotIn("description", SCHEMA, "mark が元の schema を書き換えた")

    def test_mark_copies_deep(self):
        m = mark(SCHEMA, "judge")
        m["properties"]["ok"]["type"] = "string"
        self.assertEqual(SCHEMA["properties"]["ok"]["type"], "boolean")

    def test_mark_refuses_existing_description(self):
        with self.assertRaises(ValueError):
            mark(dict(SCHEMA, description="注記"), "judge")
        with self.assertRaises(ValueError):
            mark(mark(SCHEMA, "judge"), "judge")

    def test_mark_refuses_what_parse_cannot_read(self):
        for kw in ({"name": "Judge"}, {"name": ""}, {"name": "judge", "cont": ""}, {"name": "judge", "cont": "J"},
                   {"name": "judge", "flags": ("post",)}, {"name": "judge", "flags": ("no-post", "no-post")}):
            with self.subTest(kw):
                with self.assertRaises(ValueError):
                    mark(SCHEMA, **kw)

    def test_parse_rejects_unknown(self):
        for text in ("works-node: Judge", "works-node: judge continue=", "works-node: judge flying",
                     "works-node: ", "works-node:judge", "works-node: judge  no-post", "works-node: judge no-post no-post",
                     "works-node: judge continue=a continue=b", "works-node: judge continue=J",
                     "works-node: judge\nno-post", "works-node: judge ", " works-node: judge",
                     "判定の返答", "", None, 3):
            with self.subTest(text=text):
                self.assertIsNone(parse(text))

    def test_parse_flag_before_continue(self):
        self.assertEqual(parse("works-node: pr-check no-post continue=judge"),
                         {"name": "pr-check", "cont": "judge", "flags": frozenset({"no-post"})})

    def test_strip_restores(self):
        for m in (mark(SCHEMA, "judge"), mark(SCHEMA, "rejudge", cont="judge", flags=("no-post",))):
            with self.subTest(m["description"]):
                self.assertEqual(strip(m), SCHEMA)
                self.assertIn("description", m, "strip が元を書き換えた")

    def test_strip_keeps_foreign_description(self):
        s = dict(SCHEMA, description="印でない注記")
        self.assertEqual(strip(s), s)
        self.assertEqual(strip(SCHEMA), SCHEMA)

    def test_from_argv_both_spellings(self):
        m = mark(SCHEMA, "rejudge", cont="judge")
        want = parse(m["description"])
        text = json.dumps(m, ensure_ascii=False)
        self.assertEqual(from_argv(["claude", "-p", "--json-schema", text, "--verbose"]), want)
        self.assertEqual(from_argv(["claude", "-p", f"--json-schema={text}", "--verbose"]), want)
        self.assertIsNone(from_argv(["claude", "-p", "--verbose"]))
        self.assertIsNone(from_argv(["claude", "--json-schema"]))
        self.assertIsNone(from_argv(["claude", "--json-schema", "{壊れた"]))
        self.assertIsNone(from_argv(["claude", "--json-schema=[1]"]))
        self.assertIsNone(from_argv(["claude", "--json-schema", json.dumps(SCHEMA)]))


if __name__ == "__main__":
    unittest.main()
