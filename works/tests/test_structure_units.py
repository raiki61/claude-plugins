"""h-plan が判定の単位を blk-structure の入力の契約に写す時のパスの選び方（line_edge._unit_file_paths）の決定的な試験。
盤面を作らない（写しの全体と h-plan の出口は test_edge の test_plan_hands_structure_units が見る）"""
import pathlib
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import line_edge  # noqa: E402


def unit(paths=None, key="src/a.py mean: 分母が違う"):
    u = {"key": key, "reason": "r"}
    if paths is not None:
        u["class_query"] = {"how": {"patterns": ["x"], "paths": paths}}
    return u


class UnitFilePathsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.repo / "b.py").write_text("y = 2\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_keeps_files_under_root_in_order_without_duplicates(self):
        got = line_edge._unit_file_paths(unit(["b.py", "./src/a.py", "src/a.py"]), self.repo)
        self.assertEqual(got, (["b.py", "src/a.py"], []))

    def test_drops_paths_measure_cannot_read(self):
        """measure.py は根の中のファイルしか測らない。ディレクトリ・glob・pathspec の魔法・絶対パス・根の外・無いファイルは捨てて返す"""
        bad = ["src", "*.py", ":(glob)src/*.py", str(self.repo / "b.py"), "../b.py", "src/../b.py", "gone.py"]
        self.assertEqual(line_edge._unit_file_paths(unit(["b.py", *bad]), self.repo), (["b.py"], bad))

    def test_falls_back_to_key_head_only_without_how_paths(self):
        self.assertEqual(line_edge._unit_file_paths(unit(), self.repo), (["src/a.py"], []))
        self.assertEqual(line_edge._unit_file_paths(unit(["b.py"]), self.repo), (["b.py"], []))
        self.assertEqual(line_edge._unit_file_paths(unit(key="上限を呼び手ごとに持つ"), self.repo), ([], ["上限を呼び手ごとに持つ"]))


if __name__ == "__main__":
    unittest.main()
