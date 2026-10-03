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

    def test_out_of_scope_wins_over_permits(self):
        """out_of_scope は permits（テストの変更の許し・直す裁定の limits）にも勝つ（案が外したパスが要るのは案の項目の誤りで、
        fix_plan_item の道）。行の申告したパスも、申告の無い変わったパスも拒む"""
        it = item(allowed_paths=["*.py"], out_of_scope=[{"glob": "legacy.py", "why": "古い置き場は触らない"}])
        ch = {**STATS, "legacy.py": ("a\n", "b\n")}
        for rows in ([{"unit_key": MEAN, "files": ["stats.py", "legacy.py"]}], [ROW]):
            got, _ = planscope.problems([it], rows, ch, permits=("legacy.py",))
            self.assertTrue(any("out_of_scope" in p and "legacy.py" in p for p in got), (rows, got))

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


class HeldItemCase(unittest.TestCase):
    """裁定で外れた単位の項目も範囲を与える（依頼 241。外れた単位を直させない守りは受け付けの check_excused_units）"""

    def test_held_item_grants_like_any_item(self):
        mean = item(allowed_paths=["stats.py", "mean_util.py"], out_of_scope=[{"glob": "legacy.py", "why": "古い置き場は触らない"}],
                    tests=[{"id": "test_stats.py::TestStats::test_mean_of_two"}])
        clamp = item(item=2, unit_keys=[CLAMP], allowed_paths=["stats.py", "test_stats.py", "legacy.py"])
        base = "class TestStats:\n    def test_a(self):\n        pass\n"
        ch = {**STATS, "mean_util.py": (None, "x = 1\n"),
              "test_stats.py": (base, base + "    def test_mean_of_two(self):\n        pass\n")}
        rows = [{"unit_key": CLAMP, "files": ["stats.py", "test_stats.py"]}]
        self.assertEqual(planscope.problems([mean, clamp], rows, ch)[0], [], "外れた項目 1 の範囲と tests にも入る")
        got, _ = planscope.problems([mean, clamp], [{"unit_key": CLAMP, "files": ["legacy.py"]}], {"legacy.py": ("a\n", "b\n")})
        self.assertTrue(any("out_of_scope" in p and "legacy.py" in p for p in got), "out_of_scope は今どおり拒む")


class FalseRejectCase(unittest.TestCase):
    """正しい修正を誤って拒まない（審査の Important 2・3）"""

    def test_absent_partner_unit_does_not_reject_live_unit(self):
        """項目 [MEAN, CLAMP] の MEAN が行に無い（止めた・外した）とき、足す物・消す物・tests の欠けで CLAMP を拒まない
        （Missing 側は項目の単位が全部生きている時だけ見る）。範囲の検査は残る"""
        it = item(unit_keys=[MEAN, CLAMP], adds=[{"kind": "function", "name": "median", "canonical": "stats.py に新設"}],
                  removes=["old_mean"], tests=[{"id": "test_stats.py::TestStats::test_mean_of_two"}])
        rows = [{"unit_key": CLAMP, "files": ["stats.py"]}]
        self.assertEqual(planscope.problems([it], rows, STATS)[0], [])
        got, _ = planscope.problems([it], [{"unit_key": CLAMP, "files": ["other.py"]}], {"other.py": (None, "x\n")})
        self.assertTrue(any(CLAMP in p and "other.py" in p for p in got), got)
        both = [{"unit_key": MEAN, "files": ["stats.py"]}, {"unit_key": CLAMP, "files": ["stats.py"]}]
        self.assertTrue(any("median" in p for p in planscope.problems([it], both, STATS)[0]), "全部の単位が生きていれば見る")

    def test_mentioned_removed_name_is_gone(self):
        """消した名が足した行に定義でなく現れる（消えたことを確かめる hasattr・CHANGELOG の注記）だけなら、残ったと見ない"""
        it = item(allowed_paths=["*.py", "CHANGELOG.md"], removes=["old_mean"])
        ch = {"stats.py": ("def old_mean():\n    pass\n", "def mean():\n    pass\n"),
              "check_gone.py": (None, "import stats\nassert not hasattr(stats, 'old_mean')\n"),
              "CHANGELOG.md": ("# 変更\n", "# 変更\n- `old_mean` を消した\n")}
        rows = [{"unit_key": MEAN, "files": sorted(ch)}]
        self.assertEqual(planscope.problems([it], rows, ch)[0], [])
        again = {**ch, "util.py": (None, "def old_mean():\n    pass\n")}
        got, _ = planscope.problems([it], [{"unit_key": MEAN, "files": sorted(again)}], again)
        self.assertTrue(any("old_mean" in p for p in got), "足した行に定義が在れば残ったと見る")

    def test_dotted_name_found_by_last_segment(self):
        """名は kind を問わず :: と . で割った最後の段で探す。/ を含む名は確かめず unchecked に回す"""
        it = item(adds=[{"kind": "function", "name": "Stats.median", "canonical": "stats.py の Stats に新設"},
                        {"kind": "doc", "name": "docs/scope.md", "canonical": "docs/scope.md に新設"}])
        ch = {"stats.py": ("", "class Stats:\n    def median(self):\n        pass\n")}
        got, note = planscope.problems([it], [ROW], ch)
        self.assertEqual(got, [])
        self.assertEqual(note["unchecked"], ["docs/scope.md"])


