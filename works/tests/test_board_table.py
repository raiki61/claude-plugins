"""盤面の層の節の表（.shared/core/board.py の NodeTable）の検査。

表は graph の全部の節を「このラインでどう持つか」に振る（仕様 4.2）。良い見本は NodeTable.everything で組み、
悪い見本（縛りを 1 つだけ破るように作った物）は tests/boards/tables/ に在る。graph は写しの review-loop.json。
"""
import dataclasses
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
TABLES = pathlib.Path(__file__).resolve().parent / "boards" / "tables"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

from board import BoardGap, BoardMismatch, NodeEntry, NodeTable  # noqa: E402
from engine.schema import graph_text  # noqa: E402  （board が写しの graphloops を sys.path に足す）
from engine.util import sha  # noqa: E402

GRAPH_PATH = CORE / "graphloops" / "graphs" / "review-loop.json"
GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
GRAPH_SHA = sha(graph_text(GRAPH_PATH))
ENGINE_RUN = {"p0.local_checks", "p4.ci", "p0.parallel_pr"}
# tests/boards/tables/ の悪い見本（同じ置き場には良い表も置くので、名前で数える）
BAD_TABLES = ("missing-node", "duplicate-node", "role-on-driver", "builtin-on-role", "engine-run-on-plain",
              "absent-no-reason", "bad-fallback", "missing-fallback", "parallel-pr-machine",
              "skippable-not-optional", "wrong-graph-sha", "unknown-by")


def with_node(table, nid, **fields):
    """表の 1 つの節だけを替えた表"""
    nodes = dict(table.nodes)
    nodes[nid] = dataclasses.replace(nodes[nid], **fields)
    return dataclasses.replace(table, nodes=nodes)


