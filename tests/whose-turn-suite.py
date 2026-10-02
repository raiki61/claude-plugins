#!/usr/bin/env python3
"""whose-turn.py の判定規則を pin する回帰テスト。GitHub には触らず固定の材料で回す。

規則は whose-turn.py 冒頭の定義が正本で、ここは 1 行ずつそれを入力で叩く。
実データには出ない値（未知のチェック結論、退会済みユーザー、Team 宛の依頼）も含める——
こういう値は「出ないから」で落としやすく、落ちた先が黙って消える方向なので。
"""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "whose-turn", ROOT / "attention" / "scripts" / "whose-turn.py")
flow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flow)
# 期待値は UTC の文字列で書いてある。走らせる機械のタイムゾーンに依らないよう固定する
flow.LOCAL_TZ = dt.timezone.utc

T0, T1, T2, T3 = (f"2026-08-0{n}T00:00:00Z" for n in (1, 2, 3, 4))


def user(login):
    return {"__typename": "User", "login": login}


def bot(login="copilot-pull-request-reviewer"):
    return {"__typename": "Bot", "login": login}


def team(slug="org/team"):
    return {"__typename": "Team", "combinedSlug": slug}


def conn(*nodes, total=None):
    return {"totalCount": len(nodes) if total is None else total, "nodes": list(nodes)}


def review(actor, state, at, body=""):
    # PENDING は未送信なので GraphQL が submittedAt を null で返す
    return {
        "id": f"R{at}{actor and actor.get('login')}",
        "state": state,
        "createdAt": at,
        "submittedAt": None if state == "PENDING" else at,
        "body": body,
        "author": actor,
    }


def comment(actor, at, body="", state="SUBMITTED"):
    return {
        "id": f"C{at}{(actor or {}).get('login')}",
        "state": state,
        "createdAt": at,
        "body": body,
        "author": actor,
    }


def thread(*comments, resolved=False, outdated=False, path="f.py", line=1):
    return {
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "comments": conn(*comments),
    }


def history(*events, earlier=False):
    """timelineItems の接続。本物の totalCount は itemTypes で絞る前の数なので持たせない"""
    return {"pageInfo": {"hasPreviousPage": earlier}, "nodes": list(events)}


def requested(actor, at):
    return {
        "__typename": "ReviewRequestedEvent",
        "createdAt": at,
        "requestedReviewer": actor,
    }


def assigned(login, at):
    return {
        "__typename": "AssignedEvent",
        "createdAt": at,
        "assignee": {"login": login},
    }


def event(kind, at):
    return {"__typename": kind, "createdAt": at}


def checks(*results):
    """conclusion 文字列、または ("state", 値) で StatusContext。名前は位置で振る——
    同じ名前は「同じ job の再実行」を意味するようになったので、別物には別の名前が要る。"""
    nodes = []
    for i, r in enumerate(results):
        if isinstance(r, tuple):
            nodes.append({"context": f"ctx{i}", "state": r[1], "createdAt": T2})
        else:
            nodes.append({"name": f"chk{i}", "conclusion": r, "completedAt": T2})
    return {"contexts": conn(*nodes)}


def runs(*specs):
    """(名前, conclusion, completedAt) の CheckRun を並べる。同じ名前の再実行を作るため。"""
    nodes = [{"name": n, "conclusion": c, "completedAt": at} for n, c, at in specs]
    return {"contexts": conn(*nodes)}


def rollup(r):
    return {"nodes": [{"commit": {"committedDate": T1, "statusCheckRollup": r}}]}


def pr(**kw):
    p = {
        "number": 1,
        "title": "t",
        "headRefName": "b",
        "isDraft": False,
        "reviewDecision": "REVIEW_REQUIRED",
        "mergeStateStatus": "CLEAN",
        "createdAt": T0,
        "author": user("alice"),
        "assignees": conn(),
        "reviewRequests": conn(),
        "reviews": conn(),
        "comments": conn(),
        "reviewThreads": conn(),
        "timelineItems": history(),
        "commits": rollup(None),
    }
    p.update(kw)
    p.setdefault("url", f"https://example.invalid/pull/{p['number']}")
    p.setdefault("latestOpinionatedReviews", opinions_of(p["reviews"]))
    return p


def opinions_of(reviews):
    """GitHub が reviews から出す人ごとの最新の意見（latestOpinionatedReviews）。材料の reviews と食い違わせない"""
    latest = {}
    for r in sorted(reviews["nodes"], key=lambda r: r["submittedAt"] or ""):
        if r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[(r["author"] or {}).get("login")] = r
    return conn(*({"state": r["state"], "author": r["author"]} for r in latest.values()))


def requests(*actors):
    return conn(*({"requestedReviewer": a} for a in actors))


def tiers(p):
    return {w: t for w, (t, _) in flow.pr_tiers(p).items()}


def mannequin(login):
    return {"__typename": "Mannequin", "login": login}


