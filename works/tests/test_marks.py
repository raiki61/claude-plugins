"""返答の足し欄の住処（marks）。種の表・役の型に欄を足す口・返答から欄を外す口・盤面の控えの置き場と読み書きを、関数を直に
呼んで見る（FAST。盤面・git・子のプロセスなし。控えは一時の置き場）。欄を持つモジュールが住処の表から名を引くことも見る"""
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import marks  # noqa: E402

ROW = {"type": "object", "required": ["what"], "properties": {"what": {"type": "string"}}}
SCHEMA = {"type": "object", "required": ["plan"], "properties": {
    "plan": {"type": "array", "items": {"type": "object", "required": ["no"], "properties": {
        "no": {"type": "integer"}, "narrows": {"type": "array", "items": ROW}}}},
    "faces": {"type": "array", "items": ROW}}}
F = {"x": {"type": "string"}, "y": {"type": "integer"}}


class Table(unittest.TestCase):
    def test_board_file_names_do_not_change(self):
        """盤面の控えの名は前の run と fixture が読む。名を変えない"""
        self.assertEqual({k: (v.file, v.place) for k, v in marks.KINDS.items()},
                         {"gate": ("gate-marks.json", marks.ROOT), "plan": ("plan-fields.json", marks.ROOT),
                          "delta": ("delta-verdicts.json", marks.WORK), "converge": (None, marks.WORK),
                          "query": ("query-examples.json", marks.ROOT), "purpose": ("out-of-purpose.json", marks.ROOT),
                          "pr": ("pr-excluded.json", marks.WORK), "writes": (None, marks.WORK),
                          "means": ("purpose-means.json", marks.ROOT), "answers": ("answer-ties.json", marks.ROOT)})

    def test_nodes(self):
        self.assertEqual(marks.nodes("gate"), ("p2.fix_plan", "p2.plan_review"))
        self.assertEqual(marks.nodes("delta"), ("p3.delta_review",))


class Add(unittest.TestCase):
    def test_nested_rows_get_fields_and_required(self):
        out = marks.add("gate", "p2.fix_plan", SCHEMA, F, required=("x",))
        row = out["properties"]["plan"]["items"]["properties"]["narrows"]["items"]
        self.assertEqual(list(row["properties"]), ["what", "x", "y"])
        self.assertEqual(row["required"], ["what", "x"])
        self.assertNotIn("x", SCHEMA["properties"]["plan"]["items"]["properties"]["narrows"]["items"]["properties"])   # 元は変えない

    def test_required_not_repeated_and_absent_when_none(self):
        out = marks.add("gate", "p2.plan_review", SCHEMA, F)
        self.assertEqual(out["properties"]["faces"]["items"]["required"], ["what"])
        top = marks.add("delta", "p3.delta_review", {"type": "object", "properties": {}}, F, required=("x", "x"))
        self.assertEqual(top["required"], ["x"])
        self.assertNotIn("required", marks.add("purpose", "p2.diagnose", {"type": "object"}, F))
        self.assertEqual(marks.add("purpose", "p2.diagnose", {"type": "object"}, F)["properties"], F)

    def test_node_outside_the_table_returns_the_same_schema(self):
        self.assertIs(marks.add("gate", "p3.fix", SCHEMA, F), SCHEMA)
        self.assertIs(marks.drop("gate", "p3.fix", SCHEMA, F), SCHEMA)

    def test_drop_undoes_add(self):
        """drop は add の逆（足した欄を型と required から外した写し。受け付けが写しの型で照らす時に使う）"""
        for node in ("p2.fix_plan", "p2.plan_review"):
            with self.subTest(node):
                added = marks.add("gate", node, SCHEMA, F, required=("x",))
                self.assertEqual(marks.drop("gate", node, added, F), SCHEMA)
        top = marks.add("delta", "p3.delta_review", {"type": "object", "properties": {"a": {}}, "required": ["a"]}, F,
                        required=("x", "y"))
        self.assertEqual(marks.drop("delta", "p3.delta_review", top, ("x", "y")),
                         {"type": "object", "properties": {"a": {}}, "required": ["a"]})