class NodeTableCase(unittest.TestCase):
    def setUp(self):
        self.full = NodeTable.everything(GRAPH, GRAPH_SHA)

    def errors(self, name):
        """悪い見本を読んで縛りを当てた誤りの一覧（1 つ以上在ることも見る）"""
        errs = NodeTable.load(TABLES / f"{name}.json").check(GRAPH, GRAPH_SHA)
        self.assertTrue(errs, f"{name} が通った")
        return errs

    def test_graph_is_the_copy(self):
        # 写しの graph が仕様の数えた物（60 節・機械の節 17・optional 10）に、軽量の深さで省ける 5 節の optional を足した物（持ち主の決定
        # 2026-10-06。COPIED_FROM の ! 行）であること（optional 15・graph_sha 2eb140b879e5）
        self.assertEqual(GRAPH_SHA, "2eb140b879e5")
        self.assertEqual(len(GRAPH["nodes"]), 60)
        self.assertEqual(sum(g.get("run_by") == "driver" for g in GRAPH["nodes"].values()), 17)
        self.assertEqual(sum(bool(g.get("optional")) for g in GRAPH["nodes"].values()), 15)

    def test_everything_covers_graph(self):
        t = self.full
        self.assertEqual(set(t.nodes), set(GRAPH["nodes"]))
        self.assertEqual(t.graph_sha, GRAPH_SHA)
        self.assertEqual(t.check(GRAPH, GRAPH_SHA), [])
        builtin = {n for n, e in t.nodes.items() if e.by == "builtin"}
        self.assertEqual(len(builtin), 17)
        self.assertEqual(builtin, {n for n, g in GRAPH["nodes"].items() if g["run_by"] == "driver"})
        self.assertTrue(all(t.nodes[n].run == "auto" for n in builtin))
        self.assertEqual({n for n, e in t.nodes.items() if e.by == "engine_run"}, ENGINE_RUN)
        self.assertEqual(t.nodes["p0.local_checks"].fallback, "machine")
        self.assertEqual(t.nodes["p4.ci"].fallback, "machine")
        self.assertEqual(t.nodes["p0.parallel_pr"].fallback, "role")
        rest = set(GRAPH["nodes"]) - builtin - ENGINE_RUN
        self.assertEqual({n for n, e in t.nodes.items() if e.by == "role"}, rest)
        self.assertEqual(t.absent(), [])

    def test_good_table_loads_and_round_trips(self):
        # 表のファイルの形で書いて読み直すと同じ表・同じ sha（既定の欄は書かなくてよい）
        t = with_node(self.full, "p2.history", skippable=True, where="blk-judge")
        t = with_node(t, "r1.minimality", by="absent", reason="R 系はこのラインに無い", comes_with="R 系のブロック")
        t = with_node(t, "p4.record", run="explicit")
        doc = {"line": "x", "graph_sha": t.graph_sha, "nodes": {}}
        for nid, e in t.nodes.items():
            doc["nodes"][nid] = {k: v for k, v in dataclasses.asdict(e).items()
                                 if v != getattr(NodeEntry, k, None) or k == "by"}
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "nodes.json"
            p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            back = NodeTable.load(p)
        self.assertEqual(back.check(GRAPH, GRAPH_SHA), [])
        self.assertEqual(dict(back.nodes), dict(t.nodes))
        self.assertEqual(back.sha(), dataclasses.replace(t, line="x").sha())

    def test_missing_node_named(self):
        errs = self.errors("missing-node")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("p3.delta_review2", errs[0])

    def test_extra_node_named(self):
        nodes = dict(self.full.nodes)
        nodes["p9.nothing"] = NodeEntry(by="role")
        errs = dataclasses.replace(self.full, nodes=nodes).check(GRAPH, GRAPH_SHA)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("p9.nothing", errs[0])

    def test_duplicate_node_rejected_on_load(self):
        with self.assertRaises(BoardGap) as cm:
            NodeTable.load(TABLES / "duplicate-node.json")
        self.assertIn("p2.diagnose", str(cm.exception))

    def test_shape_errors_on_load(self):
        bad = [
            "[]",
            '{"line": "x", "graph_sha": "y"}',
            '{"line": "x", "graph_sha": "y", "nodes": {"a": {"by": "role", "color": "red"}}}',
            '{"line": "x", "graph_sha": "y", "nodes": {"a": {"run": "auto"}}}',
            '{"line": "x", "graph_sha": "y", "nodes": {"a": {"by": "role", "skippable": "yes"}}}',
            '{"line": "x", "graph_sha": "y", "nodes": {"a": {"by": 1}}}',
            '{"line": "x", "graph_sha": "y", "nodes": [], "extra": 1}',
            "{not json",
        ]
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "nodes.json"
            for text in bad:
                p.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(BoardGap):
                    NodeTable.load(p)
            with self.assertRaises(BoardGap):
                NodeTable.load(pathlib.Path(d) / "none.json")

    def test_kind_matches_graph(self):
        for name, nid in (("role-on-driver", "p4.record"), ("builtin-on-role", "p2.diagnose"),
                          ("engine-run-on-plain", "p1.hygiene")):
            with self.subTest(name=name):
                errs = self.errors(name)
                self.assertEqual(len(errs), 1, errs)
                self.assertIn(nid, errs[0])
        # driver の節は machine でも持てない（role・machine はどちらでもない節だけ）、engine_run の節を role で持つのも誤り
        self.assertTrue(with_node(self.full, "converge", by="machine").check(GRAPH, GRAPH_SHA))
        self.assertTrue(with_node(self.full, "p4.ci", by="role", fallback="").check(GRAPH, GRAPH_SHA))
        # graph のどの節も absent にはできる
        self.assertEqual(with_node(self.full, "converge", by="absent", reason="r").check(GRAPH, GRAPH_SHA), [])

    def test_absent_needs_reason(self):
        errs = self.errors("absent-no-reason")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("r1.minimality", errs[0])
        errs = with_node(self.full, "r1.minimality", by="absent", reason=" \t\n").check(GRAPH, GRAPH_SHA)
        self.assertEqual(len(errs), 1, errs)
        self.assertEqual(with_node(self.full, "r1.minimality", by="absent", reason="R 系は無い").check(GRAPH, GRAPH_SHA), [])

    def test_engine_run_fallback_values(self):
        for name, nid in (("missing-fallback", "p4.ci"), ("bad-fallback", "p0.local_checks"),
                          ("parallel-pr-machine", "p0.parallel_pr")):
            with self.subTest(name=name):
                errs = self.errors(name)
                self.assertEqual(len(errs), 1, errs)
                self.assertIn(nid, errs[0])
        for fb in ("machine", "role", "absent"):
            self.assertEqual(with_node(self.full, "p4.ci", fallback=fb).check(GRAPH, GRAPH_SHA), [], fb)
        for fb in ("role", "absent"):
            self.assertEqual(with_node(self.full, "p0.parallel_pr", fallback=fb).check(GRAPH, GRAPH_SHA), [], fb)
        # fallback は engine_run の節だけの欄
        self.assertTrue(with_node(self.full, "p2.diagnose", fallback="machine").check(GRAPH, GRAPH_SHA))

    def test_run_only_on_builtin(self):
        self.assertEqual(with_node(self.full, "p4.record", run="explicit").check(GRAPH, GRAPH_SHA), [])
        self.assertTrue(with_node(self.full, "p4.record", run="later").check(GRAPH, GRAPH_SHA))
        self.assertTrue(with_node(self.full, "p2.diagnose", run="explicit").check(GRAPH, GRAPH_SHA))

    def test_skippable_only_optional(self):
        errs = self.errors("skippable-not-optional")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("p2.plan_review", errs[0])
        self.assertEqual(with_node(self.full, "p2.history", skippable=True).check(GRAPH, GRAPH_SHA), [])

    def test_graph_sha_mismatch(self):
        errs = self.errors("wrong-graph-sha")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("8676692bbcb2", errs[0])
        self.assertIn(GRAPH_SHA, errs[0])

    def test_unknown_by(self):
        errs = self.errors("unknown-by")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("p1.provenance", errs[0])
        self.assertIn("robot", errs[0])

    def test_each_bad_table_is_bad_once(self):
        # 悪い見本は、どれも在って、誤りがちょうど 1 つ（読めない duplicate-node を除く）
        self.assertEqual(len(BAD_TABLES), 12)
        for name in BAD_TABLES:
            self.assertTrue((TABLES / f"{name}.json").is_file(), name)
            if name == "duplicate-node":
                continue
            with self.subTest(name=name):
                self.assertEqual(len(self.errors(name)), 1)

    def test_absent_list_and_sha(self):
        t = with_node(self.full, "r1.minimality", by="absent", reason="R 系は無い", comes_with="R 系のブロック")
        t = with_node(t, "p0.parallel_pr", by="absent", fallback="", reason="並行 PR は見ない")
        self.assertEqual(t.check(GRAPH, GRAPH_SHA), [])
        self.assertEqual(sorted(t.absent(), key=lambda a: a["node"]), [
            {"node": "p0.parallel_pr", "reason": "並行 PR は見ない", "comes_with": ""},
            {"node": "r1.minimality", "reason": "R 系は無い", "comes_with": "R 系のブロック"},
        ])
        # absent() は表の順（everything は graph の順に組む）
        self.assertEqual([a["node"] for a in t.absent()],
                         [n for n in GRAPH["nodes"] if n in ("p0.parallel_pr", "r1.minimality")])
        s = t.sha()
        self.assertRegex(s, r"^[0-9a-f]{12}$")
        self.assertEqual(s, NodeTable(t.line, t.graph_sha, dict(t.nodes)).sha())
        self.assertNotEqual(s, with_node(t, "r1.minimality", reason="R 系は無し").sha())
        self.assertNotEqual(s, self.full.sha())

    def test_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.full.line = "y"
        with self.assertRaises(TypeError):
            self.full.nodes["p4.ci"] = NodeEntry(by="role")

    def test_nodes_must_be_entries(self):
        # 表を直に組むときも、節の値が NodeEntry でなければ BoardGap（check の中で AttributeError にしない）
        with self.assertRaises(BoardGap) as cm:
            NodeTable("x", GRAPH_SHA, {"p2.diagnose": {"by": "role"}})
        self.assertIn("p2.diagnose", str(cm.exception))

    def test_mismatch_is_gap(self):
        self.assertTrue(issubclass(BoardMismatch, BoardGap))
        self.assertTrue(issubclass(BoardGap, Exception))