class PrBalls(unittest.TestCase):
    def test_draft_is_author_since_converted(self):
        p = pr(isDraft=True, timelineItems=history(event("ConvertToDraftEvent", T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T2)])

    def test_draft_hides_pending_requests(self):
        p = pr(isDraft=True, reviewRequests=requests(user("bob")))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T0)])

    def test_ci_red_on_every_non_green_value(self):
        for v in (
            "FAILURE",
            "ERROR",
            "TIMED_OUT",
            "ACTION_REQUIRED",
            "STARTUP_FAILURE",
            "NEW_VALUE",
            ("state", "ERROR"),
        ):
            with self.subTest(v=v):
                p = pr(commits=rollup(checks("SUCCESS", v)))
                self.assertEqual(flow.pr_balls(p), [("alice", "CI 赤", T2)])

    def test_green_values_are_not_red(self):
        for v in (
            "SUCCESS",
            "NEUTRAL",
            "SKIPPED",
            "CANCELLED",
            "STALE",
            None,
            "",
            ("state", "PENDING"),
            ("state", "EXPECTED"),
        ):
            with self.subTest(v=v):
                p = pr(commits=rollup(checks(v)))
                self.assertNotIn("CI 赤", [r[1] for r in flow.pr_balls(p)])

    def test_ci_red_keeps_pending_reviewers(self):
        p = pr(commits=rollup(checks("FAILURE")), reviewRequests=requests(user("bob")))
        self.assertEqual(
            flow.pr_balls(p), [("alice", "CI 赤", T2), ("bob", "レビュー", T0)]
        )

    def test_ci_red_wins_over_changes_requested(self):
        p = pr(commits=rollup(checks("FAILURE")), reviewDecision="CHANGES_REQUESTED")
        self.assertEqual([r[1] for r in flow.pr_balls(p)], ["CI 赤"])

    def test_changes_requested_plus_pending_reviewer(self):
        p = pr(
            reviewDecision="CHANGES_REQUESTED",
            reviews=conn(
                review(user("bob"), "CHANGES_REQUESTED", T1),
                review(user("bob"), "COMMENTED", T2),
            ),
            reviewRequests=requests(user("carol")),
            timelineItems=history(requested(user("carol"), T3)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "指摘対応", T1), ("carol", "レビュー", T3)]
        )

    def test_changes_requested_then_rerequested_from_everyone_is_the_reviewers_turn(self):
        """変更要求を出した人全員に依頼し直していれば、番はレビュアーにある。依頼より前に誰が最後に喋っても同じ"""
        for last in ("alice", "bob"):
            with self.subTest(last=last):
                p = pr(
                    reviewDecision="CHANGES_REQUESTED",
                    reviews=conn(review(user("bob"), "CHANGES_REQUESTED", T0, "ここを直してください")),
                    reviewRequests=requests(user("bob")),
                    timelineItems=history(requested(user("bob"), T2)),
                    comments=conn(comment(user(last), T1, "見ました" if last == "bob" else "直しました")),
                )
                self.assertFalse(flow.turn.owes_change_requests(p))
                self.assertEqual(
                    flow.merge_rows(flow.pr_balls(p)),
                    {"alice": (["レビュー待ち"], T2), "bob": (["レビュー"], T2)},
                )
                self.assertEqual(tiers(p), {"alice": 3, "bob": 0})

    def test_a_reply_before_the_rerequest_is_not_counted(self):
        """変更要求 → 本人がスレッドで「確認しました」（未解決 0） → 作者が再依頼。人ごとの最新の意見は変更要求のまま"""
        p = pr(
            reviewDecision="CHANGES_REQUESTED",
            reviews=conn(
                review(user("bob"), "CHANGES_REQUESTED", T0, "直してください"),
                review(user("bob"), "COMMENTED", T1),
            ),
            reviewThreads=conn(thread(comment(user("bob"), T1, "確認しました"), resolved=True)),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T2)),
        )
        self.assertEqual(p["latestOpinionatedReviews"]["nodes"][0]["state"], "CHANGES_REQUESTED")
        self.assertEqual(tiers(p), {"alice": 3, "bob": 0})

    def test_a_request_resets_the_reviewers_last_word(self):
        """変更要求に限らない: 依頼より前の本人の発言は数えず、依頼より後に本人が問うたなら相手待ち"""
        before = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1, "質問です")),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T2)),
        )
        self.assertEqual(tiers(before)["bob"], 0)
        after = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T3, "質問です")),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T2)),
        )
        self.assertEqual(tiers(after)["bob"], 3)
        unseen = pr(reviews=before["reviews"], reviewRequests=requests(user("bob")))
        self.assertEqual(tiers(unseen)["bob"], 3)

    def test_the_1843_order_keeps_the_rerequested_reviewer_on_turn(self):
        """#1843 の順: 変更要求 → 作者の再依頼 → 本人が解決済みスレッドで「確認しました」（本文の無い COMMENTED つき）。
        依頼の後の本人の相槌は何も待たないので番はレビュアーにあり、その行に作者の無言の催促も出さない"""
        p = pr(
            reviewDecision="CHANGES_REQUESTED",
            comments=conn(comment(user("alice"), T0, "お願いします")),
            reviews=conn(
                review(user("bob"), "CHANGES_REQUESTED", "2026-08-01T12:00:00Z", "直してください"),
                review(user("bob"), "COMMENTED", T2),
            ),
            reviewThreads=conn(thread(comment(user("bob"), T2, "確認しました"), resolved=True)),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T1)),
        )
        self.assertEqual(p["latestOpinionatedReviews"]["nodes"][0]["state"], "CHANGES_REQUESTED")
        self.assertEqual(tiers(p), {"alice": 3, "bob": 0})
        self.assertEqual([f for f in flow.pr_facts(p, "bob") if "発言なし" in f], [])

    def test_a_rerequested_reviewer_is_shown_the_authors_silence_only_after_speaking_again(self):
        """依頼より前の本人の発言（変更要求の本文）を起点に作者の無言を催促しない。依頼の後に本人が話していれば出す"""
        def p(*after):
            return pr(
                comments=conn(comment(user("alice"), T0, "お願いします"), *after),
                reviews=conn(review(user("bob"), "CHANGES_REQUESTED", "2026-08-01T12:00:00Z", "直してください")),
                reviewDecision="CHANGES_REQUESTED",
                reviewRequests=requests(user("bob")),
                timelineItems=history(requested(user("bob"), T1)),
            )

        self.assertEqual([f for f in flow.pr_facts(p(), "bob") if "発言なし" in f], [])
        self.assertIn(
            "alice は 08-01 00:00 以降 発言なし",
            flow.pr_facts(p(comment(user("bob"), T3, "まだですか")), "bob"),
        )

    def test_a_question_left_before_the_rerequest_still_waits_for_the_answer(self):
        """未解決スレッドで本人が出した問いに作者が答えないまま再依頼しても、本人は返答待ちで相手の番。作者が答える番
        （持ち主の決定 2026-10-02: 依頼より前の発言を数えないのは最後の発言者の枝だけ）"""
        p = pr(
            reviewThreads=conn(thread(comment(user("bob"), T0, "ここはなぜですか"))),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T1)),
        )
        self.assertEqual(tiers(p), {"alice": 0, "bob": 3})

    def test_the_authors_answer_in_a_resolved_thread_after_the_rerequest_counts(self):
        """解決済みスレッドで数えないのは依頼された本人の発言だけ。依頼の後に本人が問い、作者が解決済みスレッドで
        答えたなら作者が最後で、本人の番"""
        p = pr(
            comments=conn(comment(user("bob"), T2, "質問です")),
            reviewThreads=conn(thread(comment(user("alice"), T3, "答えです"), resolved=True)),
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T1)),
        )
        self.assertEqual(tiers(p)["bob"], 0)

    def test_changes_requested_stays_with_the_author_unless_every_requester_is_asked_again(self):
        def cr(*reviews, asked=(), **kw):
            return pr(
                reviewDecision="CHANGES_REQUESTED",
                reviews=conn(*reviews),
                reviewRequests=requests(*asked),
                timelineItems=history(*(requested(a, T3) for a in asked)),
                **kw,
            )

        bob_cr, carol_cr = review(user("bob"), "CHANGES_REQUESTED", T1), review(user("carol"), "CHANGES_REQUESTED", T1)
        for name, p, owes in (
            ("片方だけに再依頼", cr(bob_cr, carol_cr, asked=(user("bob"),)), True),
            ("両方に再依頼", cr(bob_cr, carol_cr, asked=(user("bob"), user("carol"))), False),
            ("Team 宛は本人への再依頼に数えない", cr(bob_cr, asked=(team(),)), True),
            ("再依頼の後に同じ人がまた変更要求", cr(bob_cr, review(user("bob"), "CHANGES_REQUESTED", T3)), True),
            ("承認に変えた人は数えない", cr(bob_cr, carol_cr, review(user("carol"), "APPROVED", T2), asked=(user("bob"),)), False),
            ("退会済みの変更要求", cr(review(None, "CHANGES_REQUESTED", T1), asked=(user("bob"),)), True),
            ("意見が切れている", cr(bob_cr, asked=(user("bob"),), latestOpinionatedReviews=conn(
                {"state": "CHANGES_REQUESTED", "author": user("bob")}, total=31)), True),
            ("login を持つ Team 宛でも", cr(bob_cr, asked=(dict(team(), login="bob"),)), True),
            ("集約値が変更要求でない", pr(reviewRequests=requests(user("bob"))), False),
            ("集約値は変更要求だが意見に変更要求が無い", cr(review(user("bob"), "APPROVED", T1), asked=(user("bob"),)), True),
        ):
            with self.subTest(name):
                self.assertEqual(flow.turn.owes_change_requests(p), owes)
                self.assertEqual("指摘対応" in [k for _, k, _ in flow.pr_balls(p)], owes)

    def test_the_queries_read_each_reviewers_latest_opinion(self):
        for q in (flow.PR_QUERY, flow.LEGACY_PR_QUERY):
            self.assertIn(flow.turn.OPINIONS, q)

    def test_the_queries_read_whether_the_history_window_is_cut(self):
        """材料は手組みなので、turn.window_cut が読む pageInfo をクエリが取るかは字面で照らす"""
        for q in (flow.PR_QUERY, flow.LEGACY_PR_QUERY, flow.ISSUE_QUERY):
            with self.subTest(q=q[:60]):
                window = " ".join(q.split()).split("timelineItems(", 1)[1].split("nodes {", 1)[0]
                self.assertIn("pageInfo { hasPreviousPage }", window)

    def test_the_window_is_cut_as_has_previous_page_says_and_by_count_only_without_it(self):
        for conn_, cut in (
            ({"pageInfo": {"hasPreviousPage": True}, "nodes": [{}]}, True),
            ({"pageInfo": {"hasPreviousPage": True}, "nodes": [{}] * 100}, True),
            ({"pageInfo": {"hasPreviousPage": False}, "nodes": [{}] * 100}, False),
            ({"nodes": [{}] * 100}, True),
            ({"nodes": [{}] * 99}, False),
        ):
            with self.subTest(conn=conn_):
                self.assertEqual(flow.turn.window_cut(conn_, 100), cut)

    def test_review_since_is_that_reviewers_latest_request(self):
        p = pr(
            reviewRequests=requests(user("bob"), user("carol")),
            timelineItems=history(
                requested(user("bob"), T1),
                requested(user("bob"), T2),
                requested(user("carol"), T3),
            ),
        )
        self.assertEqual(
            flow.pr_balls(p),
            [
                ("bob", "レビュー", T2),
                ("carol", "レビュー", T3),
                ("alice", "レビュー待ち", T3),
            ],
        )

    def test_bot_request_does_not_count(self):
        p = pr(
            reviewRequests=requests(bot()), reviews=conn(review(bot(), "COMMENTED", T1))
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T1)])

    def test_team_request_shows_slug(self):
        p = pr(reviewRequests=requests(team()))
        self.assertEqual(
            flow.pr_balls(p),
            [("org/team", "レビュー", T0), ("alice", "レビュー待ち", T0)],
        )

    def test_approved_is_authors_merge(self):
        p = pr(
            reviewDecision="APPROVED", reviews=conn(review(user("bob"), "APPROVED", T2))
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "マージ", T2)])

    def test_approved_with_pending_request_waits_on_reviewer(self):
        p = pr(reviewDecision="APPROVED", reviewRequests=requests(user("carol")))
        self.assertEqual(
            flow.pr_balls(p),
            [("carol", "レビュー", T0), ("alice", "レビュー待ち", T0)],
        )

    def test_pending_request_keeps_the_author_visible(self):
        # 依頼を出した瞬間に作者の一覧から PR が消えると、依頼を出したこと自体が見えなくなる
        p = pr(
            reviewRequests=requests(user("bob")),
            timelineItems=history(requested(user("bob"), T2)),
        )
        self.assertEqual(
            flow.pr_balls(p),
            [("bob", "レビュー", T2), ("alice", "レビュー待ち", T2)],
        )

    def test_pending_request_does_not_add_a_second_author_row(self):
        # 作者に行があるときに足すと merge_rows が since を min() で倒し、日数が依頼日まで戻る
        red = pr(
            commits=rollup(checks("FAILURE")), reviewRequests=requests(user("bob"))
        )
        self.assertEqual(
            flow.pr_balls(red), [("alice", "CI 赤", T2), ("bob", "レビュー", T0)]
        )
        talking = pr(
            reviewRequests=requests(user("bob")),
            reviewThreads=conn(
                thread(comment(user("bob"), T3, "直してください")),
            ),
        )
        self.assertNotIn("レビュー待ち", [k for _, k, _ in flow.pr_balls(talking)])

    def test_pending_request_is_last_even_before_anyone_speaks(self):
        # waiting は「最後に発言したのが本人」で立つ。誰も喋っていない PR でも相手待ちに落とす
        self.assertEqual(flow.tier(pr(), "alice", ["レビュー待ち"], 1, False), 3)
        self.assertEqual(flow.tier(pr(), "alice", ["レビュー待ち"], 1, True), 3)

    def test_human_comment_without_request_is_rerequest(self):
        p = pr(
            reviews=conn(
                review(bot(), "COMMENTED", T1), review(user("bob"), "COMMENTED", T2)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "再依頼", T2)])

    def test_authors_own_reply_review_is_not_a_human_review(self):
        p = pr(
            reviews=conn(
                review(bot(), "COMMENTED", T1), review(user("alice"), "COMMENTED", T2)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T1)])

    def test_never_requested_counts_from_ready_for_review(self):
        p = pr(
            timelineItems=history(
                event("ConvertToDraftEvent", T1), event("ReadyForReviewEvent", T3)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T3)])

    def test_never_asked_counts_from_the_last_commit(self):
        # 作成から寝かせた期間は「待ち」ではない。最後に push した日から数える
        p = pr(commits=rollup(None))
        p["commits"]["nodes"][0]["commit"]["committedDate"] = T3
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T3)])

    def test_asking_a_human_once_is_not_never_asked(self):
        # 人に頼んだ履歴があれば、依頼が消えていても「未依頼」ではない
        p = pr(timelineItems=history(requested(user("bob"), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "レビュー依頼", T2)])

    def test_team_request_counts_as_asking(self):
        p = pr(timelineItems=history(requested(team(), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "レビュー依頼", T2)])

    def test_bot_only_request_history_is_still_never_asked(self):
        # Copilot だけに頼んだ PR は、人から見れば誰にも渡っていない
        p = pr(timelineItems=history(requested(bot(), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T1)])

    def test_unknown_decision_is_visible(self):
        p = pr(reviewDecision="SOMETHING_NEW")
        self.assertEqual(flow.pr_balls(p), [("alice", "分類なし(SOMETHING_NEW)", T0)])

    def test_pr_without_any_review_yet_is_never_asked(self):
        """レビューが 1 件も無い間 reviewDecision は null。分類なしに落とすと最上段に出る"""
        self.assertEqual(
            flow.pr_balls(pr(reviewDecision=None)), [("alice", "未依頼", T1)]
        )

    def test_deleted_author_does_not_crash(self):
        p = pr(author=None)
        self.assertEqual(flow.pr_balls(p)[0][0], None)

    # ---- 会話の状態（未解決スレッド・assignee）

    def test_threads_answered_by_author_go_back_to_opener(self):
        p = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1)),
            reviewThreads=conn(
                thread(comment(user("bob"), T1), comment(user("alice"), T2)),
                thread(comment(user("bob"), T1), comment(user("alice"), T3)),
            ),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "再依頼", T1), ("bob", "再確認 2 件", T2)]
        )

    def test_threads_waiting_on_author_add_author_row(self):
        p = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1)),
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T1),
                    comment(user("alice"), T2),
                    comment(user("bob"), T3),
                )
            ),
        )
        # 1 つのスレッドは 2 人に載る——返す作者と、返事を待っている指摘した側
        self.assertEqual(
            flow.pr_balls(p),
            [
                ("alice", "再依頼", T1),
                ("alice", "スレッド返答 1 件", T3),
                ("bob", "返答待ち 1 件", T3),
            ],
        )

    def test_resolved_bot_only_and_author_only_threads_make_no_rows(self):
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T1), comment(user("alice"), T2), resolved=True
                ),
                thread(comment(bot(), T1)),
                thread(comment(bot(), T1), comment(user("alice"), T2)),
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T1)])

    def test_assignee_other_than_author_gets_row_since_assigned(self):
        p = pr(
            assignees=conn(user("alice"), user("bob")),
            timelineItems=history(assigned("bob", T2)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "未依頼", T1), ("bob", "担当", T2)]
        )

    # ---- 持ち主（返答できる assignee に作者がいなければその全員）

    def test_owners_are_the_assignees_only_when_the_author_is_not_one(self):
        self.assertEqual(flow.owners(pr()), ["alice"])
        self.assertEqual(
            flow.owners(pr(assignees=conn(user("alice"), user("bob")))),
            ["alice"],
        )
        self.assertEqual(
            flow.owners(pr(assignees=conn(user("bob"), user("carol")))),
            ["bob", "carol"],
        )
        # Bot の起票（dependabot 等）も退会済みの作者も、assignee に入りようがない
        for author in (bot("dependabot"), None):
            with self.subTest(author=author):
                p = pr(author=author, assignees=conn(user("bob")))
                self.assertEqual(flow.owners(p), ["bob"])
                self.assertEqual(flow.pr_balls(p), [("bob", "未依頼", T1)])

    def test_only_other_assignees_take_over_every_author_row(self):
        p = pr(
            commits=rollup(checks("FAILURE")),
            assignees=conn(user("bob"), user("carol")),
            timelineItems=history(assigned("bob", T1), assigned("carol", T3)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("bob", "CI 赤", T2), ("carol", "CI 赤", T3)]
        )

    def test_draft_moves_to_the_assignee_too(self):
        p = pr(
            isDraft=True,
            assignees=conn(user("bob")),
            timelineItems=history(assigned("bob", T2)),
        )
        self.assertEqual(flow.pr_balls(p), [("bob", "draft", T2)])

    def test_review_wait_moves_to_the_assignee_and_is_not_doubled(self):
        asked = pr(
            reviewRequests=requests(user("carol")),
            assignees=conn(user("bob")),
        )
        self.assertEqual(
            flow.pr_balls(asked), [("carol", "レビュー", T0), ("bob", "レビュー待ち", T0)]
        )
        red = pr(
            commits=rollup(checks("FAILURE")),
            reviewRequests=requests(user("carol")),
            assignees=conn(user("bob")),
        )
        self.assertEqual(
            flow.pr_balls(red), [("bob", "CI 赤", T2), ("carol", "レビュー", T0)]
        )

    def test_review_wait_is_judged_per_owner(self):
        p = pr(
            reviewRequests=requests(user("dave")),
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(
                thread(comment(user("bob"), T1, "ここ要りますか"), comment(user("carol"), T2))
            ),
        )
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][0], ["再確認 1 件"])
        self.assertEqual(rows["carol"][0], ["レビュー待ち"])

    def test_authors_other_roles_stay_with_the_author(self):
        p = pr(assignees=conn(user("bob")))
        p["pendingReview"] = {"by": "alice", "comments": 1, "since": T2}
        self.assertEqual(
            flow.pr_balls(p), [("bob", "未依頼", T1), ("alice", "未送信", T2)]
        )

    def test_the_owner_sides_own_reply_is_not_a_human_review(self):
        for replier in ("alice", "bob"):
            with self.subTest(replier=replier):
                p = pr(
                    assignees=conn(user("bob")),
                    reviews=conn(review(user(replier), "COMMENTED", T2)),
                )
                self.assertEqual(flow.pr_balls(p), [("bob", "未依頼", T1)])

    def test_the_holders_own_question_keeps_the_review_wait(self):
        p = pr(
            reviewRequests=requests(user("carol")),
            assignees=conn(user("bob")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "この仕様で合っていますか"))),
        )
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"][0], ["レビュー待ち"])
        self.assertEqual(flow.pr_tiers(p)["bob"][0], 3)

    def test_a_reviewers_own_question_still_decides_their_tier(self):
        p = pr(reviewThreads=conn(thread(comment(user("carol"), T1, "これは？"))))
        p["pendingReview"] = {"by": "carol", "comments": 1, "since": T2}
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["carol"][0], ["未送信", "返答待ち 1 件"])
        self.assertEqual(flow.pr_tiers(p)["carol"][0], 3)

    def test_the_owners_unsent_draft_is_their_row_while_a_review_is_requested(self):
        p = pr(
            reviewRequests=requests(user("carol")),
            timelineItems=history(requested(user("carol"), T0)),
        )
        p["pendingReview"] = {"by": "alice", "comments": 1, "since": T2}
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["alice"], (["未送信"], T2))
        self.assertEqual(flow.pr_tiers(p)["alice"][0], 2)

    def test_received_threads_do_not_pull_the_wait_back_before_the_handover(self):
        p = pr(
            assignees=conn(user("bob")),
            timelineItems=history(assigned("bob", T3)),
            reviewThreads=conn(
                thread(comment(user("carol"), T0, "これは？")),
                thread(comment(user("bob"), T0, "この仕様で合っていますか")),
            ),
        )
        p["pendingReview"] = {"by": "bob", "comments": 1, "since": T0}
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][1], T3)
        self.assertEqual(rows["carol"], (["返答待ち 1 件"], T0))
        self.assertEqual(rows["alice"], (["スレッド返答 1 件"], T0))

    def test_the_author_who_assigned_themselves_keeps_the_wait(self):
        p = pr(
            commits=rollup(checks("FAILURE")),
            assignees=conn(user("alice"), user("bob")),
            timelineItems=history(assigned("alice", T3), assigned("bob", T2)),
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "CI 赤", T2), ("bob", "担当", T2)])

    def test_two_owners_share_every_formal_row(self):
        dave = user("dave")
        shared = {
            "CI 赤": dict(commits=rollup(checks("FAILURE"))),
            "指摘対応": dict(reviewDecision="CHANGES_REQUESTED", reviews=conn(review(dave, "CHANGES_REQUESTED", T1))),
            "マージ": dict(reviewDecision="APPROVED", reviews=conn(review(dave, "APPROVED", T1))),
            "再依頼": dict(reviews=conn(review(dave, "COMMENTED", T1))),
            "レビュー依頼": dict(timelineItems=history(requested(dave, T1))),
            "分類なし": dict(reviewDecision="NEW_VALUE"),
        }
        for kind, kw in shared.items():
            with self.subTest(kind=kind):
                two = pr(assignees=conn(user("bob"), user("carol")), **kw)
                self.assertTrue(flow.merge_rows(flow.pr_balls(two))["bob"][0][0].startswith(kind))
                self.assertEqual(tiers(two), {"bob": 1, "carol": 1})
                self.assertEqual(flow.pr_tiers(pr(assignees=conn(user("bob")), **kw))["bob"][0], 0)

    def test_two_owners_keep_their_own_rows_to_themselves(self):
        two = conn(user("bob"), user("carol"))
        rechecks = pr(
            assignees=two,
            reviewThreads=conn(thread(comment(user("bob"), T1, "ここは？"), comment(user("alice"), T2, "意図どおり"))),
        )
        self.assertEqual(tiers(rechecks), {"bob": 0, "carol": 2})
        asked = pr(assignees=two, reviewRequests=requests(user("bob")))
        self.assertEqual(tiers(asked), {"bob": 0, "carol": 3})
        red_draft = pr(assignees=two, isDraft=True, commits=rollup(checks("FAILURE")))
        self.assertEqual(
            flow.merge_rows(flow.pr_balls(red_draft)), {"bob": (["draft"], T0), "carol": (["draft"], T0)}
        )
        self.assertEqual(tiers(red_draft), {"bob": 2, "carol": 2})

    def test_an_assignees_open_question_to_the_other_side(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "この仕様で合っていますか"))),
        )
        self.assertEqual(
            flow.merge_rows(flow.pr_balls(p)),
            {
                "bob": (["未依頼"], T1),
                "carol": (["未依頼", "スレッド返答 1 件"], T1),
                "alice": (["スレッド返答 1 件"], T1),
            },
        )
        self.assertEqual(tiers(p), {"bob": 2, "carol": 1, "alice": 1})

    def test_unanswerable_assignees_are_not_handed_the_pr(self):
        for nobody in (bot("Copilot"), None, mannequin("old-bob")):
            with self.subTest(assignee=nobody):
                p = pr(assignees=conn(nobody), comments=conn(comment(user("alice"), T3, "お願いします")))
                self.assertEqual(flow.owners(p), ["alice"])
                self.assertEqual(flow.pr_balls(p), [("alice", "未依頼", T1)])
                self.assertEqual(flow.pr_tiers(p), {"alice": (2, T1)})

    def test_handed_over_only_when_the_author_left_themselves_out(self):
        for assignees, legacy, want in (
            ((user("alice"),), False, False),
            ((user("alice"), user("bob")), False, False),
            ((user("bob"),), False, True),
            ((bot("Copilot"),), False, False),
            ((bot("Copilot"),), True, True),
            ((user("alice"), user("bob")), True, False),
            ((), False, False),
        ):
            with self.subTest(assignees=assignees, legacy=legacy):
                p = pr(assignees=conn(*assignees))
                if legacy:
                    p["assigneeKindsUnknown"] = True
                self.assertEqual(flow.turn.handed_to_others(p), want)
                self.assertEqual(flow.owners(p) != ["alice"], want and not legacy)

    def test_split_and_author_holds_handed_are_shared_with_catchup(self):
        legacy = {"assigneeKindsUnknown": True}
        for name, kw, asked, kind, holds in (
            ("誰も", {}, None, "未依頼", False),
            ("依頼した", {}, T1, "レビュー依頼", False),
            ("相手のレビュー", dict(reviews=conn(review(user("dave"), "COMMENTED", T1))), None, "再依頼", False),
            ("作者の返信", dict(reviews=conn(review(user("alice"), "COMMENTED", T1))), None, "未依頼", False),
            ("Bot のレビュー", dict(reviews=conn(review(bot(), "COMMENTED", T1))), None, "未依頼", False),
            ("受けた人の返信", dict(assignees=conn(user("bob")), reviews=conn(review(user("bob"), "COMMENTED", T1))),
             None, "未依頼", False),
            ("種別の取れない GitHub で渡した", dict(assignees=conn({"login": "bob"}), **legacy), None, "未依頼", True),
            ("種別の取れない GitHub で作者も担当", dict(assignees=conn({"login": "alice"}, {"login": "bob"}), **legacy),
             None, "未依頼", False),
        ):
            with self.subTest(name):
                p = pr(**kw)
                self.assertEqual(flow.turn.split(p, p["reviews"]["nodes"], asked), kind)
                self.assertEqual(flow.turn.author_holds_handed(p), holds)

    def test_mixed_assignees_hand_the_pr_to_the_people_only(self):
        p = pr(assignees=conn(user("bob"), bot("Copilot")), commits=rollup(checks("FAILURE")))
        self.assertEqual(flow.owners(p), ["bob"])
        self.assertEqual(flow.pr_balls(p), [("bob", "CI 赤", T2)])
        self.assertIn("assignee: bob, Copilot", flow.pr_facts(p, "dave"))
        alice = flow.pr_facts(p, "alice")
        self.assertIn("担当に渡した PR（担当は bob）", alice)
        self.assertIn("assignee: Copilot", alice)
        kept = pr(assignees=conn(user("alice"), bot("Copilot")))
        self.assertEqual(flow.pr_balls(kept), [("alice", "未依頼", T1)])

    def test_two_human_reviewers_each_see_someone_else_can_move_it(self):
        self.assertEqual(tiers(pr(reviewRequests=requests(user("bob"), user("carol")))), {"bob": 1, "carol": 1, "alice": 3})
        self.assertEqual(tiers(pr(reviewRequests=requests(user("bob"), bot()))), {"bob": 0, "alice": 3})

    def test_tier_shared_review_second_and_waiting_last(self):
        def t(kinds, reviewers, waiting, shared=False, who="bob", **kw):
            return flow.tier(pr(**kw), who, kinds, reviewers, waiting, shared)

        self.assertEqual(t(["レビュー"], 2, False), 1)
        self.assertEqual(t(["レビュー"], 1, False), 0)
        self.assertEqual(t(["レビュー依頼"], 3, False), 0)
        self.assertEqual(t(["再確認 2 件"], 3, False), 0)
        self.assertEqual(t(["CI 赤", "レビュー"], 3, False), 0)
        # 相手の返事待ちは、依頼先が何人でも最後
        self.assertEqual(t(["レビュー"], 1, True), 3)
        self.assertEqual(t(["レビュー"], 2, True), 3)
        self.assertEqual(t(["再依頼"], 1, True), 3)
        # 相手にも返す番が残っているなら、その人が全部片づけても PR は終わらない
        self.assertEqual(t(["再確認 2 件"], 1, False, True), 1)
        self.assertEqual(t(["スレッド返答 1 件"], 1, False, True), 1)
        # 渡していない PR は誰も待っていないが、動かせるのは本人だけ。相手待ちより上
        self.assertEqual(t(["未依頼"], 0, False, who="alice"), 2)
        self.assertEqual(t(["draft"], 0, False, who="alice"), 2)

    def test_tier_drops_follow_up_when_only_the_author_can_clear_the_blocker(self):
        def t(who, **kw):
            return flow.tier(pr(**kw), who, ["再確認 1 件"], 1, False)

        self.assertEqual(t("bob"), 0)
        # main 未追従・衝突・CI 赤は持ち主しか外せない。残りが再確認だけなら最後
        self.assertEqual(t("bob", mergeStateStatus="BEHIND"), 3)
        self.assertEqual(t("bob", mergeStateStatus="DIRTY"), 3)
        self.assertEqual(t("bob", commits=rollup(checks("FAILURE"))), 3)
        # 作者自身は外せる側なので降ろさない
        self.assertEqual(t("alice", mergeStateStatus="BEHIND"), 0)

    def test_tier_keeps_follow_up_up_when_real_work_remains(self):
        # 同じ PR に未消化のレビュー依頼があるなら、作者が詰まっていてもその人しかできない仕事が残る
        self.assertEqual(
            flow.tier(
                pr(mergeStateStatus="BEHIND"),
                "bob",
                ["レビュー", "再確認 1 件"],
                1,
                False,
            ),
            0,
        )
        # 相手の返事待ちは shared より強い
        self.assertEqual(flow.tier(pr(), "bob", ["レビュー"], 1, True, True), 3)

    def test_owes_thread_covers_both_directions_of_unresolved_threads(self):
        self.assertTrue(flow.owes_thread(["再確認 2 件"]))
        self.assertTrue(flow.owes_thread(["マージ", "スレッド返答 5 件"]))
        self.assertFalse(flow.owes_thread(["再依頼", "レビュー"]))

    def test_shared_balls_needs_two_people_with_thread_turns(self):
        both = {
            "alice": (["マージ", "スレッド返答 5 件"], T1),
            "bob": (["再確認 7 件"], T2),
            "carol": (["レビュー"], T3),
        }
        self.assertEqual(flow.shared_balls(both), {"alice", "bob"})
        one_side = {
            "alice": (["再依頼", "スレッド返答 3 件"], T1),
            "bob": (["レビュー"], T2),
        }
        self.assertEqual(flow.shared_balls(one_side), set())
        two_openers = {"bob": (["再確認 1 件"], T1), "carol": (["再確認 2 件"], T2)}
        self.assertEqual(flow.shared_balls(two_openers), {"bob", "carol"})
        self.assertEqual(flow.shared_balls({}), set())

    def test_same_name_rerun_uses_the_last_run(self):
        p = pr(commits=rollup(runs(("chk", "FAILURE", T1), ("chk", "SUCCESS", T2))))
        self.assertNotIn("CI 赤", [r[1] for r in flow.pr_balls(p)])

    def test_same_name_rerun_that_fails_last_is_red(self):
        p = pr(commits=rollup(runs(("chk", "SUCCESS", T1), ("chk", "FAILURE", T2))))
        self.assertEqual(flow.pr_balls(p), [("alice", "CI 赤", T2)])

    def test_running_rerun_outranks_the_old_failure(self):
        p = pr(commits=rollup(runs(("chk", "FAILURE", T2), ("chk", None, None))))
        self.assertNotIn("CI 赤", [r[1] for r in flow.pr_balls(p)])

    def test_different_names_are_not_collapsed(self):
        p = pr(commits=rollup(runs(("a", "SUCCESS", T2), ("b", "FAILURE", T1))))
        self.assertEqual(flow.pr_balls(p), [("alice", "CI 赤", T1)])

    def test_merge_rows_joins_kinds_and_keeps_oldest(self):
        rows = [
            ("a", "再依頼", T2),
            ("a", "スレッド返答 3 件", T1),
            ("b", "再確認 1 件", T3),
        ]
        self.assertEqual(
            flow.merge_rows(rows),
            {"a": (["再依頼", "スレッド返答 3 件"], T1), "b": (["再確認 1 件"], T3)},
        )


