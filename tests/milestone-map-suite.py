#!/usr/bin/env python3
"""milestone-map.py の規則を pin する回帰テスト。GitHub には触らず、gh を固定の材料に差し替えて回す。

規則は milestone-map.py 冒頭の定義が正本で、ここはそれを入力で叩く。頼み（2026-11-04、guided-resolver の窓口）が
挙げた端の場合——依存 0 件・期日なし・期日切れ・閉じた件数の少ないマイルストーン——で HTML が壊れないことと、
モンテカルロの日付が乱数の種で決まることを固定する。
"""

import contextlib
import datetime as dt
import html.parser
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("milestone_map", ROOT / "attention" / "scripts" / "milestone-map.py")
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)
ghpage = sys.modules["ghpage"]

TODAY = dt.date(2026, 11, 4)
REPO = "o/r"


def issue(n, title=None, body="", blocked=(), parent=None, sub=(0, 0)):
    """open の issue の生の材料。blocked は (番号, 相手のマイルストーン, 状態, リポジトリ) の並び。"""
    nodes = [{"number": b, "title": f"blocker {b}", "url": f"https://github.com/{repo}/issues/{b}", "state": st,
              "repository": {"nameWithOwner": repo}, "milestone": {"number": ms} if ms else None}
             for b, ms, st, repo in blocked]
    return {"number": n, "title": title or f"issue {n}", "url": f"https://github.com/o/r/issues/{n}",
            "createdAt": "2026-08-01T00:00:00Z", "body": body,
            "parent": {"number": parent[0], "milestone": {"number": parent[1]} if parent[1] else None} if parent else None,
            "subIssuesSummary": {"total": sub[0], "completed": sub[1]},
            "blocking": {"totalCount": 0}, "blockedBy": {"totalCount": len(nodes), "nodes": nodes}}


def milestone(n, due=None, created="2026-06-01T00:00:00Z", issues=(), closed=(), desc="", prs=()):
    """マイルストーンの生の材料。closed は閉じた日（date）の並び。"""
    return {"number": n, "title": f"M{n}", "url": f"https://github.com/o/r/milestone/{n}", "description": desc,
            "dueOn": f"{due}T07:00:00Z" if due else None, "createdAt": created,
            "closedIssues": {"totalCount": len(closed) + 3},
            "pullRequests": {"totalCount": len(prs), "nodes": [
                {"number": p, "title": f"pr {p}", "url": f"https://github.com/o/r/pull/{p}", "isDraft": False} for p in prs]},
            "openIssues": list(issues),
            "closedRecent": [{"number": 900 + k, "closedAt": f"{d.isoformat()}T03:00:00Z"} for k, d in enumerate(closed)]}


def weeks_ago(*ks):
    return [TODAY - dt.timedelta(days=7 * k + 1) for k in ks]


def build(raw, **kw):
    kw.setdefault("trials", 500)
    return mm.build(raw, 0, REPO, TODAY, now=dt.datetime(2026, 11, 4, 9, tzinfo=dt.timezone.utc), **kw)


FIELDS = {"headline": "全体の一言", "points": ["点 1"], "notes": {}, "trays": []}


