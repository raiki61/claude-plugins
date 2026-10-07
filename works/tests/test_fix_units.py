"""修正の受け付けの単位ごとの閉鎖の表（blk-fix/lib/unitrows.py）と、裁定の出どころの縛り（blk-fix/lib/ruling.py の grounds）。

- 閉鎖は機械の数え直しで決め、修正役の申告（closure.sites の path が覆う問いの当たりの件数・remaining・作り直した how）と合わない形は拒まずに表の
  discrepancies に記録する。写しに渡す返答は、写しの数え合わせの拒否が発火しないように揃える（sites を母数に切る・空の
  remaining に機械の記録を書く）。裁定 replace_query を受けた単位は置き換えた問いで数える
- 表の行は最後の関所と報告に載る（querytest.closure_lines。合わない単位だけが関所を開ける理由）
- 依頼のファイルが在る run の ask_human は、依頼の行（grounds）か request_searched が無ければ拒む。grounds は現物で引く
盤面・git・子のプロセスは使わない（数える口と盤面は偽物）。
"""
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import querytest  # noqa: E402
import ruling  # noqa: E402
import unitrows  # noqa: E402

KEY = "stats.py clamp: 上限を超えた値に lo を返す"
HOW = {"patterns": ["return lo"], "paths": ["stats.py"], "count": "lines", "fixed": True}


def blank(s, n):
    return len((s or "").strip()) < n


def change(sites=1, remaining=None, how=None):
    c = {"unit_key": KEY, "files": ["stats.py"], "what": "直した",
         "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                     "sites": [{"site": f"s{i}", "red_seen": i == sites - 1} for i in range(sites)]}}
    if remaining or how:
        c["coverage"] = {**({"remaining": remaining} if remaining else {}), **({"how": how} if how else {})}
    return c


class BuildCase(unittest.TestCase):
    def build(self, c, *, total, after, counts="defects", judged_total=None, replaced=None):
        seen = []

        def count(how, at_rev):
            seen.append((how, at_rev))
            return (total if at_rev else after), ""
        jq = {"how": HOW, "counts": counts, **({"total": judged_total} if judged_total is not None else {})}
        out, rows = unitrows.build([c], {KEY: jq}, count=count, blank=blank, replaced=replaced)
        return out[0], rows[0], seen

    def test_honest_closed_reply_is_passed_as_is(self):
        c = change(sites=2)
        got, row, _ = self.build(c, total=2, after=0)
        self.assertEqual((row["closed"], row["discrepancies"]), (True, []))
        self.assertEqual(got["closure"], c["closure"])
        self.assertNotIn("remaining", got["coverage"])
        self.assertEqual(got["coverage"]["how"], HOW, "写しと同じ問い（判定者の how）で数えたことを返答に残す")

    def test_defects_left_after_claimed_all_is_recorded_not_rejected(self):
        got, row, _ = self.build(change(sites=2), total=2, after=1)
        self.assertIs(row["closed"], False)
        self.assertTrue(any("修正後も 1 件" in d for d in row["discrepancies"]), row)
        self.assertTrue(got["coverage"]["remaining"].startswith(unitrows.MACHINE_REMAINING),
                        "写しの defects の拒否が発火しないように、機械の記録を remaining に書く")

    def test_sites_over_population_are_cut_keeping_red(self):
        got, row, _ = self.build(change(sites=3), total=1, after=0)
        self.assertTrue(any("超える" in d for d in row["discrepancies"]), row)
        self.assertEqual(len(got["closure"]["sites"]), 1)
        self.assertTrue(got["closure"]["sites"][0]["red_seen"], "赤を見た site を先に残す（写しの fix_closure の柵）")
        self.assertEqual(row["claimed"], 3, "表には申告の元の件数を残す")

    def test_missing_remaining_is_recorded(self):
        got, row, _ = self.build(change(sites=1), total=3, after=2, counts="population")
        self.assertIs(row["closed"], False)
        self.assertTrue(any("remaining が無い" in d for d in row["discrepancies"]), row)
        self.assertIn("remaining", got["coverage"])

    def test_fixer_remaining_is_no_discrepancy(self):
        got, row, _ = self.build(change(sites=1, remaining="残りの 2 か所は次の周で塞ぐ（別の単位の直しを待つ）"),
                                 total=3, after=2, counts="population")
        self.assertEqual(row["discrepancies"], [])
        self.assertEqual(got["coverage"]["remaining"], "残りの 2 か所は次の周で塞ぐ（別の単位の直しを待つ）")

    def test_replaced_query_counts_and_names_the_ruling(self):
        new = {**HOW, "patterns": ["return lo  # hi"]}
        got, row, seen = self.build(change(sites=1), total=1, after=0, judged_total=2,
                                    replaced={KEY: {"id": "c1-1", "how": new, "counts": "defects", "hits": ["x"], "misses": []}})
        self.assertEqual({h["patterns"][0] for h, _ in seen}, {"return lo  # hi"}, "置き換えた問いで数える")
        self.assertEqual((row["how_from"], row["closed"], row["discrepancies"]), ("裁定 c1-1", True, []))
        self.assertEqual(got["coverage"]["how"], new)
        self.assertIn("c1-1", got["coverage"]["remaining"], "判定者の母数より狭い問いの理由は裁定")

    def test_replaced_query_counts_direction_comes_from_the_ruling(self):
        # 判定者は population、裁定は defects: 向きは裁定の counts。修正後も数えれば site が母数に届いても閉じていない
        got, row, _ = self.build(change(sites=1), total=1, after=1, counts="population",
                                 replaced={KEY: {"id": "c1-1", "how": HOW, "counts": "defects", "hits": ["x"], "misses": []}})
        self.assertEqual((row["counts"], row["closed"]), ("defects", False), row)
        self.assertTrue(any("修正後も 1 件" in d for d in row["discrepancies"]), row)

    def test_closed_is_decided_by_the_judge_query_not_the_fixer_how(self):
        narrow = {**HOW, "patterns": ["return lo  # none"]}

        def count(how, at_rev):
            if how == narrow:
                return (0, "") if not at_rev else (0, "")
            return (2, "") if at_rev else (1, "")
        c = change(sites=0, remaining="判定者の問いは広すぎるので狭めた（下限の枝も数える）", how=narrow)
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects", "total": 2}}, count=count, blank=blank)
        self.assertEqual(rows[0]["how_from"], "修正役")
        self.assertIs(rows[0]["closed"], False, "修正役が狭めた問いで 0 件でも、判定者の問いで残れば閉じていない")
        self.assertEqual((rows[0]["total"], rows[0]["after"]), (2, 1))
        self.assertEqual(out[0]["coverage"]["how"], narrow, "写しには修正役の how を渡す（写しは作り直しとして採る）")

    def test_uncountable_row_is_left_to_the_copy(self):
        c = change()
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (None, "走らない"),
                                   blank=blank)
        self.assertEqual((out, rows), ([c], []))