class WaitingOnOthers(unittest.TestCase):
    def test_author_who_answered_every_thread_and_spoke_last_is_waiting(self):
        p = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1, "見た")),
            reviewThreads=conn(
                thread(comment(user("bob"), T1), comment(user("alice"), T2))
            ),
            comments=conn(comment(user("alice"), T3, "全部返しました")),
        )
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["alice"][0], ["再依頼"])
        self.assertTrue(flow.waiting_on_others(p, "alice", rows["alice"][0]))
        # 同じ PR でも、確認する番のスレッドを持つ側は待っていない
        self.assertFalse(flow.waiting_on_others(p, "bob", rows["bob"][0]))

    def test_reviewer_who_asked_a_question_is_waiting(self):
        p = pr(
            reviewRequests=requests(user("bob")),
            comments=conn(comment(user("bob"), T2, "これは顧客テナントですか")),
        )
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][0], ["レビュー"])
        self.assertTrue(flow.waiting_on_others(p, "bob", rows["bob"][0]))

    def test_author_who_still_owes_thread_replies_is_not_waiting(self):
        p = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1, "見た")),
            reviewThreads=conn(thread(comment(user("bob"), T1))),
            comments=conn(comment(user("alice"), T3, "main を取り込みました")),
        )
        kinds = flow.merge_rows(flow.pr_balls(p))["alice"][0]
        self.assertIn("スレッド返答 1 件", kinds)
        self.assertFalse(flow.waiting_on_others(p, "alice", kinds))

    def test_authors_unrelated_comment_does_not_take_back_the_ball(self):
        """自分が立てたスレッドに作者が未返信なら、作者が別件で喋っても作者の番"""
        p = pr(
            reviewThreads=conn(thread(comment(user("bob"), T1, "ここが変"))),
            comments=conn(comment(user("alice"), T3, "別件のメモです")),
        )
        self.assertTrue(flow.waiting_on_others(p, "bob", ["レビュー"]))
        # 作者の側は逆で、返す番があるので相手待ちではない
        self.assertFalse(flow.waiting_on_others(p, "alice", ["スレッド返答 1 件"]))

    def test_reviewer_who_has_not_spoken_is_not_waiting(self):
        p = pr(
            reviewRequests=requests(user("bob")),
            comments=conn(comment(user("alice"), T2, "レビューをお願いします")),
        )
        self.assertFalse(flow.waiting_on_others(p, "bob", ["レビュー"]))

    def test_no_post_at_all_is_not_waiting(self):
        self.assertFalse(flow.waiting_on_others(pr(), "alice", ["未依頼"]))

    def test_bot_post_does_not_end_the_conversation(self):
        p = pr(
            comments=conn(comment(user("alice"), T1, "扱いはお任せします")),
            reviews=conn(review(bot(), "COMMENTED", T3, "自動レビュー")),
        )
        self.assertTrue(flow.waiting_on_others(p, "alice", ["未依頼"]))


