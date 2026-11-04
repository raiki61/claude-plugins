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


def issue(n, blocked=(), prs=(), who=(), made="2026-10-01T03:00:00Z", pr_by="dev"):
    """open の issue の生の材料。blocked は (番号, 相手のマイルストーン, 状態, リポジトリ) の並び、prs は (番号, 状態)。
    who は担当者の login、made は作られた時刻、pr_by は PR を出した人の login。"""
    nodes = [{"number": b, "url": f"https://github.com/{repo}/issues/{b}", "state": st,
              "repository": {"nameWithOwner": repo}, "milestone": {"number": ms} if ms else None}
             for b, ms, st, repo in blocked]
    return {"number": n, "title": f"issue <{n}>", "url": f"https://github.com/o/r/issues/{n}", "createdAt": made,
            "assignees": {"totalCount": len(who), "nodes": [{"login": w} for w in who]},
            "blockedBy": {"totalCount": len(nodes), "nodes": nodes},
            "closedByPullRequestsReferences": {"totalCount": len(prs), "nodes": [
                {"number": p, "url": f"https://github.com/o/r/pull/{p}", "state": st,
                 "author": {"login": pr_by} if pr_by else None} for p, st in prs]}}


def closed(n, made, shut, who=(), actor="closer", pr_by=None, reason="COMPLETED", bot=False):
    """閉じた issue の生の材料。made と shut は時刻（UTC）。actor は閉じる操作をした人、pr_by は閉じた PR を出した人
    （None なら PR でなく手で閉じた）。reason は閉じ方（stateReason）、bot は閉じる操作をしたのが Bot か。"""
    return {"number": n, "title": f"done <{n}>", "url": f"https://github.com/o/r/issues/{n}", "createdAt": made,
            "closedAt": shut, "stateReason": reason, "assignees": {"totalCount": len(who), "nodes": [{"login": w} for w in who]},
            "timelineItems": {"nodes": [{"actor": {"login": actor, "__typename": "Bot" if bot else "User"} if actor else None,
                                         "closer": {"author": {"login": pr_by}} if pr_by else None}]}}


def loose(opened=(), done=(), closed_all=None):
    """マイルストーンの付いていない issue（fetch の 2 つ目と同じ形）。"""
    return {"openIssues": list(opened), "closedIssueList": list(done),
            "closedIssues": {"totalCount": len(done) if closed_all is None else closed_all}, "limits": []}


def milestone(n, due=None, issues=(), closed=3, done=()):
    return {"number": n, "title": f"M{n}", "url": f"https://github.com/o/r/milestone/{n}",
            "dueOn": f"{due}T07:00:00Z" if due else None, "closedIssues": {"totalCount": closed},
            "openIssues": list(issues), "closedIssueList": list(done)}


def build(raw, stray=None, dates=None):
    return mm.build(raw, stray, REPO, TODAY, now=dt.datetime(2026, 11, 4, 9, tzinfo=dt.timezone.utc), dates=dates)


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
            issue(10, blocked=[(5, None, "OPEN", REPO)]),      # マイルストーンなしで、地図に居ない
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
        self.assertEqual(v["columns"], [{"label": "Due 10-01", "late": True}, {"label": "No due date", "late": False}])
        self.assertEqual(v["today"], {"at": 1, "label": "今日 11-04", "day": "2026-11-04"})
        # ページで選べる期間の上限は、スクリプトがマイルストーンなしの閉じた issue を取った日数と同じ値を渡す
        self.assertEqual(v["since_days"], mm.SINCE_DAYS)
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
        self.assertEqual(labels, ["Due 12-01", "Due 2027-01-05"])

    def test_missing_slot(self):
        with self.assertRaises(ValueError):
            mm.build_html("<html></html>", build([]))