class SitePathCase(unittest.TestCase):
    """site の path（works だけの任意の欄）で申告を問いの当たりにファイル単位で結び、単位の違う数（site の件数と行数）を直に比べない"""

    def build(self, sites, *, total, after, files, counts="defects", remaining=None, touched=("stats.py", "a.py")):
        """touched は修正が変えたファイル（site の path が指す当たりのファイルも、変わっていなければ覆いに数えない。SiteNeedsChangeCase）"""
        import inspect
        if "per_file" not in inspect.signature(unitrows.build).parameters:
            self.fail("unitrows.build がファイルごとの数（per_file）を受けない: site の件数を行数の母数と直に比べるしかない")
        c = {"unit_key": KEY, "files": ["stats.py"], "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v", "sites": sites}}
        if remaining:
            c["coverage"] = {"remaining": remaining}

        def count(how, at_rev):
            return (total if at_rev else after), ""

        def per_file(how, at_rev):
            return (files if at_rev else {}), ""
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": counts}}, count=count, blank=blank,
                                   per_file=per_file, touched=list(touched))
        return out[0], rows[0]

    def test_sites_outside_the_query_are_listed_not_counted_as_mismatch(self):
        sites = [{"site": "上限の枝", "red_seen": True, "path": "stats.py"},
                 {"site": "下限の枝", "red_seen": False, "path": "./stats.py"},
                 {"site": "試験", "red_seen": False, "path": "tests/test_stats.py"},
                 {"site": "文書", "red_seen": False, "path": "README.md"}]
        got, row = self.build(sites, total=2, after=0, files={"stats.py": 2})
        self.assertEqual(row["discrepancies"], [], "試験・文書の site と同じファイルの 2 件目は『超える』に数えない")
        self.assertEqual(row["covered"], 2)
        self.assertEqual(sorted(row["out_of_query"]), ["README.md", "tests/test_stats.py"],
                         "問いの外に並べた site のパスは見えるまま表に残す")
        self.assertIs(row["closed"], True)
        self.assertEqual(row["claimed"], 4)
        self.assertFalse(any("path" in s for s in got["closure"]["sites"]), "写しの sites は additionalProperties: false")

    def test_sites_piled_on_one_file_do_not_cover_other_files(self):
        sites = [{"site": f"s{i}", "red_seen": i == 0, "path": "a.py"} for i in range(3)]
        _, row = self.build(sites, total=3, after=1, files={"a.py": 2, "b.py": 1}, counts="population",
                              remaining="b.py の 1 件は並行の線の担当")
        self.assertEqual(row["covered"], 2, "同じファイルの site はそのファイルの件数を 1 回だけ足す")
        self.assertEqual(row["discrepancies"], [], row)
        self.assertIs(row["closed"], False, "population の closed は覆った当たりの件数で決める（同じファイルの site は増えない）")

    def test_sites_without_path_fall_back_to_the_site_count_with_a_reason(self):
        sites = [{"site": "上限の枝", "red_seen": True, "path": "stats.py"}, {"site": "試験", "red_seen": False}]
        _, row = self.build(sites, total=1, after=0, files={"stats.py": 1})
        self.assertTrue(row["discrepancies"][0].startswith("path が無い site 1 件"), row)
        self.assertTrue(any("超える" in d for d in row["discrepancies"]), row)

    def test_per_file_sum_not_matching_the_total_is_not_used_silently(self):
        sites = [{"site": "上限の枝", "red_seen": True, "path": "stats.py"}, {"site": "試験", "red_seen": False,
                                                                          "path": "tests/test_stats.py"}]
        _, row = self.build(sites, total=1, after=0, files={"stats.py": 3})
        self.assertTrue(any("ファイルごとの数が合計と合わない" in d for d in row["discrepancies"]), row)
        self.assertTrue(any("超える" in d for d in row["discrepancies"]), "今の数え方（len(sites)）で比べる")

    def test_shaping_leaves_the_callers_rows_as_written(self):
        """写しに渡す形に揃える（path を外す・coverage.how と remaining を書く・sites を切る）のは写しの上で、渡した行は変えない
        （受け付けは揃える前の行を 1 回目の返答の控えに残し、2 回目の修正の段がそれを数え直しに当て直す。依頼 195i の 1）"""
        sites = [{"site": f"s{i}", "red_seen": i == 0, "path": "stats.py"} for i in range(3)]
        c = {"unit_key": KEY, "files": ["stats.py"], "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v", "sites": sites},
             "coverage": {"counts": "defects"}}
        before = json.loads(json.dumps(c))
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (1, ""), blank=blank,
                                   per_file=lambda h, r: ({"stats.py": 1} if r else {}, ""))
        self.assertEqual(c, before, "揃えは写しの上で（渡した行を変えない）")
        self.assertNotEqual(out[0], before)
        self.assertIs(rows[0]["bound"], True)
        again, rows2 = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (1, ""), blank=blank,
                                      per_file=lambda h, r: ({"stats.py": 1} if r else {}, ""))
        self.assertEqual((again, rows2), (out, rows), "書いた形の行に当て直せば 1 回目と同じ表（2 回目の段の数え直し）")
        _, shaped_rows = unitrows.build(out, {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (1, ""),
                                        blank=blank, per_file=lambda h, r: ({"stats.py": 1} if r else {}, ""))
        self.assertIs(shaped_rows[0]["bound"], False, "揃えた後の行（path が無い）では結べない（だから控えは書いた形で残す）")

    def test_uncountable_row_still_drops_path_before_the_copy(self):
        c = {"unit_key": KEY, "files": ["stats.py"], "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": "s", "red_seen": True, "path": "stats.py"}]}}
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (None, "走らない"),
                                   blank=blank)
        self.assertEqual(rows, [])
        self.assertEqual(out[0]["closure"]["sites"], [{"site": "s", "red_seen": True}], "写しに任せる行も path を外す")