class PrFacts(unittest.TestCase):
    def test_red_check_names(self):
        p = pr(commits=rollup(checks("FAILURE", ("state", "ERROR"), "SUCCESS")))
        self.assertIn("CI 赤: chk0, ctx1", flow.pr_facts(p))

    def test_behind_only_matters_when_approved(self):
        self.assertEqual(
            [f for f in flow.pr_facts(pr(mergeStateStatus="BEHIND")) if "BEHIND" in f],
            [],
        )
        facts = flow.pr_facts(pr(mergeStateStatus="BEHIND", reviewDecision="APPROVED"))
        self.assertTrue(any("BEHIND" in f for f in facts))

    def test_thread_breakdown_and_last_speaker(self):
        p = pr(
            reviewThreads=conn(
                thread(comment(user("bob"), T1), comment(user("alice"), T2)),
                thread(comment(user("bob"), T1)),
                thread(comment(bot(), T1), comment(user("alice"), T2)),
                thread(comment(bot(), T1)),
            ),
            comments=conn(comment(user("carol"), T3, "x")),
        )
        facts = flow.pr_facts(p)
        self.assertIn(
            "未解決 4 スレッド（bob が再確認 1・alice が返答 1・人は alice だけ 1・Bot だけ 1）",
            facts,
        )
        self.assertIn("最後の発言: carol（08-04 00:00）", facts)

    def test_outdated_threads_are_counted_but_do_not_change_whose_turn(self):
        p = pr(
            reviewThreads=conn(
                thread(comment(user("bob"), T1), outdated=True),
                thread(comment(user("bob"), T1)),
            )
        )
        self.assertIn(
            "未解決 2 スレッド（alice が返答 2（1 は差分が動いた））", flow.pr_facts(p)
        )
        self.assertEqual(
            [r for r in flow.pr_balls(p) if "スレッド返答" in r[1]],
            [("alice", "スレッド返答 2 件", T1)],
        )

    def test_a_deleted_writer_is_not_counted_under_a_living_authors_name(self):
        note = thread(comment(user("alice"), T1, "自分メモ"), comment(None, T2, "同感"))
        self.assertIn(
            "未解決 1 スレッド（人は alice, 退会済み だけ 1）", flow.pr_facts(pr(reviewThreads=conn(note)))
        )

    def test_deleted_author_falls_back_to_the_role_word(self):
        p = pr(
            author=None,
            reviewThreads=conn(thread(comment(user("bob"), T1))),
        )
        self.assertIn("未解決 1 スレッド（作者 が返答 1）", flow.pr_facts(p))

    def test_assignee_fact(self):
        self.assertIn(
            "assignee: bob", flow.pr_facts(pr(assignees=conn(user("bob"))))
        )

    def test_author_is_named_only_when_the_reader_is_not_the_author(self):
        self.assertIn("作者: alice", flow.pr_facts(pr(), "bob"))
        self.assertNotIn("作者: alice", flow.pr_facts(pr(), "alice"))
        self.assertIn("作者: 退会済み", flow.pr_facts(pr(author=None), "bob"))

    def test_each_side_reads_its_role_once_handed_over(self):
        p = pr(
            body="入口の検査を足します。",
            additions=3, deletions=1, changedFiles=2,
            assignees=conn(user("bob"), user("carol")),
        )
        alice = flow.pr_facts(p, "alice", intro=True)
        self.assertIn("担当に渡した PR（担当は bob, carol）", alice)
        self.assertEqual(
            [f for f in alice if f.startswith(("作者:", "担当として", "本文:", "規模:"))], []
        )
        self.assertIn("担当として受けた PR（起票は alice）", flow.pr_facts(p, "bob"))
        dave = flow.pr_facts(p, "dave")
        self.assertIn("作者: alice", dave)
        self.assertEqual([f for f in dave if f.startswith("担当")], [])
        kept = pr(assignees=conn(user("alice"), user("bob")))
        self.assertEqual([f for f in flow.pr_facts(kept, "alice") if f.startswith("担当")], [])

    def test_assignee_line_does_not_repeat_the_role_line(self):
        def line(p, who):
            return [f for f in flow.pr_facts(p, who) if f.startswith("assignee:")]

        two = pr(assignees=conn(user("bob"), user("carol")))
        self.assertEqual(line(two, "alice"), [])
        self.assertEqual(line(two, "bob"), ["assignee: carol"])
        self.assertEqual(line(two, "dave"), ["assignee: bob, carol"])
        kept = pr(assignees=conn(user("alice"), user("bob")))
        self.assertEqual(line(kept, "alice"), ["assignee: bob"])
        self.assertEqual(line(kept, "bob"), ["assignee: bob"])

    def test_author_only_blockers_name_who_can_clear_them(self):
        red = pr(commits=rollup(checks("FAILURE")))
        self.assertIn(
            "CI 赤: chk0。外せるのは作者の alice だけ", flow.pr_facts(red, "bob")
        )
        self.assertIn("CI 赤: chk0", flow.pr_facts(red, "alice"))
        behind = pr(mergeStateStatus="BEHIND", reviewDecision="APPROVED")
        self.assertIn(
            "main 未追従（BEHIND）。マージ前に取り込みが要る。外せるのは作者の alice だけ",
            flow.pr_facts(behind, "bob"),
        )

    def test_blockers_name_the_assignees_once_handed_over(self):
        red = pr(
            commits=rollup(checks("FAILURE")),
            assignees=conn(user("bob"), user("carol")),
        )
        for reader in ("alice", "dave"):
            self.assertIn(
                "CI 赤: chk0。外せるのは担当の bob, carol だけ", flow.pr_facts(red, reader)
            )
        self.assertIn("CI 赤: chk0", flow.pr_facts(red, "bob"))
        self.assertTrue(flow.blocked_by_others(red, "alice", ["再確認 1 件"]))
        self.assertFalse(flow.blocked_by_others(red, "bob", ["再確認 1 件"]))

    def test_own_review_state_is_shown(self):
        p = pr(
            reviews=conn(
                review(user("bob"), "APPROVED", T1),
                review(user("bob"), "COMMENTED", T3),
                review(user("carol"), "CHANGES_REQUESTED", T2),
            )
        )
        # COMMENTED は「読んだ」以上を言わないので数えない。最後の判定だけを出す
        self.assertIn(
            "bob のレビュー: APPROVED（08-02 00:00）", flow.pr_facts(p, "bob")
        )
        self.assertIn(
            "carol のレビュー: CHANGES_REQUESTED（08-03 00:00）",
            flow.pr_facts(p, "carol"),
        )
        self.assertEqual(
            [f for f in flow.pr_facts(pr(), "bob") if "レビュー:" in f], []
        )

    def test_counterpart_silence_is_measured_when_you_spoke_last(self):
        p = pr(
            comments=conn(
                comment(user("alice"), T1, "直しました"),
                comment(user("bob"), T3, "ここも見てください"),
            )
        )
        facts = flow.pr_facts(p, "bob")
        self.assertIn("最後の発言: bob（08-04 00:00）", facts)
        self.assertIn("alice は 08-02 00:00 以降 発言なし", facts)
        # 相手が最後なら誰が待っているかは自明なので足さない
        self.assertEqual([f for f in flow.pr_facts(p, "alice") if "発言なし" in f], [])

    def test_silence_names_who_owes_a_turn_not_who_spoke_last(self):
        """通りすがりに発言した人を催促の宛先にすると、実際に止めている相手が隠れる"""
        p = pr(
            # alice が返す番のスレッド。alice の最後の発言は T1 で、その後に carol が通りすがる
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T0),
                    comment(user("alice"), T1),
                    comment(user("bob"), T2),
                )
            ),
            reviews=conn(review(user("carol"), "APPROVED", T2, "私は良いと思います")),
            comments=conn(comment(user("bob"), T3, "ここも見てください")),
        )
        facts = flow.pr_facts(p, "bob")
        self.assertIn("alice は 08-02 00:00 以降 発言なし", facts)
        self.assertEqual([f for f in facts if "carol" in f], [])

    def test_silence_names_the_assignee_who_owes_once_handed_over(self):
        p = pr(
            assignees=conn(user("bob")),
            reviewThreads=conn(thread(comment(user("carol"), T0, "これは？"))),
            comments=conn(
                comment(user("alice"), T0, "bob さんに渡します"),
                comment(user("bob"), T1, "見ます"),
                comment(user("carol"), T2, "どうでしょう"),
            ),
        )
        facts = flow.pr_facts(p, "carol")
        self.assertIn("bob は 08-02 00:00 以降 発言なし", facts)
        self.assertEqual([f for f in facts if f.startswith("alice は")], [])

    def test_silence_names_an_owner_who_never_spoke(self):
        question = conn(thread(comment(user("carol"), T2, "これは？")))
        received = pr(
            assignees=conn(user("bob")), timelineItems=history(assigned("bob", T1)), reviewThreads=question
        )
        self.assertIn(
            "bob は 08-02 00:00 以降 発言なし（この PR で発言が無い）", flow.pr_facts(received, "carol")
        )
        unknown = pr(assignees=conn(user("bob")), reviewThreads=question)
        self.assertIn(
            "bob は 08-01 00:00 以降 発言なし（この PR で発言が無い）", flow.pr_facts(unknown, "carol")
        )
        held = pr(
            assignees=conn(user("alice")), timelineItems=history(assigned("alice", T1)), reviewThreads=question
        )
        # 作者は作成日に本文を書いている
        self.assertIn("alice は 08-01 00:00 以降 発言なし", flow.pr_facts(held, "carol"))
        by_bot = pr(author=bot("dependabot"), reviewThreads=question)
        self.assertEqual([f for f in flow.pr_facts(by_bot, "carol") if "発言なし" in f], [])

    def test_silence_past_a_cut_off_window_says_only_what_was_seen(self):
        question = conn(thread(comment(user("carol"), T2, "これは？")))
        for cut_off in (
            dict(comments=conn(comment(user("dave"), T1), total=180)),
            dict(reviews=conn(total=130)),
        ):
            for owner, received in (("bob", conn(user("bob"))), ("alice", conn())):
                with self.subTest(cut_off=list(cut_off), owner=owner):
                    p = pr(assignees=received, reviewThreads=question, **cut_off)
                    self.assertIn(
                        f"{owner} は 08-01 00:00 以降 発言なし（見た範囲で発言が無い）", flow.pr_facts(p, "carol")
                    )

    def test_silence_past_a_cut_history_says_only_what_was_seen(self):
        question = conn(thread(comment(user("carol"), T2, "これは？")))
        lost = pr(assignees=conn(user("bob")), timelineItems=history(earlier=True), reviewThreads=question)
        self.assertIn("bob は 08-01 00:00 以降 発言なし（見た範囲で発言が無い）", flow.pr_facts(lost, "carol"))
        self.assertIn(
            "#1: 履歴（assign・レビュー依頼・draft の出し入れ）は新しい 100 件しか見ていない", flow.limits_of_pr(lost)
        )
        kept = pr(
            assignees=conn(user("bob")), timelineItems=history(assigned("bob", T1), earlier=True), reviewThreads=question
        )
        self.assertIn("bob は 08-02 00:00 以降 発言なし（この PR で発言が無い）", flow.pr_facts(kept, "carol"))

    def test_a_review_without_a_body_counts_as_having_spoken(self):
        p = pr(
            assignees=conn(user("bob")),
            reviews=conn(review(user("bob"), "APPROVED", T1)),
            reviewThreads=conn(thread(comment(user("carol"), T2, "これは？"))),
        )
        facts = flow.pr_facts(p, "carol")
        self.assertIn("bob は 08-02 00:00 以降 発言なし", facts)
        self.assertEqual([f for f in facts if "この PR で発言が無い" in f], [])

    def test_the_reader_who_owes_and_spoke_last_is_not_named_silent(self):
        question = conn(thread(comment(user("carol"), T1, "これは？")))
        for reader, received in (("bob", conn(user("bob"))), ("alice", conn())):
            with self.subTest(reader=reader):
                p = pr(
                    assignees=received,
                    reviewThreads=question,
                    comments=conn(comment(user(reader), T3, "別件です")),
                )
                self.assertIn(reader, {o for o, _, _ in flow.answered_threads(p)[1]})
                self.assertEqual([f for f in flow.pr_facts(p, reader) if "発言なし" in f], [])

    def test_silence_falls_back_to_the_last_other_speaker_when_nobody_owes(self):
        p = pr(
            comments=conn(
                comment(user("carol"), T0),
                comment(user("alice"), T1),
                comment(user("carol"), T2),  # 先に喋った人が最新とは限らない
                comment(user("bob"), T3),
            )
        )
        facts = flow.pr_facts(p, "bob")
        self.assertIn("carol は 08-03 00:00 以降 発言なし", facts)
        self.assertEqual([f for f in facts if "alice は" in f], [])

    def test_stale_referenced_issue_is_flagged(self):
        p = pr(
            reviewThreads=conn(
                thread(comment(user("bob"), T2, "別 PR として #7 を立てました")),
                thread(comment(user("bob"), T2, "#8 で追います")),
                thread(comment(user("bob"), T2, "#9 に寄せます"), resolved=True),
            )
        )
        issues = {
            7: issue(number=7, created=T1, updated=T1),  # 参照より前で止まっている
            8: issue(number=8, created=T1, updated=T3),  # 参照後に動いた
            9: issue(number=9, created=T1, updated=T1),  # 解決済みスレッドなので見ない
        }
        self.assertIn(
            "スレッドが逃がした先で、参照後に動いていないもの: #7",
            flow.pr_facts(p, "bob", issues),
        )
        # PR より前からある issue は元からの追跡先。参照しただけで動く義務は無い
        old = {7: issue(number=7, created=T0, updated=T0)}
        self.assertEqual(
            [f for f in flow.pr_facts(p, "bob", old) if "動いていない" in f], []
        )
        # 参照先の一覧が無ければ何も言わない（close 済みか未取得かの区別が付かない）
        self.assertEqual(
            [f for f in flow.pr_facts(p, "bob") if "動いていない" in f], []
        )

    def test_stale_referenced_pull_request_is_flagged_too(self):
        """逃がし先は issue とは限らない。PR に委ねた指摘も、行き先が止まれば一緒に止まる"""
        p = pr(
            reviewThreads=conn(
                thread(comment(user("bob"), T2, "この 9 ジョブは #7 に委ねました"))
            )
        )
        dest = pr(number=7, createdAt=T1)
        dest["updatedAt"] = T1
        self.assertIn(
            "スレッドが逃がした先で、参照後に動いていないもの: PR #7",
            flow.pr_facts(p, "bob", {7: dest}),
        )
        dest["updatedAt"] = T3  # 参照後に動いた行き先は言わない
        self.assertEqual(
            [f for f in flow.pr_facts(p, "bob", {7: dest}) if "動いていない" in f], []
        )

    def test_self_reference_is_not_a_stale_destination(self):
        """自分の番号を書いただけで自分が止まっている扱いになると、全 PR に付いて読めなくなる"""
        p = pr(
            number=7,
            createdAt=T1,
            reviewThreads=conn(thread(comment(user("bob"), T2, "#7 の話"))),
        )
        p["updatedAt"] = T1
        self.assertEqual(
            [f for f in flow.pr_facts(p, "bob", {7: p}) if "動いていない" in f], []
        )

    def test_dead_bot_thread_carries_the_moved_marker(self):
        p = pr(
            reviewThreads=conn(
                thread(comment(bot(), T1), outdated=True),
                thread(comment(bot(), T1)),
            )
        )
        self.assertIn(
            "未解決 2 スレッド（Bot だけ 2（1 は差分が動いた））", flow.pr_facts(p)
        )


