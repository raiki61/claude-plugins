"""事後の関門の束（blk-fix/lib/fixgates.py。計画 220 Task 4）の検査。

束は修正の受け付け（節 fix-accept・fix-ruled-accept）の最後の段で、修正の形に依らず base（修正前の版）から今の木までを相手に
- red_green: 承認済みの修正案の tdd の項目の受け入れのテストが、今の木で緑・base で failure の赤か（輪と同じ tddloop.red_check の事実で見る）
- test_edits: base に在った既存のテストの関数の本体を、名指し（修正案の rewrite_tests・裁定 fix_test_scope の範囲）の外で変えていないか
を確かめる。盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作り、実行器は test_blk_fix_tdd の PYTEST_LIKE
（失敗の文を message に書く）。種の stats.mean は len-1 で割る誤りを持つ。
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
import consult  # noqa: E402
import entry  # noqa: E402
import fixgates  # noqa: E402
import impact  # noqa: E402
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
_PLAN_REPLY = tbf.plan_reply   # 種の 1 項目の案。差し替えの中から呼ぶ（差し替えた名を呼ぶと自分を呼ぶ）
REWRITE = {"id": THREE_ID, "behavior": "3 つの値の平均の期待", "old": "期待は 2", "new": "期待を 2.0 に書き換える",
           "limit": "test_stats.py:8"}


def strings(v):
    """入れ子の dict・list の中の文字列の全部"""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from strings(x)


def asked_row(paths=(), new_tests=(), decision="deny", granted_new_tests=(), **over):
    """範囲の相談の確かめの行（conflict.ASKED_OP。受け付けが見つけたはみ出しを聞いた物。origin accept）"""
    return {"id": 1, "at": "2026-10-10T00:00:00+09:00", "turn": 2, "pass": "first", "round": 1, "node": "plan-answer", "item": "1",
            "unit_keys": [tbf.MEAN], "paths": list(paths), "tests": [], "new_tests": list(new_tests), "why": "案の外のはみ出しを聞いた",
            "status": "answered", "decision": decision, "granted_paths": [], "granted_tests": [],
            "granted_new_tests": list(granted_new_tests), "spec": "", "reason": "範囲の中で直せる", "notes": [], "out_of_scope": [],
            "overrode_out_of_scope": [], "session": None, "origin": "accept", **over}


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
        self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
        self.assertIn("もう通る", rows[0]["detail"])
        self.assertEqual(rows[0]["unit_keys"], [tbf.MEAN], "行は項目の単位を持つ（最後の回に unit_key で単位に結ぶ）")

    def test_wrong_red_kind_is_a_miss(self):
        """新しいテストが base で NameError（機能が無い）で落ちる failure でも、機械は赤の種類で拒まない。今の木で緑なら行は無い"""
        self.ready_with_fields()
        self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
        self.edit_tree({"def clamp(x, lo, hi):": "def halve(x):\n    return x / 2\n\n\ndef clamp(x, lo, hi):"})
        self.assertEqual(self.problems(), [])

    def agree(self, tid, red_kind, **over):
        """範囲の相談の合意（allow の行）で、項目 1 に新しいテスト tid が入った盤面にする"""
        row = asked_row(new_tests=[tid], decision="allow", granted_new_tests=[{"id": tid, "red_kind": red_kind}], **over)
        entry.open_board(self.board, allow_halted=True).trace(conflict.ASKED_OP, **row)

    def test_agreed_new_test_is_checked_red_green(self):
        """範囲の相談の合意で項目に入った新しいテストは、項目が direct（受け入れのテストが無い）でも事後の関門の red_green が
        確かめ、base で緑なら抜けの行になる"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.AGREED_RED)
        self.add_test_that_passes_on_base("test_mean_of_two")
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertIn("もう通る", rows[0]["detail"])

    def test_agreed_test_not_written_is_not_a_miss(self):
        """合意で入ったテストは許しで義務でない: 修正役が書かなければ関門に入れない（一式の結末に居ないの行にしない）"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.AGREED_RED, origin="gate")
        self.edit_tree(MEAN_FIX)
        self.assertEqual(self.problems(), [])

    def test_agreed_test_written_under_other_name_is_not_a_miss(self):
        """合意の id と別の名で書いた時も、合意の id は関門に入れない（別の名のテストは範囲の照らしのはみ出しの側）"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.AGREED_RED, origin="gate")
        self.add_test(tbt.NEW_TEST.replace("test_mean_of_two", "test_mean_pair"))
        self.edit_tree(MEAN_FIX)
        self.assertEqual(self.problems(), [])

    def test_later_agreement_fixes_red_kind(self):
        """同じ id を後の相談で守りのテストに直すと、後の合意が勝つ: base で緑でも抜けの行にならない"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.AGREED_RED, origin="gate")
        self.agree(MEAN_ID, planmarks.GUARD_KIND, id=2, turn=3)
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual(self.problems(), [])

    def test_agreed_red_green_row_is_marked_for_revert(self):
        """合意のテストの red_green の行は印 agreed を持ち、overflow_asks がそのテストだけを戻す頼み（revert）にする"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.AGREED_RED, origin="gate")
        self.add_test_that_passes_on_base("test_mean_of_two")
        (row,) = self.problems()
        self.assertTrue(row.get("agreed"), row)
        (ask,) = fixgates.overflow_asks([row], self.repo, self.base, [{"item": 1, "allowed_paths": ["test_stats.py"]}])
        self.assertEqual((ask["new_tests"], ask.get("revert")), ([MEAN_ID], True))

    def test_agreed_guard_test_needs_only_green_now(self):
        """合意の red_kind が守りのテスト（GUARD_KIND）の新しいテストは、base で緑でも抜けの行にならない。今の木で赤なら抜けの行"""
        self.ready_with_fields(direct_fields())
        self.agree(MEAN_ID, planmarks.GUARD_KIND)
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.assertEqual(self.problems(), [], "base で緑でも守りのテストは抜けにならない")
        self.edit_tests("    def test_mean_of_two(self):\n        self.assertEqual(clamp(5, 0, 10), 5)",
                        "    def test_mean_of_two(self):\n        self.assertEqual(clamp(5, 0, 10), 6)")
        rows = self.problems(attempt=2)
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertIn("今の木", rows[0]["detail"])

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
            self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
            self.assertIn("一式の結末に居ない", rows[0]["detail"])
        with self.subTest("base で error（failure でない赤）"):
            self.suite.write_text(tbt.SUITE, encoding="utf-8")   # 本体の例外を error と書く実行器
            (self.repo / "test_two.py").unlink()
            self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
            self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
            planmarks.save(self.board, entry.open_board(self.board).round, FIELDS)
            rows = self.problems(attempt=2)
            self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
            self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
            self.assertIn("error で落ちた", rows[0]["detail"])
            self.assertNotIn(fixgates.tddloop.NOT_RAN, rows[0]["detail"], "言い足しは輪の呼び手だけで、事後の関門の行には入らない")

    def test_base_row_carries_loop_red_check_text(self):
        """base の木の行の detail は『base で 』と、輪と同じ red_check が同じ JUnit の行に返す事実の文で出来ている（NOT_RAN を含まない）"""
        self.ready_with_fields()
        self.suite.write_text(tbt.SUITE, encoding="utf-8")   # 本体の例外を error と書く実行器（base の木で mean の名指しが error）
        self.edit_tests("from stats import clamp, mean", "from stats import *  # noqa: F403")
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(halve(4), 2)  # noqa: F405\n")
        self.edit_tree(HALVE)
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        row = {"classname": "test_stats.TestStats", "name": "test_mean_of_two", "outcome": "error", "fail_message": "", "fail_text": ""}
        probs, _ = fixgates.tddloop.red_check([MEAN_ID], [row], None, None)
        self.assertEqual(rows[0]["detail"], "base で " + "；".join(probs))
        self.assertIn("error で落ちた", rows[0]["detail"])
        self.assertNotIn(fixgates.tddloop.NOT_RAN, rows[0]["detail"])

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

    def test_board_without_loop_freeze_gets_both_gates(self):
        """受け付けに輪の凍結の控えが無い盤面: 束が赤緑と既存テストの変更の両方を当てる（輪の凍結の検査 1b は控えの無い run で
        何も見ないので、その凍結はこの束だけが受け持つ。Preflight F13）"""
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        self.edit_tests(*THREE_EDIT)
        rows = self.problems()
        self.assertEqual(sorted((r["gate"], r["id"]) for r in rows), [("red_green", MEAN_ID), ("test_edits", THREE_ID)])

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


