#!/usr/bin/env python3
"""milestone-map.py の規則を pin する回帰テスト。GitHub には触らず、gh を固定の材料に差し替えて回す。

規則は milestone-map.py 冒頭の定義が正本で、ここはそれを入力で叩く。blocked by が 0 本でも地図が出ること
（持ち主 2026-11-04「なかったとしてもちゃんと出るようにね」）・カードの色の決め方（赤が緑に勝つ）・線は地図に載った
issue どうしだけ・止めている側は待つ側より左の列・クリティカルパスは件数のいちばん多い鎖で輪を外す、を固定する。
"""

import contextlib
import datetime as dt
import html.parser
import importlib.util
import io
import json
import os
import pathlib
import re
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


def issue(n, blocked=(), prs=()):
    """open の issue の生の材料。blocked は (番号, 相手のマイルストーン, 状態, リポジトリ) の並び、prs は (番号, 状態)。"""
    nodes = [{"number": b, "url": f"https://github.com/{repo}/issues/{b}", "state": st,
              "repository": {"nameWithOwner": repo}, "milestone": {"number": ms} if ms else None}
             for b, ms, st, repo in blocked]
    return {"number": n, "title": f"issue <{n}>", "url": f"https://github.com/o/r/issues/{n}",
            "blockedBy": {"totalCount": len(nodes), "nodes": nodes},
            "closedByPullRequestsReferences": {"totalCount": len(prs), "nodes": [
                {"number": p, "url": f"https://github.com/o/r/pull/{p}", "state": st} for p, st in prs]}}


def milestone(n, due=None, issues=(), closed=3):
    return {"number": n, "title": f"M{n}", "url": f"https://github.com/o/r/milestone/{n}",
            "dueOn": f"{due}T07:00:00Z" if due else None, "closedIssues": {"totalCount": closed},
            "openIssues": list(issues)}


def build(raw):
    return mm.build(raw, 0, REPO, TODAY, now=dt.datetime(2026, 11, 4, 9, tzinfo=dt.timezone.utc))


def page_of(data):
    return mm.build_html(mm.TEMPLATE.read_text(encoding="utf-8"), data)


class Balance(html.parser.HTMLParser):
    """開きと閉じの対応を数える。void の要素は数えない。"""
    VOID = {"meta", "br", "input", "img", "hr", "link"}

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
    """1 枚で完結する（外のファイルを読み込まない）・差し込み口が残らない・タグの対応が合う。"""
    test.assertNotRegex(page, r"<script[^>]+src=|<link[^>]+href=")
    for slot in (mm.BODY_SLOT, mm.DATA_SLOT):
        test.assertNotIn(slot, page)
    p = Balance()
    p.feed(page)
    test.assertEqual(p.errors, [])
    test.assertEqual(p.stack, [])


def view_of(page):
    """ページのスクリプトへ渡した地図の材料。"""
    return json.loads(re.search(r'<script type="application/json" id="map-data">(.*?)</script>', page, re.S).group(1))