class LoopFrozenCase(unittest.TestCase):
    """TDD の輪が凍らせたファイル（loop: パス → 凍った時の中身）。修正役に問うのは凍った後に変えた分だけ、欠けは版から見る"""
    BASE = "class TestStats:\n    def test_a(self):\n        pass\n"
    FROZEN = BASE + "    def test_new(self):\n        pass\n"

    def test_untouched_frozen_file_not_charged(self):
        it = item(tests=[{"id": "test_stats.py::TestStats::test_new"}])
        ch = {**STATS, "test_stats.py": (self.BASE, self.FROZEN), "data.json": (None, "[]\n")}
        loop = {"test_stats.py": self.FROZEN, "data.json": "[]\n"}
        self.assertEqual(planscope.problems([it], [ROW], ch, loop=loop)[0], [])
        got = planscope.problems([it], [ROW], ch)[0]
        self.assertTrue(any("data.json" in p for p in got), "輪の無い run なら範囲の外")

    def test_test_added_after_freeze_counts(self):
        it = item(tests=[{"id": "test_stats.py::TestStats::test_new"}])
        now = self.FROZEN + "    def test_after(self):\n        pass\n"
        ch = {**STATS, "test_stats.py": (self.BASE, now)}
        got = planscope.problems([it], [ROW], ch, loop={"test_stats.py": self.FROZEN}, permits=("test_stats.py",))[0]
        self.assertTrue(any("test_after" in p for p in got), got)
        self.assertFalse(any("test_new" in p for p in got), got)

    def test_qualified_remove_sees_other_class(self):
        """removes の Stats.median は、Legacy.median を消して Stats.median を残した差分を拒む（ast の名で見る）"""
        base = "class Legacy:\n    def median(self):\n        pass\n\n\nclass Stats:\n    def median(self):\n        pass\n"
        now = "class Legacy:\n    pass\n\n\nclass Stats:\n    def median(self):\n        pass\n"
        ch = {"stats.py": (base, now)}
        got = planscope.problems([item(removes=["Stats.median"])], [ROW], ch)[0]
        self.assertTrue(any("Stats.median" in p for p in got), got)
        self.assertEqual(planscope.problems([item(removes=["Legacy.median"])], [ROW], ch)[0], [])

    def test_removed_call_with_kept_definition_remains(self):
        """呼び出しの行だけを消して定義を残した差分は、消えていない"""
        base = "def old_mean():\n    pass\n\n\nx = old_mean()\n"
        now = "def old_mean():\n    pass\n\n\nx = 1\n"
        got = planscope.problems([item(removes=["old_mean"])], [ROW], {"stats.py": (base, now)})[0]
        self.assertTrue(any("old_mean" in p for p in got), got)


