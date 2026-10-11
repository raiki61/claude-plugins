"""節ごとの読み書きの宣言 `_meta: {reads, writes}`（.shared/core/nodemeta.py）と、その照らし（.shared/core/scopes.py の
node_io_gaps・manifest_gaps）の検査。

- StripCase: Archon に渡す前に YAML の字から `_meta` を落とす（流れの形・塊の形・輪の中・塊の字の中の字は落とさない）
- ParseCase: 宣言の形（reads・writes の 2 つの並びで、要素は file:<run の置き場からの型> か record:<record|state>.<欄>）
- GapCase: 実際の読み書き（run の置き場からの相対パス）が宣言の外に出た所と、manifest と宣言の公開の名の食い違い（両向き）
- PackCase: 本物の pack の宣言が読め、宣言を持つ工程は実行する節の全部が宣言を持ち、名の形と manifest が合う
- ProbeCase: 実際の読み書きを測る道具 tests/nodeio_probe.py が拾う物（子のプロセスは python3 1 本）

YAML を読み、git を使わない。実際の読み書きを測って宣言に照らすのは、ブロックを通しで回す試験
（test_blk_structure の run_block）。
"""
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "graphloops"))
sys.path.insert(0, str(ROOT / "tests"))

import graphmap  # noqa: E402
import nodemeta  # noqa: E402
import scopes  # noqa: E402

FLOW = """\
nodes:
  - id: a
    script: a
    _meta: {reads: ['file:x/y.json'], writes: []}
    timeout: 1
  - id: b
    script: b
"""
FLOW_STRIPPED = """\
nodes:
  - id: a
    script: a
    timeout: 1
  - id: b
    script: b
"""
BLOCK = """\
nodes:
  - id: loop
    loop_group:
      max_iterations: 3
      nodes:
        - id: inner
          prompt: |
            説明の中の字
            _meta: これは落とさない
          _meta:
            reads:
              - file:a.json   # 読む

            writes: [record:state.works]
          output_format: {type: object}
  - id: last
    script: last
    _meta: {reads: [], writes: []}
"""
BLOCK_STRIPPED = """\
nodes:
  - id: loop
    loop_group:
      max_iterations: 3
      nodes:
        - id: inner
          prompt: |
            説明の中の字
            _meta: これは落とさない
          output_format: {type: object}
  - id: last
    script: last
"""


class StripCase(unittest.TestCase):
    def test_flow_meta_line_is_dropped(self):
        self.assertEqual(nodemeta.strip(FLOW), FLOW_STRIPPED)

    def test_block_meta_and_nested_nodes(self):
        """塊の形の宣言は下の行ごと落ち、輪の中の節も落ち、塊の字（prompt: |）の中の `_meta:` の字は残る"""
        self.assertEqual(nodemeta.strip(BLOCK), BLOCK_STRIPPED)

    def test_text_without_meta_is_kept_byte_for_byte(self):
        self.assertEqual(nodemeta.strip(FLOW_STRIPPED), FLOW_STRIPPED)

    def test_list_item_block_scalar_keeps_its_text(self):
        """列の要素の塊の字（`- |`）の中の `_meta:` の字は落とさない"""
        text = "nodes:\n  - id: a\n    args:\n      - |\n        _meta: 字のまま\n    script: a\n"
        self.assertEqual(nodemeta.strip(text), text)

    def test_quoted_key_is_dropped_too(self):
        """引用した鍵（`"_meta":`）も YAML では同じ鍵なので落とす"""
        self.assertEqual(nodemeta.strip(FLOW.replace("_meta:", '"_meta":')), FLOW_STRIPPED)

    def test_meta_as_the_first_key_of_a_node_is_refused(self):
        """`- _meta:` は落とすと節の頭が消えるので拒む（宣言は節の 2 つ目より後の鍵に置く）"""
        with self.assertRaises(ValueError):
            nodemeta.strip("nodes:\n  - _meta: {reads: [], writes: []}\n    id: a\n")

    def test_stripped_yaml_is_the_source_without_meta(self):
        def drop(v):
            if isinstance(v, dict):
                return {k: drop(x) for k, x in v.items() if k != nodemeta.KEY}
            if isinstance(v, list):
                return [drop(x) for x in v]
            return v
        for text in (FLOW, BLOCK):
            with self.subTest(text=text[:40]):
                self.assertEqual(yaml.safe_load(nodemeta.strip(text)), drop(yaml.safe_load(text)))