class Cards(unittest.TestCase):
    def test_colors(self):
        rows = {i["number"]: i for i in build([milestone(1, issues=[
            issue(10),
            issue(11, prs=[(5, "OPEN")]),
            issue(12, blocked=[(10, 1, "OPEN", REPO)], prs=[(6, "OPEN")]),  # 両方に当たれば赤
            issue(13, blocked=[(99, 1, "CLOSED", REPO)], prs=[(7, "MERGED")]),  # 閉じた相手・閉じた PR は数えない
        ])])["milestones"][0]["issues"]}
        self.assertEqual({n: r["state"] for n, r in rows.items()}, {10: "idle", 11: "pr", 12: "blocked", 13: "idle"})
        self.assertEqual(rows[12]["prs"], [6])

    def test_order_red_green_gray(self):
        data = build([milestone(1, issues=[issue(3), issue(2, prs=[(5, "OPEN")]), issue(4, blocked=[(9, None, "OPEN", REPO)])])])
        self.assertEqual([i["number"] for i in data["milestones"][0]["issues"]], [4, 2, 3])

    def test_off_map_blocker_is_red_without_line(self):
        data = build([milestone(1, issues=[
            issue(10, blocked=[(5, None, "OPEN", REPO)]),      # マイルストーンなし
            issue(11, blocked=[(6, 1, "OPEN", "x/y")]),         # 別のリポジトリ
            issue(12, blocked=[(7, 9, "OPEN", REPO)]),          # 閉じたマイルストーン（地図に居ない）
        ])])
        self.assertEqual(data["edges"], [])
        self.assertEqual(data["scope"]["blocked"], 3)
        title = mm.card_title(next(i for i in data["milestones"][0]["issues"] if i["number"] == 11))
        self.assertIn("x/y#6", title)

    def test_own_repo_in_other_case_is_not_other_repo(self):
        data = build([milestone(1, issues=[issue(10), issue(11, blocked=[(10, 1, "OPEN", "O/R")])])])
        self.assertEqual(data["edges"], [[10, 11]])


class Edges(unittest.TestCase):
    def raw(self):
        # 2 → 3 → 4 は 3 件の鎖（マイルストーンをまたぐ）、5 → 6 は 2 件、同じマイルストーンの中の線も引く
        return [milestone(1, "2026-11-20", [issue(2), issue(5)]),
                milestone(2, "2026-11-10", [issue(3, blocked=[(2, 1, "OPEN", REPO)]),
                                            issue(6, blocked=[(5, 1, "OPEN", REPO)])]),
                milestone(3, None, [issue(4, blocked=[(3, 2, "OPEN", REPO)])])]

    def test_edges_and_path(self):
        data = build(self.raw())
        self.assertEqual(data["edges"], [[2, 3], [3, 4], [5, 6]])
        self.assertEqual(data["critical"], {"path": [2, 3, 4], "cycles": []})

    def test_frames_ordered_by_due_then_no_due(self):
        self.assertEqual([m["number"] for m in build(self.raw())["milestones"]], [2, 1, 3])

    def test_no_edges_no_path(self):
        self.assertEqual(mm.critical_path([]), {"path": [], "cycles": []})

    def test_tie_is_stable(self):
        self.assertEqual(mm.critical_path([[5, 6], [1, 2]])["path"], [1, 2])

    def test_branching_takes_longest(self):
        self.assertEqual(mm.critical_path([[1, 2], [1, 3], [3, 4], [4, 5], [2, 9]])["path"], [1, 3, 4, 5])

    def test_cycle_is_dropped_and_reported(self):
        crit = mm.critical_path([[1, 2], [2, 1], [7, 8]])
        self.assertEqual(crit["path"], [7, 8])
        self.assertTrue(crit["cycles"])

    def test_only_cycle(self):
        self.assertEqual(mm.critical_path([[1, 2], [2, 1]])["path"], [])

    def test_cycle_downstream_keeps_the_chain_before_it(self):
        # #1 → #2 ⇄ #3 と #1 → #4。輪の中の線だけを外すので、#1 → #2 と #1 → #4 の鎖は残る
        crit = mm.critical_path([[1, 2], [2, 3], [3, 2], [1, 4]])
        self.assertEqual(crit, {"path": [1, 2], "cycles": [[2, 3, 2]]})

    def test_self_block_is_a_cycle(self):
        self.assertEqual(mm.critical_path([[5, 5], [5, 6]]), {"path": [5, 6], "cycles": [[5, 5]]})


