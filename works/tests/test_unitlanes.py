"""修正役の下請けを単位の worktree で並べる（blk-fix/lib/unitlanes.py。依頼 243 の並べ）の検査。種の git は gitkit の型の写し。

縛る事:
- 分け方: 範囲の引けない項目と、範囲が重なる項目は順。どれとも重ならない項目が 2 つ以上の時だけ並べる。glob は字のままの頭で比べ、
  広く重なりと見る
- 切る: run の作業ツリーの今の姿（未 commit を含む）を base にし、項目ごとに置き場の下へ単位の worktree を切って控えに書く
- 当てる（役の sandbox の中のコマンド）: 項目の番号の順に当て、食い違う項目は conflict で作業ツリーを変えない。2 度走らせても
  当て直さない。`.git` の指しが切った時と違う項目は broken。共通の .git が書けなくても回る（別のプロセスの python3 で）
- 締める（受け付けの前の機械）: 当てた項目の記録を写し、当てるコマンドが走らなかった項目は機械が当て、単位の worktree を片付ける
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

    def test_unknown_or_overlapping_items_stay_serial(self):
        got = unitlanes.lanes([(1, ["works/a/x.py"]), (2, None), (3, ["works/a/*.py"]), (4, ["works/d.py"]), (5, ["docs/e.md"])])
        self.assertEqual(got, [4, 5], "範囲の無い 2 と、頭が重なる 1・3 は順")

    def test_fewer_than_two_is_nothing(self):
        self.assertEqual(unitlanes.lanes([(1, ["a.py"]), (2, ["a.py"]), (3, ["b.py"])]), [])
        self.assertEqual(unitlanes.lanes([]), [])

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

    def plant(self, items=(1, 2)):
        return unitlanes.plant(self.repo, list(items), self.place, self.manifest)

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

    def test_merge_applies_in_order_and_parks_conflicts(self):
        got = self.plant((1, 2, 3))
        (pathlib.Path(got[1]["tree"]) / "a.txt").write_text("a1\nA2 one\na3\n", encoding="utf-8")
        (pathlib.Path(got[2]["tree"]) / "b.txt").write_text("b1\nB2 two\nb3\n", encoding="utf-8")
        (pathlib.Path(got[3]["tree"]) / "a.txt").write_text("a1\nA2 three\na3\n", encoding="utf-8")   # 1 と同じ行
        out = unitlanes.merge(self.manifest)
        self.assertEqual(out["applied"], [1, 2])
        self.assertEqual([c["item"] for c in out["conflict"]], [3])
        self.assertTrue(pathlib.Path(out["conflict"][0]["patch"]).is_file(), "当たらなかった差分は捨てずにファイルに残す")
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nA2 one\na3\n")
        self.assertEqual((self.repo / "b.txt").read_text(), "b1\nB2 two\nb3\n")
        self.assertEqual(out["differ"], [])
        again = unitlanes.merge(self.manifest)
        self.assertEqual((again["applied"], [c["item"] for c in again["conflict"]]), ([1, 2], [3]), "2 度目は当て直さない")
        self.assertEqual((self.repo / "a.txt").read_text(), "a1\nA2 one\na3\n")

    def test_merge_names_files_whose_content_was_combined(self):
        got = self.plant()
        (pathlib.Path(got[1]["tree"]) / "a.txt").write_text("A1\na2\na3\n", encoding="utf-8")
        (pathlib.Path(got[2]["tree"]) / "a.txt").write_text("a1\na2\nA3\n", encoding="utf-8")
        out = unitlanes.merge(self.manifest)
        self.assertEqual(out["applied"], [1, 2])
        self.assertEqual((self.repo / "a.txt").read_text(), "A1\na2\nA3\n")
        self.assertEqual(out["differ"], ["a.txt"], "2 つの差分を合わせた中身は単位の中身と違う（役が申告する）")

    def test_merge_refuses_a_tree_whose_git_pointer_changed(self):
        got = self.plant()
        (pathlib.Path(got[1]["tree"]) / "a.txt").write_text("a1\nA2\na3\n", encoding="utf-8")
        (pathlib.Path(got[1]["tree"]) / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        out = unitlanes.merge(self.manifest)
        self.assertEqual([b["item"] for b in out["broken"]], [1])
        self.assertEqual((self.repo / "a.txt").read_text(), SEED["a.txt"])

    def test_merge_command_runs_without_writing_the_common_git_dir(self):
        got = self.plant()
        (pathlib.Path(got[1]["tree"]) / "a.txt").write_text("a1\nA2\na3\n", encoding="utf-8")
        (pathlib.Path(got[2]["tree"]) / "new.txt").write_text("fresh\n", encoding="utf-8")
        common = pathlib.Path(git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        dirs = [common, *[d for d in common.rglob("*") if d.is_dir()]]
        for d in dirs:
            d.chmod(0o555)
        self.addCleanup(lambda: [d.chmod(0o755) for d in dirs])
        r = subprocess.run([sys.executable, str(ROOT / "blk-fix" / "lib" / "unitlanes.py"), str(self.manifest)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["applied"], [1, 2])
        self.assertEqual((self.repo / "new.txt").read_text(), "fresh\n")

    def test_command_line_is_the_one_the_fixer_runs(self):
        self.assertEqual(unitlanes.command("/m/units.json"),
                         f"python3 {ROOT / 'blk-fix' / 'lib' / 'unitlanes.py'} /m/units.json")

    def test_settle_carries_records_applies_leftovers_and_sweeps(self):
        got = self.plant((1, 2))
        t1, t2 = pathlib.Path(got[1]["tree"]), pathlib.Path(got[2]["tree"])
        (t1 / "a.txt").write_text("a1\nA2\na3\n", encoding="utf-8")
        log = self.home / "writes.jsonl"
        log.write_text(json.dumps({"tool_name": "Edit", "path": str((t1 / "a.txt").resolve()),
                                   "file_sha": writes._sha(str(t1 / "a.txt"))}) + "\n", encoding="utf-8")
        unitlanes.merge(self.manifest)
        (t2 / "b.txt").write_text("b1\nB2\nb3\n", encoding="utf-8")   # 当てるコマンドの後に書いた（記録に無い項目 2 ではない）
        rec = json.loads(pathlib.Path(json.loads(self.manifest.read_text())["record"]).read_text())
        del rec["items"]["2"]                                          # 当てるコマンドが項目 2 を当てなかった
        pathlib.Path(json.loads(self.manifest.read_text())["record"]).write_text(json.dumps(rec))
        keep = self.home / "board" / "kept"
        out = unitlanes.settle(self.manifest, self.repo, log, keep)
        self.assertEqual(out["applied"], [1, 2])
        self.assertEqual(out["machine"], [2], "当てるコマンドが当てなかった項目は機械が当てる")
        self.assertEqual(out["carried"], 1)
        self.assertEqual((self.repo / "b.txt").read_text(), "b1\nB2\nb3\n")
        self.assertFalse(t1.exists() or t2.exists(), "単位の worktree を片付ける")
        self.assertFalse(self.manifest.exists(), "控えを済みの名に移す（同じ周の出し直しで 2 度締めない）")
        self.assertEqual(unitlanes.settle(self.manifest, self.repo, log, keep), {"ran": False})
        problems = writes.check({}, self.repo, ["a.txt"], log)["problems"]
        self.assertEqual(problems, [], "写した記録で受け付けが通る")

    def test_settle_keeps_patches_it_could_not_merge(self):
        got = self.plant((1, 2))
        (pathlib.Path(got[1]["tree"]) / "a.txt").write_text("a1\nA2 one\na3\n", encoding="utf-8")
        (pathlib.Path(got[2]["tree"]) / "a.txt").write_text("a1\nA2 two\na3\n", encoding="utf-8")
        unitlanes.merge(self.manifest)   # 2 は conflict（修正役が順で直し直す）
        keep = self.home / "board" / "kept"
        out = unitlanes.settle(self.manifest, self.repo, self.home / "writes.jsonl", keep)
        self.assertEqual(out["conflict"], [2])
        self.assertIn("A2 two", (keep / "item-2.patch").read_text(), "直しを捨てずに盤面に残す")

    def test_settle_without_manifest_does_nothing(self):
        self.assertEqual(unitlanes.settle(self.manifest, self.repo, self.home / "w.jsonl", self.home / "k"), {"ran": False})


if __name__ == "__main__":
    unittest.main()
