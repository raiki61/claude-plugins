"""ゲートの検算の役（p1.gate_efficacy）が『条件に当たらない』を名乗れるかの works の差し替え（entry.role_judged_na_works）と、
差分に機械が見るゲートの印（entry.gate_signals）の検査。

canary の run e91112dd の事実: 差分は calc.py の docstring 1 行で、役は not_applicable と返したが、線 A の p0.base は機械が組み
（board.base_output）touches_gates を判定せずに真へ倒すので、写しの check_record が『applies_cond が真で走ったのに
not_applicable』と拒んだ。0 腕で名乗れる値は not_run（検証器の阻害）だけで、結末は round_limit になった。
差し替えは、p0.base が機械の節で、前の周の修正がゲートを変えたと申告しておらず、差分に機械が見るゲートの印が無い時だけ役の
『条件外』を受ける（印が 1 つでも在れば今どおり拒む——ゲートを足した・変えた差分は測らせる）。

関数を直に呼ぶ・偽の盤面・一時の置き場に差分のファイルを書くだけ（git・盤面・子のプロセスなし）。
"""
import pathlib
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
CORE = TESTS.parent / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import board  # noqa: E402
import entry  # noqa: E402

DOCSTRING_DIFF = '''diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -9,7 +9,7 @@ def mean(xs):
 def median(xs):
-    """中央値（個数が偶数なら真ん中の 2 つの平均）。空の xs は ValueError"""
+    """中央値（個数が偶数なら、並べた真ん中の 2 つの平均）。空の xs は ValueError"""
     if not xs:
'''


def _assert_diff(sign):
    return ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def clamp(x, lo, hi):\n"
            f"{sign}    assert lo <= hi, 'lo > hi'\n     return min(max(x, lo), hi)\n")


class SignalsCase(unittest.TestCase):
    """差分に機械が見るゲートの印: テスト・CI・pre-commit・変異の腕の一覧などの定義のファイルと、assert を足す・消す行"""

    def test_docstring_only_diff_has_no_signal(self):
        self.assertEqual(entry.gate_signals(["calc.py"], DOCSTRING_DIFF), [])

    def test_gate_files_are_signals(self):
        for f in ("tests/test_calc.py", "test_calc.py", "calc_test.go", "src/calc.test.ts", "conftest.py",
                  ".github/workflows/ci.yml", ".gitlab-ci.yml", ".pre-commit-config.yaml", ".husky/pre-commit",
                  ".review-checks.json", "pyproject.toml", "Makefile", "package.json", ".eslintrc.json"):
            with self.subTest(f):
                got = entry.gate_signals(["calc.py", f], "")
                self.assertEqual(len(got), 1, got)
                self.assertIn(f, got[0])

    def test_added_or_removed_assert_is_a_signal(self):
        for sign in "+-":
            with self.subTest(sign):
                got = entry.gate_signals(["calc.py"], _assert_diff(sign))
                self.assertEqual(len(got), 1, got)
                self.assertIn("assert", got[0])

    def test_context_assert_is_not_a_signal(self):
        """変えていない行（頭が空白）の assert は差分がゲートを変えた印にならない"""
        self.assertEqual(entry.gate_signals(["calc.py"], _assert_diff(" ")), [])


class _Table:
    def __init__(self, by):
        self.nodes = {"p0.base": type("E", (), {"by": by})()}


class FakeBoard:
    """role_judged_na_works が読む物だけを持つ盤面: 節（applies_cond）・表の p0.base の持ち主・条件（重ね書きの値つき）・
    loop の差分のファイルと変更ファイルの一覧"""

    def __init__(self, diff_text=DOCSTRING_DIFF, files=("calc.py",), p0_by="machine", fix_says_gates=False):
        self._td = tempfile.TemporaryDirectory()
        diff = pathlib.Path(self._td.name) / "diff-r1.patch"
        diff.write_text(diff_text, encoding="utf-8")
        self.nodes = {"p1.gate_efficacy": {"applies_cond": "gates_touched"},
                      "p1.test_double_fidelity": {"applies_cond": "seams_touched"}}
        self.table = _Table(p0_by)
        self.loop_state = {"diff_file": str(diff), "changed_files": list(files) if files is not None else None}
        self._fix = fix_says_gates
        self.conds = []

    def cond(self, name, overlay=None):
        self.conds.append((name, overlay))
        base = (overlay or {}).get("out.p0.base.touches_gates", True)
        ok = bool(base) or self._fix
        return ok, "差分が検証ゲートに触れる" if ok else "差分も前の周の修正も検証ゲートに触れない"

    def close(self):
        self._td.cleanup()


class PolicyCase(unittest.TestCase):
    def judged(self, **kw):
        b = FakeBoard(**kw)
        self.addCleanup(b.close)
        return entry.role_judged_na_works(b, "p1.gate_efficacy"), b

    def test_gate_free_diff_lets_the_role_judge(self):
        ok, b = self.judged()
        self.assertIs(ok, True)
        self.assertEqual(b.conds, [("gates_touched", {"out.p0.base.touches_gates": False})],
                         "機械が倒した p0.base の値を外して、写しの条件（前の周の修正の申告）で照らす")

    def test_gate_signal_keeps_the_copy_rule(self):
        for kw in ({"files": ("calc.py", "test_calc.py")}, {"diff_text": _assert_diff("+")}):
            with self.subTest(kw):
                self.assertIs(self.judged(**kw)[0], False)

    def test_fix_declared_gate_change_keeps_the_copy_rule(self):
        self.assertIs(self.judged(fix_says_gates=True)[0], False)

    def test_judged_p0_base_keeps_the_copy_rule(self):
        """p0.base を役が判定した表（本線の形）では、touches_gates は判定なので写しのまま拒む"""
        self.assertIs(self.judged(p0_by="role")[0], False)

    def test_unknown_changed_files_keeps_the_copy_rule(self):
        """変更ファイルの一覧が無い盤面は印が無いと言えない——写しのまま拒む"""
        self.assertIs(self.judged(files=None)[0], False)

    def test_other_nodes_keep_the_copy_rule(self):
        b = FakeBoard()
        self.addCleanup(b.close)
        self.assertIs(entry.role_judged_na_works(b, "p1.test_double_fidelity"), False)


class OverrideCase(unittest.TestCase):
    def test_copy_default_refuses_and_works_overrides(self):
        """写しの既定は名乗れない（本線と同じ）。works は CORE_OVERRIDES で差し替える"""
        b = FakeBoard()
        self.addCleanup(b.close)
        self.assertIs(board.rules_module().role_judged_na(b, "p1.gate_efficacy"), False)
        self.assertIs(entry.CORE_OVERRIDES["role_judged_na"][0], entry.role_judged_na_works)
        holder = type("H", (), {})()
        holder.rules, holder.state = board.rules_module(), {}
        board.DiskBoard._apply_overrides(holder, entry.CORE_OVERRIDES)
        self.assertIs(holder.rules.role_judged_na, entry.role_judged_na_works)


if __name__ == "__main__":
    unittest.main()
