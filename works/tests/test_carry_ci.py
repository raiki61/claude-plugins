"""run の後の CI の赤を次の run の依頼の prior_failures へ載せる口（.shared/core/ghreads.py の carry_ci と carry-ci）の検査。

重い試験は run の外の CI で回るので、run が見ない赤が在る。前の run の報告が書いた next-request.json に、CI が赤と言った
試験の id を prior_failures の行として足し、次の run の判定役と修正案の役へ届ける（計画 docs/plans/2026-10-06-carry-prior-failures.md の
「run の後の CI の赤」）。関数を直に呼ぶのと、ghreads.py を python3 -I で 1 本起こすだけ（git・盤面なし）。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
CORE = TESTS.parent / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import ghreads  # noqa: E402

TID = "tests/test_report.py::HeadCase::test_rows"
TID2 = "works.tests.test_edge.EdgeCase.test_fix"


class CarryCase(unittest.TestCase):
    def test_ids_become_prior_failures_rows(self):
        doc = {"findings": [{"where": "a.py:1", "text": "穴"}], "prior_failures": [{"where": "受け付け fix", "text": "前の理由"}]}
        got = ghreads.carry_ci(doc, [TID, TID2])
        self.assertEqual(got["findings"], doc["findings"])
        rows = got["prior_failures"]
        self.assertEqual(rows[0], {"where": "受け付け fix", "text": "前の理由"})
        self.assertEqual([r["where"] for r in rows[1:]], [ghreads.CI_WHERE] * 2)
        self.assertIn(TID, rows[1]["text"])
        self.assertIn(TID2, rows[2]["text"])
        self.assertEqual(ghreads.request_parts(got)["prior_failures"], rows)   # 依頼の型のまま

    def test_draft_findings_are_kept_as_they_are(self):
        """前の run の報告が下書きの印つきで運んだ目的の外の所見（findings の draft・source の行）でも止まらず、そのまま残す
        （下書きは次の run の入口が拒む。審査の再現: carry-ci が exit 2 だった）"""
        draft = {"where": "a.py:1", "text": "目的の外", "draft": True, "source": "前の run の判定が目的の外とした所見（x）"}
        doc = {"findings": [{"where": "b.py:2", "text": "穴"}, draft], "prior_failures": []}
        got = ghreads.carry_ci(doc, [TID])
        self.assertEqual(got["findings"], doc["findings"])
        self.assertEqual(len(got["prior_failures"]), 1)
        self.assertEqual(ghreads.carry_ci([draft], [TID])["findings"], [draft])

    def test_same_id_twice_or_already_carried_is_one_row(self):
        once = ghreads.carry_ci({"findings": [], "prior_failures": []}, [TID, TID, f"  {TID}  ", ""])
        self.assertEqual(len(once["prior_failures"]), 1)
        again = ghreads.carry_ci(once, [TID])
        self.assertEqual(again["prior_failures"], once["prior_failures"])

    def test_array_form_and_other_keys_are_kept(self):
        got = ghreads.carry_ci([{"where": "a.py:1", "text": "穴"}], [TID])
        self.assertEqual(got["findings"], [{"where": "a.py:1", "text": "穴"}])
        self.assertEqual(len(got["prior_failures"]), 1)
        kept = ghreads.carry_ci({"findings": [], "pr": [3], "answers": [{"question": "q", "text": "a"}]}, [TID])
        self.assertEqual(kept["pr"], [3])
        self.assertEqual(kept["answers"], [{"question": "q", "text": "a"}])

    def test_refuses_no_ids_and_broken_request(self):
        with self.assertRaises(ValueError):
            ghreads.carry_ci({"findings": []}, ["", "  "])
        with self.assertRaises(ValueError):
            ghreads.carry_ci({"findings": [], "prior_failures": [{"where": "x"}]}, [TID])


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def run_cli(self, *args, stdin=""):
        return subprocess.run([sys.executable, "-I", str(CORE / "ghreads.py"), "carry-ci", *args],
                              input=stdin, capture_output=True, text=True, encoding="utf-8")

    def test_reads_ids_file_and_writes_out(self):
        req = self.tmp / "next-request.json"
        req.write_text(json.dumps({"findings": [], "prior_failures": []}), encoding="utf-8")
        ids = self.tmp / "failed.txt"
        ids.write_text(f"# CI の赤\n{TID}\n\n{TID2}\n", encoding="utf-8")
        out = self.tmp / "req.json"
        got = self.run_cli("--request", str(req), "--failed", str(ids), "--out", str(out))
        self.assertEqual(got.returncode, 0, got.stderr)
        rows = json.loads(out.read_text(encoding="utf-8"))["prior_failures"]
        self.assertEqual(len(rows), 2)

    def test_stdin_ids_and_refusal_exit_2(self):
        req = self.tmp / "next-request.json"
        req.write_text(json.dumps({"findings": []}), encoding="utf-8")
        got = self.run_cli("--request", str(req), "--failed", "-", "--out", str(req), stdin=f"{TID}\n")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(len(json.loads(req.read_text(encoding="utf-8"))["prior_failures"]), 1)
        bad = self.run_cli("--request", str(req), "--failed", "-", "--out", str(self.tmp / "x.json"), stdin="\n")
        self.assertEqual(bad.returncode, 2)
        self.assertFalse((self.tmp / "x.json").exists())
        self.assertEqual(len(bad.stderr.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
