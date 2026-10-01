"""裁定 fix_test_scope の `<パス>:<行>` 1 つ（.py）は、その行を含むテストの関数の全体（デコレータ・直前のコメントから
本体の終わりまで）に効く。隣の関数・クラス・`<行>-<行>` の明示の範囲・.py でないファイルには広げない。
tddloop.frozen_problems の入口で見る（種の置き方は test_tdd_frozen と同じ）。"""
import json
import pathlib
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

from gitkit import committed_copy  # noqa: E402
import tddloop  # noqa: E402

SRC = """import unittest


class T(unittest.TestCase):
    def test_a(self):
        self.assertEqual(1, 1)

    # b の説明
    @unittest.skipIf(False, "x")
    def test_b(self):
        # 本体のコメント
        self.assertEqual(2, 2)

    def test_c(self):
        self.assertEqual(3, 3)
"""
F = "test_span.py"
N = "notes.txt"


class FunctionSpanCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        committed_copy(self.repo, ROOT / "dev" / "target-seed")
        (self.repo / F).write_text(SRC, encoding="utf-8")
        (self.repo / N).write_text("a\nb\nc\n", encoding="utf-8")
        self.state = tmp / "state.json"
        st = {"frozen": tddloop.hashes(self.repo, [F, N]), "frozen_tree": tddloop.snapshot(self.repo)}
        self.state.write_text(json.dumps(st), encoding="utf-8")

    def edit(self, old, new, path=F):
        p = self.repo / path
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def frozen(self, *allowed):
        return tddloop.frozen_problems(str(self.state), self.repo, allowed=list(allowed))

    def test_def_line_allows_decorator_comment_def_and_body(self):
        for old, new in [("@unittest.skipIf(False", "@unittest.skipIf(True"), ("# b の説明", "# b を直した説明"),
                         ("def test_b", "def test_bb"), ("# 本体のコメント", "# 本体"), ("assertEqual(2, 2)", "assertEqual(2, 2.0)")]:
            with self.subTest(old=old):
                self.setUp()
                self.edit(old, new)
                self.assertEqual(self.frozen(f"{F}:10"), [])

    def test_body_line_allows_def_of_same_function(self):
        self.edit("def test_b", "def test_bb")
        self.assertEqual(self.frozen(f"{F}:12"), [])

    def test_neighbour_function_is_rejected(self):
        for old in ("assertEqual(1, 1)", "assertEqual(3, 3)"):
            with self.subTest(old=old):
                self.setUp()
                self.edit(old, old.replace(")", ".0)"))
                self.assertTrue(self.frozen(f"{F}:10"))

    def test_class_line_is_not_widened(self):
        self.edit("class T(", "class U(")
        self.assertTrue(self.frozen(f"{F}:10"))

    def test_insert_above_decorator_is_inside(self):
        self.edit("    # b の説明\n", "    @unittest.expectedFailure\n    # b の説明\n")
        self.assertEqual(self.frozen(f"{F}:10"), [])

    def test_previous_trailing_comment_is_not_absorbed(self):
        (self.repo / F).write_text("class T:\n    def a(self):\n        pass\n        # a の末尾\n    def b(self):\n        pass\n",
                                   encoding="utf-8")
        st = json.loads(self.state.read_text())
        st["frozen_tree"] = tddloop.snapshot(self.repo)
        st["frozen"] = tddloop.hashes(self.repo, [F, N])
        self.state.write_text(json.dumps(st), encoding="utf-8")
        self.edit("# a の末尾", "# a の末尾を直した")
        self.assertTrue(self.frozen(f"{F}:6"))

    def test_explicit_range_is_not_widened(self):
        self.edit("def test_b", "def test_bb")
        self.assertTrue(self.frozen(f"{F}:12-12"))
        self.assertEqual(self.frozen(f"{F}:8-12"), [])

    def test_non_python_stays_one_line(self):
        self.edit("b", "B", N)
        self.assertTrue(self.frozen(f"{N}:1"))
        self.assertEqual(self.frozen(f"{N}:2"), [])

    def test_unparsable_old_text_stays_one_line(self):
        (self.repo / F).write_text("def f(:\n  x\n", encoding="utf-8")
        st = json.loads(self.state.read_text())
        st["frozen_tree"] = tddloop.snapshot(self.repo)
        st["frozen"] = tddloop.hashes(self.repo, [F, N])
        self.state.write_text(json.dumps(st), encoding="utf-8")
        self.edit("  x", "  y")
        self.assertTrue(self.frozen(f"{F}:1"))


if __name__ == "__main__":
    unittest.main()