class ChangedFilesCoverCase(unittest.TestCase):
    """population の問いの当たりのファイルは、site の path が名指さなくても、その単位の files に在って修正前の版から実際に
    変わったファイル（touched）なら覆ったと数える。canary の run a2097fd6（2026-10-07）の盤面の形: 判定の問いは mean の定義・
    TestCalc のクラス・CHANGELOG の [Unreleased] の 3 行（3 ファイルに 1 行ずつ）で、修正役は 3 ファイルを全部直して files に
    並べたのに、site はコードの 1 か所（path calc.py）だけを書いた。表は covered 1・closed false になり、検証器の『未解消』が
    報告に残って round_limit になった（差分は 2 単位とも正しく直し、最後のテストは緑）"""
    MEAN = "calc.py:mean — 分母が個数でなく個数-1で docstring の算術平均に反する"
    HOW3 = {"patterns": ["def mean(", "class TestCalc(", "## [Unreleased]"],
            "paths": ["calc.py", "test_lib.py", "CHANGELOG.md"], "count": "lines", "fixed": True}
    HITS = {"calc.py": 1, "test_lib.py": 1, "CHANGELOG.md": 1}

    def build(self, touched, files=("calc.py", "test_lib.py", "CHANGELOG.md")):
        import inspect
        if "touched" not in inspect.signature(unitrows.build).parameters:
            self.fail("unitrows.build が修正の変えたファイル（touched）を受けない: site の path だけで覆いを数え、"
                      "直して files に並べた当たりのファイルを覆っていないと数える")
        c = {"unit_key": self.MEAN, "files": list(files), "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": "calc.py:8 mean の分母", "red_seen": True, "path": "calc.py"}]}}
        out, rows = unitrows.build([c], {self.MEAN: {"how": self.HOW3, "counts": "population", "total": 3}},
                                   count=lambda h, at_rev: (3, ""), blank=blank,
                                   per_file=lambda h, at_rev: (dict(self.HITS), ""), touched=touched)
        return out[0], rows[0]

    def test_board_shape_of_run_a2097fd6_is_closed(self):
        got, row = self.build(["CHANGELOG.md", "calc.py", "test_lib.py", "textfmt.py"])
        self.assertEqual((row["covered"], row["closed"], row["discrepancies"]), (3, True, []), row)
        self.assertEqual(row["claimed"], 1, "表には申告の site の件数を残す")
        self.assertEqual(row["changed_cover"], ["CHANGELOG.md", "test_lib.py"],
                         "site が名指さず、単位の files と修正の変更で覆った当たりのファイルを表に残す")
        self.assertGreaterEqual(len(got["coverage"].get("remaining") or ""), unitrows.MIN_REMAINING,
                                "写しは site の件数（1 < 母数 3）で拒むので、機械が remaining を書いて渡す")

    def test_hit_file_not_changed_stays_open(self):
        _, row = self.build(["calc.py", "test_lib.py"])
        self.assertEqual((row["covered"], row["closed"]), (2, False), row)
        self.assertTrue(any("remaining が無い" in d for d in row["discrepancies"]), row)

    def test_changed_file_not_in_the_units_files_does_not_cover(self):
        _, row = self.build(["CHANGELOG.md", "calc.py", "test_lib.py"], files=("calc.py", "test_lib.py"))
        self.assertEqual((row["covered"], row["closed"]), (2, False), "別の単位の直しで変わったファイルを、この単位の覆いに数えない")

    def test_without_touched_nothing_covers(self):
        """変更が読めなければ site の path が指す calc.py も変わったと確かめられないので覆わない（前は site の path だけで 1 件を
        覆った。path だけで覆うと、名指して変えなかったファイルも閉じる。SiteNeedsChangeCase）"""
        _, row = self.build(None)
        self.assertEqual((row["covered"], row["closed"], row["changed_cover"]), (0, False, []), row)
        self.assertEqual(row["discrepancies"][0], unitrows.UNKNOWN_CHANGES, row)

    def test_take_hands_the_changes_since_the_review_rev(self):
        """take は受け付けの書き込みの照らしと同じ変更の集合（writes.changed を盤面の review_rev から）を build に渡す。
        git が読めなければ変更では覆わない（None）"""
        from unittest import mock
        b = types.SimpleNamespace(
            record={"process": {"diagnosis": {"units": [{"key": self.MEAN, "class_query": {"how": self.HOW3,
                                                                                           "counts": "population"}}]}}},
            state={"graph": "/g", "inputs": {"review_rev": "rev0"}}, loop_state={}, round=1)
        reply = {"changes": [{"unit_key": self.MEAN, "files": ["calc.py"], "what": "直した"}]}
        R = types.SimpleNamespace(_run_query=lambda *a, **k: (3, ""), blank=blank)
        for changed, want in ((lambda repo, rev: ["calc.py"] if rev == "rev0" else [], ["calc.py"]),
                              (mock.Mock(side_effect=unitrows.Unreadable("x")), None)):
            seen = []
            with self.subTest(want=want), \
                    mock.patch.object(unitrows._board, "rules_module", return_value=R), \
                    mock.patch.object(unitrows.writes, "changed", side_effect=changed), \
                    mock.patch.object(unitrows.conflict, "replaced_queries", return_value={}), \
                    mock.patch.object(unitrows, "build", side_effect=lambda ch, j, **k: seen.append(k["touched"]) or (ch, [])):
                unitrows.take(reply, b, pathlib.Path("/r"))
            self.assertEqual(seen, [want])


