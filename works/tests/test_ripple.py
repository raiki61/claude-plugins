"""波及の一覧（blk-plan/lib/ripple.py。設計 docs/plans/2026-10-06-tree-line.md の 2.3 の 1）の検査。

項目が変える名（単位の key の `+` の後の名・adds の名のうち対象に在る物）を `git grep -w` で引き、本体の呼び出し元と試験に分け、
項目の allowed_paths・tests・rewrite_tests に照らして覆っていない当たりを名指す。見本は run 195g の波及の見落としの形
（字のままの値を断言する試験が rewrite_tests に無い・既定の引数に頼る呼び出し元・入力の組を多くのファイルが共有する名）。
種の git は gitkit の型の写し（FAST）。
"""
import json
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import gitkit  # noqa: E402
import graphmap  # noqa: E402
import line_edge  # noqa: E402
import planblk  # noqa: E402
import planmarks  # noqa: E402
import ripple  # noqa: E402

SEED = {
    "works/report.py": "def always_rows(rows=None):\n    return rows or {}\n",
    "works/final.py": "from report import always_rows\n\n\ndef final():\n    return always_rows()\n",
    "works/tests/test_report.py": ("from report import always_rows\n\n\nclass TestReport:\n    def test_rows(self):\n"
                                   "        assert always_rows() == {}\n\n\ndef helper():\n    return always_rows([1])\n"),
    "works/edge.py": "EDGE_INPUTS = ('a', 'b')\n",
    "works/n1.py": "from edge import EDGE_INPUTS\n",
    "works/n2.py": "from edge import EDGE_INPUTS\n",
    "works/README.md": "always_rows は残りの数え\n",
    # 呼び出し元でない文書と生成物（当たりに数えない。run 68f35d6b の波及の当たりの大半が設計書の行だった）
    "works/docs/plans/2026-10-01-x.md": "always_rows の設計\n",
    "works/CHANGELOG.md": "- always_rows を足した\n",
    ".archon/workflows/works/report.py": "def always_rows(rows=None):\n    return rows or {}\n",
}
KEY = "works/report.py+always_rows: 残りの数えが今の周だけ"


def setUpModule():
    global SRC
    SRC = pathlib.Path(tempfile.mkdtemp(prefix="works-ripple-seed-"))
    for name, text in SEED.items():
        p = SRC / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def tearDownModule():
    shutil.rmtree(SRC, ignore_errors=True)


def fields(unit_keys=(KEY,), adds=(), allowed=("works/report.py",), tests=(), rewrites=()):
    return {"unit_keys": list(unit_keys), "adds": list(adds), "allowed_paths": list(allowed),
            "tests": [{"id": t} for t in tests], "rewrite_tests": [{"id": t} for t in rewrites], "out_of_scope": []}


def split_fields(unit_keys=(KEY,), removes=(), adds=(), allowed=("works/report.py",)):
    """修正案の項目を planmarks.split で欄にした物（盤面の plan-fields.json の項目の欄の形）"""
    item = {"unit_keys": list(unit_keys), "approach": "x" * 20, "adds": [{"name": a, "kind": "function", "canonical": "works/report.py"} for a in adds], "removes": list(removes),
            "shrink_first": "y" * 20, "narrows": [], "route": "tdd", "route_why": "", "tests": [], "rewrite_tests": [],
            "refactor": {"declared": False, "why": ""}, "allowed_paths": list(allowed), "out_of_scope": []}
    return planmarks.split({"plan": [item]}, pathlib.Path("."))[1][0]


class RippleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        gitkit.committed_copy(self.repo, SRC)

    def uncovered(self, doc, n=1):
        return [(h["kind"], h["at"]) for h in ripple.uncovered(doc, n)]

    def repo_with(self, extra: dict, base=SEED) -> pathlib.Path:
        """base の種に extra（パス → 中身）を足した種を commit した別のリポジトリ"""
        src = pathlib.Path(self._tmp.name) / "src"
        shutil.rmtree(src, ignore_errors=True)
        for name, text in {**base, **extra}.items():
            p = src / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        repo = pathlib.Path(self._tmp.name) / "repo2"
        shutil.rmtree(repo, ignore_errors=True)
        gitkit.committed_copy(repo, src)
        return repo

    def test_removes_names_hits_are_uncovered(self):
        """消す名（removes）も名として引く: 識別子は探す語、.py のファイルの名はモジュールの名。残る名指しは kind removed で名指す"""
        f = split_fields(removes=["report.always_rows", "final.py"])
        self.assertEqual(f.get("removes"), ["report.always_rows", "final.py"])
        doc = ripple.build(self.repo, [f])
        self.assertEqual([r["name"] for r in doc["items"][0]["names"]], ["always_rows", "final"])
        self.assertIn(("removed", "works/final.py:1"), self.uncovered(doc))

    def test_removed_and_changed_name_on_same_line_both_listed(self):
        """変える名と消す名が同じ行・同じ試験の関数に当たれば、変える名の行（code・test）と消す名の行（removed・removed_test）が両方残る"""
        doc = ripple.build(self.repo, [split_fields(removes=["report.always_rows"])])
        got = self.uncovered(doc)
        for kind, at in (("code", "works/final.py:1"), ("removed", "works/final.py:1"),
                         ("test", "works/tests/test_report.py::TestReport::test_rows"),
                         ("removed_test", "works/tests/test_report.py::TestReport::test_rows")):
            self.assertIn((kind, at), got)
        only_changed = self.uncovered(ripple.build(self.repo, [split_fields()]))
        self.assertFalse([h for h in only_changed if h[0].startswith("removed")], only_changed)
        rewritten = split_fields(removes=["report.always_rows"])
        rewritten["rewrite_tests"] = [{"id": "works/tests/test_report.py::TestReport::test_rows"}]
        got = self.uncovered(ripple.build(self.repo, [rewritten]))
        self.assertNotIn(("removed_test", "works/tests/test_report.py::TestReport::test_rows"), got)

    def test_removed_name_hits_in_plan_docs_are_counted(self):
        """消す名に限り docs/plans の行も数える（CHANGELOG・.archon は今どおり捨てる）。足す名では docs/plans を数えない"""
        got = self.uncovered(ripple.build(self.repo, [split_fields(removes=["always_rows"])]))
        self.assertIn(("removed", "works/docs/plans/2026-10-01-x.md:1"), got)
        self.assertFalse([h for h in got if "CHANGELOG" in h[1] or h[1].startswith(".archon/")], got)
        added = self.uncovered(ripple.build(self.repo, [split_fields(unit_keys=[], adds=["always_rows"])]))
        self.assertFalse([h for h in added if "docs/plans" in h[1]], added)
        self.assertIn(("code", "works/final.py:1"), added)
        both = self.uncovered(ripple.build(self.repo, [split_fields(removes=["always_rows"])]))
        self.assertNotIn(("code", "works/docs/plans/2026-10-01-x.md:1"), both)

    def test_plan_docs_do_not_make_a_removed_name_common(self):
        """消す名の当たりに数え入れる計画書の数で、多い名（数だけ）に落とさない: 本体と試験の当たりのファイルの数だけで決める"""
        repo = self.repo_with({"works/docs/plans/2026-10-02-y.md": "EDGE_INPUTS の話\n"})
        f = split_fields(unit_keys=["works/edge.py+EDGE_INPUTS: 入力の組"], removes=["EDGE_INPUTS"], allowed=("works/edge.py",))
        row = ripple.build(repo, [f], common_files=3)["items"][0]["names"][0]
        self.assertEqual((row["common"], row["files"]), (False, 4))
        self.assertIn(("removed", "works/n1.py:1"), self.uncovered(ripple.build(repo, [f], common_files=3)))

    def test_removed_path_hits_are_uncovered(self):
        """消すファイルのパスは、パスの字のままの名指しと、.py ならモジュールの名の import も残りとして名指す"""
        repo = self.repo_with({"works/README.md": "道具は works/old_tool.py\n", "works/user.py": "import old_tool\n"})
        f = split_fields(unit_keys=["works/old_tool.py: 古い道具を消す"], removes=["works/old_tool.py"], allowed=("works/old_tool.py",))
        got = self.uncovered(ripple.build(repo, [f]))
        self.assertIn(("removed", "works/README.md:1"), got)
        self.assertIn(("removed", "works/user.py:1"), got)
        self.assertEqual([h for h in got if h[0] != "removed"], [])

    def test_removed_non_python_path_uses_file_name(self):
        """.py でないパスは、最後の段のファイルの名も名にする"""
        repo = self.repo_with({"works/docs/old-notes.md": "古い\n", "works/README.md": "メモは old-notes.md にある\n"})
        f = split_fields(unit_keys=["x: y"], removes=["works/docs/old-notes.md"], allowed=("works/docs/old-notes.md",))
        self.assertIn(("removed", "works/README.md:1"), self.uncovered(ripple.build(repo, [f])))

    def graph_repo(self):
        return self.repo_with({
            "works/archon-plugin.json": json.dumps({"entrypoints": {"line": "line/line.yaml"}}),
            "works/line/line.yaml": "name: line\n",
            "works/blk-a/blk-a.yaml": "name: blk-a\n",
            "works/line/line.graph.json": json.dumps({"version": graphmap.GRAPH_VERSION, "entry": "line", "workflows": {"line": {"nodes": []}},
                                                      "sources": {"line/line.yaml": "0", "blk-a/blk-a.yaml": "0"}}),
            "works/docs/line-design.md": "# line の設計図\n"})

    def test_graph_source_in_scope_without_map_is_uncovered(self):
        """範囲が工程の YAML を含むのに、その YAML から組む地図の元と設計図が範囲に無ければ kind graph で名指す（name は YAML）"""
        repo = self.graph_repo()
        doc = ripple.build(repo, [split_fields(allowed=("works/blk-a/**",))])
        rows = [(h["kind"], h["at"], h["name"]) for h in ripple.uncovered(doc, 1)]
        self.assertEqual(sorted(h for h in rows if h[0] == "graph"),
                         [("graph", "works/docs/line-design.md", "works/blk-a/blk-a.yaml"),
                          ("graph", "works/line/line.graph.json", "works/blk-a/blk-a.yaml")])
        both = split_fields(allowed=("works/blk-a/**", "works/line/line.graph.json", "works/docs/line-design.md"))
        self.assertEqual([h for h in self.uncovered(ripple.build(repo, [both])) if h[0] == "graph"], [])
        elsewhere = split_fields(allowed=("works/other/**",))
        self.assertEqual([h for h in self.uncovered(ripple.build(repo, [elsewhere])) if h[0] == "graph"], [])
        self.assertEqual([h for h in self.uncovered(ripple.build(self.repo, [split_fields(allowed=("works/**",))])) if h[0] == "graph"], [])

    def test_unreadable_map_is_reported_not_dropped(self):
        """読めない地図の元（壊れた JSON）は黙って落とさず、一覧の unread_maps に理由の行で残して節に出す"""
        broken = self.repo_with({"works/archon-plugin.json": json.dumps({"entrypoints": {"line": "line/line.yaml"}}),
                                 "works/line/line.yaml": "name: line\n", "works/line/line.graph.json": "{not json"})
        doc = ripple.build(broken, [split_fields(allowed=("works/line/**",))])
        self.assertEqual(doc["error"], "")
        self.assertEqual(len(doc["unread_maps"]), 1, doc["unread_maps"])
        self.assertTrue(doc["unread_maps"][0].startswith("works/line/line.yaml: "), doc["unread_maps"])
        text = ripple.section(doc, 1)
        self.assertIn(ripple.UNREAD_NOTE, text)
        self.assertIn(doc["unread_maps"][0], text)

    def test_map_source_outside_root_is_reported(self):
        """root の外を指す sources を持つ地図の元も、読めなかった物として残す"""
        outside = self.repo_with({"works/archon-plugin.json": json.dumps({"entrypoints": {"line": "line/line.yaml"}}),
                                  "works/line/line.yaml": "name: line\n",
                                  "works/line/line.graph.json": json.dumps({"version": graphmap.GRAPH_VERSION, "entry": "line",
                                                                          "workflows": {"line": {"nodes": []}},
                                                                          "sources": {"../../elsewhere.yaml": "0"}})})
        self.assertEqual(len(ripple.build(outside, [split_fields()])["unread_maps"]), 1)

    def test_unmade_map_is_not_unreadable(self):
        """地図の元をまだ作っていない入口は読めない物に数えない"""
        unmade = self.repo_with({"works/archon-plugin.json": json.dumps({"entrypoints": {"line": "line/line.yaml"}}),
                                 "works/line/line.yaml": "name: line\n"})
        doc = ripple.build(unmade, [split_fields()])
        self.assertEqual(doc["unread_maps"], [])
        self.assertNotIn(ripple.UNREAD_NOTE, ripple.section(doc, 1))

    def test_unlistable_root_is_error_not_empty_table(self):
        """root の一覧が引けない（OSError）時は空の表にせず、一覧の error に理由を書く"""
        with mock.patch.object(pathlib.Path, "iterdir", side_effect=PermissionError("denied")):
            doc = ripple.build(self.repo, [split_fields()])
        self.assertIn("denied", doc["error"])
        self.assertEqual(doc["items"], [])
        self.assertIn(ripple.ERROR_NOTE.format(error=doc["error"]), ripple.section(doc, 1))

    def test_item_text_marks_removed_name_hits(self):
        """消す名の当たりの行には、消した後に壊れる参照である印を出す。kind graph の行には、生成物を範囲に入れて作り直す手を書けと出す"""
        doc = ripple.build(self.repo, [split_fields(removes=["report.always_rows"])])
        text = ripple.section(doc, 1)
        marked = [x for x in text.splitlines() if x.startswith("- h") and " removed" in x]
        self.assertTrue(marked, text)
        self.assertTrue(all("消す名の残り" in x for x in marked), marked)
        plain = next(x for x in text.splitlines() if x.startswith("- h") and " code " in x)
        self.assertNotIn("消す名の残り", plain)
        gtext = ripple.section(ripple.build(self.graph_repo(), [split_fields(allowed=("works/blk-a/**",))]), 1)
        graph_lines = [x for x in gtext.splitlines() if x.startswith("- h") and " graph " in x]
        self.assertTrue(graph_lines, gtext)
        self.assertTrue(all("作り直す手を approach に書け" in x for x in graph_lines), graph_lines)

    def test_names_from_unit_key_and_adds(self):
        """単位の key の `+` の後から `:` までの ASCII の名と、adds の名の ASCII の語（日本語の語は名でない）"""
        self.assertEqual(ripple.names([KEY, "stats.py mean: 分母"], ["removed_rounds", "lens 数え"]),
                         ["always_rows", "removed_rounds", "lens"])
        self.assertEqual(ripple.names(["a.py+Report.rows: x"], []), ["Report", "rows"])

    def test_names_skip_test_ids_and_paths(self):
        """adds の試験の id・パスと試験の名（test_・Test）は変える名でない（run 68f35d6b: 試験の id の断片 works・tests・
        test_report・HeadCase が当たりの大半を作った）"""
        self.assertEqual(ripple.names([KEY], ["works/tests/test_report.py::HeadCase::test_rows_carry", "_removed_file",
                                              "TestCleanIgnored", "test_report", "works/report.py", "report.always_rows"]),
                         ["always_rows", "_removed_file", "report"])

    def test_docs_and_generated_copies_are_not_hits(self):
        """設計書（docs/plans）・CHANGELOG・pack の写し（.archon）は当たりに数えない（ファイルの数にも）"""
        doc = ripple.build(self.repo, [fields()])
        ats = [h[1] for h in self.uncovered(doc)]
        self.assertFalse([a for a in ats if "docs/plans" in a or "CHANGELOG" in a or a.startswith(".archon/")], ats)
        row = doc["items"][0]["names"][0]
        self.assertEqual(row["files"], 4)   # report.py・final.py・test_report.py・README.md

    def test_literal_test_not_in_rewrite_is_uncovered(self):
        """字のままの値を断言する試験（195g の removed-exact-dict-test-not-in-rewrite の形）は試験の関数の id で名指す"""
        doc = ripple.build(self.repo, [fields()])
        self.assertIn(("test", "works/tests/test_report.py::TestReport::test_rows"), self.uncovered(doc))
        doc = ripple.build(self.repo, [fields(rewrites=["works/tests/test_report.py::TestReport::test_rows"])])
        self.assertNotIn(("test", "works/tests/test_report.py::TestReport::test_rows"), self.uncovered(doc))

    def test_caller_outside_scope_is_uncovered(self):
        """既定の引数に頼る呼び出し元（195g の always-rows-left-none-undefined の形）は本体の当たりで名指す。定義の在るファイルは
        allowed_paths の中なので覆っている。試験のファイルの試験でない関数は行で名指す。文書の当たりも本体に数える"""
        doc = ripple.build(self.repo, [fields()])
        got = self.uncovered(doc)
        self.assertIn(("code", "works/final.py:1"), got)
        self.assertIn(("code", "works/final.py:5"), got)
        self.assertIn(("test", "works/tests/test_report.py:10"), got)
        self.assertIn(("code", "works/README.md:1"), got)
        self.assertFalse([h for h in got if h[1].startswith("works/report.py")])
        doc = ripple.build(self.repo, [fields(allowed=("works/*.py", "works/tests/test_report.py", "works/README.md"))])
        self.assertEqual(self.uncovered(doc), [("test", "works/tests/test_report.py::TestReport::test_rows")])

    def test_hit_ids_are_stable_per_item(self):
        doc = ripple.build(self.repo, [fields()])
        ids = [h["id"] for h in ripple.uncovered(doc, 1)]
        self.assertEqual(ids, [f"h{i}" for i in range(1, len(ids) + 1)])

    def test_common_name_counts_only(self):
        """当たりのファイルが多い名は数だけ載せ、覆っていない当たりに入れない（下請けが判断する）"""
        f = fields(unit_keys=["works/edge.py+EDGE_INPUTS: 入力の組"], allowed=("works/edge.py",))
        doc = ripple.build(self.repo, [f], common_files=2)
        row = doc["items"][0]["names"][0]
        self.assertEqual((row["name"], row["common"], row["files"]), ("EDGE_INPUTS", True, 3))
        self.assertEqual(self.uncovered(doc), [])
        doc = ripple.build(self.repo, [f])
        self.assertEqual(self.uncovered(doc), [("code", "works/n1.py:1"), ("code", "works/n2.py:1")])

    def test_names_absent_from_repo_are_dropped(self):
        doc = ripple.build(self.repo, [fields(unit_keys=["works/report.py+no_such_name: x"], adds=["also_missing"])])
        self.assertEqual(doc["items"][0]["names"], [])

    def test_overlaps_between_items(self):
        """2 つ以上の項目の allowed_paths・波及の当たりに出たファイル（相乗りの審査が突き合わせる）"""
        doc = ripple.build(self.repo, [fields(), fields(unit_keys=["works/final.py+final: y"], allowed=("works/final.py",))])
        self.assertIn({"at": "works/final.py", "items": [1, 2]}, doc["overlaps"])

    def test_units_have_hits_without_coverage(self):
        """案の前（修正案の役に渡す）は単位の key の名だけを引き、照らす範囲が無いので覆っていない当たりを持たない"""
        doc = ripple.for_units(self.repo, [KEY])
        row = doc["units"][0]
        self.assertEqual(row["unit_key"], KEY)
        self.assertIn("works/final.py:5", row["names"][0]["code"])
        self.assertIn("works/tests/test_report.py::TestReport::test_rows", row["names"][0]["tests"])

    def test_not_a_repo_gives_error_not_raise(self):
        doc = ripple.build(pathlib.Path(self._tmp.name) / "none", [fields()])
        self.assertTrue(doc["error"])
        self.assertEqual(ripple.uncovered(doc, 1), [])

    def test_section_names_uncovered_and_asks_scope(self):
        """指示書の節: 覆っていない当たりを id つきで並べ、範囲に先に入れるか（修正中の範囲の相談を減らす）を言う"""
        doc = ripple.build(self.repo, [fields()])
        text = ripple.section(doc, 1)
        self.assertIn("works/final.py:5", text)
        self.assertIn("h1", text)
        self.assertIn(ripple.SCOPE_ASK, ripple.section(doc))