class Pending(unittest.TestCase):
    """未送信（PENDING）のレビューは書いた本人にしか見えない。判定に混ぜると相手の番に化ける"""

    def draft(self):
        return pr(
            reviews=conn(review(user("bob"), "PENDING", T2, "まとめ")),
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T2, "下書きの指摘", state="PENDING"),
                    path="only-draft.py",
                ),
                thread(
                    comment(user("carol"), T0, "送信済みの指摘"),
                    comment(user("bob"), T2, "下書きの相乗り", state="PENDING"),
                    path="mixed.py",
                ),
            ),
        )

    def test_pending_review_and_comments_leave_the_judgement(self):
        p = self.draft()
        self.assertEqual(
            flow.drop_pending(p), {"by": "bob", "comments": 2, "since": T2}
        )
        self.assertEqual(p["reviews"]["nodes"], [])
        # 下書きだけのスレッドは相手に存在しないので消える。相乗りは元の指摘だけ残る
        self.assertEqual(
            [
                (t["path"], [c["body"] for c in t["comments"]["nodes"]])
                for t in p["reviewThreads"]["nodes"]
            ],
            [("mixed.py", ["送信済みの指摘"])],
        )

    def test_dropping_keeps_the_truncation_check_honest(self):
        p = self.draft()
        flow.drop_pending(p)
        self.assertEqual([w for w in flow.limits_of_pr(p) if w], [])

    def test_pending_does_not_hand_the_ball_to_the_other_side(self):
        p = self.draft()
        flow.drop_pending(p)
        # 下書きは carol の指摘を隠さない。作者が答える番のままで、bob には移らない
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")], ["送信済みの指摘"]
        )
        self.assertEqual(flow.turn_threads(p, "bob"), [])

    def test_unsent_review_is_its_own_ball_and_is_not_waiting_on_anyone(self):
        p = self.draft()
        flow.drop_pending(p)
        self.assertIn(("bob", "未送信", T2), flow.pr_balls(p))
        self.assertIn(
            "未送信のレビュー 2 件。書いただけで相手には届いていない",
            flow.pr_facts(p, "bob"),
        )
        # 書いた本人にしか見えないので、他の人の行には出さない
        self.assertNotIn(
            "未送信のレビュー 2 件。書いただけで相手には届いていない",
            flow.pr_facts(p, "carol"),
        )
        # まだ誰にも渡していない段（2）。相手待ち（3）に沈めると送り忘れが埋もれる
        self.assertEqual(flow.tier(p, "bob", ["未送信"], 0, False), 2)

    def test_unsent_review_does_not_hide_the_authors_own_ball(self):
        """未送信は別人の行。作者の形式上の行（マージ・未依頼）を押しのけてはいけない"""
        p = self.draft()
        p["reviewDecision"] = "APPROVED"
        p["reviews"]["nodes"].append(review(user("carol"), "APPROVED", T1))
        flow.drop_pending(p)
        rows = flow.pr_balls(p)
        self.assertIn(("alice", "マージ", T1), rows)
        self.assertIn(("bob", "未送信", T2), rows)

    def test_unsent_review_survives_draft(self):
        p = self.draft()
        p["isDraft"] = True
        flow.drop_pending(p)
        self.assertIn(("bob", "未送信", T2), flow.pr_balls(p))

    def test_unsent_review_does_not_break_sorting_posts(self):
        """PENDING の submittedAt は null。落とさないと発言を時刻で並べる所で全体が落ちる"""
        p = self.draft()
        with self.assertRaises(TypeError):
            flow.posts_of_pr(p)
        flow.drop_pending(p)
        self.assertEqual(
            flow.latest_human_post(flow.posts_of_pr(p))["body"], "送信済みの指摘"
        )


class References(unittest.TestCase):
    REPO = "IL-SW-AI/guided-resolver"

    def test_bare_number_and_own_url_are_picked_up(self):
        self.assertEqual(flow.issue_refs("#1466 を立てました", self.REPO), {1466})
        self.assertEqual(
            flow.issue_refs(
                f"https://github.com/{self.REPO}/issues/1466 を参照", self.REPO
            ),
            {1466},
        )
        self.assertEqual(
            flow.issue_refs(f"https://github.com/{self.REPO}/pull/12", self.REPO), {12}
        )

    def test_another_repositorys_url_is_not_ours(self):
        """番号空間が重なるので、他所の URL を拾うと自分の別物を指す"""
        self.assertEqual(
            flow.issue_refs(
                "https://github.com/argoproj/argo-cd/issues/7673", self.REPO
            ),
            set(),
        )

    def test_code_and_quotes_do_not_count(self):
        self.assertEqual(flow.issue_refs("`#1466`", self.REPO), set())
        self.assertEqual(flow.issue_refs("> #1466 と言われた", self.REPO), set())


class UnverifiedReplies(unittest.TestCase):
    """本文コメントは返信が紐づかない。返したことにしている分を数えて在り処を出す"""

    def test_a_call_followed_by_your_post_counts_as_unverified(self):
        p = pr(
            comments=conn(
                comment(user("bob"), T1, "@alice ここどうしますか"),
                comment(user("alice"), T2, "別件ですが CI を直しました"),
            )
        )
        self.assertEqual(
            [x["body"] for x in flow.unverified_replies(p, "alice")],
            ["@alice ここどうしますか"],
        )

    def test_a_call_with_no_reply_is_not_counted(self):
        """それは呼びかけの節が拾う。ここは『返したことになっている』分だけ"""
        p = pr(comments=conn(comment(user("bob"), T1, "@alice ここどうしますか")))
        self.assertEqual(flow.unverified_replies(p, "alice"), [])

    def test_thread_comments_are_not_counted(self):
        """スレッドは返信が紐づくので機械が誰の番か決められる"""
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T1, "@alice ここどうしますか"),
                    comment(user("alice"), T2, "直しました"),
                )
            )
        )
        self.assertEqual(flow.unverified_replies(p, "alice"), [])


