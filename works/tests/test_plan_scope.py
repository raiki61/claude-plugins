"""承認済みの修正案の項目と修正の差分の照らし（blk-fix の planscope。依頼 218）。純粋な関数 problems・new_test_ids・
added_removed を直に呼んで見る（FAST。盤面・git・子のプロセスなし）。単位の key は linekit.reply("judge_ok") の物"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))
if str(ROOT / "blk-fix" / "lib") not in sys.path:   # 修正のブロックの模块。後ろに足して core の名を隠さない
    sys.path.append(str(ROOT / "blk-fix" / "lib"))
import linekit  # noqa: E402
import planscope  # noqa: E402

MEAN, CLAMP = (u["key"] for u in linekit.reply("judge_ok")["units"])

ITEM = {"item": 1, "unit_keys": [MEAN], "adds": [], "removes": [], "route": "direct", "tests": [], "rewrite_tests": [],
        "allowed_paths": ["stats.py"], "out_of_scope": []}
ROW = {"unit_key": MEAN, "files": ["stats.py"]}
STATS = {"stats.py": ("def mean(xs):\n    return 0\n", "def mean(xs):\n    return 1\n")}


def item(**over):
    return {**ITEM, **over}


class ProblemsCase(unittest.TestCase):
    def test_inside_allowed_passes(self):
        self.assertEqual(planscope.problems([ITEM], [ROW], STATS)[0], [])

    def test_file_outside_allowed_names_unit_and_item(self):
        got, _ = planscope.problems([ITEM], [{"unit_key": MEAN, "files": ["other.py"]}], {**STATS, "other.py": (None, "x = 1\n")})
        self.assertTrue(any(MEAN in p and "other.py" in p and "項目 1" in p for p in got), got)

    def test_out_of_scope_wins_over_allowed(self):
        it = item(allowed_paths=["*.py"], out_of_scope=[{"glob": "test_*.py", "why": "既存の試験は触らない"}])
        got, _ = planscope.problems([it], [{"unit_key": MEAN, "files": ["test_stats.py"]}], {"test_stats.py": ("a\n", "b\n")})
        self.assertTrue(any("out_of_scope" in p and "test_*.py" in p for p in got), got)

    def test_undeclared_change_outside_every_item(self):
        got, _ = planscope.problems([ITEM], [ROW], {**STATS, "stray.py": (None, "x\n")})
        self.assertTrue(any("stray.py" in p for p in got), got)

    def test_item_without_footprint_is_missing(self):
        got, _ = planscope.problems([ITEM], [ROW], {})
        self.assertTrue(any("範囲の中に変えたファイルが無い" in p and MEAN in p for p in got), got)

    def test_adds_identifier_must_appear_in_added_lines(self):
        it = item(adds=[{"kind": "function", "name": "median", "canonical": "stats.py に新設（平均と同じ置き場）"}])
        self.assertTrue(any("median" in p for p in planscope.problems([it], [ROW], STATS)[0]))
        ok = {"stats.py": ("", "def median(xs):\n    return xs[0]\n")}
        self.assertEqual(planscope.problems([it], [ROW], ok)[0], [])

    def test_canonical_elsewhere_definition_is_extra(self):
        it = item(allowed_paths=["*.py"], adds=[{"kind": "function", "name": "median", "canonical": "stats.py に新設"}])
        ch = {"stats.py": ("", "def median(xs):\n    pass\n"), "util.py": ("", "def median(xs):\n    pass\n")}
        got, _ = planscope.problems([it], [{"unit_key": MEAN, "files": ["stats.py", "util.py"]}], ch)
        self.assertTrue(any("util.py" in p and "canonical" in p for p in got), got)

    def test_removes_identifier_must_be_gone(self):
        it = item(removes=["old_mean"])
        kept = {"stats.py": ("def old_mean():\n    pass\n", "def old_mean():\n    return 1\n")}
        self.assertTrue(any("old_mean" in p for p in planscope.problems([it], [ROW], kept)[0]))
        gone = {"stats.py": ("def old_mean():\n    pass\n", "def mean():\n    pass\n")}
        self.assertEqual(planscope.problems([it], [ROW], gone)[0], [])

    def test_prose_names_not_checked(self):
        it = item(adds=[{"kind": "doc", "name": "平均の定義の注記", "canonical": "新設（stats.py の頭）"}], removes=["古い注記の文"])
        got, note = planscope.problems([it], [ROW], STATS)
        self.assertEqual(got, [])
        self.assertEqual(note["unchecked"], ["平均の定義の注記", "古い注記の文"])

    def test_new_test_must_be_named_in_tests(self):
        base = "class TestStats:\n    def test_a(self):\n        pass\n"
        ch = {**STATS, "test_stats.py": (base, base + "    def test_extra(self):\n        pass\n")}
        rows = [{"unit_key": MEAN, "files": ["stats.py", "test_stats.py"]}]
        it = item(allowed_paths=["stats.py", "test_stats.py"])
        self.assertTrue(any("test_stats.py::TestStats::test_extra" in p for p in planscope.problems([it], rows, ch)[0]))
        named = item(tests=[{"id": "test_stats.py::TestStats::test_extra"}])
        self.assertEqual(planscope.problems([named], rows, ch)[0], [])

    def test_named_test_missing_after_fix(self):
        it = item(tests=[{"id": "test_stats.py::TestStats::test_mean_of_two"}])
        self.assertTrue(any("test_mean_of_two" in p and MEAN in p for p in planscope.problems([it], [ROW], STATS)[0]))

    def test_exempt_units_skip_path_checks(self):
        got, _ = planscope.problems([ITEM], [{"unit_key": MEAN, "files": ["other.py"]}], {"other.py": (None, "x\n")},
                                    exempt={MEAN})
        self.assertEqual(got, [])

    def test_permit_paths_are_in_scope(self):
        ch = {**STATS, "test_stats.py": ("a\n", "b\n")}
        self.assertEqual(planscope.problems([ITEM], [ROW], ch, permits=("test_stats.py",))[0], [])

    def test_new_test_ids_only_test_modules(self):
        src = "def test_x():\n    pass\n"
        self.assertEqual(planscope.new_test_ids("util.py", None, src), [], "試験のモジュールの名でない .py は数えない")
        self.assertEqual(planscope.new_test_ids("test_util.py", None, src), ["test_util.py::test_x"])
        self.assertEqual(planscope.new_test_ids("util_test.py", "", src), ["util_test.py::test_x"])
        self.assertEqual(planscope.new_test_ids("test_util.py", None, "def test_x(:\n"), [], "構文の壊れた now は []")
        self.assertEqual(planscope.new_test_ids("test_util.md", None, src), [])

    def test_added_removed_replace(self):
        self.assertEqual(planscope.added_removed("a\nb\n", "a\nc\n"), (["c"], ["b"]))
        self.assertEqual(planscope.added_removed(None, "x\n"), (["x"], []), "None は空の中身")
        self.assertEqual(planscope.added_removed("x\n", None), ([], ["x"]))

    def test_note_records_checked_items(self):
        _, note = planscope.problems([ITEM, item(item=2, unit_keys=[CLAMP])], [ROW], STATS)
        self.assertEqual((note["checked"], note["items"]), (True, [1]), "見る項目は rows の単位と重なる項目だけ")

    def test_problem_lines_carry_unit_keys_for_binding(self):
        """拒否の行は単位の key か項目の unit_keys の全部を字のまま含める（3 回目の拒否で単位に結ぶ）"""
        it = item(unit_keys=[MEAN, CLAMP], adds=[{"kind": "function", "name": "median", "canonical": "stats.py に新設"}],
                  removes=["old_mean"], tests=[{"id": "test_stats.py::TestStats::test_two"}])
        got, _ = planscope.problems([it], [{"unit_key": MEAN, "files": ["other.py"]}, {"unit_key": CLAMP, "files": ["stats.py"]}],
                                    {"other.py": (None, "x\n")})
        unit_lines = [p for p in got if "どの項目の allowed_paths にも無い" not in p]
        self.assertTrue(unit_lines)
        for p in unit_lines:
            self.assertTrue(MEAN in p or CLAMP in p, p)


if __name__ == "__main__":
    unittest.main()