class PopulationMembersCase(unittest.TestCase):
    """population の当たりは修正が変える物の全部（直す対象の母集団）で、閉じたかは当たりを全部覆ったかで決める。canary の
    large の 2 つの run の盤面の形（2026-10-07）: 『公開の関数に docstring が無い』単位で、b44c480f の判定は欠けた 2 つの def を
    名指す問い（当たり 2）にして、修正役が 2 つのファイルに docstring を足して閉じた。a2fcf33a の判定は決まりがかかる範囲の全部
    （5 つのモジュールの公開関数 14 本。うち 12 本はもう docstring を持つ）を数え、同じ正しい直しが覆うのは 4 件で閉じず、
    検証器の『未解消』で round_limit になった。もう正しい物は修正が変えないので、機械は『直さなくてよい物』と『直し漏らした物』を
    分けられない——閉鎖の決まりは緩めず、広すぎる問いは判定の問いの書き方（diagnose.md 6 項）と、修正役の申し出 query
    （裁定 replace_query が問いを置き換える）で直す"""
    KEY = "money.py:split_even・slugs.py:slugify — 公開の関数に約束の docstring が無く help() に約束が出ない"
    RULE = {"patterns": ["^def [a-z]"], "paths": ["stats.py", "textfmt.py", "units.py", "money.py", "slugs.py"], "count": "lines"}
    RULE_HITS = {"stats.py": 4, "textfmt.py": 3, "units.py": 3, "money.py": 2, "slugs.py": 2}
    MEMBERS = {"patterns": ["def split_even(", "def slugify("], "paths": ["money.py", "slugs.py"], "count": "lines", "fixed": True}
    MEMBER_HITS = {"money.py": 1, "slugs.py": 1}

    def build(self, judged_how, *, touched=("money.py", "slugs.py"), remaining=None, replaced=None):
        hits = {json.dumps(self.RULE): self.RULE_HITS, json.dumps(self.MEMBERS): self.MEMBER_HITS}
        # 修正役は変えたファイルだけを files と site に書く（直し漏らした物は名指さない）
        names = {"money.py": "money.py:split_even", "slugs.py": "slugs.py:slugify"}
        c = {"unit_key": self.KEY, "files": list(touched), "what": "docstring を足した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": names[p], "red_seen": False, "path": p} for p in touched]}}
        if remaining:
            c["coverage"] = {"remaining": remaining}
        total = sum(hits[json.dumps(judged_how)].values())
        out, rows = unitrows.build([c], {self.KEY: {"how": judged_how, "counts": "population", "total": total}},
                                   count=lambda h, at_rev: (sum(hits[json.dumps(h)].values()), ""), blank=blank,
                                   per_file=lambda h, at_rev: (dict(hits[json.dumps(h)]), ""), touched=list(touched),
                                   replaced=replaced)
        return out[0], rows[0]

    def test_members_query_closes_the_correct_fix(self):
        """b44c480f の形: 問いは欠けた物だけを名指し（当たり 2）、正しい直しは 2 つとも覆って閉じる"""
        _, row = self.build(self.MEMBERS)
        self.assertEqual((row["total"], row["after"], row["covered"], row["closed"], row["discrepancies"]),
                         (2, 2, 2, True, []), row)

    def test_members_query_stays_open_when_the_fix_misses_a_member(self):
        """直し漏らした物（slugs.py を変えず、名指してもいない）は閉じない（閉鎖の決まりを緩めていない）"""
        _, row = self.build(self.MEMBERS, touched=("money.py",))
        self.assertEqual((row["covered"], row["closed"]), (1, False), row)

    def test_rule_domain_query_stays_open_even_with_remaining(self):
        """a2fcf33a の形: 問いがもう正しい 12 本も数えると、正しい直しも 4 件しか覆わず閉じない。remaining は黙って残さない
        ための記録で、閉じる理由にはならない（『直さなくてよい』と書くだけで閉じるなら、直し漏らしも同じ文で閉じる）"""
        for remaining in (None, "残りの 12 本はもう docstring を持つので直さない"):
            with self.subTest(remaining=remaining):
                _, row = self.build(self.RULE, remaining=remaining)
                self.assertEqual((row["total"], row["after"], row["covered"], row["closed"]), (14, 14, 4, False), row)
                self.assertEqual(any("remaining が無い" in d for d in row["discrepancies"]), remaining is None, row)

    def test_rule_domain_query_replaced_by_a_ruling_closes(self):
        """同じ形で修正役が query の申し出を出し、裁定 replace_query が欠けた物だけを名指す問いに置き換えれば、正しい直しは閉じ、
        直し漏らしは閉じない"""
        ruled = {self.KEY: {"id": "c1-1", "how": self.MEMBERS, "counts": "population",
                            "hits": ["def split_even(total, n):"], "misses": ["def format_yen(amount):"]}}
        got, row = self.build(self.RULE, replaced=ruled)
        self.assertEqual((row["how_from"], row["total"], row["covered"], row["closed"], row["discrepancies"]),
                         ("裁定 c1-1", 2, 2, True, []), row)
        self.assertIn("c1-1", got["coverage"]["remaining"], "判定者の母数より狭い理由は裁定（機械が書く）")
        _, row = self.build(self.RULE, replaced=ruled, touched=("money.py",))
        self.assertEqual((row["covered"], row["closed"]), (1, False), row)