class Columns(unittest.TestCase):
    """左から右へ時間が流れる置き方。止めている側は、待つ側より左の列へ寄せる。"""

    def test_blockers_go_left_of_what_they_block(self):
        data = build(Edges().raw())
        col, rank, heads, width = mm.columns(data)
        # 期日の列は 11-10・11-20・期日なし。#2 と #5（11-20）は 11-10 の #3・#6 を止めるので 11-10 の列へ寄り、
        # 同じ列の中で #3・#6 より左の段に並ぶ
        self.assertEqual(col, {2: 0, 5: 0, 3: 0, 6: 0, 4: 2})
        self.assertEqual(rank, {2: 0, 5: 0, 3: 1, 6: 1, 4: 0})
        self.assertEqual(heads, {0: "2026-11-10", 1: "2026-11-20", 2: None})
        self.assertEqual(width, 3)
        for a, b in data["edges"]:
            self.assertLess((col[a], rank[a]), (col[b], rank[b]))

    def test_chain_inside_one_milestone_keeps_its_due(self):
        # 同じマイルストーンの中の鎖は期日の列を動かず、列の中で段が進む
        data = build([milestone(1, "2026-12-01", [issue(1), issue(2, blocked=[(1, 1, "OPEN", REPO)]),
                                                  issue(3, blocked=[(2, 1, "OPEN", REPO)]), issue(4)])])
        col, rank, _, _ = mm.columns(data)
        self.assertEqual((col, rank), ({1: 0, 2: 0, 3: 0, 4: 0}, {1: 0, 2: 1, 3: 2, 4: 0}))

    def test_without_lines_each_issue_sits_at_its_due(self):
        data = build([milestone(1, "2026-12-01", [issue(1)]), milestone(2, "2026-11-01", [issue(2)]), milestone(3, None, [issue(3)])])
        self.assertEqual(mm.columns(data), ({2: 0, 1: 1, 3: 2}, {2: 0, 1: 0, 3: 0}, {0: "2026-11-01", 1: "2026-12-01", 2: None}, 3))

    def test_cycle_does_not_hang(self):
        data = build([milestone(1, "2026-12-01", [issue(1, blocked=[(2, 1, "OPEN", REPO)]),
                                                  issue(2, blocked=[(1, 1, "OPEN", REPO)])])])
        col, rank, _, _ = mm.columns(data)
        self.assertEqual((set(col), set(rank.values())), ({1, 2}, {0}))

    def test_late_edges(self):
        # 止めている側のマイルストーンの期日が後ろ（#2 は 11-20 で #3 は 11-10）。期日なしの側へ向かう線は逆転でない
        self.assertEqual(mm.late_edges(build(Edges().raw())), [[2, 3], [5, 6]])


