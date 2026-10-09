"""考えの住処の柵を、対象のリポジトリの変更に当てる口（.shared/core/conceptfence.py の tables・places・scan_change。
計画 2026-10-09-clean-whole の Task 2.2）。種の git は gitkit の型の写し（試験ごとに作らない）"""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))
import conceptfence as cf  # noqa: E402
import gitkit  # noqa: E402

TABLE = {"about": "種", "exclude": ["tests/**"], "concepts": {
    "word": {"status": "住処あり", "fences": [{"what": "語", "pattern": r"\bWORD\b", "allowed": ["home.py"],
                                              "known": {"old.py": [1, "前からの漏れ"]}}]},
    "loose": {"status": "散らばり", "fences": []}}}
_SEED = None


def seed() -> pathlib.Path:
    """種: 根に関係の無い a.txt、sub/ の下に柵の表と住処と既知の漏れ（表の中のパスは sub からの相対）"""
    global _SEED
    if _SEED is None:
        home = pathlib.Path(tempfile.mkdtemp(prefix="works-concept-change-"))
        files = {"a.txt": "WORD\n", "sub/docs/concepts.json": json.dumps(TABLE), "sub/home.py": "WORD = 1\n",
                 "sub/old.py": "x = WORD\n", "sub/mid.py": "y = 1\n", "sub/tests/t.py": "WORD\n"}
        for rel, text in files.items():
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            (home / rel).write_text(text, encoding="utf-8")
        _SEED = home
    return _SEED


def tearDownModule():
    if _SEED is not None:
        shutil.rmtree(_SEED, ignore_errors=True)


class ChangeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "r"
        self.base = gitkit.committed_copy(self.repo, seed())

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        (self.repo / rel).write_text(text, encoding="utf-8")

    def test_tables_found_nested(self):
        got, why = cf.tables(self.repo)
        self.assertEqual(why, [])
        self.assertEqual([b for b, _ in got], ["sub"])
        self.assertIn("word", got[0][1]["concepts"])

    def test_scan_change_reports_only_increase(self):
        """住処の外に語を 1 行足すと 1 件、消すと 0 件。住処の中と除く所は数えない"""
        table = cf.tables(self.repo)[0][0][1]
        self.put("sub/mid.py", "y = 1\nz = WORD\n")
        self.put("sub/home.py", "WORD = 1\nWORD2 = WORD\n")
        self.put("sub/tests/t.py", "WORD\nWORD\n")
        got = cf.scan_change(self.repo, self.base, table, "sub")
        self.assertEqual(got, [{"concept": "word", "what": "語", "path": "sub/mid.py", "before": 0, "after": 1}])
        self.put("sub/mid.py", "y = 1\n")
        self.put("sub/old.py", "x = 1\n")   # 既知の漏れが減っただけは増えに数えない
        self.assertEqual(cf.scan_change(self.repo, self.base, table, "sub"), [])

    def test_scan_change_counts_new_file_outside_base_not(self):
        table = cf.tables(self.repo)[0][0][1]
        self.put("sub/new.py", "WORD\n")
        self.put("a.txt", "WORD\nWORD\n")   # 表の持ち主のフォルダの外は見ない
        got = cf.scan_change(self.repo, self.base, table, "sub")
        self.assertEqual([(g["path"], g["before"], g["after"]) for g in got], [("sub/new.py", 0, 1)])

    def test_places_for_unit_paths(self):
        """単位のファイルに当たる柵ごとに、そのファイルの行の数・住処か・考えを知る場所の数（住処を含む全部）"""
        table = cf.tables(self.repo)[0][0][1]
        got = cf.places(self.repo, "sub", table, ["sub/old.py", "sub/mid.py", "a.txt"])
        self.assertEqual(got, [{"concept": "word", "what": "語", "path": "sub/old.py", "lines": 1, "home": False,
                                "known_places": 2}])

    def test_no_table_gives_nothing(self):
        shutil.rmtree(self.repo / "sub" / "docs")
        gitkit.git(self.repo, "add", "-A")
        gitkit.git(self.repo, "commit", "-q", "-m", "drop")
        self.assertEqual(cf.tables(self.repo), ([], []))


if __name__ == "__main__":
    unittest.main()