class TestBaseCache(FixGatesCase):
    """base の木の結末は base の版（writes.base_rev）・実行器・受け入れのテストの id・そのテストのファイル（と写す conftest.py）の
    中身で鍵を作り、盤面の周の置き場に残して受け付けの回・1 回目と 2 回目の修正の段をまたいで使い回す（base は run の中で
    動かない。195g は回ごとに base の worktree で一式を 1 分半走らせ直した）。決まり（今の木で緑・base で案の種類の赤）は変えない"""

    def counted(self):
        """tddloop.run_suite を数える {"now": 今の木の回数, "base": それ以外の回数}"""
        real = fixgates.tddloop.run_suite
        calls = {"now": 0, "base": 0}

        def run(exe, repo, *a, **k):
            calls["now" if pathlib.Path(repo).resolve() == self.repo.resolve() else "base"] += 1
            return real(exe, repo, *a, **k)
        return calls, mock.patch.object(fixgates.tddloop, "run_suite", side_effect=run)

    def test_base_runs_once_across_attempts(self):
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        calls, patch = self.counted()
        with patch:
            self.assertEqual(self.problems(attempt=1), [])
            self.assertEqual(self.problems(attempt=2), [])
            self.assertEqual(self.problems(attempt=1, pass_="ruled"), [])
        self.assertEqual(calls, {"now": 3, "base": 1}, "今の木は回ごと・base は 1 回")

    def test_cached_base_keeps_the_rule(self):
        """使い回した base の結末でも決まりは同じ: base で緑なら回をまたいでも行"""
        self.ready_with_fields()
        self.add_test_that_passes_on_base("test_mean_of_two")
        calls, patch = self.counted()
        with patch:
            first = self.problems(attempt=1)
            second = self.problems(attempt=2)
        self.assertEqual([(r["gate"], r["id"], r["detail"]) for r in first],
                         [(r["gate"], r["id"], r["detail"]) for r in second])
        self.assertTrue(second[0]["detail"].startswith("base で "), second[0]["detail"])
        self.assertIn("もう通る", second[0]["detail"])
        self.assertEqual(calls["base"], 1)

    def test_changed_test_file_reruns_base(self):
        """受け入れのテストのファイルの中身が変われば鍵が変わり、base を走らせ直す（古い結末で通さない）"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        calls, patch = self.counted()
        with patch:
            self.assertEqual(self.problems(attempt=1), [])
            self.edit_tests("self.assertEqual(mean([2, 4]), 3)", "self.assertEqual(clamp(5, 0, 10), 5)")
            rows = self.problems(attempt=2)
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", MEAN_ID)])
        self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
        self.assertIn("もう通る", rows[0]["detail"])
        self.assertEqual(calls["base"], 2)

    def test_other_base_rev_reruns_base(self):
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        calls, patch = self.counted()
        with patch:
            self.assertEqual(self.problems(attempt=1), [])
            (self.repo / "note.txt").write_text("x", encoding="utf-8")
            self.git("add", "note.txt")
            self.git("commit", "-q", "-m", "版を進める")
            head = self.git("rev-parse", "HEAD")
            with mock.patch.object(fixgates.writes, "base_rev", return_value=head):
                self.problems(attempt=2)
        self.assertEqual(calls["base"], 2)

    def test_second_pass_reuses_first_pass_base(self):
        """2 回目の修正の段（include refitting。帳面は別の置き場）も、同じ鍵なら 1 回目の段の base の結末を使う"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        calls, patch = self.counted()
        refit = {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": "refitting__fix-loop.fix-accept"})}
        accept = str(ROOT / "blk-fix" / "scripts" / "accept.py")
        with patch:
            self.assertEqual(self.problems(attempt=1), [])
            with mock.patch.dict(os.environ, refit), mock.patch.object(sys, "argv", [accept]):
                self.assertEqual(self.problems(attempt=1), [])
        self.assertEqual(calls["base"], 1)

    def test_failed_base_run_is_not_cached(self):
        """base で実行器が結末を出さなかった回は残さない（次の回は走らせ直す）"""
        self.ready_with_fields()
        self.add_test_mean_of_two()
        self.edit_tree(MEAN_FIX)
        real = fixgates.tddloop.run_suite
        calls = {"base": 0}

        def run(exe, repo, *a, **k):
            if pathlib.Path(repo).resolve() != self.repo.resolve():
                calls["base"] += 1
                if calls["base"] == 1:
                    return None, None, ["base で JUnit を書かなかった"]
            return real(exe, repo, *a, **k)
        with mock.patch.object(fixgates.tddloop, "run_suite", side_effect=run):
            self.assertEqual(self.problems(attempt=1), [])
            self.assertTrue(fixgates.skipped(self.board, pass_="first", attempt=1))
            self.assertEqual(self.problems(attempt=2), [])
        self.assertEqual(calls["base"], 2)
        self.assertEqual(fixgates.skipped(self.board, pass_="first", attempt=2), [])


STUB = "def halve(x):\n    return 0  # 仮の実装\n\n\ndef clamp(x, lo, hi):"   # test の段で赤を作るために足す最小の仮の実装
TWICE_ID = "test_two.py::TestTwo::test_twice"
SAB_ID = "test_sab.py::TestSab::test_clamp_in_range"
SAB = ("import unittest\n\nfrom stats import clamp\n\n\nclass TestSab(unittest.TestCase):\n    def test_clamp_in_range(self):\n"
       "        self.assertEqual(clamp(5, 0, 10), 5)\n")   # base で通るテスト（直す前から緑）


class TestLoopRedTree(FixGatesCase):
    """輪が仮の実装（テストでないファイル）を足して赤を確かめた単位の受け入れのテストは、事後の関門も輪の記録した赤の木
    （red_tree。仮の実装を含む）で名指しを走らせ直して failure を見る（持ち主の直す前の関所の答え (3) A）。base の木にテストの
    ファイルだけを写すと、仮の実装が無く組み立てで落ちて『一式の結末に居ない』と拒むため。今の木のテストのファイルが赤の記録と
    輪が終わった時（frozen）と違う単位は、赤の木が今のテストを表さないので base の木で見る（今どおり）。赤の木を使う名指しも
    base の木＋テストのファイルで 1 回走らせ、passed（直す前から通る）なら拒む（仮の実装の名目で既存の実装を壊した偽の赤を拒む）"""

    def stub_red(self):
        """test_two.py（halve を読む）を書き、仮の実装で赤にした木を輪の単位の記録に残し、本物の実装に直す"""
        self.ready_with_fields(self.fields_for(TWO_ID))
        (self.repo / "test_two.py").write_text(TWO_FILE, encoding="utf-8")
        self.edit_tree({"def clamp(x, lo, hi):": STUB})
        red = fixgates.tddloop.snapshot(self.repo)
        self.save_unit(red)
        self.edit_tree({"return 0  # 仮の実装": "return x / 2"})
        return red

    def save_unit(self, red_tree, **over):
        """盤面の根の輪の状態 tdd-1/state.json に、赤を確かめた単位の記録を置く（輪の _test が残す欄だけ。frozen は輪が終わった
        時のテストのファイルの hash で、今の姿）"""
        unit = {"unit_key": tbf.MEAN, "route": "tdd", "red": "ok", "tests": [TWO_ID], "test_files": ["test_two.py"],
                "test_hashes": fixgates.tddloop.hashes(self.repo, ["test_two.py"]), "red_tree": red_tree, "stub_files": ["stats.py"],
                **over}
        self.save_units({tbf.MEAN: unit})

    def save_units(self, units):
        files = sorted({f for u in units.values() for f in u["test_files"]})
        d = self.board / "tdd-1"
        d.mkdir(parents=True, exist_ok=True)
        (d / fixgates.tddloop.STATE).write_text(json.dumps({"units": units, "frozen": fixgates.tddloop.hashes(self.repo, files)},
                                                           ensure_ascii=False), encoding="utf-8")

    def test_stub_red_rechecked_on_loop_red_tree(self):
        """base の木では一式の結末に居ないテストでも、輪の赤の木で failure なら行は無い"""
        self.stub_red()
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.worktrees(), self.worktrees()[:1], "走らせ直した一時の worktree は残さない")

    def test_red_tree_that_passes_is_a_miss(self):
        """赤の木で名指しが通る（記録が赤を映していない）なら行。文は『輪の赤の木で 』と red_check の事実"""
        self.stub_red()
        self.save_unit(fixgates.tddloop.snapshot(self.repo))   # 直した後の木を赤の木と書く
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", TWO_ID)])
        self.assertTrue(rows[0]["detail"].startswith(fixgates.RED_TREE_HEAD), rows[0]["detail"])
        self.assertIn("もう通る", rows[0]["detail"])

    def test_test_file_moved_after_loop_falls_back_to_base(self):
        """輪が終わった後（やり直し・裁定）にテストのファイルが変わった単位は、赤の木が今のテストを表さないので base の木で見る
        （仮の実装が無く拒む）"""
        self.stub_red()
        path = self.repo / "test_two.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# 赤の後の書き足し\n", encoding="utf-8")
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", TWO_ID)])
        self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
        self.assertIn("一式の結末に居ない", rows[0]["detail"])

    def test_two_units_share_a_test_file(self):
        """後の単位が同じテストのファイルに足し、後の単位の仮の実装を頭で読んでも、先の単位は輪の赤の木で見る（輪が終わった時の
        テストのファイルと今が同じなら、赤の時の hash と違っても base に戻さない）"""
        self.ready_with_fields([{**FIELDS[0], "tests": [{**TEST_ROW, "id": TWO_ID}, {**TEST_ROW, "id": TWICE_ID}]}])
        path = self.repo / "test_two.py"
        path.write_text(TWO_FILE, encoding="utf-8")
        self.edit_tree({"def clamp(x, lo, hi):": STUB})
        a = {"unit_key": "a", "route": "tdd", "red": "ok", "tests": [TWO_ID], "test_files": ["test_two.py"],
             "test_hashes": fixgates.tddloop.hashes(self.repo, ["test_two.py"]), "red_tree": fixgates.tddloop.snapshot(self.repo)}
        self.edit_tree({"return 0  # 仮の実装": "return x / 2"})   # 単位 a を直す
        path.write_text(path.read_text(encoding="utf-8").replace("from stats import halve", "from stats import halve, twice")
                        + "\n    def test_twice(self):\n        self.assertEqual(twice(2), 4)\n", encoding="utf-8")
        self.edit_tree({"def clamp(x, lo, hi):": "def twice(x):\n    return 0  # 仮の実装\n\n\ndef clamp(x, lo, hi):"})
        b = {"unit_key": "b", "route": "tdd", "red": "ok", "tests": [TWICE_ID], "test_files": ["test_two.py"],
             "test_hashes": fixgates.tddloop.hashes(self.repo, ["test_two.py"]), "red_tree": fixgates.tddloop.snapshot(self.repo)}
        self.edit_tree({"return 0  # 仮の実装": "return x * 2"})   # 単位 b を直す
        self.save_units({"a": a, "b": b})
        self.assertEqual(self.problems(), [])

    def test_sabotaged_red_tree_green_at_base_is_a_miss(self):
        """test の段が既存の実装を壊した木を赤の木に残し、fix の段で戻しても、base の木＋テストのファイルで通る（直す前から緑）
        なら行（別の目 R1 の写し）"""
        self.ready_with_fields(self.fields_for(SAB_ID))
        (self.repo / "test_sab.py").write_text(SAB, encoding="utf-8")
        self.edit_tree({"def clamp(x, lo, hi):": "def clamp(x, lo, hi):\n    return -1  # 壊す\n"})
        self.save_unit(fixgates.tddloop.snapshot(self.repo), tests=[SAB_ID], test_files=["test_sab.py"],
                       test_hashes=fixgates.tddloop.hashes(self.repo, ["test_sab.py"]))
        self.edit_tree({"    return -1  # 壊す\n": ""})
        rows = self.problems()
        self.assertEqual([(r["gate"], r["id"]) for r in rows], [("red_green", SAB_ID)])
        self.assertTrue(rows[0]["detail"].startswith("base で "), rows[0]["detail"])
        self.assertIn("もう通る", rows[0]["detail"])

    def test_red_tree_result_is_cached(self):
        """赤の木は run の中で動かないので、結末を控えて回をまたいで使い回す"""
        self.stub_red()
        real = fixgates.tddloop.run_suite
        calls = []

        def run(exe, repo, *a, **k):
            calls.append(pathlib.Path(repo).resolve() == self.repo.resolve())
            return real(exe, repo, *a, **k)
        with mock.patch.object(fixgates.tddloop, "run_suite", side_effect=run):
            self.assertEqual(self.problems(attempt=1), [])
            self.assertEqual(self.problems(attempt=2), [])
        self.assertEqual(calls.count(False), 2, "赤の木と base の木は 1 回ずつだけ走らせる")


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

    def test_second_pass_keeps_first_pass_ruled_limit(self):
        """2 回目の修正の段（案を直した行が在る。conflict.second_pass。依頼 226）の受け付けは、裁定の前（first）でも 1 回目の段の
        裁定 fix_test_scope の範囲の直しを通す（base からの差分に 1 回目の直しが在る）"""
        self.ready_with_fields(direct_fields())
        self.rule(["test_stats.py:9"])
        self.edit_tests(*THREE_EDIT)
        self.assertEqual([(r["gate"], r["id"]) for r in self.problems(pass_="first")], [("test_edits", THREE_ID)],
                         "1 回目の段の裁定の前は今どおり")
        self.rule(["test_stats.py:9"], amended=True)
        self.assertEqual(self.problems(pass_="first"), [])

    CLAMP_TESTS = [("test_stats.py::TestStats::test_clamp_within_range", "test_stats.py:11"),
                   ("test_stats.py::TestStats::test_clamp_above_range", "test_stats.py:14")]   # 本体で clamp を名指す種のテスト

    def removes_fields(self, *, base_tests=None, rows=()):
        """removes に stats.clamp を持つ direct の項目の欄を、種の木を相手に planmarks.split で作る（リポジトリの複製はまだ無い）。
        base_tests を渡せば split が removes_tests を引き、rows を渡せばその行（{id, limit}）を欄にそのまま足す"""
        it = {"unit_keys": [tbf.MEAN], "approach": "x" * 20, "adds": [], "removes": ["stats.clamp"], "shrink_first": "y" * 20,
              "narrows": [], "route": "direct", "route_why": "既存の期待の書き換えだけの項目", "tests": [], "rewrite_tests": [],
              "refactor": {"declared": False, "why": ""}}
        kw = {} if base_tests is None else {"base_tests": base_tests}
        _, fields = planmarks.split({"plan": [it]}, tbf.SEED, **kw)
        if rows:
            fields[0]["removes_tests"] = [{"id": i, "limit": lim} for i, lim in rows]
        return fields

    def test_removes_permit_is_a_test_permits_row(self):
        """removes を名指すテストの許しは conflict.test_permits の行（test にテストの id、limit つき）として返り、凍結の検査が読む
        ruled_test_limits にも同じ limit が入る（許しの元は test_permits の 1 本だけ）"""
        b = self.ready_with_fields(self.removes_fields(rows=self.CLAMP_TESTS))
        rows = [p for p in conflict.test_permits(b) if p.get("test") in dict(self.CLAMP_TESTS)]
        self.assertEqual(sorted((p["test"], p["limit"]) for p in rows), sorted(self.CLAMP_TESTS))
        self.assertTrue(all(p["id"] == f"{conflict.REMOVES_TEST_ID}-1" and p["why"] for p in rows), rows)
        self.assertTrue({lim for _, lim in self.CLAMP_TESTS} <= set(conflict.ruled_test_limits(b)))

    def test_edit_of_test_naming_removes_passes(self):
        """run 6a51125d: 修正案の項目の removes（消す名）を本体で名指す既存のテストは、書き換え・消しを許す（消す仕組みを縛る
        テストは変えざるを得ない）。許しは split が base の版のテストの本体から引いて凍結した欄の removes_tests（conflict.test_permits の
        行）。removes を名指さないテストの書き換えは今までどおり拒む"""
        base_tests = {"test_stats.py": (tbf.SEED / "test_stats.py").read_text(encoding="utf-8")}
        self.ready_with_fields(self.removes_fields(base_tests=base_tests))
        self.edit_tests("self.assertEqual(clamp(15, 0, 10), 10)", "pass")   # test_clamp_above_range（clamp を名指す）の書き換え
        self.edit_tests("    def test_clamp_within_range(self):\n        self.assertEqual(clamp(5, 0, 10), 5)\n\n", "")   # 消し
        self.assertEqual(self.problems(), [])
        self.edit_tests(*THREE_EDIT)   # test_mean_of_three は clamp を名指さない
        self.assertEqual([(r["gate"], r["id"]) for r in self.problems()], [("test_edits", THREE_ID)])

    def rule(self, limits, *, amended=False):
        """裁定 fix_test_scope の行（範囲 limits）を置く。amended なら案を直した fix_plan_item の行も（2 回目の修正の段の盤面）"""
        rows = [{"id": "c1-1", "unit_key": tbf.MEAN, "between": ["stats.py:9", "test_stats.py:9"],
                 "why_both_cannot_hold": "期待の型が依頼と食い違う", "which_is_right": "test", "status": "ruled",
                 "ruling": {"decision": "fix_test_scope", "text": "期待を float で書いてよい", "limits": limits}}]
        if amended:
            rows.append({"id": "c1-2", "unit_key": tbf.CLAMP, "between": ["stats.py:12", "test_stats.py:12"],
                         "why_both_cannot_hold": "案の項目が誤り", "which_is_right": "request", "status": "ruled",
                         "ruling": {"decision": conflict.REPLAN, "text": "項目を直せ", "limits": []},
                         conflict.REPLAN_STATE: conflict.AMENDED})
        entry.open_board(self.board).work(conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False),
                                                                    encoding="utf-8")

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