class Page(unittest.TestCase):
    def test_no_blocked_by_still_renders(self):
        data = build([milestone(1, "2026-10-01", [issue(1), issue(2, prs=[(3, "OPEN")])]), milestone(2), milestone(3)])
        page = page_of(data)
        assert_page(self, page)
        # 線が無いときは、見出しにクリティカルパスの行を出さない（無いと断る行も要らない。持ち主 2026-11-04）
        self.assertNotIn('class="path"', page.split('<header class="top">')[1].split("</header>")[0])
        v = view_of(page)
        self.assertEqual((v["edges"], v["path"], v["late"]), ([], [], []))
        self.assertEqual(v["columns"], [{"label": "期日 10-01", "late": True}, {"label": "期日なし", "late": False}])
        self.assertEqual(v["today"], {"at": 1, "label": "今日 11-04"})
        self.assertEqual([(m["n"], m["col"], m["open"], m["overdue"]) for m in v["milestones"]], [(1, 0, 2, 34), (2, 1, 0, 0), (3, 1, 0, 0)])
        self.assertEqual([(i["n"], i["state"], i["col"]) for i in v["milestones"][0]["issues"]], [(2, "pr", 0), (1, "idle", 0)])

    def test_empty_repo(self):
        page = page_of(build([]))
        assert_page(self, page)
        self.assertEqual((view_of(page)["milestones"], view_of(page)["columns"]), ([], []))

    def test_lines_and_path_reach_the_script(self):
        page = page_of(build(Edges().raw()))
        assert_page(self, page)
        v = view_of(page)
        self.assertEqual(v["edges"], [[2, 3], [3, 4], [5, 6]])
        self.assertEqual(v["path"], [[2, 3], [3, 4]])
        self.assertEqual(v["late"], [[2, 3], [5, 6]])
        self.assertIn("クリティカルパス 3 件", page)
        crit = sorted(i["n"] for m in v["milestones"] for i in m["issues"] if i["crit"])
        self.assertEqual(crit, [2, 3, 4])
        cols = {i["n"]: i["col"] for m in v["milestones"] for i in m["issues"]}
        self.assertEqual(cols, {2: 0, 5: 0, 3: 0, 6: 0, 4: 2})

    def test_titles_are_escaped(self):
        page = page_of(build([milestone(1, issues=[issue(1)])]))
        self.assertNotIn("issue <1>", page)
        self.assertEqual(view_of(page)["milestones"][0]["issues"][0]["title"], "issue <1>")

    def test_year_shown_when_not_this_year(self):
        labels = [c["label"] for c in view_of(page_of(build([milestone(1, "2027-01-05"), milestone(2, "2026-12-01")])))["columns"]]
        self.assertEqual(labels, ["期日 12-01", "期日 2027-01-05"])

    def test_missing_slot(self):
        with self.assertRaises(ValueError):
            mm.build_html("<html></html>", build([]))


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
            ms = [{k: v for k, v in m.items() if k != "openIssues"} for m in raw]
            repo = {"milestones": page(ms, start, max(1, -(-len(ms) // pages)))}
        elif q == mm.OPEN_ISSUES_QUERY:
            repo = {"milestone": {"issues": page(by[int(vs["number"])]["openIssues"], start)}}
        elif q == mm.COUNT_QUERY:
            repo = {"all": {"totalCount": 10 + no_milestone}, "withMilestone": {"totalCount": 10}}
        else:
            raise AssertionError("知らない問い合わせ")
        return json.dumps({"data": {"repository": repo}})

    return run, calls


class Fetch(unittest.TestCase):
    def raw(self):
        return [milestone(n, due=f"2026-12-{n:02d}", issues=[issue(n * 10)]) for n in range(1, 6)]

    def test_pages_and_counts(self):
        run, calls = fake_gh(self.raw())
        with mock.patch.object(ghpage, "gh", run), mock.patch.object(mm, "gh", run):
            ms, no_ms = mm.fetch("o", "r")
        self.assertEqual(sorted(m["number"] for m in ms), [1, 2, 3, 4, 5])
        self.assertEqual(no_ms, 3)
        self.assertEqual(sum(1 for q, _, _ in calls if q == mm.MILESTONES_QUERY), 2)
        self.assertTrue(all(len(m["openIssues"]) == 1 for m in ms))

    def test_main_writes_page(self):
        run, _ = fake_gh(self.raw())
        with tempfile.TemporaryDirectory() as root, mock.patch.object(ghpage, "gh", run), mock.patch.object(mm, "gh", run):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = mm.main(["--repo", "O/R", "--today", "2026-11-04"], env={"ATTENTION_CATCHUP_OPEN": "0"}, root=root)
            self.assertEqual(code, 0)
            lines = out.getvalue().splitlines()
            path = pathlib.Path(lines[0])
            self.assertEqual((path.parent.name, path.name), ("o-r", "map.html"))
            self.assertIn("マイルストーン 5 本・issue 5 件", lines[1])
            self.assertIn("クリティカルパスなし", lines[1])
            assert_page(self, path.read_text(encoding="utf-8"))

    def test_help_has_not_seen(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            mm.main(["--help"])
        self.assertIn("見ていないもの", out.getvalue())
        self.assertIn("Projects", out.getvalue())


if __name__ == "__main__":
    unittest.main()