class Round3Case(unittest.TestCase):
    """修飾子をファイルごとに解く規則・凍った時の中身が無いファイル・凍ったファイルの外れと余分（審査の M1〜M4）"""
    FROZEN_HELPER = "def median(xs):\n    return xs[0]\n"

    def test_module_qualified_moved_definition_remains(self):
        """stats.old_mean（モジュール名の修飾子）・stats.py::old_mean の定義を同じファイルの中で移しただけの差分は拒む"""
        base = "def old_mean():\n    pass\n\n\ndef a():\n    pass\n\n\ndef b():\n    pass\n"
        now = "def a():\n    pass\n\n\ndef b():\n    pass\n\n\ndef old_mean():\n    pass\n"
        self.assertIn("def old_mean():", planscope.added_removed(base, now)[1], "定義の行は消した行にも出る（移した）")
        for raw in ("stats.old_mean", "stats.py::old_mean"):
            with self.subTest(raw):
                got = planscope.problems([item(removes=[raw])], [ROW], {"stats.py": (base, now)})[0]
                self.assertTrue(any(raw in p for p in got), got)

    def test_module_qualified_other_module_keeps_own_name(self):
        """legacy.median を消し、stats.py が自前の median を残す（その名を含む行は消した）差分は通る"""
        it = item(allowed_paths=["*.py"], removes=["legacy.median"])
        ch = {"legacy.py": ("def median(xs):\n    return 0\n", "x = 1\n"),
              "stats.py": ("def median(xs):\n    return 0\n\n\ny = median([1])\n", "def median(xs):\n    return 0\n")}
        rows = [{"unit_key": MEAN, "files": ["legacy.py", "stats.py"]}]
        self.assertEqual(planscope.problems([it], rows, ch)[0], [])

    def test_unreadable_frozen_content_falls_back_to_base(self):
        """凍った時の中身が無い（None）ファイルは、版からの差分で数える（版から在るテストを足した物と見ない）"""
        base = "class TestStats:\n    def test_a(self):\n        pass\n"
        ch = {**STATS, "test_stats.py": (base, base + "    def test_b(self):\n        pass\n")}
        it = item(allowed_paths=["stats.py", "test_stats.py"], tests=[{"id": "test_stats.py::TestStats::test_b"}])
        rows = [{"unit_key": MEAN, "files": ["stats.py", "test_stats.py"]}]
        self.assertEqual(planscope.problems([it], rows, ch, loop={"test_stats.py": None})[0], [])

    def test_canonical_elsewhere_in_frozen_file(self):
        """輪が書いて凍らせたファイルの同名の定義は canonical の外として問わない。凍った後に修正役が足した物は拒む"""
        it = item(allowed_paths=["*.py"], adds=[{"kind": "function", "name": "median", "canonical": "stats.py に新設"}])
        stats = ("", "def median(xs):\n    return xs[0]\n")
        rows = [{"unit_key": MEAN, "files": ["stats.py"]}]
        loop_written = {"stats.py": stats, "helper.py": (None, self.FROZEN_HELPER)}
        self.assertEqual(planscope.problems([it], rows, loop_written, loop={"helper.py": self.FROZEN_HELPER})[0], [])
        after = {"stats.py": stats, "helper.py": (None, "x = 1\n" + self.FROZEN_HELPER)}
        got = planscope.problems([it], rows, after, loop={"helper.py": "x = 1\n"})[0]
        self.assertTrue(any("helper.py" in p and "canonical" in p for p in got), got)

    def test_tdd_shape_with_test_adds_passes(self):
        """TDD の形: adds の kind test の test_mean_of_two は輪が書いて凍らせ、凍った後に変わっていなくても、版からの差分で在る"""
        base = "class TestStats:\n    def test_a(self):\n        pass\n"
        frozen = base + "    def test_mean_of_two(self):\n        pass\n"
        it = item(allowed_paths=["stats.py"], tests=[{"id": "test_stats.py::TestStats::test_mean_of_two"}],
                  adds=[{"kind": "test", "name": "test_stats.py::TestStats::test_mean_of_two", "canonical": "test_stats.py に新設"}])
        ch = {**STATS, "test_stats.py": (base, frozen)}
        self.assertEqual(planscope.problems([it], [ROW], ch, loop={"test_stats.py": frozen})[0], [])

    def test_declared_untouched_frozen_file_not_rejected(self):
        """行が凍った後に変わっていないファイル（範囲の外）を申告しても拒まない"""
        ch = {**STATS, "data.json": (None, "[]\n")}
        rows = [{"unit_key": MEAN, "files": ["stats.py", "data.json"]}]
        self.assertEqual(planscope.problems([ITEM], rows, ch, loop={"data.json": "[]\n"})[0], [])

    def test_same_name_in_untouched_lines_of_other_file_is_gone(self):
        """名を含む行に触れていない別の .py に同じ名の定義が在っても、残ったとは見ない"""
        it = item(allowed_paths=["*.py"], removes=["old_mean"])
        ch = {"stats.py": ("def old_mean():\n    pass\n", "def mean():\n    pass\n"),
              "util.py": ("def old_mean():\n    pass\n\n\nA = 1\n", "def old_mean():\n    pass\n\n\nA = 2\n")}
        rows = [{"unit_key": MEAN, "files": ["stats.py", "util.py"]}]
        self.assertEqual(planscope.problems([it], rows, ch)[0], [])


if __name__ == "__main__":
    unittest.main()