def fake_gh(raw, stray=None, pages=2):
    """gh の代わり。問い合わせの文で答えを選ぶ。マイルストーンの一覧は pages に分けて返す。stray はマイルストーンの
    付いていない issue（loose の形）で、検索の問いに答える。"""
    stray = stray or loose()
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
        text = next((a[k + 1][len("q="):] for k, v in enumerate(a) if v == "-f" and a[k + 1].startswith("q=")), None)
        if q in (mm.LOOSE_OPEN_QUERY, mm.LOOSE_CLOSED_QUERY, mm.COUNT_QUERY):
            calls[-1] = (q, {"q": text}, cursor)
            nodes = stray["openIssues"] if q == mm.LOOSE_OPEN_QUERY else stray["closedIssueList"]
            search = {"issueCount": stray["closedIssues"]["totalCount"] if q == mm.COUNT_QUERY else len(nodes)}
            if q != mm.COUNT_QUERY:
                search.update(page(nodes, start, 1))
            return json.dumps({"data": {"search": search}})
        if q == mm.MILESTONES_QUERY:
            ms = [{k: v for k, v in m.items() if k not in ("openIssues", "closedIssueList")} for m in raw]
            repo = {"milestones": page(ms, start, max(1, -(-len(ms) // pages)))}
        elif q == mm.OPEN_ISSUES_QUERY:
            repo = {"milestone": {"issues": page(by[int(vs["number"])]["openIssues"], start)}}
        elif q == mm.CLOSED_ISSUES_QUERY:
            repo = {"milestone": {"issues": page(by[int(vs["number"])]["closedIssueList"], start)}}
        else:
            raise AssertionError("知らない問い合わせ")
        return json.dumps({"data": {"repository": repo}})

    return run, calls


class People(unittest.TestCase):
    """誰が進めているか・期間の動きに使う事実（持ち主 2026-11-04「今どこを誰が攻めてるのか」「期間指定したときのその変化や進捗」）。"""

    def test_who_and_pr_authors_reach_the_script(self):
        raw = issue(1, prs=[(7, "OPEN"), (8, "OPEN"), (9, "MERGED")], who=("b", "a"), made="2026-10-20T03:00:00Z")
        raw["closedByPullRequestsReferences"]["nodes"][1]["author"] = None   # 消えたアカウント
        raw["closedByPullRequestsReferences"]["nodes"][2]["author"] = {"login": "merged-only"}
        v = view_of(page_of(build([milestone(1, "2026-11-30", [raw])])))
        i = v["milestones"][0]["issues"][0]
        # 担当者は GitHub の並びのまま。PR を出した人は open の PR だけから取り、null を落として並べる
        self.assertEqual((i["who"], i["prBy"], i["made"]), (["b", "a"], ["dev"], "2026-10-20"))
        # PR の数は、その PR を出した人にだけ数える（人の一覧の「PR」）
        self.assertEqual(i["prOf"], [[7, "dev"], [8, None]])

    def test_closed_issues_are_sorted_by_close_day(self):
        done = [closed(5, "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z", who=("a",)),
                closed(3, "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z"),
                closed(4, "2026-09-01T03:00:00Z", "2026-10-30T03:00:00Z")]
        v = view_of(page_of(build([milestone(1, "2026-11-30", [issue(1)], done=done)])))
        self.assertEqual([(d["n"], d["shut"], d["who"]) for d in v["milestones"][0]["done"]],
                         [(4, "2026-10-30", []), (3, "2026-11-02", []), (5, "2026-11-02", ["a"])])

    @unittest.skipUnless(hasattr(__import__("time"), "tzset"), "TZ を替えられない OS")
    def test_days_are_local_dates(self):
        import time
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Tokyo"
            time.tzset()
            # UTC の 11-03 16:00 は東京の 11-04 01:00。期間は手元の日付で切る
            self.assertEqual(mm.local_day("2026-11-03T16:00:00Z"), "2026-11-04")
            self.assertIsNone(mm.local_day(None))
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_too_many_assignees_is_reported(self):
        raw = issue(1, who=("a", "b"))
        raw["assignees"]["totalCount"] = mm.WHO_FIRST + 1
        self.assertIn("担当者", "・".join(build([milestone(1, None, [raw])])["limits"]))
        many = closed(2, "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z", who=("a",))
        many["assignees"]["totalCount"] = mm.WHO_FIRST + 1
        self.assertIn("#2", "・".join(build([milestone(1, None, [issue(1)], done=[many])])["limits"]))


class Fetch(unittest.TestCase):
    def raw(self):
        return [milestone(n, due=f"2026-12-{n:02d}", issues=[issue(n * 10)]) for n in range(1, 6)]

    def test_pages_and_counts(self):
        stray = loose([issue(91), issue(92)], [closed(93, "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z")], closed_all=7)
        run, calls = fake_gh(self.raw(), stray)
        with mock.patch.object(ghpage, "gh", run), mock.patch.object(mm, "gh", run):
            ms, got = mm.fetch("o", "r", TODAY)
        self.assertEqual(sorted(m["number"] for m in ms), [1, 2, 3, 4, 5])
        self.assertEqual(sum(1 for q, _, _ in calls if q == mm.MILESTONES_QUERY), 2)
        self.assertTrue(all(len(m["openIssues"]) == 1 for m in ms))
        # マイルストーンの付いていない issue は検索で、全ページを取る（1 件ずつのページにしてある）
        self.assertEqual(([i["number"] for i in got["openIssues"]], [i["number"] for i in got["closedIssueList"]]), ([91, 92], [93]))
        self.assertEqual(got["closedIssues"]["totalCount"], 7)
        self.assertEqual([x for x in got["limits"] if x], [])
        asked = {v["q"] for q, v, _ in calls if q in (mm.LOOSE_OPEN_QUERY, mm.LOOSE_CLOSED_QUERY)}
        base = "repo:o/r is:issue no:milestone sort:created-asc"
        self.assertEqual(asked, {base + " is:open", f"{base} is:closed closed:>={TODAY - dt.timedelta(days=mm.SINCE_DAYS)}"})

    def test_search_drops_repeats(self):
        # 検索の途中で issue が直されると、同じ issue が 2 ページに出る。1 件にする
        pages = [{"issueCount": 2, "pageInfo": {"hasNextPage": True, "endCursor": "1"}, "nodes": [issue(1)]},
                 {"issueCount": 2, "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [issue(1), issue(2), None]}]
        it = iter(pages)
        with mock.patch.object(mm, "gh", lambda *a, **k: json.dumps({"data": {"search": next(it)}})):
            got = mm.search_all(mm.LOOSE_OPEN_QUERY, "q")
        self.assertEqual([i["number"] for i in got["nodes"]], [1, 2])

    def test_search_cap_is_reported(self):
        run, _ = fake_gh([], loose([issue(91)]))

        def capped(*args, **kw):
            out = json.loads(run(*args, **kw))
            if "search" in out["data"] and "nodes" in out["data"]["search"]:
                out["data"]["search"]["issueCount"] = 1500   # 検索は 1000 件までしか返さない
            return json.dumps(out)
        with mock.patch.object(ghpage, "gh", capped), mock.patch.object(mm, "gh", capped):
            _, got = mm.fetch("o", "r", TODAY)
        self.assertIn("1500 件のうち 1 件", "・".join(build([], got)["limits"]))

    def test_bad_dates_stop(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "dates.json"
            f.write_text('["2026-11-20"]', encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(mm.main(["--repo", "O/R", "--dates", str(f)]), 2)
            self.assertIn("--dates", err.getvalue())

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


class Stray(unittest.TestCase):
    """マイルストーンの付いていない issue（持ち主 2026-11-04「マイルストーンに紐づかない野良issueも存在できるように」
    「MSなしは野良部隊みたいな感じでおらせたら」「期日があればね。見たいかもしれない」）。"""

    def test_stray_issues_form_the_last_frame_and_join_lines(self):
        stray = loose([issue(50, blocked=[(10, 1, "OPEN", REPO)]), issue(51)], closed_all=4)
        data = build([milestone(1, "2026-11-30", [issue(10)]), milestone(2, None, [issue(20)])], stray)
        self.assertEqual([(m["number"], m["none"]) for m in data["milestones"]], [(1, False), (2, False), (0, True)])
        self.assertEqual(data["edges"], [[10, 50]])   # マイルストーンの在る issue との線も引く
        self.assertEqual((data["scope"]["milestones"], data["scope"]["no_milestone_issues"], data["scope"]["open_issues"]), (2, 2, 4))
        self.assertEqual(data["milestones"][2]["closed"], 4)
        v = view_of(page_of(data))
        self.assertEqual([(m["n"], m["none"], m["due"]) for m in v["milestones"]][2], (0, True, "No due date"))
        self.assertIn("「No milestone」の枠に置いた", mm.body_html(data))

    def test_no_stray_issues_no_frame(self):
        data = build([milestone(1, None, [issue(10)])], loose())
        self.assertEqual([m["number"] for m in data["milestones"]], [1])
        self.assertNotIn("No milestone", mm.body_html(data))

    def test_dates_place_stray_issues_in_their_column(self):
        d = mm.read_dates('{"50": "2026-11-20", "52": "2026-11-20", "60": "2026-01-01", "10": "2026-12-31", "53": null}')
        self.assertEqual(d, {50: dt.date(2026, 11, 20), 52: dt.date(2026, 11, 20), 60: dt.date(2026, 1, 1), 10: dt.date(2026, 12, 31)})
        done = [closed(52, "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z"), closed(60, "2026-01-01T03:00:00Z", "2026-11-03T03:00:00Z")]
        data = build([milestone(1, "2026-11-30", [issue(10)])], loose([issue(50), issue(51)], done, closed_all=9), dates=d)
        got = [(m["number"], m["due"], [i["number"] for i in m["issues"]], [i["number"] for i in m["done"]], m["closed"])
               for m in data["milestones"]]
        # 日付の在る open の issue は、その日の「マイルストーンなし」の枠へ。閉じた issue は、同じ日付の枠が在ればそこへ、
        # 無ければ期日なしの枠へ（閉じた issue だけの枠は作らない）。マイルストーンの在る issue の日付は使わない
        self.assertEqual(got, [(-1, "2026-11-20", [50], [52], 1), (1, "2026-11-30", [10], [], 3), (0, None, [51], [60], 8)])
        v = view_of(page_of(data))
        self.assertEqual(v["milestones"][0]["due"], "渡した日付 " + mm.md("2026-11-20", 2026))

    def test_two_dated_frames_are_ordered_by_date(self):
        d = {50: dt.date(2026, 11, 20), 51: dt.date(2026, 11, 10)}
        data = build([], loose([issue(50), issue(51), issue(52)]), dates=d)
        got = [(m["number"], m["due"], [i["number"] for i in m["issues"]]) for m in data["milestones"]]
        self.assertEqual(got, [(-1, "2026-11-10", [51]), (-2, "2026-11-20", [50]), (0, None, [52])])
        v = view_of(page_of(data))
        self.assertEqual(len({m["n"] for m in v["milestones"]}), 3)

    def test_only_closed_stray_issues_keep_the_frame(self):
        # 閉じた issue だけでも枠を残す（期間の数から、マイルストーンなしの閉じた issue が抜けないように）
        done = [closed(60, "2026-10-01T03:00:00Z", "2026-11-03T03:00:00Z")]
        data = build([milestone(1, None, [issue(10)])], loose([], done, closed_all=5))
        self.assertEqual([(m["number"], m["open"], m["closed"], len(m["done"])) for m in data["milestones"]], [(1, 1, 3, 0), (0, 0, 5, 1)])

    def test_bad_dates(self):
        for text in ('["2026-11-20"]', '{"x": "2026-11-20"}', '{"5": "11/20"}', '{"5": 20261120}', '{"5": ["2026-11-20"]}'):
            with self.assertRaises(ValueError):
                mm.read_dates(text)


class Closer(unittest.TestCase):
    """閉じる PR を出した人も実質の担当（持ち主 2026-11-04「PRをやってclosesに入れた人も実質担当じゃないかな」）。"""

    def test_closer(self):
        made, shut = "2026-10-01T03:00:00Z", "2026-11-02T03:00:00Z"
        self.assertEqual(mm.closer_of(closed(1, made, shut, who=("a",), pr_by="dev")), ("dev", "pr"))   # PR で閉じた
        self.assertEqual(mm.closer_of(closed(2, made, shut, actor="x")), ("x", "hand"))                 # 手で閉じ、担当者なし
        self.assertEqual(mm.closer_of(closed(3, made, shut, who=("a",), actor="x")), (None, None))      # 手で閉じ、担当者あり
        self.assertEqual(mm.closer_of(closed(4, made, shut, actor=None)), (None, None))                 # 消えたアカウント
        self.assertEqual(mm.closer_of(closed(6, made, shut, actor="x", reason="NOT_PLANNED")), (None, None))  # not planned
        self.assertEqual(mm.closer_of(closed(7, made, shut, actor="x", reason="DUPLICATE")), (None, None))    # duplicate
        self.assertEqual(mm.closer_of(closed(8, made, shut, actor="stale", bot=True)), (None, None))          # Bot が閉じた
        bare = closed(5, made, shut)
        bare["timelineItems"] = {"nodes": []}
        self.assertEqual(mm.closer_of(bare), (None, None))
        v = view_of(page_of(build([milestone(1, None, [issue(9)], done=[closed(1, made, shut, who=("a",), pr_by="dev")])])))
        d = v["milestones"][0]["done"][0]
        self.assertEqual((d["who"], d["by"], d["how"]), (["a"], "dev", "pr"))


_pd = importlib.util.spec_from_file_location("project_dates", ROOT / "attention" / "scripts" / "project-dates.py")
pd = importlib.util.module_from_spec(_pd)
_pd.loader.exec_module(pd)


class ProjectDates(unittest.TestCase):
    """Projects の日付のフィールドを --dates の JSON にする固有の部品（持ち主 2026-11-04「データとして流せるようにしておいて、
    その日付を取得するところは固有とかの方がいいかもね」）。"""

    @staticmethod
    def item(n, *vals):
        return {"number": n, "projectItems": {"nodes": [
            {"project": {"number": p}, "fieldValueByName": {"date": d} if d else None} for p, d in vals]}}

    def test_dates_of(self):
        issues = [self.item(1, (9, "2026-11-20"), (3, "2026-11-10")), self.item(2, (9, None)), self.item(3, (3, "2026-12-01"))]
        self.assertEqual(pd.dates_of(issues), {"1": "2026-11-10", "3": "2026-12-01"})   # 2 つ以上なら早い方
        self.assertEqual(pd.dates_of(issues, project=9), {"1": "2026-11-20"})
        self.assertEqual(mm.read_dates(json.dumps(pd.dates_of(issues))), {1: dt.date(2026, 11, 10), 3: dt.date(2026, 12, 1)})

    def test_search_pages(self):
        pages = [{"pageInfo": {"hasNextPage": True, "endCursor": "1"}, "nodes": [self.item(1, (9, "2026-11-20"))]},
                 {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [self.item(2, (9, "2026-11-21")), {}]}]
        seen = []

        def run(*args, **kw):
            seen.append(list(args))
            return json.dumps({"data": {"search": pages[len(seen) - 1]}})
        with mock.patch.object(pd, "gh", run):
            got = pd.search_all("repo:o/r is:issue no:milestone is:open", "Target Date")
        self.assertEqual([i["number"] for i in got], [1, 2])
        self.assertIn("field=Target Date", seen[0])
        self.assertIn("cursor=1", seen[1])

    def test_search_cap_goes_to_stderr(self):
        page = {"issueCount": 1500, "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [self.item(1, (9, "2026-11-20"))]}
        err = io.StringIO()
        with mock.patch.object(pd, "gh", lambda *a, **k: json.dumps({"data": {"search": page}})), contextlib.redirect_stderr(err):
            self.assertEqual(len(pd.search_all("q", "Target Date")), 1)
        self.assertIn("1500 件のうち 1 件", err.getvalue())


if __name__ == "__main__":
    unittest.main()