class TurnThreads(unittest.TestCase):
    def test_turn_follows_the_last_speaker(self):
        answered = thread(
            comment(user("bob"), T1, "ここが壊れています"),
            comment(user("alice"), T2, "d151bbee で直しました"),
            path="a.py",
            line=3,
        )
        unanswered_t = thread(comment(user("bob"), T2, "これはどうなりますか"))
        own = thread(comment(user("alice"), T1, "自分メモ"))
        done = thread(
            comment(user("bob"), T1), comment(user("alice"), T2), resolved=True
        )
        p = pr(reviewThreads=conn(answered, unanswered_t, own, done))
        # 相手が答えたスレッドは立てた人が再確認する番、答えていないスレッドは作者の番
        self.assertEqual(
            [(t["path"], c["body"]) for t, c in flow.turn_threads(p, "bob")],
            [("a.py", "d151bbee で直しました")],
        )
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")],
            ["これはどうなりますか"],
        )

    def test_bot_only_thread_belongs_to_nobody(self):
        p = pr(reviewThreads=conn(thread(comment(bot(), T1, "[block] fail-open です"))))
        self.assertEqual(flow.turn_threads(p, "alice"), [])
        self.assertEqual(flow.turn_threads(p, "bob"), [])

    def test_a_second_reviewer_adds_a_turn_instead_of_taking_one(self):
        """レビュアーが 2 人入ると番は 2 人に載る。1 人に潰すと、潰した側の指摘が黙って落ちる"""
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T0, "ここが壊れています"),
                    comment(user("alice"), T1, "d151bbee で直しました"),
                    comment(user("carol"), T2, "別ケースだと戻りませんか"),
                )
            )
        )
        # bob は作者の修正を再確認する番。carol の発言では消えない
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "bob")],
            ["d151bbee で直しました"],
        )
        # 作者は carol に答える番。渡る材料は bob の指摘ではなく carol の発言
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")],
            ["別ケースだと戻りませんか"],
        )
        self.assertEqual(flow.turn_threads(p, "carol"), [])
        self.assertEqual(flow.answered_threads(p), ([("bob", T1, False)], [("alice", T2, False)]))
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("bob", "再確認 1 件", T1),
                ("alice", "スレッド返答 1 件", T2),
                ("carol", "返答待ち 1 件", T2),
            ],
        )
        # 再確認する番の bob は今日動ける。答えを待っている carol は作者待ち
        self.assertFalse(flow.waiting_on_others(p, "bob", ["再確認 1 件"]))
        self.assertTrue(flow.waiting_on_others(p, "carol", ["返答待ち 1 件"]))

    def test_a_third_party_does_not_take_over_the_original_turn(self):
        """相槌でも番は増えるだけ。立てた人の再確認が消えて材料が相槌に化けてはいけない"""
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T0, "ここが壊れています"),
                    comment(user("alice"), T1, "d151bbee で直しました"),
                    comment(user("carol"), T2, "同意です"),
                )
            )
        )
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "bob")],
            ["d151bbee で直しました"],
        )
        self.assertEqual(
            flow.pr_facts(p, "bob")[1],
            "未解決 1 スレッド（bob が再確認 1・alice が返答 1）",
        )

    def test_three_reviewers_each_keep_their_own_turn(self):
        """作者が答えていないスレッドでは、後から入った人だけでなく全員が待ちに載る"""
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T0, "ここが壊れています"),
                    comment(user("carol"), T1, "こちらも見てください"),
                    comment(user("dave"), T2, "同じ型が別の行にもあります"),
                )
            )
        )
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")],
            ["同じ型が別の行にもあります"],
        )
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("alice", "スレッド返答 1 件", T2),
                ("bob", "返答待ち 1 件", T2),
                ("carol", "返答待ち 1 件", T2),
                ("dave", "返答待ち 1 件", T2),
            ],
        )
        for who in ("bob", "carol", "dave"):
            self.assertTrue(flow.waiting_on_others(p, who, ["返答待ち 1 件"]), who)

    # ---- 作者以外の人だけが assignee の PR: 答える側は作者と受けた人

    def test_the_assignees_reply_answers_a_third_partys_thread(self):
        by_bob = thread(comment(user("carol"), T0, "ここが変"), comment(user("bob"), T1, "直しました"))
        by_alice = thread(comment(user("carol"), T0, "これは？"), comment(user("alice"), T1, "意図どおり"))
        p = pr(assignees=conn(user("bob")), reviewThreads=conn(by_bob, by_alice))
        self.assertEqual(flow.conversation_balls(p), [("carol", "再確認 2 件", T1)])

    def test_a_third_partys_open_question_is_the_assignees_turn(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("dave"), T1, "これは？"))),
        )
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("bob", "スレッド返答 1 件", T1),
                ("carol", "スレッド返答 1 件", T1),
                ("dave", "返答待ち 1 件", T1),
            ],
        )
        self.assertIn(
            "未解決 1 スレッド（bob が返答 1・carol が返答 1）", flow.pr_facts(p)
        )

    def test_each_owner_counts_only_their_own_moved_threads(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(
                thread(comment(user("dave"), T1, "これは？"), outdated=True),
                thread(comment(user("dave"), T1, "こちらは？")),
            ),
        )
        self.assertIn(
            "未解決 2 スレッド（bob が返答 2（1 は差分が動いた）・carol が返答 2（1 は差分が動いた））", flow.pr_facts(p)
        )

    def test_the_author_and_the_assignee_ask_each_other(self):
        """渡した作者は受けた人の実装をスレッドでレビューする（作者はレビュー依頼も承認も受けられない）"""
        alice_asks = thread(comment(user("alice"), T1, "ここは別の関数に？"))
        bob_asks = thread(comment(user("bob"), T1, "この仕様で合っていますか"))
        p = pr(assignees=conn(user("bob")), reviewThreads=conn(alice_asks, bob_asks))
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("alice", "スレッド返答 1 件", T1),
                ("bob", "スレッド返答 1 件", T1),
                ("alice", "返答待ち 1 件", T1),
            ],
        )
        answered = pr(
            assignees=conn(user("bob")),
            reviewThreads=conn(
                thread(comment(user("alice"), T1, "ここは別の関数に？"), comment(user("bob"), T2, "分けました")),
                thread(comment(user("bob"), T1, "この仕様で合っていますか"), comment(user("alice"), T2, "合っています")),
            ),
        )
        self.assertEqual(
            flow.conversation_balls(answered),
            [("alice", "再確認 1 件", T2), ("bob", "再確認 1 件", T2)],
        )

    def test_a_third_party_joining_the_authors_question_also_waits_on_the_assignee(self):
        p = pr(
            assignees=conn(user("bob")),
            reviewThreads=conn(
                thread(comment(user("alice"), T0, "ここは？"), comment(user("dave"), T1, "同じ疑問です"))
            ),
        )
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("bob", "スレッド返答 1 件", T1),
                ("alice", "返答待ち 1 件", T1),
                ("dave", "返答待ち 1 件", T1),
            ],
        )

    def test_a_deleted_or_bot_author_cannot_be_asked(self):
        for author, named in ((None, "退会済み"), (bot("dependabot"), "dependabot"), (mannequin("old-alice"), "old-alice")):
            with self.subTest(author=author):
                p = pr(
                    author=author,
                    isDraft=True,
                    assignees=conn(user("bob")),
                    reviewThreads=conn(
                        thread(comment(user("bob"), T1, "この仕様で合っていますか")),
                        thread(comment(user("bob"), T1, "ここも？"), comment(user("carol"), T2, "同じ疑問です")),
                    ),
                )
                self.assertEqual(flow.pr_balls(p), [("bob", "draft", T0)])
                facts = flow.pr_facts(p, "bob")
                self.assertIn(f"担当として受けた PR（起票は {named}）", facts)
                self.assertIn(
                    "未解決 2 スレッド（人は bob だけ 1・人は bob, carol だけ 1）", facts
                )
                self.assertEqual(flow.pr_tiers(p)["bob"][0], 2)
                third = pr(
                    author=author,
                    assignees=conn(user("bob")),
                    reviewThreads=conn(thread(comment(user("carol"), T1, "これは？"))),
                )
                self.assertEqual(
                    flow.conversation_balls(third),
                    [("bob", "スレッド返答 1 件", T1), ("carol", "返答待ち 1 件", T1)],
                )

    def test_two_assignees_ask_each_other_too(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(
                thread(comment(user("bob"), T1, "ここは任せます"), comment(user("carol"), T2, "引き取りました"))
            ),
        )
        self.assertEqual(flow.conversation_balls(p), [("bob", "再確認 1 件", T2)])

    def test_the_authors_own_note_is_skipped_only_while_the_author_holds_it(self):
        note = thread(comment(user("alice"), T1, "自分メモ"))
        self.assertEqual(flow.conversation_balls(pr(reviewThreads=conn(note))), [])
        self.assertIn(
            "未解決 1 スレッド（人は alice だけ 1）", flow.pr_facts(pr(reviewThreads=conn(note)))
        )
        handed = pr(assignees=conn(user("bob")), reviewThreads=conn(note))
        self.assertIn(("bob", "スレッド返答 1 件", T1), flow.conversation_balls(handed))
        self.assertIn("未解決 1 スレッド（bob が返答 1）", flow.pr_facts(handed))


def issue(
    body="",
    author=user("alice"),
    comments=(),
    assignees=(),
    timeline=(),
    number=1,
    created=T0,
    updated=T0,
):
    return {
        "id": "I1",
        "number": number,
        "title": "t",
        "url": f"https://example.invalid/issues/{number}",
        "createdAt": created,
        "updatedAt": updated,
        "body": body,
        "author": author,
        "assignees": conn(*({"login": a} for a in assignees)),
        "comments": conn(*(comment(a, at, b) for a, at, b in comments)),
        "timelineItems": history(*timeline),
    }


class Mentions(unittest.TestCase):
    def test_regex_boundaries(self):
        self.assertEqual(
            flow.mentions("@alice、@bob. と @190578_daifuku:"),
            {"alice", "bob", "190578_daifuku"},
        )
        self.assertEqual(flow.mentions("mail a@b.com @@x @-y"), set())
        self.assertEqual(flow.mentions("@IL-SW-AI/team に依頼"), set())
        self.assertEqual(flow.mentions("担当は@alice"), {"alice"})

    def test_code_quotes_are_ignored_and_links_are_flattened(self):
        text = "```\n@fence\n```\n`@inline` と\n> @quoted\n@real"
        self.assertEqual(flow.mentions(text), {"real"})
        self.assertEqual(
            flow.mentions("[清村 (@alice)](https://github.com/alice) 様"), {"alice"}
        )
        self.assertEqual(
            flow.excerpt(
                "[清村 (@alice)](https://github.com/alice) 様 確認ください", "alice"
            ),
            "@alice) 様 確認ください",
        )

    def test_unanswered_until_mentioned_person_comments(self):
        posts = flow.posts_of_issue(issue(comments=[(user("alice"), T1, "@bob 見て")]))
        self.assertEqual(flow.unanswered(posts)["bob"]["since"], T1)
        posts = flow.posts_of_issue(
            issue(
                comments=[(user("alice"), T1, "@bob 見て"), (user("bob"), T2, "見た")]
            )
        )
        self.assertEqual(flow.unanswered(posts), {})

    def test_mention_after_reply_reopens(self):
        posts = flow.posts_of_issue(
            issue(
                comments=[
                    (user("alice"), T1, "@bob"),
                    (user("bob"), T2, "ok"),
                    (user("alice"), T3, "@bob もう一度"),
                ]
            )
        )
        self.assertEqual(flow.unanswered(posts)["bob"]["since"], T3)

    def test_body_mention_counts_and_self_mention_does_not(self):
        posts = flow.posts_of_issue(issue(body="@bob @alice", author=user("alice")))
        self.assertEqual(list(flow.unanswered(posts)), ["bob"])

    def test_bot_mention_is_ignored(self):
        posts = flow.posts_of_issue(
            issue(comments=[(bot("github-actions"), T1, "@bob 期限です")])
        )
        self.assertEqual(flow.unanswered(posts), {})

    def test_deleted_commenter_does_not_crash(self):
        posts = flow.posts_of_issue(issue(comments=[(None, T1, "@bob")]))
        self.assertEqual(flow.unanswered(posts)["bob"]["by"], None)

    def test_materials_excerpt_and_reply_to_own(self):
        posts = flow.posts_of_issue(
            issue(
                comments=[
                    (user("bob"), T1, "質問です"),
                    (user("alice"), T2, "@bob 回答です。ありがとう"),
                ]
            )
        )
        info = flow.unanswered(posts)["bob"]
        self.assertEqual(info["excerpt"], "@bob 回答です。ありがとう")
        self.assertEqual(info["text"], "@bob 回答です。ありがとう")
        self.assertTrue(info["reply_to_own"])
        self.assertFalse(info["reacted"])
        self.assertEqual(info["post_id"], f"C{T2}alice")

    def test_pr_posts_include_reviews_and_threads_in_time_order(self):
        p = pr(
            comments=conn(comment(user("bob"), T3, "@alice c")),
            reviews=conn(review(user("carol"), "COMMENTED", T1, body="@alice r")),
            reviewThreads=conn(thread(comment(user("dave"), T2, "@alice t"))),
        )
        posts = flow.posts_of_pr(p)
        self.assertEqual([x["at"] for x in posts], [T1, T2, T3])
        self.assertEqual(flow.unanswered(posts)["alice"]["since"], T1)

    def test_open_prs_referencing_dedups_and_skips_closed(self):
        tl = [
            {
                "__typename": "CrossReferencedEvent",
                "source": {"__typename": "PullRequest", "number": 9, "state": "OPEN"},
            },
            {
                "__typename": "CrossReferencedEvent",
                "source": {"__typename": "PullRequest", "number": 9, "state": "OPEN"},
            },
            {
                "__typename": "CrossReferencedEvent",
                "source": {"__typename": "PullRequest", "number": 8, "state": "MERGED"},
            },
            {
                "__typename": "CrossReferencedEvent",
                "source": {"__typename": "Issue", "number": 7},
            },
        ]
        self.assertEqual(flow.open_prs_referencing(issue(timeline=tl)), [9])

    def test_open_prs_by_branch_or_title_token(self):
        prs = [
            pr(number=20, headRefName="feature/1-tacit", title="x"),
            pr(number=21, headRefName="fix/11-other", title="Feature/1 design"),
            pr(number=22, headRefName="fix/11-other", title="no match 10"),
        ]
        self.assertEqual(flow.open_prs_referencing(issue(), prs), [20, 21])

    def test_assigned_at_uses_latest_event_for_that_person(self):
        i = issue(
            timeline=[assigned("bob", T1), assigned("bob", T2), assigned("alice", T3)]
        )
        self.assertEqual(flow.assigned_at(i, "bob"), T2)
        self.assertIsNone(flow.assigned_at(i, "carol"))

    def test_fill_reactions_marks_reacted_and_limits(self):
        waits = [
            ("bob", {"post_id": "C1", "reacted": False}, None),
            ("carol", {"post_id": "C2", "reacted": False}, None),
        ]
        payload = {
            "data": {
                "nodes": [
                    {
                        "id": "C1",
                        "reactions": {
                            "totalCount": 1,
                            "nodes": [{"user": {"login": "bob"}}],
                        },
                    },
                    {
                        "id": "C2",
                        "reactions": {
                            "totalCount": 60,
                            "nodes": [{"user": {"login": "x"}}] * 50,
                        },
                    },
                ]
            }
        }
        original = flow.gh
        flow.gh = lambda *_args: json.dumps(payload)
        try:
            limits = flow.fill_reactions(waits)
        finally:
            flow.gh = original
        self.assertTrue(waits[0][1]["reacted"])
        self.assertFalse(waits[1][1]["reacted"])
        self.assertEqual(limits, ["C2: リアクション 60 件のうち 50 件しか見ていない"])


def gh_runs(calls, *responses):
    """subprocess.run の偽。(終了コード, 本文[, stderr]) を順に返す。本文は文字列ならそのまま、ほかは JSON"""
    results = iter(responses)

    def run(argv, **_kw):
        calls.append(argv)
        code, body, *err = next(results)
        out = body if isinstance(body, str) else json.dumps(body)
        return subprocess.CompletedProcess(argv, code, out, err[0] if err else ("gh: error" if code else ""))

    return run


def missing(field):
    return {"errors": [{
        "message": f"Field '{field}' doesn't exist on type 'PullRequest'",
        "extensions": {"code": "undefinedField", "typeName": "PullRequest", "fieldName": field},
    }]}


def page(*nodes):
    return {"data": {"repository": {"pullRequests": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(nodes)}}}}


