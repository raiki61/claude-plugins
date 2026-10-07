"""単位の worktree で項目・枝を並べる共通の部品（blk-fix/lib/unitlanes.py。依頼 243 の並べ）の検査。種の git は gitkit の型の写し。

縛る事:
- 分け方: 範囲の引けない項目は順。範囲の在る項目は重なっても並べる（2 つ以上の時だけ。依頼 243 の並べの 3 段目）。重なりの見込み
  （expect）は glob の字のままの頭で比べ、広く重なりと見る
- 合わせる試験のファイル: 2 つの項目が同じ試験のファイルの末尾に足しただけなら、先の項目の行の後に後の項目の行を置いて当てる。
  同じ名のテストの定義が 2 つになる中身は合わせない（tests_unique）。出口の shared は 2 つ以上の差分に出たファイル
- 切る: run の作業ツリーの今の姿（未 commit を含む）を base にし、項目ごとに置き場の下へ単位の worktree を切って控えに書く
- 記録を写す: 当てた枝の単位の worktree の書き込みの記録を run の作業ツリーへ（重なりのファイルは合わせた中身に 1 行）。当てるのと
  締めるのは使い手の締めの節（tddlanes・fixlanes。前の形の当てるコマンドと締めの節 fix-units は外した）
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import unitlanes  # noqa: E402
import unittrees  # noqa: E402
import writes  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

SEED = {"a.txt": "a1\na2\na3\n", "b.txt": "b1\nb2\nb3\n", "c.txt": "c1\nc2\nc3\n"}
_SRC = None


def setUpModule():
    global _SRC
    _SRC = pathlib.Path(tempfile.mkdtemp(prefix="works-unitlanes-src-"))
    for rel, text in SEED.items():
        (_SRC / rel).write_text(text, encoding="utf-8")


def tearDownModule():
    shutil.rmtree(_SRC, ignore_errors=True)


class Lanes(unittest.TestCase):
    def test_disjoint_items_run_side_by_side(self):
        got = unitlanes.lanes([(1, ["works/a/x.py"]), (2, ["works/b/**"]), (3, ["works/c.py", "tests/test_c.py"])])
        self.assertEqual(got, [1, 2, 3])

    def test_unknown_items_stay_serial_and_overlapping_items_run_side_by_side(self):
        items = [(1, ["works/a/x.py"]), (2, None), (3, ["works/a/*.py"]), (4, ["works/d.py"]), (5, ["docs/e.md"])]
        self.assertEqual(unitlanes.lanes(items), [1, 3, 4, 5], "範囲の無い 2 だけ順。頭が重なる 1・3 も並べる")
        self.assertEqual(unitlanes.expect(items), [[1, 3]], "重なりの見込みは頭が重なる組")

    def test_fewer_than_two_is_nothing(self):
        self.assertEqual(unitlanes.lanes([(1, ["a.py"]), (2, None)]), [])
        self.assertEqual(unitlanes.lanes([]), [])
        self.assertEqual(unitlanes.lanes([(1, ["a.py"]), (2, ["a.py"])]), [1, 2], "同じ範囲でも並べる")

    def test_tests_unique_refuses_a_name_defined_twice(self):
        ok = b"class TestA:\n    def test_x(self):\n        pass\n\nclass TestB:\n    def test_x(self):\n        pass\n"
        self.assertTrue(unitlanes.tests_unique("tests/test_a.py", ok), "別のクラスの同じ名は隠さない")
        twice = b"def test_x():\n    pass\n\ndef test_x():\n    pass\n"
        self.assertFalse(unitlanes.tests_unique("tests/test_a.py", twice))
        cls = b"class TestA:\n    def test_y(self):\n        pass\n\n    def test_y(self):\n        pass\n"
        self.assertFalse(unitlanes.tests_unique("tests/test_a.py", cls))
        self.assertFalse(unitlanes.tests_unique("tests/test_a.py", b"def test_(:\n"), "読めない中身は合わせない")
        self.assertTrue(unitlanes.tests_unique("tests/a.txt", b"x\nx\n"), ".py でなければ照らさない")

    def test_overlap_reads_literal_heads(self):
        self.assertTrue(unitlanes.overlap(["works/blk-fix/lib/*.py"], ["works/blk-fix/lib/tddloop.py"]))
        self.assertTrue(unitlanes.overlap(["**/*.md"], ["works/a.py"]), "頭の無い glob は全部に重なる")
        self.assertTrue(unitlanes.overlap(["works/a.py"], ["works/a.py"]))
        self.assertFalse(unitlanes.overlap(["works/a.py"], ["works/b.py"]))
        self.assertFalse(unitlanes.overlap([], ["works/b.py"]), "範囲が空の項目は何にも重ならない")


class Trees(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="works-unitlanes-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.repo = self.home / "run"
        committed_copy(self.repo, _SRC)
        self.addCleanup(lambda: unittrees.sweep(self.repo) if self.repo.exists() else None)
        self.place = self.home / "run-place" / "units"
        self.manifest = self.home / "board" / "units.json"
        (self.repo / "c.txt").write_text("c1\nC2 by loop\nc3\n", encoding="utf-8")   # 輪の直し（未 commit）

    def plant(self, items=(1, 2), union=()):
        return unitlanes.plant(self.repo, list(items), self.place, self.manifest, union)

    def test_plant_cuts_a_tree_per_item_from_the_current_tree(self):
        got = self.plant()
        self.assertEqual(sorted(got), [1, 2])
        doc = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual([r["item"] for r in doc["items"]], [1, 2])
        for n, row in got.items():
            tree = pathlib.Path(row["tree"])
            self.assertEqual(tree, self.place / f"item-{n}")
            self.assertEqual((tree / "c.txt").read_text(), "c1\nC2 by loop\nc3\n", "輪の直しが見える")
            self.assertEqual(row["base"], doc["base"])

    def test_carry_records_moves_tree_records_to_the_run_tree(self):
        """当てた枝の単位の worktree の書き込みの記録を run の作業ツリーへ写す: 重なりでないファイルは中身が同じ時だけ（writes.carry）、
        重なりのファイルは合わせた中身に 1 行（writes.carry_merged。どの枝の中身にも記録が在る時だけ）"""
        got = self.plant((1, 2))
        t1, t2 = pathlib.Path(got[1]["tree"]), pathlib.Path(got[2]["tree"])
        (t1 / "a.txt").write_text("A1\na2\na3\n", encoding="utf-8")
        (t1 / "b.txt").write_text("b1\nB2\nb3\n", encoding="utf-8")
        (t2 / "a.txt").write_text("a1\na2\nA3\n", encoding="utf-8")
        log = self.home / "writes.jsonl"
        log.write_text("".join(json.dumps({"tool_name": "Edit", "path": str((t / n).resolve()), "file_sha": writes._sha(str(t / n))}) + "\n"
                               for t, n in ((t1, "a.txt"), (t1, "b.txt"), (t2, "a.txt"))), encoding="utf-8")
        applied = []
        for n, t in ((1, t1), (2, t2)):
            patch = self.home / f"lane-{n}.patch"
            patch.write_text(unittrees.diff(t, got[n]["base"]), encoding="utf-8")
            ok, why = unittrees.apply(self.repo, patch.read_text(encoding="utf-8"))
            self.assertTrue(ok, why)
            applied.append((t, patch))
        self.assertEqual((self.repo / "a.txt").read_text(), "A1\na2\nA3\n", "同じファイルの別の行は 3 方向で合う")
        self.assertEqual(writes.check({}, self.repo, ["a.txt", "b.txt"], log)["problems"] != [], True, "写す前は記録が無い")
        unitlanes.carry_records(log, self.repo, applied, ["a.txt"])
        self.assertEqual(writes.check({}, self.repo, ["a.txt", "b.txt"], log)["problems"], [], "写した記録で受け付けが通る")
        unitlanes.carry_records(self.home / "none.jsonl", self.repo, applied, [])   # 記録の無い run は何もしない
        self.assertFalse((self.home / "none.jsonl").exists())

if __name__ == "__main__":
    unittest.main()