class ParseCase(unittest.TestCase):
    def test_good_declaration(self):
        got = nodemeta.parse({"reads": ["file:structure/eye.json", "record:record.findings"],
                              "writes": ["record:state.works.validator_hook"]}, "n")
        self.assertEqual(got, {"reads": ["file:structure/eye.json", "record:record.findings"],
                               "writes": ["record:state.works.validator_hook"]})

    def test_bad_declarations_are_refused(self):
        bad = ({"reads": []},                                    # writes が無い
               {"reads": [], "writes": [], "notes": []},         # 知らない鍵
               {"reads": "file:a", "writes": []},                # 並びでない
               {"reads": ["a.json"], "writes": []},              # 種類の頭が無い
               {"reads": ["file:"], "writes": []},               # 型が空
               {"reads": [], "writes": ["record:findings"]},     # record・state のどちらの記録か無い
               {"reads": [], "writes": ["record:trace.x"]},      # 共有の記録でないファイル
               {"reads": ["file:a", "file:a"], "writes": []},    # 2 度書き
               ["file:a"])
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                nodemeta.parse(raw, "n")


class GapCase(unittest.TestCase):
    META = {"reads": ["file:structure/eye.json", "record:state.works"],
            "writes": ["file:structure/eye-prompt-*.md", "file:structure/eye.json"]}

    def test_inside_the_declaration_has_no_gap(self):
        self.assertEqual(scopes.node_io_gaps(self.META, reads={"structure/eye.json", "board/state.json"},
                                             writes={"structure/eye-prompt-2.md"}), [])

    def test_undeclared_read_and_write_are_named(self):
        got = scopes.node_io_gaps(self.META, reads={"structure/structure.json"}, writes={"structure/design.jsonl"})
        self.assertEqual(len(got), 2, got)
        self.assertIn("structure/structure.json", got[0])
        self.assertIn("structure/design.jsonl", got[1])

    def test_read_named_by_an_input_is_the_wire_s_declaration(self):
        """入力（with:）で名指されたファイルの読みは線の配線が宣言している（_meta に書かない）。書きは名指されても宣言が要る"""
        named = ("/art/structure/structure.json", '{"after_file": {"type": "archon_artifact", "path": "structure/after.json"}}')
        got = scopes.node_io_gaps(self.META, reads={"structure/structure.json", "structure/after.json"},
                                  writes={"structure/after.json"}, named=named, root="/art")
        self.assertEqual(len(got), 1, got)
        self.assertIn("書き", got[0])

    def test_shared_record_needs_a_record_declaration(self):
        """盤面の共有の記録（record.json・state.json）は file: でなく record:<そのファイル>.<欄> で宣言する"""
        got = scopes.node_io_gaps({"reads": ["file:board/record.json"], "writes": []}, reads={"board/record.json"}, writes=set())
        self.assertEqual(len(got), 1, got)
        self.assertIn("record:record.", got[0])

    def test_manifest_names_need_a_declaring_node(self):
        man = {"owner": "blk-x", "consumes": [{"name": "lens.json"}],
               "produces": [{"name": "delta.json", "format": "json", "schema": "s.json"},
                            {"name": "reads-x.json", "format": "json", "schema": "s.json", "per_include": True},
                            {"name": "top.md", "format": "md", "at": "root"}]}
        full = [{"reads": ["file:board/r*/lens.json"], "writes": ["file:board/r*/delta.json"]},
                {"reads": [], "writes": ["file:board/*/r*/reads-x.json", "file:board/top.md"]}]
        self.assertEqual(scopes.manifest_gaps(man, full), [])
        got = scopes.manifest_gaps(man, [full[1]])
        self.assertEqual(len(got), 2, got)
        self.assertIn("lens.json", got[0])
        self.assertIn("delta.json", got[1])

    def test_public_board_files_in_declarations_need_the_manifest(self):
        """宣言が盤面の公開の置き場を読み書きするなら manifest に名が要る（逆向き）。scope の根の私物と共有の記録は要らない"""
        man = {"owner": "blk-x", "consumes": [], "produces": [{"name": "delta.json", "format": "json", "schema": "s.json"}]}
        ok = [{"reads": ["file:board/r*/delta.json", "file:board/*/r*/mine.json"],
               "writes": ["file:board/r*/delta.json", "file:board/*/note.md", "file:board/trace.jsonl", "file:structure/x.json"]}]
        self.assertEqual(scopes.manifest_gaps(man, ok), [])
        bad = [{"reads": ["file:board/r*/lens.json"], "writes": ["file:board/r*/delta.json", "file:board/r*/extra.json"]}]
        got = scopes.manifest_gaps(man, bad)
        self.assertEqual(len(got), 2, got)
        self.assertIn("lens.json", got[0])
        self.assertIn("extra.json", got[1])