class Fetch(unittest.TestCase):
    def fetch(self, *responses):
        calls = []
        with (
            mock.patch.object(flow.shutil, "which", return_value="gh"),
            mock.patch.object(flow.subprocess, "run", gh_runs(calls, *responses)),
        ):
            got = flow.fetch_prs("o", "n")
        return got, [next(a for a in argv if a.startswith("query=")) for argv in calls]

    def test_the_query_reads_the_kind_of_assignee_and_author(self):
        q = " ".join(flow.PR_QUERY.split())
        self.assertIn(
            "assignees: assignedActors(first: 10) { totalCount nodes { __typename ... on Actor { login } } }", q
        )
        self.assertIn("author { login __typename }", q)

    def test_a_github_without_assigned_actors_is_read_again_without_kinds(self):
        got, queries = self.fetch((1, missing("assignedActors")), (0, page({"number": 1})))
        self.assertEqual(got, [{"number": 1, "assigneeKindsUnknown": True}])
        self.assertEqual(queries, ["query=" + flow.PR_QUERY, "query=" + flow.LEGACY_PR_QUERY])
        self.assertEqual(self.fetch((0, page({"number": 1})))[0], [{"number": 1}])
        # UserConnection の __typename はいつも User で、取ると Bot も人に数える
        self.assertIn("assignees(first: 10) { totalCount nodes { login } }", " ".join(flow.LEGACY_PR_QUERY.split()))

    def test_a_504_is_retried_with_or_without_an_errors_body(self):
        for body in ("", {"errors": [{"message": "Something went wrong"}]}):
            with self.subTest(body=body):
                calls = []
                timeout = (1, body, "gh: HTTP 504: Gateway Timeout")
                with (
                    mock.patch.object(flow.shutil, "which", return_value="gh"),
                    mock.patch.object(flow.subprocess, "run", gh_runs(calls, timeout, (0, {}))),
                ):
                    self.assertEqual(flow.gh("api", "graphql"), "{}")
                self.assertEqual(len(calls), 2)

    def test_a_second_504_stops(self):
        calls = []
        timeout = (1, "", "gh: HTTP 504: Gateway Timeout")
        with (
            mock.patch.object(flow.shutil, "which", return_value="gh"),
            mock.patch.object(flow.subprocess, "run", gh_runs(calls, timeout, timeout)),
            self.assertRaises(SystemExit),
        ):
            flow.gh("api", "graphql")
        self.assertEqual(len(calls), 2)

    def test_other_graphql_errors_still_stop(self):
        for body in (missing("isDraft"), {"errors": [{"message": "Resource limits exceeded"}]}):
            with self.subTest(body=body), self.assertRaises(SystemExit):
                self.fetch((1, body))


class Truncation(unittest.TestCase):
    def test_reports_when_total_exceeds_fetched(self):
        c = conn(*([None] * 100), total=130)
        self.assertEqual(
            flow.truncated(c, "コメント", "#9"),
            "#9: コメント 130 件のうち 100 件しか見ていない",
        )
        self.assertIsNone(flow.truncated(conn(*([None] * 100)), "コメント", "#9"))

    def test_pr_limits_cover_reviews_and_thread_comments(self):
        p = pr(
            reviews=conn(total=70),
            timelineItems=history(earlier=True),
            reviewThreads=conn(
                {
                    "isResolved": False,
                    "comments": conn(comment(user("bob"), T1), total=40),
                }
            ),
        )
        self.assertEqual(
            [w for w in flow.limits_of_pr(p) if w],
            [
                "#1: レビュー 70 件のうち 0 件しか見ていない",
                "#1: スレッド内コメント 40 件のうち 1 件しか見ていない",
                "#1: 履歴（assign・レビュー依頼・draft の出し入れ）は新しい 100 件しか見ていない",
            ],
        )

    def test_pr_limits_cover_each_reviewers_latest_opinion(self):
        """切れていると指摘対応を集約値どおり残す（turn.owes_change_requests）ので、そのことを見ていないものに出す"""
        p = pr(latestOpinionatedReviews=conn({"state": "CHANGES_REQUESTED", "author": user("bob")}, total=31))
        self.assertIn("#1: 人ごとの意見 31 件のうち 1 件しか見ていない", flow.limits_of_pr(p))

    def test_issue_limits_cover_the_history_window(self):
        cut = issue(number=3)
        cut["timelineItems"] = history(earlier=True)
        self.assertEqual(
            [w for w in flow.limits_of_issue(cut) if w],
            ["#3: 履歴（assign・参照した PR）は新しい 100 件しか見ていない"],
        )
        self.assertEqual([w for w in flow.limits_of_issue(issue(number=3)) if w], [])


class LocalTime(unittest.TestCase):
    """時刻は全部ローカルで出す。見出しだけローカルで行が UTC だと同じ報告の中で 9 時間ずれる"""

    def test_rows_follow_local_tz(self):
        jst = dt.timezone(dt.timedelta(hours=9))
        with mock.patch.object(flow, "LOCAL_TZ", jst):
            self.assertEqual(flow.local_time("2026-08-01T23:30:00Z"), "08-02 08:30")
            self.assertEqual(
                flow.local_time("2026-08-01T23:30:00Z", "%Y-%m-%d"), "2026-08-02"
            )
            p = pr(reviews=conn(review(user("bob"), "APPROVED", "2026-08-01T23:30:00Z")))
            self.assertEqual(
                flow.review_state_fact(p, "bob"),
                ["bob のレビュー: APPROVED（08-02 08:30）"],
            )


class Display(unittest.TestCase):
    def test_cut_by_display_width(self):
        self.assertEqual(flow.cut("日本語abc", 7), "日本語a…")
        self.assertEqual(flow.cut("short", 10), "short")


def report(*prs, issues=(), who="bob", args=(), legacy=False):
    """固定の材料で main を回し、報告の全文を返す。GitHub には触らない。
    legacy は assignedActors の無い GitHub（欄が無いと返す）"""

    def fetch_all(query, _owner, _name, field, optional=()):
        if legacy and "assignedActors" in query:
            assert "assignedActors" in optional
            raise flow.MissingField()
        return list(prs) if field == "pullRequests" else list(issues)

    def gh(*_args):  # 呼びかけがあるとき fill_reactions が引くリアクション。空で返す
        return json.dumps({"data": {"nodes": []}})

    buf = io.StringIO()
    with (
        mock.patch.object(flow, "fetch_all", fetch_all),
        mock.patch.object(flow, "gh", gh),
        contextlib.redirect_stdout(buf),
    ):
        flow.main([who, "--repo", "o/n", *args])
    return buf.getvalue()


