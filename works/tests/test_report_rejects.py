"""run をまたいで報告の拒否の数を集計する口（dev/report_rejects.py）の検査。

盤面の置き場の根の下の board/r*/ を探し、run（board の親のディレクトリ名）ごとに 1 行、拒否の回数・種類ごとの回数
（cold・format・answer・不明）・上限の受け取りの件数を出す。数えは blk-report/lib/report_roles の数え方を使う。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "dev" / "report_rejects.py"
REJECTS_NAME = "report-rejects.json"
COLD_MARK_NAME = "report-cold-unpassed.json"


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


class ReportRejectsCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._td.name)
        # run-a: kind が入る前の行 2 行・kind の在る行 2 行（周をまたぐ）・上限の受け取り 1 件
        a = self.root / "runs" / "run-a" / "board"
        _write(a / "r1" / REJECTS_NAME, [{"node": "report", "reason": "古い行"}, {"node": "report", "reason": "古い行"}])
        _write(a / "r2" / REJECTS_NAME, [{"node": "report", "kind": "cold"}, {"node": "report.human_items", "kind": "format"}])
        _write(a / "r2" / COLD_MARK_NAME, {"reason": "冒頭で止まった"})
        # run-b: 拒否の無い run
        (self.root / "runs" / "run-b" / "board" / "r1").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def run_tool(self):
        return subprocess.run([sys.executable, str(TOOL), str(self.root)], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)

    def line_of(self, out, run):
        got = [ln for ln in out.splitlines() if ln.split("\t")[0] == run]
        self.assertEqual(len(got), 1, f"run {run} の行がちょうど 1 行ではない:\n{out}")
        return got[0].split("\t")

    def test_counts_per_run_with_unknown_and_cold_unpassed(self):
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stderr)
        a = self.line_of(r.stdout, "run-a")
        self.assertIn("拒否 4", a)
        self.assertIn("cold 1", a)
        self.assertIn("format 1", a)
        self.assertIn("answer 0", a)
        self.assertIn("不明 2", a, "kind の無い行は捨てずに不明として数える")
        self.assertIn("上限の受け取り 1", a)
        b = self.line_of(r.stdout, "run-b")
        self.assertIn("拒否 0", b)
        self.assertIn("上限の受け取り 0", b)

    def test_output_is_deterministic_and_writes_nothing(self):
        before = sorted(p.relative_to(self.root) for p in self.root.rglob("*"))
        first, second = self.run_tool(), self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        runs = [ln.split("\t")[0] for ln in first.stdout.splitlines() if ln.startswith("run-")]
        self.assertEqual(runs, ["run-a", "run-b"], "run の並びはパスの順")
        self.assertEqual(sorted(p.relative_to(self.root) for p in self.root.rglob("*")), before, "何も書かない")

    def test_unreadable_json_is_named_not_zero(self):
        _write(self.root / "runs" / "run-c" / "board" / "r1" / REJECTS_NAME, "{JSON でない")
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.line_of(r.stdout, "run-c")
        self.assertTrue(any("読めない" in cell for cell in c), f"読めない JSON を名指ししない: {c}")
        self.line_of(r.stdout, "run-a")


if __name__ == "__main__":
    unittest.main()