class ProbeCase(unittest.TestCase):
    """実際の読み書きを測る道具（tests/nodeio_probe.py）が拾う物を、字のままの期待で縛る（道具が何も拾わなくなると
    宣言の照らしが空振りで緑になるため）。子のプロセスは python3 1 本"""

    def test_probe_records_reads_and_writes_under_the_run_place(self):
        import json
        import subprocess
        import tempfile
        from hermetic import child_env
        import nodeio_probe
        with tempfile.TemporaryDirectory() as d:
            art = pathlib.Path(d) / "art"
            (art / "in").mkdir(parents=True)
            (art / "in" / "a.json").write_text("{}", encoding="utf-8")
            (art / "gone.txt").write_text("x", encoding="utf-8")
            (pathlib.Path(d) / "outside.txt").write_text("x", encoding="utf-8")
            script = pathlib.Path(d) / "node.py"
            script.write_text(
                "import os, pathlib, sys\n"
                "art = pathlib.Path(os.environ['ARTIFACTS_DIR'])\n"
                "(art / 'in' / 'a.json').read_text()\n"
                "(art.parent / 'outside.txt').read_text()\n"
                "(art / 'out.tmp').write_text('1')\n"
                "os.replace(art / 'out.tmp', art / 'out.json')\n"
                "(art / 'gone.txt').unlink()\n"
                "with open(os.open(art / 'raw.bin', os.O_WRONLY | os.O_CREAT), 'wb') as f: f.write(b'1')\n"
                "sys.exit(3)\n", encoding="utf-8")
            log = pathlib.Path(d) / "log.json"
            p = subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "nodeio_probe.py"), str(script)],
                               env=child_env(ARTIFACTS_DIR=str(art), **{nodeio_probe.LOG_ENV: str(log)}),
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 3, p.stderr)   # 終了コードはスクリプトのまま
            self.assertEqual(json.loads(log.read_text(encoding="utf-8")),
                             {"reads": ["in/a.json"], "writes": ["gone.txt", "out.json", "out.tmp", "raw.bin"]})


def _deep(nodes):
    for n in nodes:
        yield n
        yield from _deep((n.get("loop_group") or {}).get("nodes") or ())


def _gdeep(nodes):
    """地図の元の節（輪の body も）"""
    for n in nodes:
        yield n
        yield from _gdeep(n.get("body") or ())


def _workflows():
    for p in sorted(ROOT.glob("*/*.yaml")):
        if p.stem == p.parent.name:
            yield p, yaml.safe_load(p.read_text(encoding="utf-8"))


class PackCase(unittest.TestCase):
    """本物の pack の宣言"""

    def test_declarations_parse_and_name_valid_patterns(self):
        for path, doc in _workflows():
            for n in _deep(doc["nodes"]):
                if nodemeta.KEY in n:
                    with self.subTest(node=f"{path.parent.name}/{n['id']}"):
                        meta = nodemeta.parse(n[nodemeta.KEY], n["id"])
                        self.assertEqual(scopes.node_meta_errors(meta, n["id"]), [])

    def test_a_declared_workflow_declares_every_running_node(self):
        """宣言を 1 つでも持つ工程は、実行する節（script・bash・AI）の全部が宣言を持つ（勘で一部だけ埋めない）。
        未宣言の節は地図の元から数える（graphmap.undeclared）"""
        eps = graphmap.entrypoints(ROOT)
        (rel,) = eps.values()
        g = graphmap.build(ROOT / rel, graphmap.pack_resolver(ROOT, yaml.safe_load), ROOT, yaml.safe_load)
        left = graphmap.undeclared(g)
        declared = [name for name, wf in g["workflows"].items() if any("reads" in n for n in _gdeep(wf["nodes"]))]
        self.assertIn("blk-structure", declared)
        for name in declared:
            with self.subTest(workflow=name):
                self.assertEqual(left.get(name, []), [])

    def test_declared_blocks_agree_with_their_manifest(self):
        """宣言を持つブロックの manifest の consumes・produces の名は、どれかの節の宣言が読み書きする"""
        for path, doc in _workflows():
            metas = [nodemeta.parse(n[nodemeta.KEY], n["id"]) for n in _deep(doc["nodes"]) if nodemeta.KEY in n]
            if metas and (path.parent / scopes.MANIFEST).is_file():
                with self.subTest(block=path.parent.name):
                    self.assertEqual(scopes.manifest_gaps(scopes.manifest(path.parent), metas), [])


if __name__ == "__main__":
    unittest.main()