class TestTestFilesDeclared(FixGatesCase):
    def test_declared_path_counts_as_test_file(self):
        """名の慣習に当たらないファイルも、受け入れのテスト・書き換えの名指しのパスならテストのファイル（写す・凍結の照らし）"""
        self.ready_with_fields(direct_fields())
        (self.repo / "checks.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
        (self.repo / "calc_test.go").write_text("package calc\n", encoding="utf-8")
        tree = fixgates.tddloop.snapshot(self.repo)
        self.assertEqual(fixgates._test_files(self.repo, self.base, tree), ["calc_test.go"])
        self.assertEqual(sorted(fixgates._test_files(self.repo, self.base, tree, ["./checks.py::test_x"])),
                         ["calc_test.go", "checks.py"])


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
        self.assertEqual({(r["pass"], r["attempt"]) for r in rows}, {("first", 3)})
        self.assertEqual(set(rows[0]), {"pass", "attempt", "gate", "id", "detail", "unit_keys"})
        self.problems(attempt=1, pass_="ruled")
        self.assertEqual(len(self.ledger()["rows"]), 4, "裁定の後の 1 回目は別の回")

    def test_second_pass_rows_live_under_its_scope(self):
        """2 回目の修正の段（include refitting）の行と飛ばした理由はその scope の帳面に積み、1 回目の段の同じ (pass, attempt) の
        物と混ざらない（行に回の印の鍵を置かない）"""
        self.ready_with_fields()
        self.edit_tests(*THREE_EDIT)
        self.problems(suite="", attempt=1)
        refit = {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": "refitting__fix-loop.fix-accept"})}
        accept = str(ROOT / "blk-fix" / "scripts" / "accept.py")
        with mock.patch.dict(os.environ, refit), mock.patch.object(sys, "argv", [accept]):
            self.problems(suite="", attempt=1)
            self.assertEqual(fixgates.skipped(self.board, pass_="first", attempt=1), [fixgates.NO_SUITE])
            second = json.loads(entry.open_board(self.board).work(fixgates.LEDGER).read_text(encoding="utf-8"))
        self.assertEqual(entry.open_board(self.board).work(fixgates.LEDGER).parent.parent, self.board)
        self.assertEqual(self.ledger()["skipped"], second["skipped"], "同じ回の印・同じ中身（置き場だけが違う）")
        self.assertEqual(len(self.ledger()["skipped"]), 1)
        self.assertEqual(fixgates.skipped(self.board, pass_="first", attempt=1), [fixgates.NO_SUITE])
        self.assertTrue((self.board / "refitting" / "r1" / fixgates.LEDGER).is_file())
        self.assertNotIn("tag", {k for r in self.ledger()["rows"] + second["rows"] for k in r})

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

    def test_accept_traces_unproven_tests(self):
        """修正案の外で足したテスト（案の照らしの記録の overflow）は、赤を確かめずに SKIPPED_OP へ名指して受けず、はみ出しとして
        相談に積む（受け付けは queued・done なし。相談の状態の queued にそのテストを new_tests として積む）"""
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        mod = self.accept_mod()
        tid = "test_stats.py::TestStats::test_extra"
        line = f"{tid} は修正案のどの項目の tests にも無いテストを足した"
        note = {"checked": True, "unchecked": [], "items": [1],
                "overflow": [{"line": line, "item": 1, "unit_key": tbf.MEAN, "paths": [], "new_tests": [tid]}]}
        with self.env(), mock.patch.object(mod, "check_plan_scope", return_value=([line], note)):
            got = mod.with_done(mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo))
        self.assertIs(got.get("queued"), True, got)
        self.assertIs(got["done"], False, got)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.trace_rows(b, fixgates.SKIPPED_OP), [], "応急処置の載せは外した")
        (queued,) = consult.state(b, "first")["queued"]
        self.assertEqual(queued["new_tests"], [tid])

    def test_accept_rejects_new_red_in_selected_test(self):
        """tdd-start が取った元の結末で、受け付けは変更に当たる試験を選んで回す（強み 6）。元で緑だった選んだ試験を赤にした直しは、
        受け付けの 1c（check_tests）が拒む"""
        import tddloop
        self.fix_ready()
        start = tddloop.start(self.board, self.repo, self.SUITE, tbt.OPEN)
        self.assertTrue(start["go"], start)
        self.edit_tree({**tbf.FIXED, "    return x\n": "    return lo\n"})   # 直した上で、元で緑の test_clamp_within_range を赤に
        mod = self.accept_mod()
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": start["state_file"]}):
            got = mod.accept_fix(tbf.load("fix2_ok"), self.board, "", self.repo)
        self.assertIs(got["ok"], False, got)
        self.assertIn("元で赤でなかった試験が赤", got["reason"])
        self.assertIn("test_clamp_within_range", got["reason"])

    def overflow_ready(self, allowed=("stats.py",), **over):
        """p3.fix が待つ盤面に、direct の項目 1（mean と clamp。範囲は allowed）を控え、stats.py を直した作業ツリーにする"""
        self.fix_ready()
        row = {**tbf.PLAN_FIELDS[0], "unit_keys": [tbf.MEAN, tbf.CLAMP], "route": "direct", "route_why": "見本。先にテストを書かない",
               "tests": [], "allowed_paths": list(allowed), "out_of_scope": [], **over}
        planmarks.save(self.board, entry.open_board(self.board).round, [row])
        self.edit_tree(tbf.FIXED)

    def overflow_reply(self):
        """mean の行が、項目の範囲の外の notes.txt も申告した返答（notes.txt は作業ツリーに在る）"""
        (self.repo / "notes.txt").write_text("控え\n", encoding="utf-8")
        reply = tbf.load("fix2_ok")
        reply["changes"][0]["files"] = ["stats.py", "notes.txt"]
        return reply

    def accept_done(self, mod, reply, iteration="1"):
        with self.env(iteration):
            return mod.with_done(mod.accept_fix(reply, self.board, "", self.repo))

    def test_overflow_only_is_queued_not_rejected(self):
        """単位が changes[].files に申告した範囲の外のパスだけがはみ出した返答は拒まない。受け付けは queued true・done false で、
        相談の状態の queued にそのパスと項目を積む（積む周では戻さない）"""
        self.overflow_ready()
        got = self.accept_done(self.accept_mod(), self.overflow_reply())
        self.assertIs(got.get("queued"), True, got)
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        b = entry.open_board(self.board, allow_halted=True)
        (row,) = consult.state(b, "first")["queued"]
        self.assertEqual((str(row["item"]), row["paths"]), ("1", ["notes.txt"]))
        self.assertTrue((self.repo / "notes.txt").exists(), "積む周では戻さない")
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_denied_overflow_is_reverted_and_rest_accepted(self):
        """受け付けが積んだ頼み（単位が申告したパス）が deny で答えられた後の受け付けは、そのパスだけを段の頭の木に戻し、
        changes[].files からも外して、残りの直しを受ける。trace の ACCEPT_OVERFLOW_OP に戻したパスと patch が載る"""
        self.overflow_ready()
        reply = self.overflow_reply()
        entry.open_board(self.board, allow_halted=True).trace(conflict.ASKED_OP, **asked_row(paths=["notes.txt"]))
        got = self.accept_done(self.accept_mod(), reply)
        self.assertIs(got["ok"], True, got)
        self.assertFalse((self.repo / "notes.txt").exists(), "頼んだパスは段の頭の木に戻す")
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "残りの直しは残る")
        self.assertNotIn("notes.txt", [f for c in got["changes"] for f in c["files"]])
        b = entry.open_board(self.board, allow_halted=True)
        (row,) = report.trace_rows(b, impact.ACCEPT_OVERFLOW_OP)
        patches = [s for s in strings(row) if s.endswith(".patch")]
        self.assertIn("notes.txt", list(strings(row)))
        self.assertTrue(patches and pathlib.Path(patches[0]).is_file(), row)

    def gate_ready(self):
        """直す前の関所で人が条件つきの continue を答え、direct の項目 1（範囲 stats.py・test_stats.py）が承認され、stats.py を
        直した盤面。関所の条件の相談（本線の頼みの節）を回して答えの節の答えを確かめる関数を返す"""
        import adapter
        self.fix_ready(narrows=tbf.NARROWS, answer=("continue", "既存の clamp を壊さないことを確かめるテストを足してから直せ"))
        row = {**tbf.PLAN_FIELDS[0], "unit_keys": [tbf.MEAN, tbf.CLAMP], "route": "direct", "route_why": "見本。先にテストを書かない",
               "tests": [], "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}
        planmarks.save(self.board, entry.open_board(self.board).round, [row])
        self.edit_tree(tbf.FIXED)
        home = self.tmp / "adapter-home"
        path = adapter.session_path(self.repo, "plan", home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("11111111-2222-3333-4444-555555555555\n", encoding="utf-8")

        def consult_gate(new_tests):
            b = entry.open_board(self.board, allow_halted=True)
            out = consult.ask(b, self.repo, {"changes": []}, "plan", "first", "plan-answer", home_dir=home)
            self.assertEqual((out["consulted"], out["go"]), (True, True), out)
            answer = {"answers": [{"ask": 1, "decision": "allow", "paths": [], "tests": [], "spec": "", "new_tests": new_tests,
                                   "reason": "人の条件のテストを項目に足してよい"}]}
            consult.settle(b, answer, "first", "plan-answer")
            consult.take(b, "first")
        return consult_gate

    def test_gate_condition_consult_then_accept_passes(self):
        """端から端まで: 関所の条件 → 本線の頼みの節が修正案の役に聞く → 守りのテストを許す → 修正役がそのテストを足す → 受け付けが
        通り（案の外のテストの拒否にも欠けにもならない）、受けた回の trace が認めたテストの id と赤の種類を名指す"""
        consult_gate = self.gate_ready()
        guard = "test_stats.py::TestStats::test_clamp_kept"
        consult_gate([{"id": guard, "red_kind": planmarks.GUARD_KIND}])
        self.add_test_that_passes_on_base("test_clamp_kept")
        got = self.accept_done(self.accept_mod(), tbf.load("fix2_ok"))
        self.assertIs(got["ok"], True, got)
        self.assertIn("def test_clamp_kept", (self.repo / "test_stats.py").read_text(encoding="utf-8"))
        b = entry.open_board(self.board, allow_halted=True)
        (row,) = report.trace_rows(b, impact.ACCEPT_OVERFLOW_OP)
        self.assertEqual(row["gate_tests"], [f"{guard}（{planmarks.GUARD_KIND}）"])
        self.assertTrue(any(guard in line for line in report.plan_ask_lines(b)), report.plan_ask_lines(b))

    def test_gate_agreed_test_failing_red_green_is_reverted_alone(self):
        """関所の条件の相談で赤を求めて許したテストが base で緑（赤緑が立たない）なら、受け付けはそのテストだけを戻して名指し、
        残りの直しを受ける（単位の直しを取り下げない）"""
        consult_gate = self.gate_ready()
        tid = "test_stats.py::TestStats::test_clamp_kept"
        consult_gate([{"id": tid, "red_kind": planmarks.AGREED_RED}])
        self.add_test_that_passes_on_base("test_clamp_kept")
        got = self.accept_done(self.accept_mod(), tbf.load("fix2_ok"))
        self.assertIs(got["ok"], True, got)
        self.assertNotIn("def test_clamp_kept", (self.repo / "test_stats.py").read_text(encoding="utf-8"), "合意のテストだけを戻す")
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "残りの直しは残る")
        b = entry.open_board(self.board, allow_halted=True)
        (row,) = report.trace_rows(b, impact.ACCEPT_OVERFLOW_OP)
        self.assertEqual([x["new_tests"] for x in row["reverted"]], [[tid]])

    def freeze_loop(self):
        """TDD の輪が test_stats.py に受け入れのテスト test_mean_of_two を足して凍らせた後の形（輪の状態のファイルを返す）"""
        import tddloop
        self.overflow_ready(["stats.py", "test_stats.py"])
        self.add_test_mean_of_two()
        state = self.tmp / "tdd-state.json"
        state.write_text(json.dumps({"frozen": tddloop.hashes(self.repo, ["test_stats.py"]), "frozen_tree": tddloop.snapshot(self.repo),
                                     "units": {tbf.MEAN: {"route": "tdd", "green": "ok", "tests": [MEAN_ID]}}}), encoding="utf-8")
        return str(state)

    def test_frozen_edit_outside_loop_tests_is_overflow(self):
        """TDD の輪が凍らせたファイルの、輪の受け入れのテストでない既存のテストの関数の中だけを書き換えた返答は、拒まずに相談に
        積む。輪の受け入れのテスト自身の書き換えと、関数の外（既存の import の行）の書き換えは、今どおり frozen の拒否の行"""
        state = self.freeze_loop()
        path = self.repo / "test_stats.py"
        frozen = path.read_text(encoding="utf-8")
        mod = self.accept_mod()
        reply = tbf.load("fix2_ok")
        edits = {"輪の受け入れのテスト": ("self.assertEqual(mean([2, 4]), 3)", "self.assertEqual(mean([2, 4]), 3.0)"),
                 "関数の外の import": ("from stats import clamp, mean", "from stats import mean, clamp")}
        for name, (old, new) in edits.items():
            with self.subTest(name):
                self.assertIn(old, frozen)
                path.write_text(frozen.replace(old, new), encoding="utf-8")
                with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": state}), \
                        mock.patch.object(mod, "check_tests", return_value=([], "")):
                    got = mod.with_done(mod.accept_fix(reply, self.board, "", self.repo))
                self.assertIs(got["ok"], False, got)
                self.assertNotIn("queued", got)
                self.assertIn("凍った", got["reason"])
        old, new = "self.assertEqual(clamp(5, 0, 10), 5)", "self.assertEqual(clamp(5, 0, 10), 5.0)"
        self.assertIn(old, frozen)
        path.write_text(frozen.replace(old, new), encoding="utf-8")
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": state}), \
                mock.patch.object(mod, "check_tests", return_value=([], "")):
            got = mod.with_done(mod.accept_fix(reply, self.board, "", self.repo))
        self.assertIs(got.get("queued"), True, got)
        self.assertIs(got["done"], False, got)

    LOOP_TEST = ("    def test_mean_of_two(self):\n        self.assertEqual(mean([2, 4]), 3)\n\n")   # 輪が既存のテストの上に足す受け入れのテスト
    CLAMP_EDIT = ("self.assertEqual(clamp(5, 0, 10), 5)", "self.assertEqual(clamp(5, 0, 10), 5.0)")

    def freeze_loop_above(self):
        """freeze_loop と同じだが、輪の受け入れのテストを既存のテストの上に足す（既存のテストの行が base と凍結の木でずれる）。
        返りは (輪の状態のファイル, 凍結の木の test_stats.py の中身)"""
        import tddloop
        self.overflow_ready(["stats.py", "test_stats.py"], tests=[TEST_ROW])
        self.edit_tests("class TestStats(unittest.TestCase):\n", "class TestStats(unittest.TestCase):\n" + self.LOOP_TEST)
        state = self.tmp / "tdd-state.json"
        state.write_text(json.dumps({"frozen": tddloop.hashes(self.repo, ["test_stats.py"]), "frozen_tree": tddloop.snapshot(self.repo),
                                     "units": {tbf.MEAN: {"route": "tdd", "green": "ok", "tests": [MEAN_ID]}}}), encoding="utf-8")
        return str(state), (self.repo / "test_stats.py").read_text(encoding="utf-8")

    def accept_frozen(self, state, reply=None):
        mod = self.accept_mod()
        with self.env(), mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": state}), mock.patch.object(mod, "check_tests", return_value=([], "")):
            return mod.with_done(mod.accept_fix(reply or tbf.load("fix2_ok"), self.board, "", self.repo))

    def test_ask_lines_for_frozen_file_are_base_lines(self):
        """凍ったファイルの関数の書き換えを相談に積む頼みの行は、輪の木でなく修正前の版の行（輪が上に足したテストで行がずれていても、
        事後の関門の頼みと同じ読む木 1 つ）"""
        state, frozen = self.freeze_loop_above()
        self.assertEqual(planmarks.line_in(self.git("show", "HEAD:test_stats.py"), "test_stats.py::TestStats::test_clamp_within_range"), 11)
        self.assertEqual(planmarks.line_in(frozen, "test_stats.py::TestStats::test_clamp_within_range"), 14, "輪の木では 3 行ずれる")
        self.edit_tests(*self.CLAMP_EDIT)
        got = self.accept_frozen(state)
        self.assertIs(got.get("queued"), True, got)
        (row,) = consult.state(entry.open_board(self.board, allow_halted=True), "first")["queued"]
        self.assertEqual(row["tests"], ["test_stats.py:11"])

    def test_agreed_permit_line_is_read_in_the_base_tree(self):
        """相談で許したテストの書き換えの行は修正前の版の行で、凍結の検査は輪の木へ移して読む。輪が上に足したテストで行がずれても、
        許した関数の書き換えは通り（事後の関門と同じ読み）、別の関数を許した行では通らず相談に積まれる"""
        state, _ = self.freeze_loop_above()
        self.edit_tests(*self.CLAMP_EDIT)
        board = entry.open_board(self.board, allow_halted=True)
        board.trace(conflict.ASKED_OP, **asked_row(decision="allow", tests=["test_stats.py:8"], granted_tests=["test_stats.py:8"]))
        got = self.accept_frozen(state)
        self.assertIs(got.get("queued"), True, f"別の関数（test_mean_of_three）を許した行では通らない: {got}")
        board.trace(conflict.ASKED_OP, **asked_row(decision="allow", tests=["test_stats.py:11"], granted_tests=["test_stats.py:11"], id=2))
        got = self.accept_frozen(state)
        self.assertIs(got["ok"], True, f"許した関数（test_clamp_within_range。base の 11 行は輪の木の 14 行）は通る: {got}")
        self.assertIn(self.CLAMP_EDIT[1], (self.repo / "test_stats.py").read_text(encoding="utf-8"), "許した書き換えは戻されない")
        (row,) = report.trace_rows(entry.open_board(self.board, allow_halted=True), impact.ACCEPT_OVERFLOW_OP)
        self.assertEqual(row["reverted"], [], row)

    def test_agreed_permit_lets_the_test_be_deleted(self):
        """許した既存のテストの関数を丸ごと消す直しは、前後の区切りの空行を含めて許しの幅の中（事後の関門も凍結の検査も通す）"""
        state, _ = self.freeze_loop_above()
        self.edit_tests("    def test_clamp_within_range(self):\n        self.assertEqual(clamp(5, 0, 10), 5)\n\n", "")
        entry.open_board(self.board, allow_halted=True).trace(
            conflict.ASKED_OP, **asked_row(decision="allow", tests=["test_stats.py:11"], granted_tests=["test_stats.py:11"]))
        got = self.accept_frozen(state)
        self.assertIs(got["ok"], True, got)

    def test_unrevertable_overflow_is_rejected_not_dropped(self):
        """答えが deny で、戻した後も同じ頼みの line が残るはみ出しは、黙って落とさず『はみ出しを戻せない』という成り立たない行で
        拒まれる（同じ物を 2 度積まない）"""
        self.fix_ready()
        self.edit_tree(tbf.FIXED)
        reply = self.overflow_reply()
        entry.open_board(self.board, allow_halted=True).trace(conflict.ASKED_OP, **asked_row(paths=["notes.txt"]))
        line = "notes.txt は項目 1 の allowed_paths の外"
        note = {"checked": True, "unchecked": [], "items": [1],
                "overflow": [{"line": line, "item": 1, "unit_key": tbf.MEAN, "paths": ["notes.txt"], "new_tests": []}]}
        mod = self.accept_mod()
        with self.env(), mock.patch.object(mod, "check_plan_scope", return_value=([line], note)):
            got = mod.with_done(mod.accept_fix(reply, self.board, "", self.repo))
        self.assertIs(got["ok"], False, got)
        self.assertNotIn("queued", got)
        self.assertIn("はみ出しを戻せない", got["reason"])
        self.assertIn(line, got["reason"])
        self.assertFalse(consult.queued(entry.open_board(self.board, allow_halted=True), "first"), "同じ物を 2 度積まない")

    def test_last_attempt_overflow_is_not_parked(self):
        """輪の最後の回（iteration 3）でも、はみ出しだけの返答は単位を止めず（PARKED_OP の行が無い）、相談に積んで done を立てない"""
        self.overflow_ready()
        got = self.accept_done(self.accept_mod(), self.overflow_reply(), iteration="3")
        self.assertIs(got.get("queued"), True, got)
        self.assertIs(got["done"], False, got)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.trace_rows(b, conflict.ACCEPT_PARKED_OP), [])
        self.assertTrue((self.repo / "notes.txt").exists())

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