TDD_PATH = CORE / "graphloops" / "graphs" / "review-loop-tdd.json"
TDD_SHA = sha(graph_text(TDD_PATH))


class GraphChoiceCase(unittest.TestCase):
    """表の graph の欄（仕様 tdd-spec 5 節）: 表が写しの graphs の下の graph を名指す。無ければ review-loop.json"""

    def write_table(self, d, **top):
        doc = json.loads((TABLES / "entry-line.json").read_text(encoding="utf-8"))
        doc.update(top)
        p = pathlib.Path(d) / "nodes.json"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return p

    def test_absent_graph_is_default_and_sha_unchanged(self):
        # 今の表は graph の欄を持たない——既定の review-loop.json で、表の sha は欄を足す前と同じ（盤面の table_sha を崩さない）
        t = NodeTable.load(TABLES / "entry-line.json")
        self.assertEqual(t.graph, "review-loop.json")
        self.assertEqual(t.sha(), "218f277fc510")   # graph_sha 2eb140b879e5 の表（2026-10-06 に optional を足して付け替えた）
        self.assertEqual(NodeTable.load(ROOT / "darkfactory" / "nodes.json").graph, "review-loop.json")
        self.assertEqual(NodeTable.everything(GRAPH, GRAPH_SHA).graph, "review-loop.json")
        # 既定の値を書いても書かなくても同じ表・同じ sha
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(NodeTable.load(self.write_table(d, graph="review-loop.json")).sha(), t.sha())

    def test_tdd_table_names_tdd_graph(self):
        t = NodeTable.load(TABLES / "tdd-line.json")
        self.assertEqual(t.graph, "review-loop-tdd.json")
        self.assertEqual(t.graph_sha, TDD_SHA)
        tdd = json.loads(TDD_PATH.read_text(encoding="utf-8"))
        from board import graph_expanded
        self.assertEqual(t.check(graph_expanded(TDD_PATH), TDD_SHA), [])
        for nid in tdd["nodes"]:
            self.assertIn(nid, t.nodes)
        self.assertEqual({n: t.nodes[n].by for n in ("p3.tdd_start", "p3.tdd_tests", "p3.tdd_red", "p3.tdd_green")},
                         {"p3.tdd_start": "builtin", "p3.tdd_tests": "role", "p3.tdd_red": "builtin", "p3.tdd_green": "builtin"})
        # graph が違えば同じ節の振りでも別の表（sha が違う）
        self.assertNotEqual(t.sha(), dataclasses.replace(t, graph="review-loop.json").sha())
        self.assertEqual(NodeTable.everything(graph_expanded(TDD_PATH), TDD_SHA, "review-loop-tdd.json").graph,
                         "review-loop-tdd.json")

    def test_unknown_graph_refused(self):
        # 写しの graphs の下に無い名前・パスの形の名前・文字列でない値は、読む時も直に組む時も BoardGap
        with tempfile.TemporaryDirectory() as d:
            for bad in ("nope.json", "../graphs/review-loop.json", "graphs/review-loop.json", "", "review-loop", 1, None):
                with self.subTest(bad=bad):
                    with self.assertRaises(BoardGap) as cm:
                        NodeTable.load(self.write_table(d, graph=bad))
                    self.assertIn("写しの graphs", str(cm.exception))   # 知らない欄としてでなく、名前として拒む
        for bad in ("nope.json", "../rules/review-loop.py"):
            with self.subTest(direct=bad):
                with self.assertRaises(BoardGap):
                    NodeTable("x", GRAPH_SHA, {}, bad)


if __name__ == "__main__":
    unittest.main()
