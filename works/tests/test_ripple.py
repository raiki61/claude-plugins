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

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import gitkit  # noqa: E402
import line_edge  # noqa: E402
import planblk  # noqa: E402
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


class RippleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        gitkit.committed_copy(self.repo, SRC)

    def uncovered(self, doc, n=1):
        return [(h["kind"], h["at"]) for h in ripple.uncovered(doc, n)]

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
