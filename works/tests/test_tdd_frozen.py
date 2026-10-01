"""TDD の輪で凍ったテストのファイルと、裁定 fix_test_scope の範囲（tddloop.frozen_problems の allowed）の検査。

裁定が範囲（limits。`<パス>` か `<パス>:<行>[-<行>]`）に並べた所の直しは、凍ったファイルでも拒まない。範囲の外の行・
範囲の無いファイルの変更は今どおり拒む。行は凍った時の木（st["frozen_tree"]。_finish が書く）に対する旧い側で見る。
st["handoff"] は frozen_tree の無い古い状態の時だけの控え。輪で足した未追跡のテストのファイルも同じに見る。
.py の `<パス>:<行>` 1 つは、その行を含む関数の全体に広がる（`<行>-<行>` は書いたとおり）。この試験の「範囲の外の行」は
その広がりの外を指す（広がりの試験は test_tdd_frozen_function_span.py）。
種の git は gitkit の型の写し（盤面・子の実行器なし）。
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "dev" / "target-seed"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

from gitkit import committed_copy  # noqa: E402
import tddloop  # noqa: E402

TEST_FILE = "test_stats.py"
NEW_FILE = "test_new.py"   # 輪で足した、まだ追跡されていないテストのファイル
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"   # どのファイルも無い木（控えに使われれば、どの変更も外になる）


class FrozenRuledScopeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        committed_copy(self.repo, SEED)
        (self.repo / NEW_FILE).write_text("import unittest\n\n\nclass T(unittest.TestCase):\n"
                                          "    def test_one(self):\n        self.assertEqual(1, 1)\n", encoding="utf-8")
        self.state = tmp / "state.json"
        self.freeze(frozen_tree=tddloop.snapshot(self.repo), handoff=EMPTY_TREE)

    def freeze(self, **trees):
        st = {"frozen": tddloop.hashes(self.repo, [TEST_FILE, NEW_FILE]), **trees}
        self.state.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

    def edit(self, old, new, path=TEST_FILE):
        p = self.repo / path
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new), encoding="utf-8")

    def frozen(self, allowed):
        try:
            return tddloop.frozen_problems(str(self.state), self.repo, allowed=allowed)
        except TypeError as e:
            self.fail(f"frozen_problems が裁定の範囲（allowed）を受けない: {e}")

    def test_change_inside_ruled_lines_is_allowed(self):
        self.edit("mean([1, 2, 3]), 2)", "mean([1, 2, 3]), 2.0)")   # 9 行目
        self.assertEqual(self.frozen([f"{TEST_FILE}:9"]), [], "frozen_tree で見る（handoff の空の木で見れば外になる）")

    def test_change_outside_ruled_lines_is_rejected(self):
        self.edit("clamp(5, 0, 10), 5)", "clamp(5, 0, 10), 5.0)")   # 12 行目
        got = self.frozen([f"{TEST_FILE}:9"])
        self.assertTrue(got, "範囲の外の行の変更は拒む")
        self.assertIn(TEST_FILE, " ".join(got))

    def test_ruled_whole_file_allows_any_line(self):
        self.edit("clamp(5, 0, 10), 5)", "clamp(5, 0, 10), 5.0)")
        self.assertEqual(self.frozen([TEST_FILE]), [])

    def test_no_ruling_still_rejects(self):
        self.edit("mean([1, 2, 3]), 2)", "mean([1, 2, 3]), 2.0)")
        self.assertTrue(self.frozen([]), "裁定の無い変更は今どおり拒む")

    def test_untracked_new_file_inside_ruled_lines_is_allowed(self):
        self.edit("assertEqual(1, 1)", "assertEqual(1, 1.0)", NEW_FILE)   # 6 行目
        self.assertEqual(self.frozen([f"{NEW_FILE}:6"]), [])

    def test_untracked_new_file_outside_ruled_lines_is_rejected(self):
        self.edit("class T(", "class U(", NEW_FILE)   # 4 行目（6 行目を含む関数の幅の外）
        got = self.frozen([f"{NEW_FILE}:6"])
        self.assertTrue(got, "未追跡のファイルでも範囲の外の行の変更は拒む")
        self.assertIn(NEW_FILE, " ".join(got))

    def test_old_state_without_frozen_tree_falls_back_to_handoff(self):
        self.freeze(handoff=tddloop.snapshot(self.repo))
        self.edit("mean([1, 2, 3]), 2)", "mean([1, 2, 3]), 2.0)")
        self.assertEqual(self.frozen([f"{TEST_FILE}:9"]), [])


if __name__ == "__main__":
    unittest.main()