class Balance(html.parser.HTMLParser):
    """開きと閉じの対応を数える。void の要素は数えない。"""
    VOID = {"meta", "br", "input", "img", "hr", "link", "path", "line", "rect"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> に対応する開きが無い（開いている: {self.stack[-3:]}）")
        else:
            self.stack.pop()


def assert_page(test, page):
    test.assertNotIn("<script", page.lower())
    test.assertNotIn("<!--__BODY__-->", page)
    p = Balance()
    p.feed(page)
    test.assertEqual(p.errors, [])
    test.assertEqual(p.stack, [])
    test.assertIn("見ていないもの", page)
    test.assertIn("https://www.hanssamios.com/dokuwiki/why_a_plan_based_on_average_velocity_will_fail", page)


def page_of(data, fields=FIELDS):
    return mm.build_html(mm.TEMPLATE.read_text(encoding="utf-8"), data, fields)


class WeeklyClosed(unittest.TestCase):
    def test_counts_by_week_oldest_first(self):
        dates = [TODAY, TODAY - dt.timedelta(days=6), TODAY - dt.timedelta(days=7), TODAY - dt.timedelta(days=30)]
        self.assertEqual(mm.weekly_closed(dates, dt.date(2026, 1, 1), TODAY, weeks=5), [1, 0, 0, 1, 2])

    def test_weeks_before_creation_are_not_samples(self):
        # 20 日前に作ったマイルストーンは満ちた 2 週だけ（作る前と、作った日を含む端数の週を混ぜると見込みが遅く出る）
        self.assertEqual(len(mm.weekly_closed([], TODAY - dt.timedelta(days=20), TODAY, weeks=16)), 2)
        self.assertEqual(len(mm.weekly_closed([], TODAY - dt.timedelta(days=14), TODAY, weeks=16)), 2)

    def test_created_today_has_one_week(self):
        self.assertEqual(mm.weekly_closed([], TODAY, TODAY, weeks=16), [0])

    def test_older_than_window_is_dropped(self):
        self.assertEqual(mm.weekly_closed([TODAY - dt.timedelta(days=200)], None, TODAY, weeks=4), [0, 0, 0, 0])


class Forecast(unittest.TestCase):
    WEEKLY = [0, 3, 1, 4, 2, 0, 5, 2, 1, 3, 2, 4]

    def test_same_seed_same_dates(self):
        a = mm.forecast(20, self.WEEKLY, TODAY, seed=7, key=3, trials=2000)
        b = mm.forecast(20, self.WEEKLY, TODAY, seed=7, key=3, trials=2000)
        self.assertEqual(a, b)

    def test_seed_is_used(self):
        runs = {mm.forecast(20, self.WEEKLY, TODAY, seed=s, key=3, trials=200)["p85"] for s in range(1, 12)}
        self.assertGreater(len(runs), 1)

    def test_pinned_dates(self):
        # 規則（復元抽出・分位の取り方・週を今日に足す）を変えたら、ここが変わる
        f = mm.forecast(20, self.WEEKLY, TODAY, seed=1, key=1, trials=10000)
        self.assertEqual((f["weeks50"], f["weeks85"]), (9, 12))
        self.assertEqual((f["p50"], f["p85"]), ("2027-01-06", "2027-01-27"))

    def test_p50_not_after_p85(self):
        f = mm.forecast(37, self.WEEKLY, TODAY, trials=1000)
        self.assertLessEqual(f["p50"], f["p85"])

    def test_done_and_none(self):
        self.assertEqual(mm.forecast(0, [], TODAY)["state"], "done")
        self.assertEqual(mm.forecast(5, [0, 0, 0], TODAY)["state"], "none")

    def test_wide_when_few_samples(self):
        f = mm.forecast(3, [1, 0, 2], TODAY, trials=200)
        self.assertEqual(len(f["wide"]), 2)
        self.assertEqual(mm.forecast(3, self.WEEKLY * 2, TODAY, trials=200)["wide"], [])

    def test_late_against_due(self):
        self.assertTrue(mm.forecast(20, self.WEEKLY, TODAY, trials=500, due=TODAY)["late"])
        self.assertFalse(mm.forecast(20, self.WEEKLY, TODAY, trials=500, due=dt.date(2030, 1, 1))["late"])

    def test_capped_when_throughput_is_tiny(self):
        f = mm.forecast(500, [1] + [0] * 15, TODAY, trials=50)
        self.assertTrue(f["capped"])
        self.assertEqual(f["weeks85"], mm.CAP_WEEKS)

    def test_no_average_division(self):
        # 平均（2.25 件/週）で割ると 9 週。分布の 85% はそれより後ろに出る
        f = mm.forecast(20, self.WEEKLY, TODAY, trials=10000)
        self.assertGreater(f["weeks85"], 20 / (sum(self.WEEKLY) / len(self.WEEKLY)))


class Headings(unittest.TestCase):
    def test_headings_skip_code(self):
        text = "## 概要\n本文\n```\n# コードの中\n```\n### 着手順 ##\n#タグ\n"
        self.assertEqual(mm.headings(text), ["概要", "着手順"])

    def test_none(self):
        self.assertEqual(mm.headings(None), [])


class Edges(unittest.TestCase):
    def raw(self):
        return [
            milestone(1, due="2026-12-01", issues=[issue(10)], closed=weeks_ago(1, 2)),
            milestone(2, due="2026-11-20", issues=[
                issue(20, blocked=[(10, 1, "OPEN", REPO)]),
                issue(21, blocked=[(10, 1, "OPEN", REPO), (99, None, "OPEN", REPO)]),
                issue(22, blocked=[(5, 7, "OPEN", "x/other"), (6, 1, "CLOSED", REPO), (23, 2, "OPEN", REPO)]),
                issue(23)], closed=weeks_ago(1)),
            milestone(3, issues=[issue(30, blocked=[(31, 42, "OPEN", REPO)])]),
        ]

    def test_cross_edges_and_outside(self):
        d = build(self.raw())
        self.assertEqual(d["edges"], [{"from": 1, "to": 2, "count": 2, "pairs": [[20, 10], [21, 10]], "reversed": True}])
        where = sorted((o["number"], o["where"]) for o in d["outside"])
        self.assertEqual(where, [(21, "no_milestone"), (22, "other_repo"), (30, "closed_milestone")])
        # 閉じた相手（#6）と同じマイルストーンの中（#23）は線にも外にも出ない
        self.assertEqual(d["scope"]["cross_edges"], 2)
        self.assertIn("（1 件）", d["not_seen"])

    def test_critical_chain_follows_latest_finish(self):
        d = build(self.raw())
        self.assertEqual(d["critical"]["chain"], [1, 2])
        self.assertEqual(d["critical"]["tail_due"], "2026-11-20")
        self.assertEqual(d["critical"]["unknown"], [])

    def test_no_edges_no_critical(self):
        d = build([milestone(1, due="2026-12-01", issues=[issue(10)])])
        self.assertEqual(d["edges"], [])
        self.assertIsNone(d["critical"])

    def test_unknown_forecast_is_not_on_chain(self):
        raw = [milestone(1, issues=[issue(10)]),  # 閉じた実績が無い
               milestone(2, issues=[issue(20, blocked=[(10, 1, "OPEN", REPO)])], closed=weeks_ago(1))]
        crit = build(raw)["critical"]
        self.assertEqual(crit["chain"], [])
        self.assertEqual(crit["unknown"], [1, 2])

    def test_cycle_is_reported(self):
        ms = [{"number": n, "today": "2026-11-04", "forecast": {"state": "ok", "p85": "2026-12-01"}} for n in (1, 2)]
        edges = [{"from": 1, "to": 2}, {"from": 2, "to": 1}]
        crit = mm.critical_chain(ms, edges)
        self.assertTrue(crit["cycles"])
        self.assertEqual(crit["chain"], [])


class RepoNames(unittest.TestCase):
    def test_own_repo_in_other_case_is_not_other_repo(self):
        raw = [milestone(1, issues=[issue(10)], closed=weeks_ago(1)),
               milestone(2, issues=[issue(20, blocked=[(10, 1, "OPEN", "O/R")])], closed=weeks_ago(1))]
        d = build(raw)
        self.assertEqual([(e["from"], e["to"]) for e in d["edges"]], [(1, 2)])
        self.assertEqual(d["outside"], [])

    def test_other_repo_blocker_does_not_hide_candidate(self):
        raw = [milestone(1, issues=[issue(10, body="#20 が先", blocked=[(20, None, "OPEN", "x/other")])]),
               milestone(2, issues=[issue(20)])]
        self.assertEqual([(c["a"], c["b"]) for c in build(raw)["candidates"]], [(1, 2)])


class Candidates(unittest.TestCase):
    def test_mentions_in_other_milestone(self):
        many = " ".join(f"#{n}" for n in range(100, 120))
        raw = [milestone(1, issues=[issue(10, body="#20 が先。#11 は同じ所。https://github.com/o/r/issues/30 も"),
                                    issue(11, body="#20 は blocked by 済み", blocked=[(20, 2, "OPEN", REPO)]),
                                    issue(12, body="棚卸し " + many + " #20")]),
               milestone(2, issues=[issue(20, body="`#10` はコードの中")]),
               milestone(3, issues=[issue(30)])]
        d = build(raw)
        self.assertEqual(d["candidates"], [{"a": 1, "b": 2, "count": 1, "pairs": [[10, 20]]},
                                           {"a": 1, "b": 3, "count": 1, "pairs": [[10, 30]]}])
        self.assertTrue(any("#12" in x for x in d["limits"]))
        self.assertIn("一覧とみなして外した issue が 1 件", d["not_seen"])


class Fields(unittest.TestCase):
    data = {"milestones": [{"number": 4}, {"number": 9}]}

    def test_good(self):
        self.assertEqual(mm.validate_fields({"headline": "h", "points": ["a"], "notes": {"4": "n"}, "trays": [9]},
                                            self.data), [])
        self.assertEqual(mm.validate_fields({"headline": "h"}, self.data), [])

    def test_errors(self):
        errs = mm.validate_fields({"headline": "x" * 81, "points": ["a"] * 7, "notes": {"5": "n", "4": ""},
                                   "trays": [9, 8], "extra": 1}, self.data)
        joined = "\n".join(errs)
        for word in ("知らないキー extra", "headline が 81 字", "points が 7 件", "notes の 5", "notes の 4 が空",
                     "trays の 8"):
            self.assertIn(word, joined)

    def test_wrong_types(self):
        self.assertTrue(mm.validate_fields([], self.data))
        self.assertTrue(mm.validate_fields({"headline": "h", "trays": ["4"]}, self.data))
        self.assertTrue(mm.validate_fields({"headline": "h", "trays": [True]}, self.data))
        self.assertTrue(mm.validate_fields({"headline": " "}, self.data))
        self.assertTrue(mm.validate_fields({"headline": "h", "notes": {"²": "n"}}, self.data))


class Page(unittest.TestCase):
    def test_edge_cases_render(self):
        raw = [milestone(1, due="2026-10-20", issues=[issue(10)], closed=weeks_ago(3)),         # 期日切れ・少ない標本
               milestone(2, issues=[issue(20), issue(21)], created="2026-10-30T00:00:00Z"),   # 期日なし・実績なし
               milestone(3, due="2026-12-24", issues=[]),                                     # 残り 0
               milestone(4, due="2027-03-01", issues=[issue(40, title="<b>&\"'")], closed=weeks_ago(*range(16)) * 2,
                         desc="## 概要\n<script>alert(1)</script>", prs=[7])]
        d = build(raw)
        self.assertEqual(d["milestones"][0]["overdue_days"], 15)
        page = page_of(d, {"headline": "<一言>", "points": [], "notes": {"2": "期日なし"}, "trays": [3]})
        assert_page(self, page)
        self.assertIn("期日切れ 15 日", page)
        self.assertIn("期日なし", page)
        self.assertIn("0 件なので、依存の線は出ない", page)
        self.assertIn("&lt;一言&gt;", page)
        self.assertIn("<h2>受け皿</h2>", page)
        self.assertNotIn("律速", page.split("<h2>依存</h2>")[1].split("<h2>")[0])

    def test_empty_repo(self):
        page = page_of(build([]))
        assert_page(self, page)

    def test_lines_and_critical(self):
        raw = Edges().raw()
        page = page_of(build(raw))
        assert_page(self, page)
        self.assertIn("marker-end", page)
        self.assertIn("律速", page)
        self.assertIn("期日の逆転", page)

    def test_candidates_hidden_by_default(self):
        raw = [milestone(1, due="2026-12-01", issues=[issue(10, body="#20")]),
               milestone(2, due="2026-12-10", issues=[issue(20)])]
        page = page_of(build(raw))
        assert_page(self, page)
        self.assertIn('id="showcand"', page)
        self.assertIn('<g class="cand">', page)
        self.assertIn(".fig .cand { display: none; }", page)

    def test_year_shown_when_not_this_year(self):
        self.assertEqual(mm.md("2026-12-01", 2026), "12-01")
        self.assertEqual(mm.md("2027-01-20", 2026), "2027-01-20")

    def test_box_lines_fit(self):
        m = build([milestone(1, due="2026-10-01", issues=[issue(10)], closed=weeks_ago(1))])["milestones"][0]
        m["title"] = "とても長い名前" * 10
        for s, _, _ in mm.box_lines(m, 2026):
            self.assertLessEqual(mm.width(s), mm.BOX_CHARS)

    def test_missing_slot(self):
        with self.assertRaises(ValueError):
            mm.build_html("<html></html>", build([]), FIELDS)


def fake_gh(raw, no_milestone=3, pages=2):
    """gh の代わり。問い合わせの文で答えを選ぶ。マイルストーンの一覧は pages に分けて返す。"""
    by = {m["number"]: m for m in raw}
    calls = []

    def run(*args, graphql_errors=False):
        a = list(args)
        if a[:2] == ["repo", "view"]:
            calls.append(("repo", a, None))
            return "o/r\n"
        q = a[a.index("-f") + 1][len("query="):]
        vs = dict(x.split("=", 1) for x in (a[k + 1] for k, v in enumerate(a) if v == "-F"))
        cursor = next((a[k + 1][len("cursor="):] for k, v in enumerate(a) if v == "-f" and a[k + 1].startswith("cursor=")),
                      None)
        calls.append((q, vs, cursor))

        def page(nodes, start=0, size=None):
            size = size or max(1, len(nodes))
            chunk = nodes[start:start + size]
            more = start + size < len(nodes)
            return {"pageInfo": {"hasNextPage": more, "endCursor": str(start + size) if more else None}, "nodes": chunk}

        start = int(cursor or 0)
        if q == mm.MILESTONES_QUERY:
            ms = [{k: v for k, v in m.items() if k not in ("openIssues", "closedRecent")} for m in raw]
            repo = {"milestones": page(ms, start, max(1, -(-len(ms) // pages)))}
        elif q == mm.OPEN_ISSUES_QUERY:
            repo = {"milestone": {"issues": page(by[int(vs["number"])]["openIssues"], start)}}
        elif q == mm.CLOSED_ISSUES_QUERY:
            assert vs["since"].endswith("Z")
            repo = {"milestone": {"issues": page(by[int(vs["number"])]["closedRecent"], start)}}
        elif q == mm.COUNT_QUERY:
            repo = {"all": {"totalCount": 10 + no_milestone}, "withMilestone": {"totalCount": 10}}
        else:
            raise AssertionError("知らない問い合わせ")
        return json.dumps({"data": {"repository": repo}})

    return run, calls


class Fetch(unittest.TestCase):
    def raw(self):
        return [milestone(n, due=f"2026-12-{n:02d}", issues=[issue(n * 10)], closed=weeks_ago(1)) for n in range(1, 6)]

    def test_pages_and_counts(self):
        run, calls = fake_gh(self.raw())
        with mock.patch.object(ghpage, "gh", run), mock.patch.object(mm, "gh", run):
            ms, no_ms = mm.fetch("o", "r", TODAY, 16)
        self.assertEqual(sorted(m["number"] for m in ms), [1, 2, 3, 4, 5])
        self.assertEqual(no_ms, 3)
        self.assertEqual(sum(1 for q, _, _ in calls if q == mm.MILESTONES_QUERY), 2)
        self.assertTrue(all(len(m["openIssues"]) == 1 for m in ms))

    def test_collect_writes_data_and_materials(self):
        run, _ = fake_gh(self.raw())
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(ghpage, "gh", run), mock.patch.object(mm, "gh", run):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = mm.main(["--repo", "O/R", "--today", "2026-11-04", "--trials", "200"])
            self.assertEqual(code, 0)
            mat = json.loads(out.getvalue())
            data_path = pathlib.Path(mat["data_path"])
            self.assertTrue(data_path.is_file())
            self.assertEqual(data_path.parent.name, "o-r")
            self.assertNotIn("issues", mat["milestones"][0])
            fields = pathlib.Path(mat["fields_path"])
            fields.write_text(json.dumps(FIELDS, ensure_ascii=False), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"ATTENTION_CATCHUP_OPEN": "0"}):
                code = mm.main(["--render", str(data_path), str(fields)])
            self.assertEqual(code, 0)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].endswith("map.html"))
            self.assertEqual(lines[1], "全体の一言")
            assert_page(self, pathlib.Path(lines[0]).read_text(encoding="utf-8"))

    def test_render_rejects_bad_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / "data.json"
            d.write_text(json.dumps(build([])), encoding="utf-8")
            f = pathlib.Path(tmp) / "data-fields.json"
            f.write_text(json.dumps({"headline": ""}), encoding="utf-8")
            code, lines = mm.render(d, f)
            self.assertEqual(code, 2)
            self.assertFalse((pathlib.Path(tmp) / "map.html").exists())
            d.write_text(json.dumps({"schema": 0}), encoding="utf-8")
            self.assertEqual(mm.render(d, f)[0], 2)

    def test_help_has_not_seen(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            mm.main(["--help"])
        self.assertIn("見ていないもの", out.getvalue())
        self.assertIn("Projects", out.getvalue())


if __name__ == "__main__":
    unittest.main()
