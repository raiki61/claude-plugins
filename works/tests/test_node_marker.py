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

    def test_no_tree_write_flag(self):
        """旗 no-tree-write（包みが役の cwd の作業ツリーを書かせない。CI の任せ先の役。裁定 R56）を読み書きできる"""
        self.assertEqual(node_marker.FLAGS, frozenset({"no-post", "no-tree-write", "isolated", "self-resume", "lane", "fork", "map"}))
        m = mark(SCHEMA, "ci", flags=("no-tree-write",))
        self.assertEqual(m["description"], "works-node: ci no-tree-write")
        self.assertEqual(parse(m["description"]), {"name": "ci", "cont": None, "flags": frozenset({"no-tree-write"})})
        self.assertEqual(parse("works-node: x no-post no-tree-write")["flags"], frozenset({"no-post", "no-tree-write"}))
        self.assertIsNone(parse("works-node: ci no-tree-write no-tree-write"))

    def test_self_resume_flag(self):
        """旗 self-resume（SDK が会話を継ぐ起動は、包みがこの節自身の会話を継ぐ。輪に範囲の相談の答えの節が挟まる修正役）"""
        m = mark(SCHEMA, "fix", flags=("self-resume",))
        self.assertEqual(m["description"], "works-node: fix self-resume")
        self.assertEqual(parse(m["description"]), {"name": "fix", "cont": None, "flags": frozenset({"self-resume"})})
        self.assertIsNone(parse("works-node: fix self-resume self-resume"))

    def test_isolated_flag(self):
        """旗 isolated（道具ゼロの役を Git の外の置き場で起こす。独立の目の blind-judge。graphloops の commands._isolated_cwd）"""
        m = mark(SCHEMA, "r2-design", flags=("isolated",))
        self.assertEqual(m["description"], "works-node: r2-design isolated")
        self.assertEqual(parse(m["description"])["flags"], frozenset({"isolated"}))
        self.assertIsNone(parse("works-node: r2-design isolated isolated"))

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


class EngineChildCase(unittest.TestCase):
    """印のある起動の子（役の claude。その Bash の子へ継がれる）の env に、本流の engine の子の目印（role_run.ENGINE_CHILD_ENV
    ＝1）を立てる。対象の重い一式（tests/run.sh・変異の撃ち）はこれを見て AI の役から拒む。名は読む側が既に読む本流の名"""

    REPO = ROOT.parent
    TOOLS = "Read,Grep,Glob,Edit,Write,Bash"

    def setUp(self):
        import re
        import tempfile
        import adapter
        self.adapter = adapter
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        (self.tmp / "wt").mkdir()
        role_run = self.REPO / "graphloops" / "engine" / "role_run.py"
        found = re.search(r'^ENGINE_CHILD_ENV = "([A-Z_]+)"', role_run.read_text(encoding="utf-8"), re.M) \
            if role_run.is_file() else None
        self.name = found.group(1) if found else "GRAPHLOOPS_ENGINE_CHILD"

    def plan(self, desc):
        schema = json.dumps(mark(SCHEMA, *desc.split(" ", 1)[:1],
                                 flags=tuple(desc.split(" ")[1:])), ensure_ascii=False)
        argv = ["--output-format", "stream-json", "--json-schema", schema, "--tools", self.TOOLS,
                "--setting-sources=project,user"]
        return self.adapter.plan(argv, self.tmp / "wt", self.tmp / "home", "true", env={"PATH": "/usr/bin:/bin"})

    def test_marked_launch_child_gets_engine_child_marker(self):
        p = self.plan("fix")
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual((p.env or {}).get(self.name), "1")

    def test_marked_launch_child_cannot_start_background_tasks(self):
        """背景を残した会話を引き継ぐと空の result で終わるので、印のある起動の子は背景の作業を起こせない"""
        for desc in ("fix", "pr-check no-post"):
            p = self.plan(desc)
            self.assertEqual((p.env or {}).get("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"), "1", desc)

    def test_no_post_env_keeps_engine_child_marker(self):
        p = self.plan("pr-check no-post")
        self.assertEqual(p.mode, "merged", p.why)
        env = p.env or {}
        self.assertIn("WORKS_GH", env, "no-post の口は残る")
        self.assertEqual(env.get(self.name), "1")


if __name__ == "__main__":
    unittest.main()