class ReplanRippleCase(unittest.TestCase):
    """同じ run の中の案の直しの後の波及の一覧（2 回目の修正の段へ線が渡す ripple.json）は、直した項目の範囲で作り直す
    （1 回目の案の一覧を使い回さない）。盤面は偽の b（dir・round・work）に plan-fields.json と案の直しの控え replan.json を置くだけ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        gitkit.committed_copy(self.repo, SRC)
        self.dir = pathlib.Path(self._tmp.name) / "board"
        (self.dir / "r1").mkdir(parents=True)
        self.b = types.SimpleNamespace(dir=self.dir, round=1, work=lambda name: self.dir / "r1" / name)
        (self.dir / "plan-fields.json").write_text(json.dumps({"round": 1, "fields": [fields()]}), encoding="utf-8")

    def trip(self, *rows):
        self.b.work("replan.json").write_text(json.dumps({"round": 1, "items": list(rows)}), encoding="utf-8")

    def test_rebuilt_from_revised_item(self):
        first = ripple.build(self.repo, [fields()])
        self.assertIn(("code", "works/final.py:1"), [(h["kind"], h["at"]) for h in ripple.uncovered(first, 1)])
        new = {**fields(allowed=("works/report.py", "works/final.py")), "adds": []}
        self.trip({"item": 1, "old": fields(), "new": new})
        latest = self.b.work(planblk.RIPPLE_LATEST)
        latest.write_text("{}", encoding="utf-8")   # 1 回目の案の一覧（案を書いた include の物。周ごとに書き手は 1 つなので上書きしない）
        got = planblk.replan_ripple(self.b, self.repo)
        self.assertEqual(got, str(self.b.work(planblk.RIPPLE_REPLAN)))
        self.assertEqual(latest.read_text(encoding="utf-8"), "{}")
        doc = json.loads(pathlib.Path(got).read_text(encoding="utf-8"))
        ats = [h["at"] for h in ripple.uncovered(doc, 1)]
        self.assertFalse([a for a in ats if a.startswith("works/final.py")], ats)   # 直した項目の範囲で照らした
        self.assertIn("works/README.md:1", ats)
        # 線の h-refit は 2 回目の修正の段へ、作り直した一覧が在ればそれを、無ければ 1 回目の一覧を渡す
        self.assertEqual(line_edge.refit_ripple_file(self.b), got)
        self.assertEqual(line_edge.RIPPLE_REPLAN_FILE, planblk.RIPPLE_REPLAN)

    def test_nothing_revised_makes_nothing(self):
        self.assertEqual(planblk.replan_ripple(self.b, self.repo), "")   # 案の直しの控えが無い
        self.trip({"item": 1, "old": fields(), "new": None})            # 修正案の役が直せなかった
        self.assertEqual(planblk.replan_ripple(self.b, self.repo), "")
        self.assertFalse(self.b.work(planblk.RIPPLE_REPLAN).exists())
        self.assertEqual(line_edge.refit_ripple_file(self.b), "")
        self.b.work(planblk.RIPPLE_LATEST).write_text("{}", encoding="utf-8")
        self.assertEqual(line_edge.refit_ripple_file(self.b), str(self.b.work(planblk.RIPPLE_LATEST)))


if __name__ == "__main__":
    unittest.main()