class Split(unittest.TestCase):
    REPLY = {"plan": [{"no": 1, "narrows": [{"what": "a", "x": "1"}, {"what": "b"}]}, "壊れた行", {"no": 2}],
             "faces": [{"what": "c", "y": 2}, 3]}

    def test_nested_shape_follows_the_path(self):
        before = json.dumps(self.REPLY)
        bare, got = marks.split("gate", "p2.fix_plan", self.REPLY, ("x", "y"))
        self.assertEqual(got, [[{"x": "1"}, {}], [], []])
        self.assertEqual(bare["plan"][0]["narrows"][0], {"what": "a"})
        self.assertEqual(json.dumps(self.REPLY), before)   # 元は変えない
        _, faces = marks.split("gate", "p2.plan_review", self.REPLY, ("x", "y"))
        self.assertEqual(faces, [{"y": 2}, {}])

    def test_top_level_and_misshapen_replies(self):
        self.assertEqual(marks.split("delta", "p3.delta_review", {"a": 1, "x": 2}, ("x",)), ({"a": 1}, {"x": 2}))
        self.assertEqual(marks.split("delta", "p3.delta_review", ["x"], ("x",)), (["x"], {}))
        self.assertEqual(marks.split("gate", "p2.fix_plan", "文", ("x",)), ("文", []))
        self.assertEqual(marks.split("gate", "p2.fix_plan", {"plan": {"no": 1}}, ("x",))[1], [])
        self.assertEqual(marks.split("gate", "p2.plan_review", {"faces": "文"}, ("x",))[1], [])

    def test_node_outside_the_table(self):
        self.assertEqual(marks.split("gate", "p3.fix", {"x": 1}, ("x",)), ({"x": 1}, None))

    def test_rows_reads_in_place(self):
        """rows は欄を持つ行をその場のまま（写さずに）道の形で返す。検査が行を名指すのに使う"""
        got = marks.rows("gate", "p2.fix_plan", self.REPLY)
        self.assertEqual(got, [[{"what": "a", "x": "1"}, {"what": "b"}], [], []])
        self.assertIs(got[0][0], self.REPLY["plan"][0]["narrows"][0])
        self.assertEqual(marks.rows("gate", "p2.plan_review", self.REPLY), [{"what": "c", "y": 2}, 3])
        self.assertEqual(marks.rows("gate", "p2.fix_plan", None), [])
        self.assertIsNone(marks.rows("gate", "p3.fix", self.REPLY))


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_of_root_and_work(self):
        b = types.SimpleNamespace(dir=self.d, work=lambda n: self.d / "r3" / n)
        self.assertEqual(marks.path_of("gate", b), self.d / "gate-marks.json")
        self.assertEqual(marks.path_of("gate", str(self.d)), self.d / "gate-marks.json")
        self.assertEqual(marks.path_of("delta", b), self.d / "r3" / "delta-verdicts.json")

    def test_write_replaces_without_leftovers_or_following_links(self):
        target = self.d / "外.json"
        target.write_text("前", encoding="utf-8")
        p = self.d / "c.json"
        os.symlink(target, p)
        (self.d / "c.json.tmp").symlink_to(self.d / "tmp の先")
        raw = marks.write(p, {"a": "字"})
        self.assertEqual(raw, (json.dumps({"a": "字"}, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        self.assertFalse(p.is_symlink())
        self.assertEqual(p.read_bytes(), raw)
        self.assertEqual(target.read_text(encoding="utf-8"), "前")
        self.assertFalse((self.d / "tmp の先").exists())
        self.assertEqual(sorted(x.name for x in self.d.iterdir()), ["c.json", "外.json"])

    def test_load(self):
        p = self.d / "c.json"
        self.assertIsNone(marks.load(p))
        p.write_text("{壊れた", encoding="utf-8")
        self.assertIsNone(marks.load(p))
        p.write_bytes(b"\xff")
        self.assertIsNone(marks.load(p))
        p.write_text('[1]', encoding="utf-8")
        self.assertEqual(marks.load(p), [1])


class Owners(unittest.TestCase):
    """欄を持つモジュールは、節と控えの名を住処の表から引く（同じ名を 2 か所で持たない）"""

    def test_owners_read_the_table(self):
        import converge
        import deltamarks
        import gatemarks
        import outpurpose
        import planmarks
        import prcheck
        import querytest
        import refix
        import worldmark
        self.assertEqual((gatemarks.NODES, gatemarks.MARKS_FILE), (marks.nodes("gate"), marks.KINDS["gate"].file))
        self.assertEqual((planmarks.NODES, planmarks.FIELDS_FILE), (marks.nodes("plan"), marks.KINDS["plan"].file))
        self.assertEqual((deltamarks.NODES, deltamarks.VERDICTS_FILE), (marks.nodes("delta"), marks.KINDS["delta"].file))
        self.assertEqual(tuple(converge.FIELDS), marks.nodes("converge"))
        self.assertEqual((querytest.NODES, querytest.EXAMPLES_FILE), (marks.nodes("query"), marks.KINDS["query"].file))
        self.assertEqual((outpurpose.NODES, outpurpose.FILE), (marks.nodes("purpose"), marks.KINDS["purpose"].file))
        self.assertEqual(((prcheck.NODE,), prcheck.EXCLUDED), (marks.nodes("pr"), marks.KINDS["pr"].file))
        self.assertEqual(tuple(refix.FIX_ROLE.values()), marks.nodes("writes"))
        self.assertEqual(worldmark.MEANS_NODES, marks.nodes(worldmark.MEANS))


if __name__ == "__main__":
    unittest.main()