class Buckets(unittest.TestCase):
    """報告は段を出さず「自分の番 / 相手の番」の 2 節に分ける。段は並びの鍵としてだけ残る。"""

    def render(self, *prs, who="bob", args=()):
        return report(*prs, who=who, args=args)

    def bucket(self, out, n=1):
        head, _, tail = out.partition("## 相手の番")
        if re.search(rf"^  #{n}\b", head, re.M):
            return "自分の番"
        if re.search(rf"^  #{n}\b", tail, re.M):
            return "相手の番"
        return "無し"

    def test_both_sides_owing_threads_stay_in_my_ball(self):
        p = pr(
            reviewThreads=conn(
                thread(comment(user("bob"), T1), comment(user("alice"), T2)),
                thread(comment(user("bob"), T2)),
            )
        )
        # 相手にも返す番があっても、自分の分は今日できる。待ちには落とさない
        for who in ("bob", "alice"):
            self.assertEqual(self.bucket(self.render(p, who=who)), "自分の番", who)

    def test_one_sided_thread_turn_is_my_ball(self):
        p = pr(reviewThreads=conn(thread(comment(user("bob"), T2))))
        self.assertEqual(self.bucket(self.render(p, who="alice")), "自分の番")
        # 指摘した側は返事を待っている
        self.assertEqual(self.bucket(self.render(p, who="bob")), "相手の番")

    def test_assignee_counts_as_handing_the_pr_over(self):
        """レビュー依頼を押さずに assignee で渡す運用がある。作者以外の人だけが assignee なら、
        作者の一覧からは外れ、受けた人のまだ誰にも渡していない番になる"""
        handed = pr(
            number=1,
            assignees=conn(user("bob")),
            comments=conn(comment(user("alice"), T3, "扱いはお任せします")),
        )
        self.assertEqual(self.bucket(self.render(handed, who="alice")), "無し")
        self.assertEqual(self.bucket(self.render(handed, who="bob")), "自分の番")

    def test_a_pr_given_only_to_bots_or_deleted_accounts_stays_with_the_author(self):
        for nobody in (bot("Copilot"), None, mannequin("old-bob")):
            with self.subTest(assignee=nobody):
                p = pr(
                    number=1,
                    assignees=conn(nobody),
                    comments=conn(comment(user("alice"), T3, "Copilot に頼みました")),
                )
                self.assertEqual(self.bucket(self.render(p, who="alice")), "自分の番")
        mixed = pr(number=1, assignees=conn(user("bob"), bot("Copilot")))
        self.assertEqual(self.bucket(self.render(mixed, who="alice")), "無し")
        self.assertEqual(self.bucket(self.render(mixed, who="bob")), "自分の番")
        self.assertNotIn("  Copilot — ", self.render(mixed, args=("--all",)))

    def test_a_github_without_assigned_actors_keeps_the_pr_with_the_author(self):
        def legacy(*assignees):
            return pr(number=1, assignees=conn(*assignees), commits=rollup(checks("FAILURE")))

        self.assertNotIn("assignedActors", self.render(legacy(user("bob"))))
        for assignees in (({"login": "bob"},), (user("bob"),), ({"login": "Copilot"},)):
            with self.subTest(assignees=assignees):
                other = assignees[0]["login"]
                out = report(legacy(*assignees), who="alice", legacy=True)
                self.assertIn(flow.KINDS_NOT_SEEN, out)
                self.assertEqual(self.bucket(out), "自分の番")
                self.assertNotIn("担当に渡した PR", out)
                p = legacy(*assignees)
                p["assigneeKindsUnknown"] = True
                self.assertEqual(flow.owners(p), ["alice"])
                self.assertEqual(flow.merge_rows(flow.pr_balls(p)), {"alice": (["CI 赤"], T2), other: (["担当"], T0)})
                self.assertIn("作者: alice", flow.pr_facts(p, other))
                # 渡した未依頼は、誰も発言していなくても作者の相手の番（/catchup の「担当 X 待ち」と同じ読み）
                unasked = pr(number=1, assignees=conn(*assignees), assigneeKindsUnknown=True)
                self.assertEqual(tiers(unasked), {"alice": 3, other: 0})

    def test_a_handed_unrequested_pr_on_a_github_without_kinds_stays_mine_while_i_owe_a_thread(self):
        p = pr(
            assignees=conn({"login": "bob"}),
            assigneeKindsUnknown=True,
            reviewThreads=conn(thread(comment(user("carol"), T1, "これは？"))),
        )
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["alice"][0], ["未依頼", "スレッド返答 1 件"])
        self.assertEqual(tiers(p)["alice"], 0)

    def test_received_draft_and_never_asked_stay_mine_whoever_spoke_last(self):
        """受けた人が「了解、積みます」と返した直後でも、受けた人の自分の番から落とさない——
        落とすと誰の一覧にも出ない"""
        for draft in (True, False):
            with self.subTest(draft=draft):
                p = pr(
                    number=1,
                    isDraft=draft,
                    assignees=conn(user("bob")),
                    comments=conn(
                        comment(user("alice"), T2, "実装して Ready for review にしてください"),
                        comment(user("bob"), T3, "了解、積みます"),
                    ),
                )
                self.assertEqual(self.bucket(self.render(p, who="alice")), "無し")
                self.assertEqual(self.bucket(self.render(p, who="bob")), "自分の番")
                self.assertEqual(flow.pr_tiers(p)["bob"][0], 2)

    def test_received_draft_and_never_asked_stay_mine_while_asking_the_author(self):
        for draft in (True, False):
            for last in ("alice", "bob"):
                with self.subTest(draft=draft, last=last):
                    p = pr(
                        number=1,
                        isDraft=draft,
                        assignees=conn(user("bob")),
                        reviewThreads=conn(thread(comment(user("bob"), T1, "この仕様で合っていますか"))),
                        comments=conn(comment(user(last), T3, "進めます")),
                    )
                    self.assertEqual(self.bucket(self.render(p, who="bob")), "自分の番")
                    self.assertEqual(self.bucket(self.render(p, who="alice")), "自分の番")
                    self.assertEqual(flow.pr_tiers(p)["bob"][0], 2)

    def test_the_holders_own_question_does_not_sink_the_merge(self):
        p = pr(
            number=1,
            reviewDecision="APPROVED",
            assignees=conn(user("bob")),
            reviews=conn(review(user("carol"), "APPROVED", T1)),
            reviewThreads=conn(thread(comment(user("bob"), T2, "マージ前に、この仕様で合っていますか"))),
        )
        self.assertEqual(self.bucket(self.render(p, who="bob")), "自分の番")
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"][0], ["マージ"])
        self.assertEqual(flow.pr_tiers(p)["bob"][0], 0)
        # 問いの後に本人が最後に発言したなら、作者が持つ PR と同じく相手の番
        p["comments"] = conn(comment(user("bob"), T3, "返事を待ってからマージします"))
        self.assertEqual(self.bucket(self.render(p, who="bob")), "相手の番")

    def test_the_holders_own_question_does_not_pull_the_days_back(self):
        p = pr(
            reviewDecision="APPROVED",
            assignees=conn(user("bob")),
            reviews=conn(review(user("carol"), "APPROVED", T3)),
            reviewThreads=conn(thread(comment(user("bob"), T0, "この仕様で合っていますか"))),
        )
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"], (["マージ"], T3))
        self.assertEqual(flow.pr_tiers(p)["bob"], (0, T3))
        # 持ち主でない人には返答待ちが立ち、段と日数を決める
        asked = pr(reviewThreads=conn(thread(comment(user("carol"), T0, "これは？"))))
        asked["pendingReview"] = {"by": "carol", "comments": 1, "since": T2}
        self.assertEqual(flow.pr_tiers(asked)["carol"], (3, T0))

    def test_a_reply_in_the_holders_question_thread_counts_like_one_in_the_body(self):
        for replier in ("alice", "dave"):
            reply = comment(user(replier), T2, "合っています")
            body = [comment(user("bob"), T0, "マージします")]
            question = [comment(user("bob"), T1, "この仕様で合っていますか"), comment(user("bob"), T3, "例外も？")]
            for where, comments, threaded in (
                ("スレッド", body, [question[0], reply, question[1]]),
                ("本文", body + [reply], question),
            ):
                with self.subTest(replier=replier, where=where):
                    p = pr(
                        reviewDecision="APPROVED",
                        assignees=conn(user("bob")),
                        reviews=conn(review(user("carol"), "APPROVED", T0)),
                        comments=conn(*comments),
                        reviewThreads=conn(thread(*threaded)),
                    )
                    self.assertEqual(tiers(p)["bob"], 0)

    def test_a_co_holders_reply_in_the_question_thread_does_not_sink_the_merge(self):
        p = pr(
            reviewDecision="APPROVED",
            assignees=conn(user("bob"), user("carol")),
            reviews=conn(review(user("dave"), "APPROVED", T0)),
            comments=conn(comment(user("bob"), T0, "マージします")),
            reviewThreads=conn(thread(
                comment(user("bob"), T1, "この仕様で合っていますか"),
                comment(user("carol"), T2, "合っています"),
                comment(user("bob"), T3, "例外も？"),
            )),
        )
        self.assertEqual(tiers(p)["bob"], 1)

    def test_two_assignees_both_keep_a_received_draft_and_see_who_else_can_move_it(self):
        p = pr(
            number=1,
            isDraft=True,
            assignees=conn(user("bob"), user("carol")),
            commits=rollup(checks("FAILURE")),
            reviewThreads=conn(thread(comment(user("dave"), T1, "これは？"))),
            comments=conn(comment(user("carol"), T3, "見ます")),
        )
        for who in ("bob", "carol"):
            self.assertEqual(self.bucket(self.render(p, who=who)), "自分の番", who)
        self.assertEqual(self.bucket(self.render(p, who="dave")), "相手の番")
        self.assertEqual(self.bucket(self.render(p, who="alice")), "無し")
        self.assertEqual(tiers(p), {"bob": 1, "carol": 1, "dave": 3})
        # draft だけなら持ち主が 2 人でも誰も待っていない段 2
        bare = pr(isDraft=True, assignees=conn(user("bob"), user("carol")))
        self.assertEqual(tiers(bare), {"bob": 2, "carol": 2})
        everyone = self.render(p, args=("--all",))
        self.assertIn("  bob — 1 件", everyone)
        self.assertIn("  carol — 1 件", everyone)

    def test_draft_stays_undelivered_when_the_author_is_also_assigned(self):
        """draft は作者が自分で「まだ出さない」と印を付けた状態"""
        out = self.render(
            pr(
                number=1,
                isDraft=True,
                assignees=conn(user("alice"), user("bob")),
            ),
            who="alice",
        )
        self.assertEqual(self.bucket(out), "自分の番")

    def test_never_asked_with_the_author_also_assigned_stays_undelivered(self):
        """作者も assignee に残っていれば作者が持っていて、まだ誰にも渡していない（/catchup も依頼先を決めるのは私）"""
        for legacy in (False, True):
            for last in (None, "alice", "bob"):
                with self.subTest(legacy=legacy, last=last):
                    p = pr(
                        number=1,
                        assignees=conn(user("alice"), user("bob")),
                        comments=conn(comment(user(last), T3, "扱いはお任せします")) if last else conn(),
                    )
                    if legacy:
                        p["assigneeKindsUnknown"] = True
                    self.assertEqual(flow.pr_tiers(p)["alice"][0], 2)
                    self.assertEqual(self.bucket(report(p, who="alice", legacy=legacy)), "自分の番")

    def test_received_pr_reads_as_the_implementers_own(self):
        """受けた人の行に `作者:` を出すと、読む側が役割をレビュアーと書く。本文と規模は付ける——
        受けた人はその本文を書いていない"""
        p = pr(
            number=1,
            body="入口の検査を足します。続き。",
            additions=3, deletions=1, changedFiles=2,
            assignees=conn(user("bob")),
        )
        out = self.render(p, who="bob")
        self.assertEqual(self.bucket(out), "自分の番")
        self.assertIn("担当として受けた PR（起票は alice）", out)
        self.assertNotIn("作者: alice", out)
        self.assertIn("本文: 入口の検査を足します。", out)
        self.assertIn("規模: 2 ファイル +3/-1", out)

    def test_undelivered_pr_outranks_waiting_on_the_other_side(self):
        """未依頼はあなたしか動かせない。相手待ちと同じ段に混ぜると本当のボールが沈む"""
        undelivered = pr(number=1)
        waiting = pr(
            number=2,
            reviews=conn(review(user("bob"), "COMMENTED", T1, "見た")),
            comments=conn(comment(user("alice"), T3, "全部返しました")),
        )
        out = self.render(undelivered, waiting, who="alice")
        self.assertEqual(self.bucket(out, 1), "自分の番")
        self.assertEqual(self.bucket(out, 2), "相手の番")

    def test_review_request_outranks_follow_up_the_author_is_blocking(self):
        """自分が作者でない PR で main 未追従なら、再確認だけの行は先頭に来ない"""
        to_review = pr(number=1, reviewRequests=requests(user("bob")))
        behind = pr(
            number=2,
            mergeStateStatus="BEHIND",
            reviewThreads=conn(
                thread(comment(user("bob"), T1), comment(user("alice"), T2))
            ),
        )
        out = self.render(to_review, behind, who="bob")
        self.assertEqual(self.bucket(out, 1), "自分の番")
        self.assertEqual(self.bucket(out, 2), "相手の番")

    def test_only_you_can_move_it_sorts_first_inside_my_ball(self):
        """段は印字しないが並びには残る。渡していない PR より、人を待たせている行が先"""
        undelivered = pr(number=1)
        to_review = pr(number=2, reviewRequests=requests(user("alice")))
        out = self.render(undelivered, to_review, who="alice")
        self.assertEqual(self.bucket(out, 1), "自分の番")
        self.assertEqual(self.bucket(out, 2), "自分の番")
        self.assertLess(out.index("  #2 "), out.index("  #1 "))

    def test_materials_carry_the_last_word_of_threads_you_must_re_check(self):
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T1, "ここが壊れています"),
                    comment(user("alice"), T2, "`d151bbee` で直しました"),
                    path="a.py",
                    line=7,
                    outdated=True,
                ),
                thread(comment(user("bob"), T2, "まだ答えていない指摘")),
            )
        )
        out = self.render(p, who="bob", args=("--materials",))
        head, materials = out.split(flow.MATERIALS_MARK)
        self.assertIn(
            "### PR #1 スレッド → bob  a.py:7  alice 2026-08-03・差分が動いた",
            materials,
        )
        self.assertIn("で直しました", materials)
        # 相手の番のスレッドは相手の材料。数は上に出ているので本文は重ねない
        self.assertNotIn("まだ答えていない指摘", materials)
        self.assertNotIn("で直しました", head)

    def test_intro_and_size_only_for_others_pr_in_my_ball(self):
        """人の PR が自分の番なら、作者の本文の 1 文と規模を添える。件名だけだと次の問いが
        「内容は？」になる（実測）。自分の PR には付けない（本文は自分が書いた）。"""
        p = pr(
            body="## 概要\n\nPR 段階の検証ゲートを追加します。1 つのジョブで 2 つを見ます。",
            additions=1541, deletions=12, changedFiles=14,
            reviewRequests=requests(user("bob")),
        )
        out = self.render(p, who="bob")
        self.assertEqual(self.bucket(out), "自分の番")
        self.assertIn("本文: PR 段階の検証ゲートを追加します。", out)
        self.assertIn("規模: 14 ファイル +1541/-12", out)
        own = self.render(p, who="alice")
        self.assertNotIn("本文:", own)
        self.assertNotIn("規模:", own)

    def test_intro_not_added_in_others_ball(self):
        """相手の番の行には付けない。読まない件で行が増えるだけ。"""
        p = pr(
            body="本文の 1 文。",
            additions=1, deletions=0, changedFiles=1,
            reviewRequests=requests(user("carol")),
        )
        out = self.render(p, who="bob")
        self.assertNotIn("本文:", out)

    def test_intro_line_skips_headings_and_html(self):
        self.assertEqual(
            flow.intro_line("<!-- template -->\n# 題\n\n**太字**の説明です。続き。"),
            "太字の説明です。",
        )
        self.assertEqual(flow.intro_line(""), "")
        self.assertEqual(flow.intro_line("- 箇条書きだけ"), "- 箇条書きだけ")
        # コードブロックの中身は説明ではない。閉じていないコメントの残骸も拾わない
        self.assertEqual(flow.intro_line("# 概要\n```\nrm -rf /\n```\nこれは説明。続き。"), "これは説明。")
        self.assertEqual(flow.intro_line("```python\nfoo = 1\n```"), "")
        self.assertEqual(flow.intro_line("<!-- template\nsecret line\nreal body"), "")
        # 略語のピリオドで切らない。v1.2 も切らない
        self.assertEqual(flow.intro_line("Fixes the bug, e.g. when foo is empty. Also refactors."),
                         "Fixes the bug, e.g. when foo is empty.")
        self.assertEqual(flow.intro_line("v1.2 を直す。ほか"), "v1.2 を直す。")



class Links(unittest.TestCase):
    """各行の 2 行目は URL。読む側（AI）が番号をリンクにする材料で、番号から組み立てさせない
    ——GHES では host が違い、issue と PR で path も違う（/issues と /pull）。"""

    def render(self, prs=(), issues=(), who="bob", args=()):
        return report(*prs, issues=issues, who=who, args=args).splitlines()

    def line_after(self, lines, head):
        i = next(i for i, line in enumerate(lines) if line.startswith(head))
        return lines[i + 1]

    def test_pr_rows_carry_the_url_right_under_the_number(self):
        mine = pr(number=1, reviewRequests=requests(user("bob")))
        theirs = pr(number=2, reviewThreads=conn(thread(comment(user("bob"), T2))))
        # bob には #1 が自分の番、#2 が相手の番。どちらの節でも番号の次の行が URL
        lines = self.render(prs=[mine, theirs], who="bob")
        self.assertEqual(
            self.line_after(lines, "  #1 "), "    https://example.invalid/pull/1"
        )
        self.assertEqual(
            self.line_after(lines, "  #2 "), "    https://example.invalid/pull/2"
        )

    def test_mention_and_assigned_issue_rows_carry_the_url(self):
        called = issue(number=3, comments=[(user("alice"), T1, "@bob 見て")])
        assigned = issue(number=4, assignees=["bob"])
        lines = self.render(issues=[called, assigned], who="bob")
        self.assertEqual(
            self.line_after(lines, "  #3 "), "    https://example.invalid/issues/3"
        )
        # issue に PR の役割は無い。URL の次はすぐ呼びかけの抜粋
        self.assertTrue(self.line_after(lines, "    https://example.invalid/issues/3").startswith("         alice: 「"))
        self.assertEqual(
            self.line_after(lines, "  #4 "), "    https://example.invalid/issues/4"
        )

    def test_numbers_outside_the_ball_rows_carry_the_url_and_the_role(self):
        """呼びかけと本文コメントの噛み合いの番号は、読む側が自分の番へ移すことがある"""
        called = pr(number=1, comments=conn(comment(user("alice"), T1, "@bob 見て")))
        lines = self.render(prs=[called], who="bob")
        i = lines.index("    https://example.invalid/pull/1")
        self.assertTrue(lines[i - 1].startswith("  #1 "))
        self.assertEqual(lines[i + 1], "    作者: alice")
        replied = pr(
            number=2,
            assignees=conn(user("bob")),
            reviewRequests=requests(user("carol")),
            comments=conn(comment(user("carol"), T1, "@bob ここは？"), comment(user("bob"), T2, "別件です")),
        )
        for args, head in (((), "      #2"), (("--all",), "      #2 → bob")):
            with self.subTest(args=args):
                lines = self.render(prs=[replied], args=args)
                i = lines.index(head)
                self.assertEqual(
                    lines[i + 1 : i + 3],
                    ["        https://example.invalid/pull/2", "        担当として受けた PR（起票は alice）"],
                )

    def test_team_requests_carry_the_number_the_url_and_the_role(self):
        asked = pr(number=7, author=user("carol"), reviewRequests=requests(team("org/team")))
        lines = self.render(prs=[asked], who="bob")
        i = lines.index("      #7 → org/team")
        self.assertEqual(lines[i - 1], "    該当 1 件（依頼先の Team に入っていれば、その人の番）:")
        self.assertEqual(lines[i + 1 : i + 3], ["        https://example.invalid/pull/7", "        作者: carol"])
        everyone = self.render(prs=[asked], args=("--all",))
        self.assertIn("  - Team 宛のレビュー依頼の所属展開（該当 1 件。番号は Team の節）", everyone)
        self.assertNotIn("      #7 → org/team", everyone)
        self.assertEqual(self.line_after(everyone, "  org/team — 1 件")[:7], "    #7 ")
        draft = pr(number=8, author=user("carol"), isDraft=True, reviewRequests=requests(team("org/team")))
        both = self.render(prs=[asked, draft], who="carol", args=("--all",))
        i = both.index("      #8 → org/team")
        self.assertEqual(
            both[i - 1], "    該当 2 件（依頼先の Team に入っていれば、その人の番。ほかの 1 件の番号は Team の節）:"
        )
        self.assertEqual(both[i + 1 : i + 3], ["        https://example.invalid/pull/8", "        作者: carol"])
        self.assertNotIn("      #7 → org/team", both)
        self.assertIn("  - Team 宛のレビュー依頼の所属展開（該当 0 件）", self.render(prs=[pr(number=7)]))

    def test_all_mode_keeps_the_url_under_each_row(self):
        lines = self.render(prs=[pr(number=1, reviewRequests=requests(user("bob")))],
                            args=("--all",))
        self.assertEqual(
            self.line_after(lines, "    #1 "), "      https://example.invalid/pull/1"
        )

if __name__ == "__main__":
    unittest.main(verbosity=1)
