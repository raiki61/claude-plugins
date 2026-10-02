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
import report  # noqa: E402

MEAN_ID = "test_stats.py::TestStats::test_mean_of_two"
THREE_ID = "test_stats.py::TestStats::test_mean_of_three"
TEST_ROW = {"id": MEAN_ID, "behavior": "2 つの値の平均", "path": "stats.mean を直に呼ぶ", "red_kind": "assertion",
            "red_why": "今は len-1 で割る"}
# 欄の形は test_plan_brief.FIELDS と同じ（unit_keys は修正案の項目の名指し。planmarks.split が欄に写す）
FIELDS = [{"unit_keys": [tbf.MEAN], "route": "tdd", "route_why": "", "tests": [TEST_ROW], "rewrite_tests": [],
           "refactor": {"declared": False, "why": ""}}]
MEAN_FIX = {"return sum(xs) / (len(xs) - 1)": "return sum(xs) / len(xs)"}
THREE_EDIT = ("self.assertEqual(mean([1, 2, 3]), 2)", "self.assertEqual(mean([1, 2, 3]), 2.0)")   # 既存のテストの期待の書き換え
HALVE = {"def clamp(x, lo, hi):": "def halve(x):\n    return x / 2\n\n\ndef clamp(x, lo, hi):"}   # 今の木で足す関数
TWO_ID = "test_two.py::TestTwo::test_halve"
TWO_FILE = ("import unittest\n\nfrom stats import halve\n\n\nclass TestTwo(unittest.TestCase):\n    def test_halve(self):\n"
            "        self.assertEqual(halve(4), 2)\n")   # base では読み込みで落ちる（halve が無い）新しいテストのファイル