class TestAgreedPermitTrees(unittest.TestCase):
    """範囲の相談の合意の範囲の行は修正前の版の行（読む木は 1 つ）。凍結の検査のように別の木を読む側へは conflict.agreed_permits が移す"""
    BASE = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n\n    def test_b(self):\n        self.assertEqual(2, 2)\n"
    LOOP = BASE.replace("class T(unittest.TestCase):\n", "class T(unittest.TestCase):\n    def test_new(self):\n        self.assertEqual(0, 0)\n\n")

    def limits(self, lim, *, source=True, base=True):
        rows = [{"item": "1", "id": 1, "granted_tests": [lim], "reason": "許した"}]
        src = {"t.py": self.LOOP}.get if source else None
        old = {"t.py": self.BASE}.get if base else None
        return [p["limit"] for p in conflict.agreed_permits(rows, source=src, base=old)]

    def test_single_line_follows_the_function(self):
        self.assertEqual(self.limits("t.py:8"), ["t.py:11"], "test_b の定義の行は 3 行ずれる")
        self.assertEqual(self.limits("t.py:9"), ["t.py:11"], "関数の中の行も、その関数の定義の行へ")

    def test_range_moves_both_ends_or_is_dropped(self):
        self.assertEqual(self.limits("t.py:8-9"), ["t.py:11-12"])
        self.assertEqual(self.limits("t.py:3-5"), [], "書き換わった行を含む範囲は移せない")

    def test_whole_file_and_unread_trees(self):
        self.assertEqual(self.limits("t.py"), ["t.py"], "ファイルだけの指しは木に依らない")
        self.assertEqual(self.limits("t.py:8", source=False), ["t.py:8"], "読む木が修正前の版ならそのまま")
        self.assertEqual(self.limits("t.py:8", base=False), [], "修正前の版が読めないなら許しを捨てる（広げない）")
        self.assertEqual(self.limits("u.py:8"), [], "読む木に無いファイルの許しは捨てる")


if __name__ == "__main__":
    unittest.main()