class SiteNeedsChangeCase(unittest.TestCase):
    """site の path が名指す当たりのファイルも、修正前の版から実際に変わったファイル（touched）でなければ覆ったと数えない
    （問いの種類に依らない）。審査の再現: population の問いの当たりが 5 ファイルに 14 行で、修正役が 5 ファイルを全部 site に
    並べて 2 ファイルだけを変えると、site の path だけで 14 件を覆ったと数えて単位が閉じた（直し漏らしが閉じたと報告される）"""
    KEY = PopulationMembersCase.KEY
    RULE, RULE_HITS = PopulationMembersCase.RULE, PopulationMembersCase.RULE_HITS
    DEF_HOW = {"patterns": ["return lo"], "paths": ["a.py", "b.py"], "count": "lines", "fixed": True}
    DEF_HITS = {"a.py": 2, "b.py": 1}

    def build(self, how, hits, *, counts, sites, files, touched, after, remaining=None):
        c = {"unit_key": self.KEY, "files": list(files), "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": f"{p}:1", "red_seen": False, "path": p} for p in sites]}}
        if remaining:
            c["coverage"] = {"remaining": remaining}
        total = sum(hits.values())
        out, rows = unitrows.build([c], {self.KEY: {"how": how, "counts": counts, "total": total}},
                                   count=lambda h, at_rev: ((total if at_rev else after), ""), blank=blank,
                                   per_file=lambda h, at_rev: (dict(hits), ""), touched=touched)
        return out[0], rows[0]

    def test_reviewer_reproduction_stays_open(self):
        """5 ファイルを site に並べ、2 ファイルだけを変えた直しは閉じない（files に 5 つ並べても、2 つだけ並べても）"""
        five = sorted(self.RULE_HITS)
        for files in (("money.py", "slugs.py"), five):
            with self.subTest(files=files):
                _, row = self.build(self.RULE, self.RULE_HITS, counts="population", sites=five, files=files,
                                    touched=["money.py", "slugs.py"], after=14)
                self.assertEqual((row["total"], row["covered"], row["closed"]), (14, 4, False), row)
                self.assertEqual(row["unchanged_sites"], ["stats.py", "textfmt.py", "units.py"],
                                 "site が名指したが修正で変わっていない当たりのファイルを表に残す")
                self.assertTrue(any("remaining が無い" in d for d in row["discrepancies"]), row)

    def test_population_fix_changing_every_named_file_closes(self):
        five = sorted(self.RULE_HITS)
        _, row = self.build(self.RULE, self.RULE_HITS, counts="population", sites=five, files=five, touched=five, after=14)
        self.assertEqual((row["covered"], row["closed"], row["discrepancies"], row["unchanged_sites"]),
                         (14, True, [], []), row)

    def test_defects_fix_closes_when_the_hits_drop_to_zero(self):
        _, row = self.build(self.DEF_HOW, self.DEF_HITS, counts="defects", sites=["a.py", "b.py"], files=["a.py", "b.py"],
                            touched=["a.py", "b.py"], after=0)
        self.assertEqual((row["covered"], row["closed"], row["discrepancies"], row["unchanged_sites"]),
                         (3, True, [], []), row)

    def test_defects_site_on_an_unchanged_file_does_not_cover(self):
        """defects の closed は修正後の数で決まる（変わっていないファイルの当たりは減らない）。覆いの数も変わった物だけにする"""
        _, row = self.build(self.DEF_HOW, self.DEF_HITS, counts="defects", sites=["a.py", "b.py"], files=["a.py", "b.py"],
                            touched=["a.py"], after=1)
        self.assertEqual((row["covered"], row["closed"], row["unchanged_sites"]), (2, False, ["b.py"]), row)
        self.assertFalse(any("全部塞いだと申告" in d for d in row["discrepancies"]),
                         "変わっていないファイルを名指した site は塞いだ申告に数えない")

    def test_without_touched_sites_do_not_cover(self):
        """修正の変えたファイルが読めない時は、site の path が指すファイルも変わったと確かめられないので覆いに数えず、理由を残す"""
        five = sorted(self.RULE_HITS)
        _, row = self.build(self.RULE, self.RULE_HITS, counts="population", sites=five, files=five, touched=None, after=14)
        self.assertEqual((row["covered"], row["closed"], row["changed_cover"]), (0, False, []), row)
        self.assertEqual(row["discrepancies"], [unitrows.UNKNOWN_CHANGES],
                         "覆いを数えなかった理由だけを書き、覆いから出る食い違い（remaining が無い）を重ねない")

    def test_shortfall_reads_as_covered_by_the_fix(self):
        """食い違いの文は覆いの新しい意味（修正で変わった当たり）で書く（site は 14 件全部を名指している）"""
        five = sorted(self.RULE_HITS)
        _, row = self.build(self.RULE, self.RULE_HITS, counts="population", sites=five, files=five,
                            touched=["money.py", "slugs.py"], after=14)
        self.assertIn("母数 14 のうち修正で覆った当たりは 4 件で、remaining が無い", row["discrepancies"], row)

    def test_judged_query_that_cannot_be_bound_is_named(self):
        """修正役が問いを作り直した単位は判定者の問いで結び直す。そこで結べない（site の件数で数えた）理由も表に出す
        （捨てると、site を名指しただけで変えていない単位が黙って閉じる）"""
        mine = {**self.RULE, "paths": ["money.py", "slugs.py", "units.py"]}
        c = {"unit_key": self.KEY, "files": ["units.py"], "what": "直した",
             "coverage": {"how": mine, "remaining": "money.py と slugs.py は並行の線の担当で、今の周では塞がない"},
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": f"{p}:1", "red_seen": False, "path": p} for p in ("money.py", "slugs.py", "units.py")]}}
        mine_hits = {"money.py": 2, "slugs.py": 2, "units.py": 3}

        def per_file(h, at_rev):
            return (dict(mine_hits), "") if h == mine else (None, "走らない")
        _, rows = unitrows.build([c], {self.KEY: {"how": self.RULE, "counts": "population", "total": 14}},
                                 count=lambda h, at_rev: ((7, "") if h == mine else (14, "")), blank=blank,
                                 per_file=per_file, touched=[])
        row = rows[0]
        self.assertTrue(any(d.startswith("判定者の問いで") and "走らない" in d for d in row["discrepancies"]), row)


class ClosureLinesCase(unittest.TestCase):
    def test_lines_and_mismatched_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        b = types.SimpleNamespace(dir=pathlib.Path(tmp.name), round=1, scope_root=pathlib.Path(tmp.name))
        self.assertEqual(querytest.closure_lines(b), [])
        rows = [{"unit_key": "a", "closed": True, "discrepancies": []},
                {"unit_key": "b", "closed": False, "discrepancies": []},
                {"unit_key": "c", "closed": True, "discrepancies": ["合わない"]}]
        querytest.save_closure(b, rows)
        self.assertEqual(json.loads((b.dir / querytest.CLOSURE_FILE).read_text(encoding="utf-8"))["round"], 1)
        self.assertEqual([x.split(":")[0] for x in querytest.closure_lines(b)], ["b", "c"])
        self.assertEqual([x.split(":")[0] for x in querytest.closure_lines(b, mismatched_only=True)], ["c"])
        b.round = 2
        self.assertEqual(querytest.closure_lines(b), [], "前の周の表は読まない")


    def test_line_names_site_files_the_fix_did_not_change(self):
        """site が名指したが修正で変わっていない当たりのファイルを行に並べる（申告の site の数と覆った数が食い違う理由が行で読める）"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b = types.SimpleNamespace(dir=pathlib.Path(tmp.name), round=1, scope_root=pathlib.Path(tmp.name))
        querytest.save_closure(b, [{"unit_key": "a", "counts": "population", "total": 14, "after": 14, "claimed": 5,
                                    "covered": 4, "bound": True, "closed": False, "how_from": "判定者",
                                    "unchanged_sites": ["stats.py", "units.py"], "discrepancies": []}])
        line, = querytest.closure_lines(b)
        self.assertIn("修正で覆った当たり 4", line)
        self.assertIn("site が名指したが修正で変わっていない当たりのファイル: stats.py, units.py", line)

class ClosureScopesCase(unittest.TestCase):
    def test_rows_come_from_the_last_include_with_this_round(self):
        """閉鎖の表は修正のブロックの include ごとに scope の根に在る（依頼 239）。今の周の表のうち最後に登録した include の物を
        読み、前の周の表しか無い include は飛ばす（後に登録した include の古い表で今の周の行を消さない）"""
        import scopes
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        for scope in ("fixing", "refitting"):
            scopes.claim(d, 2, scope, "blk-fix")
        for scope, rnd, key in (("fixing", 2, "a"), ("refitting", 1, "b")):
            querytest.save_closure(types.SimpleNamespace(dir=d, round=rnd, scope_root=d / scope),
                                   [{"unit_key": key, "closed": False, "discrepancies": []}])
        b = types.SimpleNamespace(dir=d, round=2, scope_root=d)
        self.assertEqual([r["unit_key"] for r in querytest.closure_rows(b)], ["a"])
        querytest.save_closure(types.SimpleNamespace(dir=d, round=2, scope_root=d / "refitting"),
                               [{"unit_key": "c", "closed": True, "discrepancies": []}])
        self.assertEqual([r["unit_key"] for r in querytest.closure_rows(b)], ["c"])


class StuckLinesCase(unittest.TestCase):
    """直したのに判定の問いの当たりが減っていない単位（defects で total>0 かつ after>=total）は、申告と合わない単位と別の見出しに出す"""

    def lines(self, rows, **kw):
        import inspect
        if "stuck_only" not in inspect.signature(querytest.closure_lines).parameters:
            self.fail("closure_lines が減っていない単位だけを返す口（stuck_only）を持たない: 合わない単位と同じ 1 節に埋もれる")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b = types.SimpleNamespace(dir=pathlib.Path(tmp.name), round=1, scope_root=pathlib.Path(tmp.name))
        querytest.save_closure(b, rows)
        return [x.split(":")[0] for x in querytest.closure_lines(b, **kw)]

    def test_stuck_defects_get_their_own_head_and_leave_the_closure_section(self):
        head = getattr(querytest, "STUCK_HEAD", None)
        if not isinstance(head, str) or not head or head == querytest.CLOSURE_HEAD:
            self.fail("減っていない単位の見出し STUCK_HEAD が CLOSURE_HEAD と別に無い")
        rows = [{"unit_key": "stuck", "counts": "defects", "total": 23, "after": 23, "closed": False, "discrepancies": []},
                {"unit_key": "stuck-claimed", "counts": "defects", "total": 16, "after": 16, "closed": False,
                 "discrepancies": ["母数 16 を全部塞いだと申告したが、修正後も 16 件を数える"]},
                {"unit_key": "fewer", "counts": "defects", "total": 5, "after": 2, "closed": False, "discrepancies": []},
                {"unit_key": "pop", "counts": "population", "total": 3, "after": 3, "closed": False, "discrepancies": []},
                {"unit_key": "empty", "counts": "defects", "total": 0, "after": 0, "closed": True, "discrepancies": []},
                {"unit_key": "noise", "counts": "defects", "total": 2, "after": 0, "closed": True, "discrepancies": ["合わない"]}]
        self.assertEqual(self.lines(rows, stuck_only=True), ["stuck", "stuck-claimed"])
        self.assertEqual(self.lines(rows), ["fewer", "pop", "noise"],
                         "減ったが閉じていない defects と population の閉じていない単位は今の節に残り、減っていない単位は二重に並べない")
        self.assertEqual(self.lines(rows, mismatched_only=True), ["stuck-claimed", "noise"],
                         "関所を開ける理由（合わない単位）は今と同じ")


class GroundsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "stats.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        self.request = pathlib.Path(tmp.name) / "request.md"
        self.request.write_text("# 依頼\n- 分母は len(xs)\n", encoding="utf-8")
        self.todo = {"c1-1": {"id": "c1-1", "unit_key": KEY, "which_is_right": "unknown"}}

    def errs(self, **extra):
        reply = {"rulings": [{"id": "c1-1", "decision": "ask_human", "text": "方針の変更で人が決める", "limits": [], **extra}]}
        return ruling.problems(reply, self.todo, self.repo, str(self.request), (str(self.request),))

    def test_ask_human_needs_request_line_or_search(self):
        self.assertTrue(any("request_searched" in e for e in self.errs()), "依頼の在る run の出どころの無い ask_human は拒む")
        self.assertEqual(self.errs(request_searched="依頼に分母の答えを探したが無い"), [])
        self.assertEqual(self.errs(grounds=[f"{self.request}:2"]), [])
        self.assertTrue(self.errs(grounds=["stats.py:1"]), "依頼の外の名指しだけでは、依頼を当たった証拠にならない")

    def test_grounds_are_checked_against_the_tree(self):
        self.assertTrue(any("無い" in e or "外" in e for e in self.errs(grounds=[f"{self.request}:9"])))
        self.assertTrue(self.errs(grounds=["nope.py:1"], request_searched="依頼に分母の答えを探したが無い"))

    def test_run_without_request_does_not_bind(self):
        reply = {"rulings": [{"id": "c1-1", "decision": "ask_human", "text": "方針の変更で人が決める", "limits": []}]}
        self.assertEqual(ruling.problems(reply, self.todo, self.repo), [])


if __name__ == "__main__":
    unittest.main()