NO_JUNIT = "import sys\nsys.exit(0)\n"   # JUnit を書かない実行器
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
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
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

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()

    def fields_for(self, test_id):
        """受け入れのテスト test_id を 1 本持つ tdd の項目（単位は mean）"""
        return [{**FIELDS[0], "tests": [{**TEST_ROW, "id": test_id}]}]

    def problems(self, suite=None, attempt=1, **kw):
        return fixgates.problems(self.board, self.repo, self.base, self.SUITE if suite is None else suite, attempt, **kw)

    def ledger(self):
        return json.loads(entry.open_board(self.board).work(fixgates.LEDGER).read_text(encoding="utf-8"))

    def worktrees(self):
        out = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout
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
        self.assertEqual(rows[0]["unit_keys"], [tbf.MEAN], "行は項目の単位を持つ（最後の回に unit_key で単位に結ぶ）")

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

    def test_declared_name_error_is_the_wanted_red(self):
        """base の NameError の無い名前が、項目の adds に宣言した名前なら『機能が無い』赤（輪の _kind_problems と同じ決まり。225）"""
        self.ready_with_fields([{**FIELDS[0], "adds": ["halve"]}])
        self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
        self.edit_tree(HALVE)
        self.assertEqual(self.problems(), [])

    def test_not_green_now_is_a_miss(self):
        """受け入れのテストが base で正しく赤でも、今の木で緑でなければ行（直していない）"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertIn("今の木で failure", rows[0]["detail"])

    def test_base_missing_and_non_failure_are_misses(self):
        with self.subTest("base で一式の結末に居ない（読み込みで落ちる）"):
            self.ready_with_fields(self.fields_for(TWO_ID))
            (self.repo / "test_two.py").write_text(TWO_FILE, encoding="utf-8")
            self.edit_tree(HALVE)
            rows = self.problems()
            self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", TWO_ID)])
            self.assertIn("base で一式の結末に居ない", rows[0]["detail"])
        with self.subTest("base で error（failure でない赤）"):
            self.suite.write_text(tbt.SUITE, encoding="utf-8")   # 本体の例外を error と書く実行器
            (self.repo / "test_two.py").unlink()
            self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
            self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
            planmarks.save(self.board, entry.open_board(self.board).round, FIELDS)
            rows = self.problems(attempt=2)
            self.assertEqual([(r["gate"], r["id"], r["detail"].split("（")[0]) for r in rows],
                             [("red_green", MEAN_ID, "base で error")])

    def test_runner_inside_repo_runs_its_base_copy(self):
        """実行器が対象のリポジトリの中に在れば、base の木では worktree の中の base の版を走らせる"""
        self.ready_with_fields()
        runner = self.repo / "runner.py"
        runner.write_text(tbt.PYTEST_LIKE, encoding="utf-8")
        self.git("add", "runner.py")
        self.git("commit", "-q", "-m", "runner")
        head = self.git("rev-parse", "HEAD")
        # 今の木の実行器は、印のファイルが無い置き場（base の worktree）では受け入れのテストを緑と書く（base の版を走らせない誤りを露わにする）
        runner.write_text("import os, sys\nif not os.path.exists('now-only.txt'):\n    open(sys.argv[1], 'w').write("
                          "'<testsuite><testcase classname=\"test_stats.TestStats\" name=\"test_mean_of_two\"/></testsuite>')\n"
                          "    sys.exit(0)\n" + tbt.PYTEST_LIKE, encoding="utf-8")
        (self.repo / "now-only.txt").write_text("", encoding="utf-8")
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        with mock.patch.object(fixgates.writes, "base_rev", return_value=head):
            self.assertEqual(self.problems(suite=str(runner)), [])

    def test_runner_without_junit_skips_and_records(self):
        """今の木で実行器が JUnit を書かない → 拒まず、帳面の skipped に理由（受けた回は trace にも載る。TestAcceptWiring）"""
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.suite.write_text(NO_JUNIT, encoding="utf-8")
        self.assertEqual(self.problems(), [])
        why = fixgates.skipped(self.board, pass_="first", attempt=1)
        self.assertEqual(len(why), 1, why)
        self.assertTrue(why[0].startswith(fixgates.NO_RUN), why)
        self.assertIn("今の木", why[0])

    def test_base_tree_that_cannot_be_made_skips_and_records(self):
        """base の版から worktree を作れない（commit でない版）→ 拒まず、帳面の skipped に理由。worktree は残さない"""
        b = self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        tree = self.git("rev-parse", f"{b.state['inputs']['review_rev']}^{{tree}}")
        with mock.patch.object(fixgates.writes, "base_rev", return_value=tree):
            self.assertEqual(self.problems(), [])
        why = fixgates.skipped(self.board, pass_="first", attempt=1)
        self.assertEqual(len(why), 1, why)
        self.assertTrue(why[0].startswith(fixgates.NO_RUN), why)
        self.assertIn("base の木", why[0])
        self.assertEqual(len(self.worktrees()), 1, self.worktrees())

    def test_no_suite_skips_and_records(self):
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual([r for r in self.problems(suite="") if r["gate"] == "red_green"], [])
        self.assertEqual(self.ledger()["skipped"][0]["why"], fixgates.NO_SUITE)

    def test_g1_board_gets_both_gates(self):
        """修正の形 g1（TDD の輪を回さない。受け付けに輪の凍結の控えが無い）: 束が赤緑と既存テストの変更の両方を当てる
        （輪の凍結の検査 1b は控えの無い run で何も見ないので、g1 の凍結はこの束だけが受け持つ。Preflight F13）"""
        self.ready_with_fields()
        fixshape.choose(self.board, "g1", by="試験", why="g1 の束を見る")
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.edit_tests(*THREE_EDIT)
        rows = self.problems()
        self.assertEqual(sorted((r["gate"], r["id"]) for r in rows), [("red_green", MEAN_ID), ("test_edits", THREE_ID)])
        self.assertEqual({r["shape"] for r in self.ledger()["rows"]}, {"g1"})

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
        why = fixgates.skipped(self.board, pass_="first", attempt=1)
        self.assertEqual(len(why), 1, why)
        for w in (fixgates.OUT_OF_DUTY, "項目 1", tbf.MEAN):   # 見なかった項目と単位を名指して残す
            self.assertIn(w, why[0])
        self.assertEqual(fixgates.unchecked(self.board, pass_="first", attempt=1), [], "義務の外の項目は確かめずに通したに数えない")

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

    def rule(self, limits):
        entry.open_board(self.board).work(conflict.FILE).write_text(json.dumps({"items": [
            {"id": "c1-1", "unit_key": tbf.MEAN, "between": ["stats.py:9", "test_stats.py:9"],
             "why_both_cannot_hold": "期待の型が依頼と食い違う", "which_is_right": "test", "status": "ruled",
             "ruling": {"decision": "fix_test_scope", "text": "期待を float で書いてよい", "limits": limits}}]},
            ensure_ascii=False), encoding="utf-8")

    def test_ruled_scope_reads_like_the_frozen_check(self):
        """範囲の読みは輪の凍結の検査と同じ: ファイルだけは全部・1 行の指しは関数の全体・`<行>-<行>` は書いたとおり"""
        self.ready_with_fields(direct_fields())
        self.edit_tests(*THREE_EDIT)   # test_mean_of_three の本体の 9 行目
        for limits, ok in ((["test_stats.py"], True), (["test_stats.py:8"], True), (["test_stats.py:9-9"], True),
                           (["test_stats.py:8-8"], False), (["test_stats.py:11-12"], False)):
            with self.subTest(limits):
                self.rule(limits)
                got = [(r["gate"], r["id"]) for r in self.problems(pass_="ruled")]
                self.assertEqual(got, [] if ok else [("test_edits", THREE_ID)])


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
        self.assertEqual(set(rows[0]), {"pass", "attempt", "shape", "gate", "id", "detail", "unit_keys"})
        self.problems(attempt=1, pass_="ruled")
        self.assertEqual(len(self.ledger()["rows"]), 4, "裁定の後の 1 回目は別の回")

    def test_reject_text_lists_every_row(self):
        rows = [{"gate": "red_green", "id": MEAN_ID, "detail": "base で緑", "unit_keys": [tbf.MEAN]},
                {"gate": "test_edits", "id": THREE_ID, "detail": "名指しの外", "unit_keys": []}]
        lines = fixgates.reject_lines(rows)
        self.assertEqual(len(lines), 2, "行ごとに 1 つの文（最後の回に文ごとに単位に結ぶ）")
        self.assertTrue(all(t.startswith(fixgates.REJECT) for t in lines), lines)
        self.assertIn(tbf.MEAN, lines[0], "red_green の文は項目の単位を名指す")
        self.assertTrue(lines[-1].endswith(fixgates.REDO) and fixgates.REDO not in lines[0], "出し直しの頼みは最後の文の末だけ")
        text = fixgates.reject_text(rows)
        self.assertEqual(text, " / ".join(lines))
        for w in (f"red_green {MEAN_ID}: base で緑", f"test_edits {THREE_ID}: 名指しの外", "全部"):
            self.assertIn(w, text)
        self.assertEqual(fixgates.GATES, ("red_green", "test_edits"))

    def test_report_counts_unchecked_acceptances(self):
        class B:
            dir = self.tmp
        self.assertEqual(report.gates_lines(B), [])
        rows = [{"op": fixgates.SKIPPED_OP, "node": "fix", "why": [fixgates.NO_SUITE]},
                {"op": fixgates.SKIPPED_OP, "node": "fix", "why": [fixgates.NO_SUITE]}]
        (self.tmp / "trace.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        lines = report.gates_lines(B)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("受け付け 2 回", lines[0])
        self.assertEqual(lines[0].count(fixgates.NO_SUITE), 1, "同じ理由は 1 度")


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
        rows = [{"gate": "red_green", "id": MEAN_ID, "detail": "base で緑", "unit_keys": [tbf.MEAN]}]
        with self.env(), mock.patch.object(mod.fixgates, "problems", return_value=rows) as gates, \
                mock.patch.object(mod.recount, "accept_fix", wraps=mod.recount.accept_fix) as recount:
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], False, got)
        self.assertIn(fixgates.REJECT, got["reason"])
        gates.assert_called_once_with(self.board, self.repo, "", self.SUITE, 1, pass_="first")
        recount.assert_called_once()   # 写しの照らしは乾いた形だけ（盤面に done("p3.fix") を書く前に拒む。preflight F12）
        self.assertIs(recount.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_accept_traces_skipped_red_green(self):
        """束が赤緑を確かめずに受けた回（実行器の無い run）は、盤面の trace の SKIPPED_OP に理由を載せ、報告が数える"""
        self.fix_ready()
        planmarks.save(self.board, entry.open_board(self.board).round, FIELDS)
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_SUITE": ""}):
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], True, got)
        b = entry.open_board(self.board, allow_halted=True)
        rows = report.trace_rows(b, fixgates.SKIPPED_OP)
        self.assertEqual([r["why"] for r in rows], [[fixgates.NO_SUITE]])
        self.assertIn("受け付け 1 回", report.gates_lines(b)[0])

    def test_out_of_duty_items_alone_are_not_traced(self):
        """飛ばした理由が義務の外の項目だけなら、受けた回の trace に載せない（確かめずに通したに数えない。帳面にだけ残る）"""
        self.fix_ready()
        planmarks.save(self.board, entry.open_board(self.board).round, [{**FIELDS[0], "unit_keys": ["判定に無い単位"]}])
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        with self.env():
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], True, got)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertTrue(fixgates.skipped(self.board, pass_="first", attempt=1), "帳面には残る")
        self.assertEqual(report.trace_rows(b, fixgates.SKIPPED_OP), [])

    def test_out_of_duty_and_real_skip_in_one_acceptance(self):
        """1 回の受け付けに義務の外の項目（OUT_OF_DUTY）と実の飛ばし（実行器の無い run の NO_SUITE）が並ぶ: 帳面は両方を残し、
        trace は実の飛ばしだけを載せ、報告は 1 回と数える"""
        self.fix_ready()
        planmarks.save(self.board, entry.open_board(self.board).round, [{**FIELDS[0], "unit_keys": ["判定に無い単位"]}, FIELDS[0]])
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        # 欄の控えは 2 項目・種の修正案は 1 項目なので、案の項目と差分の照らし（218。項目と控えの数を突き合わせる）は外す
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_SUITE": ""}), \
                mock.patch.object(mod, "check_plan_scope", return_value=([], None)):
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], True, got)
        why = fixgates.skipped(self.board, pass_="first", attempt=1)
        self.assertEqual(len(why), 2, why)
        self.assertTrue(why[0].startswith(fixgates.OUT_OF_DUTY), why)
        self.assertEqual(why[1], fixgates.NO_SUITE)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual([r["why"] for r in report.trace_rows(b, fixgates.SKIPPED_OP)], [[fixgates.NO_SUITE]])
        lines = report.gates_lines(b)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("受け付け 1 回", lines[0])
        self.assertNotIn(fixgates.OUT_OF_DUTY, lines[0])

    def test_g1_accept_rejects_new_red_in_selected_test(self):
        """修正の形 g1: tdd-start は輪を回さないが元の結末は取る（強み 6: どの形も受け付けで変更に当たる試験を選んで回す）。
        元で緑だった選んだ試験を赤にした直しは、受け付けの 1c（check_tests）が拒む"""
        import tddloop
        self.fix_ready()
        fixshape.choose(self.board, "g1", by="試験", why="g1 の受け付けの 1c を見る")
        start = tddloop.start(self.board, self.repo, self.SUITE, tbt.OPEN)
        self.assertEqual((start["go"], start["reason"], start["summary_file"]), (False, tddloop.G1_NO_LOOP, ""))
        self.edit_tree({**tbf.FIXED, "    return x\n": "    return lo\n"})   # 直した上で、元で緑の test_clamp_within_range を赤に
        mod = self.accept_mod()
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": start["state_file"]}):
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], False, got)
        self.assertIn("元で赤でなかった試験が赤", got["reason"])
        self.assertIn("test_clamp_within_range", got["reason"])

    def test_clean_battery_lets_fix_through(self):
        """束が何も見つけなければ今までどおり受ける（修正案の欄の無い run・既存のテストを変えない直し）"""
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        with self.env():
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], True, got)
        self.assertEqual(report.trace_rows(entry.open_board(self.board, allow_halted=True), fixgates.SKIPPED_OP), [],
                         "飛ばした物が無ければ trace に載せない")


if __name__ == "__main__":
    unittest.main()
