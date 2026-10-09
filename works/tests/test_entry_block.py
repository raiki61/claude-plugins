"""入口のブロック blk-entry の置き場と約束の縛り（計画 docs/plans/2026-10-09-one-entry-shape.md の 2.5 節）。YAML と JSON を
読むだけ（FAST。git・子のプロセスなし）。

- 線の最初の節は入口のブロックの include で、起動の関所（launch）と start の script（節 open）はブロックの中に在る。線の最上段に
  起動の関所・start の script が残っていない
- ブロックの出口 open の output_format は入口の入力の形 input を持ち、入口の種（entry）を持たない
- 始めの記録の約束 schemas/start.schema.json の欄 input は、出口の約束 schemas/input.schema.json と同じ形
- 始めの記録（start.json・github.json・prior-failures-in.json・fixture-outside/**）を出すのは入口のブロックの宣言だけ
"""
import json
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
BLOCK = ROOT / "blk-entry"
LINE = ROOT / "darkfactory"


def load_yaml(p):
    return yaml.safe_load(pathlib.Path(p).read_text(encoding="utf-8"))


def load_json(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


class EntryBlockCase(unittest.TestCase):
    def test_line_starts_with_entry_block(self):
        """線の最初の節が入口のブロックの include で、起動の関所と start の script は線の最上段に無い"""
        nodes = load_yaml(LINE / "darkfactory.yaml")["nodes"]
        self.assertEqual(nodes[0].get("include"), "blk-entry")
        self.assertFalse([n["id"] for n in nodes if "approval" in n and n["id"] == "launch"])
        self.assertFalse([n["id"] for n in nodes if n.get("script") == "start"])
        self.assertFalse((LINE / "scripts" / "start.py").exists())

    def test_block_holds_launch_gate_and_open(self):
        """ブロックの中は起動の関所 launch → 節 open（script start）の順で、出口は open"""
        doc = load_yaml(BLOCK / "blk-entry.yaml")
        ids = [n["id"] for n in doc["nodes"]]
        self.assertEqual(ids, ["launch", "open"])
        self.assertIn("approval", doc["nodes"][0])
        self.assertEqual((doc["nodes"][1]["script"], doc["nodes"][1]["depends_on"]), ("start", ["launch"]))
        self.assertEqual(doc["returns"], "open")
        self.assertIs(doc["interactive"], True)
        self.assertTrue((BLOCK / "scripts" / "start.py").is_file())

    def test_exit_has_input_not_entry_kind(self):
        """出口の型は入口の入力の形 input を持ち、入口の種 entry を持たない"""
        doc = load_yaml(BLOCK / "blk-entry.yaml")
        props = doc["nodes"][1]["output_format"]["properties"]
        self.assertEqual(props["input"], {"type": "object"})
        self.assertNotIn("entry", props)

    def test_start_record_schema_embeds_input_schema(self):
        """始めの記録の約束の欄 input は出口の約束 input.schema.json と同じ形（$ref を展開しない写しの型検査のため字で写す）"""
        exit_ = load_json(BLOCK / "schemas" / "input.schema.json")
        rec = load_json(BLOCK / "schemas" / "start.schema.json")["properties"]["input"]
        strip = lambda d: {k: v for k, v in d.items() if k not in ("$schema", "title", "description")}
        self.assertEqual(strip(rec), strip(exit_))
        self.assertEqual(set(exit_["required"]), {"base", "head_rev", "diff", "requests", "request_file", "pr", "spec"})

    def test_start_record_is_declared_by_entry_block_only(self):
        """start の作る盤面のファイルを出すのは入口のブロックの宣言だけ（線の宣言に残さない）"""
        names = {"start.json", "github.json", "prior-failures-in.json", "fixture-outside/**"}
        block = {p["name"] for p in load_json(BLOCK / "manifest.json")["produces"]}
        line = {p["name"] for p in load_json(LINE / "manifest.json")["produces"]}
        self.assertLessEqual(names, block)
        self.assertEqual(names & line, set())


# 入口の種類を知ってよい変換の層（計画 docs/plans/2026-10-09-one-entry-shape.md の 10.1 節の機械の確かめ。持ち主 2026-10-09
# 「入口を環境変数や引数に変換する層」）: 生の事実を集める殻と、線の最初のブロックと、その中身が触る core の唯一の模块と、
# 線の入力を宣言して入口のブロックへ渡すだけの YAML
CONVERSION_LAYER = {".shared/core/entryshape.py", "blk-entry/**", "dev/use.sh", "dev/canary.sh", "dev/dogfood.sh",
                    "darkfactory/darkfactory.yaml"}


class ConversionLayerCase(unittest.TestCase):
    def test_only_conversion_layer_knows_entry_kind(self):
        """入口の種類（差分の根の名指しの読み・入口の種類での分かれ・消した種の名）を書くのは変換の層だけで、既知の漏れも無い
        （考えの住処の柵 entry-kind を、変換の層の外の当たりが 0 件と縛る形で当てる）"""
        sys.path.insert(0, str(ROOT / "tests"))
        import conceptfence
        table = conceptfence.load(ROOT)
        fences = table["concepts"]["entry-kind"]["fences"]
        self.assertEqual(table["concepts"]["entry-kind"]["status"], "住処あり")
        self.assertGreaterEqual(len(fences), 2)
        paths = conceptfence.tracked(ROOT)
        for f in fences:
            with self.subTest(f["what"][:30]):
                self.assertLessEqual(set(f["allowed"]), CONVERSION_LAYER)
                self.assertEqual(f["known"], {})
                self.assertEqual(conceptfence.scan(ROOT, paths, f, table["exclude"]), {})

if __name__ == "__main__":
    unittest.main()
