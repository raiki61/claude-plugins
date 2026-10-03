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

    def build(self, sites, *, total, after, files, counts="defects", remaining=None):
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
                                   per_file=per_file)
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

    def test_uncountable_row_still_drops_path_before_the_copy(self):
        c = {"unit_key": KEY, "files": ["stats.py"], "what": "直した",
             "closure": {"mechanism": "m", "fix_mechanism": "f", "verified_how": "v",
                         "sites": [{"site": "s", "red_seen": True, "path": "stats.py"}]}}
        out, rows = unitrows.build([c], {KEY: {"how": HOW, "counts": "defects"}}, count=lambda h, r: (None, "走らない"),
                                   blank=blank)
        self.assertEqual(rows, [])
        self.assertEqual(out[0]["closure"]["sites"], [{"site": "s", "red_seen": True}], "写しに任せる行も path を外す")


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
