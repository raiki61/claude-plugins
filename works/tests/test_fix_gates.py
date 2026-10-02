"""事後の関門の束（blk-fix/lib/fixgates.py。計画 220 Task 4）の検査。

束は修正の受け付け（節 fix-accept・fix-ruled-accept）の最後の段で、修正の形に依らず base（修正前の版）から今の木までを相手に
- red_green: 承認済みの修正案の tdd の項目の受け入れのテストが、今の木で緑・base で案の種類の赤か
- test_edits: base に在った既存のテストの関数の本体を、名指し（修正案の rewrite_tests・裁定 fix_test_scope の範囲）の外で変えていないか
を確かめる。盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作り、実行器は test_blk_fix_tdd の PYTEST_LIKE
（赤の種類を message に書く）。種の stats.mean は len-1 で割る誤りを持つ。
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import test_blk_fix as tbf  # noqa: E402
import test_blk_fix_tdd as tbt  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import fixgates  # noqa: E402
import fixshape  # noqa: E402
import planmarks  # noqa: E402

MEAN_ID = "test_stats.py::TestStats::test_mean_of_two"
THREE_ID = "test_stats.py::TestStats::test_mean_of_three"
TEST_ROW = {"id": MEAN_ID, "behavior": "2 つの値の平均", "path": "stats.mean を直に呼ぶ", "red_kind": "assertion",
            "red_why": "今は len-1 で割る"}
# 欄の形は test_plan_brief.FIELDS と同じ（unit_keys は修正案の項目の名指し。planmarks.split が欄に写す）
FIELDS = [{"unit_keys": [tbf.MEAN], "route": "tdd", "route_why": "", "tests": [TEST_ROW], "rewrite_tests": [],
           "refactor": {"declared": False, "why": ""}}]
MEAN_FIX = {"return sum(xs) / (len(xs) - 1)": "return sum(xs) / len(xs)"}
THREE_EDIT = ("self.assertEqual(mean([1, 2, 3]), 2)", "self.assertEqual(mean([1, 2, 3]), 2.0)")   # 既存のテストの期待の書き換え
REWRITE = {"id": THREE_ID, "behavior": "3 つの値の平均の期待", "old": "期待は 2", "new": "期待を 2.0 に書き換える",
           "limit": "test_stats.py:8"}


def direct_fields(**over):
    """受け入れのテストの無い direct の項目（red_green を回さず test_edits だけを見る）"""
    return [{**FIELDS[0], "route": "direct", "route_why": "既存の期待の書き換えだけの項目", "tests": [], **over}]


class FixGatesCase(tbf.BoardCase):
    def setUp(self):
        super().setUp()
        self.suite = self.tmp / "suite.py"
        self.suite.write_text(tbt.PYTEST_LIKE, encoding="utf-8")
        self.SUITE = str(self.suite)

    def ready_with_fields(self, fields=None):
        """p3.fix が待つ盤面に、承認済みの修正案の欄の控え（凍結の印つき）を置く。base は種の commit"""
        self.fix_ready()
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, FIELDS if fields is None else fields)
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True,
                                   check=True).stdout.strip()
        return entry.open_board(self.board)

    def edit_tests(self, old, new):
        path = self.repo / "test_stats.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def add_test(self, body):
        self.edit_tests("\n\nif __name__", body + "\n\nif __name__")

    def add_test_mean_of_two(self):
        self.add_test(tbt.NEW_TEST)

    def add_test_that_passes_on_base(self, name):
        self.add_test(f"\n    def {name}(self):\n        self.assertEqual(clamp(5, 0, 10), 5)\n")

    def problems(self, suite=None, attempt=1, **kw):
        return fixgates.problems(self.board, self.repo, self.base, self.SUITE if suite is None else suite, attempt, **kw)

    def ledger(self):
        return json.loads(entry.open_board(self.board).work(fixgates.LEDGER).read_text(encoding="utf-8"))

    def worktrees(self):
        out = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, check=True).stdout
        return out.strip().splitlines()


class TestRedGreen(FixGatesCase):
    def test_real_red_green_passes(self):
        self.ready_with_fields()                  # 項目 1: tdd・tests=[test_mean_of_two（red_kind assertion）]
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        self.assertEqual(self.problems(), [])
        self.assertFalse(entry.open_board(self.board).work(fixgates.LEDGER).exists(), "積む物が無ければ帳面を書かない")

    def test_test_green_at_base_is_a_miss(self):
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertIn("base で緑", rows[0]["detail"])

    def test_wrong_red_kind_is_a_miss(self):
        """新しいテストが base で NameError（機能が無い）——案は assertion。今の木では緑"""
        self.ready_with_fields()
        self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
        self.edit_tree({"def clamp(x, lo, hi):": "def halve(x):\n    return x / 2\n\n\ndef clamp(x, lo, hi):"})
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        for w in ("base で", "NameError", "assertion"):
            self.assertIn(w, rows[0]["detail"])

    def test_not_green_now_is_a_miss(self):
        """受け入れのテストが base で正しく赤でも、今の木で緑でなければ行（直していない）"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertIn("今の木で failure", rows[0]["detail"])

    def test_no_suite_skips_and_records(self):
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual([r for r in self.problems(suite="") if r["gate"] == "red_green"], [])
        self.assertEqual(self.ledger()["skipped"][0]["why"], fixgates.NO_SUITE)

    def test_plain_run_ignores_plan_fields(self):
        """平の run（修正の形 current）は修正案の欄を見ない: base で緑のテストでも red_green の行が無い"""
        self.ready_with_fields()
        fixshape.choose(self.board, "current", by="試験", why="平の run の束を見る")
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual(self.problems(), [])

    def test_unit_out_of_duty_is_not_checked(self):
        """最後の回に止めた（ask_human に裁いた）単位だけを名指す項目は見ない（戻したテストを抜けに数えない）"""
        b = self.ready_with_fields()
        conflict.park(b, [{"unit_key": tbf.MEAN, "between": [], "why_both_cannot_hold": "試験で止めた単位",
                           "which_is_right": "unknown"}], source="fix",
                      ruling={"decision": conflict.ASK, "text": "試験で止めた", "limits": [], "by": "works:fix-accept"})
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual(self.problems(), [])

    def test_worktree_removed_after(self):
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.problems()
        self.assertEqual(len(self.worktrees()), 1, self.worktrees())

    def test_worktree_removed_when_base_run_breaks(self):
        """base の木で実行器を走らせる所が落ちても、一時の worktree は消す"""
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        real = fixgates.tddloop.run_suite

        def broken(exe, repo, *a, **k):
            if pathlib.Path(repo).resolve() != self.repo.resolve():
                raise RuntimeError("base の木で落ちた")
            return real(exe, repo, *a, **k)
        with mock.patch.object(fixgates.tddloop, "run_suite", side_effect=broken):
            with self.assertRaises(RuntimeError):
                self.problems()
        self.assertEqual(len(self.worktrees()), 1, self.worktrees())

    def test_suite_leftovers_are_removed_from_tree(self):
        """今の木で一式を走らせて出来たファイルは消す（書き込みの出どころの突き合わせに載せない）"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        self.suite.write_text(tbt.PYTEST_LIKE.replace("out = sys.argv[1]", "out = sys.argv[1]\nopen('made.txt', 'w').close()"),
                              encoding="utf-8")
        self.assertEqual(self.problems(), [])
        self.assertFalse((self.repo / "made.txt").exists())


class TestTestEdits(FixGatesCase):
    def test_unnamed_existing_edit_is_a_miss(self):
        self.ready_with_fields(direct_fields())
        self.edit_tests(*THREE_EDIT)
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("test_edits", THREE_ID)])

    def test_named_rewrite_and_ruled_limit_pass(self):
        with self.subTest("修正案の rewrite_tests の名指し"):
            self.ready_with_fields(direct_fields(rewrite_tests=[REWRITE]))
            self.edit_tests(*THREE_EDIT)
            self.assertEqual(self.problems(), [])
        with self.subTest("平の run では修正案の名指しを許しにしない"):
            fixshape.choose(self.board, "current", by="試験", why="平の run の束を見る")
            self.assertEqual([(r["gate"], r["id"]) for r in self.problems()], [("test_edits", THREE_ID)])

    def test_ruled_limit_passes_after_ruling(self):
        """裁定 fix_test_scope の範囲 test_stats.py:9（test_mean_of_three の本体の行）を含む関数は通す。1 回目（裁定の前）は通さない"""
        b = self.ready_with_fields(direct_fields())
        b.work(conflict.FILE).write_text(json.dumps({"items": [
            {"id": "c1-1", "unit_key": tbf.MEAN, "between": ["stats.py:9", "test_stats.py:9"],
             "why_both_cannot_hold": "期待の型が依頼と食い違う", "which_is_right": "test", "status": "ruled",
             "ruling": {"decision": "fix_test_scope", "text": "期待を float で書いてよい", "limits": ["test_stats.py:9"]}}]},
            ensure_ascii=False), encoding="utf-8")
        self.edit_tests(*THREE_EDIT)
        self.assertEqual(self.problems(pass_="ruled"), [])
        self.assertEqual([(r["gate"], r["id"]) for r in self.problems(pass_="first")], [("test_edits", THREE_ID)])


class TestLedgerAndText(FixGatesCase):
    def test_ledger_marks_the_attempt_and_does_not_repeat_rows(self):
        """帳面の行は受け付けの回の印（pass・attempt）を持つ。最後の回の通し直しで同じ回に 2 度走っても行は 1 度だけ（preflight F23）"""
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.edit_tests(*THREE_EDIT)
        first = self.problems(attempt=3)
        again = self.problems(attempt=3)
        self.assertEqual(first, again)
        self.assertEqual(sorted(r["gate"] for r in first), ["red_green", "test_edits"], "どちらの関門の行も返す")
        rows = self.ledger()["rows"]
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual({(r["pass"], r["attempt"], r["shape"]) for r in rows}, {("first", 3, fixshape.DEFAULT)})
        self.assertEqual(set(rows[0]), {"pass", "attempt", "shape", "gate", "id", "detail"})
        self.problems(attempt=1, pass_="ruled")
        self.assertEqual(len(self.ledger()["rows"]), 4, "裁定の後の 1 回目は別の回")

    def test_reject_text_lists_every_row(self):
        rows = [{"gate": "red_green", "id": MEAN_ID, "detail": "base で緑"},
                {"gate": "test_edits", "id": THREE_ID, "detail": "名指しの外"}]
        text = fixgates.reject_text(rows)
        self.assertTrue(text.startswith(fixgates.REJECT), text)
        for w in (f"red_green {MEAN_ID}: base で緑", f"test_edits {THREE_ID}: 名指しの外", "全部"):
            self.assertIn(w, text)
        self.assertEqual(fixgates.GATES, ("red_green", "test_edits"))


class TestAcceptWiring(FixGatesCase):
    """blk-fix の受け付け（scripts/accept.py）の最後の段に束が在る: ほかの確かめが全部通った後・数え直し（盤面の done）の前"""

    def accept_mod(self):
        spec = importlib.util.spec_from_file_location("blk_fix_accept_for_gates", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def env(self, iteration="1"):
        return mock.patch.dict(os.environ, {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "", "INPUTS_PASS": "first",
                                            "INPUTS_TDD_SUITE": self.SUITE})

    def test_accept_rejects_with_battery_last(self):
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        rows = [{"gate": "red_green", "id": MEAN_ID, "detail": "base で緑"}]
        with self.env(), mock.patch.object(mod.fixgates, "problems", return_value=rows) as gates, \
                mock.patch.object(mod.recount, "accept_fix", wraps=mod.recount.accept_fix) as recount:
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], False, got)
        self.assertTrue(got["reason"].startswith(fixgates.REJECT), got["reason"])
        gates.assert_called_once_with(self.board, self.repo, "", self.SUITE, 1, pass_="first")
        recount.assert_not_called()   # 盤面に done("p3.fix") を書く前に拒む（preflight F12）
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_other_reject_does_not_run_battery(self):
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        reply = tbf.load("fix2_ok")
        reply["changes"].append(reply["changes"][0])   # 同じ unit_key を 2 行に（works だけの検査が拒む）
        mod = self.accept_mod()
        with self.env(), mock.patch.object(mod.fixgates, "problems", return_value=[]) as gates:
            got = mod.accept_fix(reply, self.board, "", self.repo)
        self.assertIs(got["ok"], False, got)
        gates.assert_not_called()

    def test_clean_battery_lets_fix_through(self):
        """束が何も見つけなければ今までどおり受ける（修正案の欄の無い run・既存のテストを変えない直し）"""
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        with self.env():
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], True, got)


if __name__ == "__main__":
    unittest.main()
