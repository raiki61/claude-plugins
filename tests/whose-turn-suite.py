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
import os
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
        "timelineItems": conn(),
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


def full_history(*events):
    """履歴の接続を last: 100 の窓いっぱいにする（古い方が切れている恐れがある形）。埋め草は判定が見ない種類"""
    pad = [{"__typename": "UnlabeledEvent", "createdAt": T0}] * (flow.TIMELINE_LAST - len(events))
    return conn(*events, *pad)


class PrBalls(unittest.TestCase):
    def test_draft_is_author_since_converted(self):
        p = pr(isDraft=True, timelineItems=conn(event("ConvertToDraftEvent", T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T2)])

    def test_draft_from_the_start_counts_its_requests(self):
        # 最初から draft で依頼を付けた PR は、依頼された人のターン（実測 IL-SW-AI/guided-resolver #2233）。作者は draft のまま
        p = pr(isDraft=True, reviewRequests=requests(user("bob")), timelineItems=conn(requested(user("bob"), T1)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T0), ("bob", "review", T1)])
        self.assertEqual(tiers(p), {"alice": 2, "bob": 0})
        # 依頼の日時が履歴に無くても、draft へ戻した記録が無ければ数える（待ちは作成日から）
        p = pr(isDraft=True, reviewRequests=requests(user("bob")))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T0), ("bob", "review", T0)])

    def test_requests_before_going_back_to_draft_are_not_counted(self):
        # ready → 依頼 → draft へ戻す: 「直すから待って」。GitHub は依頼を消さないが、作者のターン（draft のまま）
        p = pr(isDraft=True, reviewRequests=requests(user("bob")),
               timelineItems=conn(event("ReadyForReviewEvent", T0), requested(user("bob"), T1),
                                  event("ConvertToDraftEvent", T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T2)])
        self.assertEqual(tiers(p), {"alice": 2})
        self.assertIsNone(flow.review_since(p, "bob"))
        # 日時が履歴に無い依頼は、戻す前の物と見分けられないので数えない
        p = pr(isDraft=True, reviewRequests=requests(user("bob")), timelineItems=conn(event("ConvertToDraftEvent", T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T2)])

    def test_requests_after_going_back_to_draft_are_counted(self):
        # ready → draft へ戻す → 依頼: 戻した後に頼んだのは「今見てほしい」
        p = pr(isDraft=True, reviewRequests=requests(user("bob"), user("carol")),
               timelineItems=conn(requested(user("carol"), T0), event("ReadyForReviewEvent", T0),
                                  event("ConvertToDraftEvent", T1), requested(user("bob"), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "draft", T1), ("bob", "review", T2)])
        self.assertEqual(flow.review_since(p, "bob"), T2)

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
                self.assertEqual(flow.pr_balls(p), [("alice", "ci_red", T2)])

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
                self.assertNotIn("ci_red", [r[1] for r in flow.pr_balls(p)])

    def test_ci_red_keeps_pending_reviewers(self):
        p = pr(commits=rollup(checks("FAILURE")), reviewRequests=requests(user("bob")))
        self.assertEqual(
            flow.pr_balls(p), [("alice", "ci_red", T2), ("bob", "review", T0)]
        )

    def test_ci_red_wins_over_changes_requested(self):
        p = pr(commits=rollup(checks("FAILURE")), reviewDecision="CHANGES_REQUESTED")
        self.assertEqual([r[1] for r in flow.pr_balls(p)], ["ci_red"])

    def test_changes_requested_plus_pending_reviewer(self):
        p = pr(
            reviewDecision="CHANGES_REQUESTED",
            reviews=conn(
                review(user("bob"), "CHANGES_REQUESTED", T1),
                review(user("bob"), "COMMENTED", T2),
            ),
            reviewRequests=requests(user("carol")),
            timelineItems=conn(requested(user("carol"), T3)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "changes_requested", T1), ("carol", "review", T3)]
        )

    def test_changes_requested_then_rerequested_from_everyone_is_the_reviewers_turn(self):
        """変更要求を出した人全員に依頼し直していれば、ターンはレビュアーにある。依頼より前に誰が最後に喋っても同じ（#1843）"""
        for last in ("alice", "bob"):
            with self.subTest(last=last):
                p = pr(
                    reviewDecision="CHANGES_REQUESTED",
                    reviews=conn(review(user("bob"), "CHANGES_REQUESTED", T0, "ここを直してください")),
                    reviewRequests=requests(user("bob")),
                    timelineItems=conn(requested(user("bob"), T2)),
                    comments=conn(comment(user(last), T1, "見ました" if last == "bob" else "直しました")),
                )
                self.assertFalse(flow.turn.owes_change_requests(p))
                self.assertEqual(
                    flow.merge_rows(flow.pr_balls(p)),
                    {"alice": (["awaiting_review"], T2), "bob": (["review"], T2)},
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
            timelineItems=conn(requested(user("bob"), T2)),
        )
        self.assertEqual(p["latestOpinionatedReviews"]["nodes"][0]["state"], "CHANGES_REQUESTED")
        self.assertEqual(tiers(p), {"alice": 3, "bob": 0})

    def test_a_request_resets_the_reviewers_last_word(self):
        """変更要求に限らない: 依頼より前の本人の発言は数えず、依頼より後に本人が問うたなら相手待ち。
        依頼の日時が履歴に無ければ、全部の発言で見る"""
        before = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1, "質問です")),
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T2)),
        )
        self.assertEqual(tiers(before)["bob"], 0)
        after = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T3, "質問です")),
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T2)),
        )
        self.assertEqual(tiers(after)["bob"], 3)
        unseen = pr(reviews=before["reviews"], reviewRequests=requests(user("bob")))
        self.assertEqual(tiers(unseen)["bob"], 3)

    def test_the_1843_order_keeps_the_rerequested_reviewer_on_turn(self):
        """#1843 の順: 変更要求 → 作者の再依頼 → 本人が解決済みスレッドで「確認しました」（本文の無い COMMENTED つき）。
        依頼の後の本人の相槌は何も待たないのでターンはレビュアーにあり、その行に作者の無言の催促も出さない"""
        p = pr(
            reviewDecision="CHANGES_REQUESTED",
            comments=conn(comment(user("alice"), T0, "お願いします")),
            reviews=conn(
                review(user("bob"), "CHANGES_REQUESTED", "2026-08-01T12:00:00Z", "直してください"),
                review(user("bob"), "COMMENTED", T2),
            ),
            reviewThreads=conn(thread(comment(user("bob"), T2, "確認しました"), resolved=True)),
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T1)),
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
                timelineItems=conn(requested(user("bob"), T1)),
            )

        self.assertEqual([f for f in flow.pr_facts(p(), "bob") if "発言なし" in f], [])
        self.assertIn(
            "alice は 08-01 00:00 以降 発言なし",
            flow.pr_facts(p(comment(user("bob"), T3, "まだですか")), "bob"),
        )

    def test_a_question_left_before_the_rerequest_still_waits_for_the_answer(self):
        """未解決スレッドで本人が出した問いに作者が答えないまま再依頼しても、本人は返答待ちで相手の番。作者が答えるターン
        （依頼より前の発言を数えないのは最後の発言者の判定だけ）"""
        p = pr(
            reviewThreads=conn(thread(comment(user("bob"), T0, "ここはなぜですか"))),
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T1)),
        )
        self.assertEqual(tiers(p), {"alice": 0, "bob": 3})

    def test_the_authors_answer_in_a_resolved_thread_after_the_rerequest_counts(self):
        """解決済みスレッドで数えないのは依頼された本人の発言だけ。依頼の後に本人が問い、作者が解決済みスレッドで
        答えたなら作者が最後で、本人のターン"""
        p = pr(
            comments=conn(comment(user("bob"), T2, "質問です")),
            reviewThreads=conn(thread(comment(user("alice"), T3, "答えです"), resolved=True)),
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T1)),
        )
        self.assertEqual(tiers(p)["bob"], 0)

    def test_changes_requested_stays_with_the_author_unless_every_requester_is_asked_again(self):
        def cr(*reviews, asked=(), **kw):
            return pr(
                reviewDecision="CHANGES_REQUESTED",
                reviews=conn(*reviews),
                reviewRequests=requests(*asked),
                timelineItems=conn(*(requested(a, T3) for a in asked)),
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
                self.assertEqual("changes_requested" in [k for _, k, _ in flow.pr_balls(p)], owes)

    def test_the_queries_read_each_reviewers_latest_opinion(self):
        for q in (flow.PR_QUERY, flow.LEGACY_PR_QUERY):
            self.assertIn(flow.turn.OPINIONS, q)

    def test_review_since_is_that_reviewers_latest_request(self):
        p = pr(
            reviewRequests=requests(user("bob"), user("carol")),
            timelineItems=conn(
                requested(user("bob"), T1),
                requested(user("bob"), T2),
                requested(user("carol"), T3),
            ),
        )
        self.assertEqual(
            flow.pr_balls(p),
            [
                ("bob", "review", T2),
                ("carol", "review", T3),
                ("alice", "awaiting_review", T3),
            ],
        )

    def test_bot_request_does_not_count(self):
        p = pr(
            reviewRequests=requests(bot()), reviews=conn(review(bot(), "COMMENTED", T1))
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T1)])

    def test_team_request_shows_slug(self):
        p = pr(reviewRequests=requests(team()))
        self.assertEqual(
            flow.pr_balls(p),
            [("org/team", "review", T0), ("alice", "awaiting_review", T0)],
        )

    def test_approved_is_authors_merge(self):
        p = pr(
            reviewDecision="APPROVED", reviews=conn(review(user("bob"), "APPROVED", T2))
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "merge", T2)])

    def test_approved_with_pending_request_waits_on_reviewer(self):
        p = pr(reviewDecision="APPROVED", reviewRequests=requests(user("carol")))
        self.assertEqual(
            flow.pr_balls(p),
            [("carol", "review", T0), ("alice", "awaiting_review", T0)],
        )

    def test_pending_request_keeps_the_author_visible(self):
        # 依頼を出した瞬間に作者の一覧から PR が消えると、依頼を出したこと自体が見えなくなる
        p = pr(
            reviewRequests=requests(user("bob")),
            timelineItems=conn(requested(user("bob"), T2)),
        )
        self.assertEqual(
            flow.pr_balls(p),
            [("bob", "review", T2), ("alice", "awaiting_review", T2)],
        )

    def test_pending_request_does_not_add_a_second_author_row(self):
        # 作者に行があるときに足すと merge_rows が since を min() で倒し、日数が依頼日まで戻る
        red = pr(
            commits=rollup(checks("FAILURE")), reviewRequests=requests(user("bob"))
        )
        self.assertEqual(
            flow.pr_balls(red), [("alice", "ci_red", T2), ("bob", "review", T0)]
        )
        talking = pr(
            reviewRequests=requests(user("bob")),
            reviewThreads=conn(
                thread(comment(user("bob"), T3, "直してください")),
            ),
        )
        self.assertNotIn("awaiting_review", [k for _, k, _ in flow.pr_balls(talking)])

    def test_pending_request_is_last_even_before_anyone_speaks(self):
        # waiting は「最後に発言したのが本人」で立つ。誰も喋っていない PR でも相手待ちに落とす
        self.assertEqual(flow.tier(pr(), "alice", ["awaiting_review"], 1, False), 3)
        self.assertEqual(flow.tier(pr(), "alice", ["awaiting_review"], 1, True), 3)

    def test_human_comment_without_request_is_rerequest(self):
        p = pr(
            reviews=conn(
                review(bot(), "COMMENTED", T1), review(user("bob"), "COMMENTED", T2)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "rerequest", T2)])

    def test_authors_own_reply_review_is_not_a_human_review(self):
        p = pr(
            reviews=conn(
                review(bot(), "COMMENTED", T1), review(user("alice"), "COMMENTED", T2)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T1)])

    def test_never_requested_counts_from_ready_for_review(self):
        p = pr(
            timelineItems=conn(
                event("ConvertToDraftEvent", T1), event("ReadyForReviewEvent", T3)
            )
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T3)])

    def test_never_asked_counts_from_the_last_commit(self):
        # 作成から寝かせた期間は「待ち」ではない。最後に push した日から数える
        p = pr(commits=rollup(None))
        p["commits"]["nodes"][0]["commit"]["committedDate"] = T3
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T3)])

    def test_asking_a_human_once_is_not_never_asked(self):
        # 人に頼んだ履歴があれば、依頼が消えていても「未依頼」ではない
        p = pr(timelineItems=conn(requested(user("bob"), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "review_requested", T2)])

    def test_team_request_counts_as_asking(self):
        p = pr(timelineItems=conn(requested(team(), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "review_requested", T2)])

    def test_bot_only_request_history_is_still_never_asked(self):
        # Copilot だけに頼んだ PR は、人から見れば誰にも渡っていない
        p = pr(timelineItems=conn(requested(bot(), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T1)])

    def test_unknown_decision_is_visible(self):
        p = pr(reviewDecision="SOMETHING_NEW")
        self.assertEqual(flow.pr_balls(p), [("alice", "unclassified", T0)])

    def test_pr_without_any_review_yet_is_never_asked(self):
        """レビューが 1 件も無い間 reviewDecision は null。分類なしに落とすと最上段に出る"""
        self.assertEqual(
            flow.pr_balls(pr(reviewDecision=None)), [("alice", "unrequested", T1)]
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
            flow.pr_balls(p), [("alice", "rerequest", T1), ("bob", "recheck", T2)]
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
                ("alice", "rerequest", T1),
                ("alice", "thread_reply", T3),
                ("bob", "awaiting_reply", T3),
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
        self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T1)])

    def test_assignee_other_than_author_gets_row_since_assigned(self):
        p = pr(
            assignees=conn(user("alice"), user("bob")),
            timelineItems=conn(assigned("bob", T2)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "unrequested", T1), ("bob", "assigned", T2)]
        )

    # ---- 持ち主（返答できる assignee に作者がいなければその全員）

    def test_owners_are_the_assignees_only_when_the_author_is_not_one(self):
        self.assertEqual(flow.owners(pr()), ["alice"])
        self.assertEqual(flow.owners(pr(assignees=conn(user("alice"), user("bob")))), ["alice"])
        self.assertEqual(flow.owners(pr(assignees=conn(user("bob"), user("carol")))), ["bob", "carol"])
        # Bot の起票（dependabot 等）も退会済みの作者も、assignee に入りようがない
        for author in (bot("dependabot"), None):
            with self.subTest(author=author):
                p = pr(author=author, assignees=conn(user("bob")))
                self.assertEqual(flow.owners(p), ["bob"])
                self.assertEqual(flow.pr_balls(p), [("bob", "unrequested", T1)])

    def test_only_other_assignees_take_over_every_author_row(self):
        p = pr(
            commits=rollup(checks("FAILURE")),
            assignees=conn(user("bob"), user("carol")),
            timelineItems=conn(assigned("bob", T1), assigned("carol", T3)),
        )
        self.assertEqual(flow.pr_balls(p), [("bob", "ci_red", T2), ("carol", "ci_red", T3)])

    def test_draft_moves_to_the_assignee_too(self):
        p = pr(isDraft=True, assignees=conn(user("bob")), timelineItems=conn(assigned("bob", T2)))
        self.assertEqual(flow.pr_balls(p), [("bob", "draft", T2)])

    def test_review_wait_moves_to_the_assignee_and_is_not_doubled(self):
        asked = pr(reviewRequests=requests(user("carol")), assignees=conn(user("bob")))
        self.assertEqual(flow.pr_balls(asked), [("carol", "review", T0), ("bob", "awaiting_review", T0)])
        red = pr(commits=rollup(checks("FAILURE")), reviewRequests=requests(user("carol")), assignees=conn(user("bob")))
        self.assertEqual(flow.pr_balls(red), [("bob", "ci_red", T2), ("carol", "review", T0)])

    def test_review_wait_is_judged_per_owner(self):
        p = pr(
            reviewRequests=requests(user("dave")),
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "ここ要りますか"), comment(user("carol"), T2))),
        )
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][0], ["recheck"])
        self.assertEqual(rows["carol"][0], ["awaiting_review"])

    def test_authors_other_roles_stay_with_the_author(self):
        p = pr(assignees=conn(user("bob")))
        p["pendingReview"] = {"by": "alice", "comments": 1, "since": T2}
        self.assertEqual(flow.pr_balls(p), [("bob", "unrequested", T1), ("alice", "pending_review", T2)])

    def test_the_owner_sides_own_reply_is_not_a_human_review(self):
        for replier in ("alice", "bob"):
            with self.subTest(replier=replier):
                p = pr(assignees=conn(user("bob")), reviews=conn(review(user(replier), "COMMENTED", T2)))
                self.assertEqual(flow.pr_balls(p), [("bob", "unrequested", T1)])

    def test_the_holders_own_question_keeps_the_review_wait(self):
        p = pr(
            reviewRequests=requests(user("carol")),
            assignees=conn(user("bob")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "この仕様で合っていますか"))),
        )
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"][0], ["awaiting_review"])
        self.assertEqual(flow.pr_tiers(p)["bob"][0], 3)

    def test_a_reviewers_own_question_still_decides_their_tier(self):
        p = pr(reviewThreads=conn(thread(comment(user("carol"), T1, "これは？"))))
        p["pendingReview"] = {"by": "carol", "comments": 1, "since": T2}
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["carol"][0], ["pending_review", "awaiting_reply"])
        self.assertEqual(flow.pr_tiers(p)["carol"][0], 3)

    def test_the_owners_unsent_draft_is_their_row_while_a_review_is_requested(self):
        p = pr(reviewRequests=requests(user("carol")), timelineItems=conn(requested(user("carol"), T0)))
        p["pendingReview"] = {"by": "alice", "comments": 1, "since": T2}
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["alice"], (["pending_review"], T2))
        self.assertEqual(flow.pr_tiers(p)["alice"][0], 2)

    def test_received_threads_do_not_pull_the_wait_back_before_the_handover(self):
        p = pr(
            assignees=conn(user("bob")),
            timelineItems=conn(assigned("bob", T3)),
            reviewThreads=conn(
                thread(comment(user("carol"), T0, "これは？")),
                thread(comment(user("bob"), T0, "この仕様で合っていますか")),
            ),
        )
        p["pendingReview"] = {"by": "bob", "comments": 1, "since": T0}
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][1], T3)
        self.assertEqual(rows["carol"], (["awaiting_reply"], T0))
        self.assertEqual(rows["alice"], (["thread_reply"], T0))

    def test_the_author_who_assigned_themselves_keeps_the_wait(self):
        p = pr(
            commits=rollup(checks("FAILURE")),
            assignees=conn(user("alice"), user("bob")),
            timelineItems=conn(assigned("alice", T3), assigned("bob", T2)),
        )
        self.assertEqual(flow.pr_balls(p), [("alice", "ci_red", T2), ("bob", "assigned", T2)])

    def test_two_owners_share_every_formal_row(self):
        dave = user("dave")
        shared = {
            "ci_red": dict(commits=rollup(checks("FAILURE"))),
            "changes_requested": dict(reviewDecision="CHANGES_REQUESTED", reviews=conn(review(dave, "CHANGES_REQUESTED", T1))),
            "merge": dict(reviewDecision="APPROVED", reviews=conn(review(dave, "APPROVED", T1))),
            "rerequest": dict(reviews=conn(review(dave, "COMMENTED", T1))),
            "review_requested": dict(timelineItems=conn(requested(dave, T1))),
            "unclassified": dict(reviewDecision="NEW_VALUE"),
        }
        for kind, kw in shared.items():
            with self.subTest(kind=kind):
                two = pr(assignees=conn(user("bob"), user("carol")), **kw)
                self.assertEqual(flow.merge_rows(flow.pr_balls(two))["bob"][0], [kind])
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
        self.assertEqual(flow.merge_rows(flow.pr_balls(red_draft)), {"bob": (["draft"], T0), "carol": (["draft"], T0)})
        self.assertEqual(tiers(red_draft), {"bob": 2, "carol": 2})

    def test_an_assignees_open_question_to_the_other_side(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "この仕様で合っていますか"))),
        )
        self.assertEqual(
            flow.merge_rows(flow.pr_balls(p)),
            {
                "bob": (["unrequested"], T1),
                "carol": (["unrequested", "thread_reply"], T1),
                "alice": (["thread_reply"], T1),
            },
        )
        self.assertEqual(tiers(p), {"bob": 2, "carol": 1, "alice": 1})

    def test_unanswerable_assignees_are_not_handed_the_pr(self):
        for nobody in (bot("Copilot"), None, mannequin("old-bob")):
            with self.subTest(assignee=nobody):
                p = pr(assignees=conn(nobody), comments=conn(comment(user("alice"), T3, "お願いします")))
                self.assertEqual(flow.owners(p), ["alice"])
                self.assertEqual(flow.pr_balls(p), [("alice", "unrequested", T1)])
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
                self.assertEqual(flow.turn.author_holds_handed(p), want and legacy)
                self.assertEqual(flow.owners(p) != ["alice"], want and not legacy)

    def test_mixed_assignees_hand_the_pr_to_the_people_only(self):
        p = pr(assignees=conn(user("bob"), bot("Copilot")), commits=rollup(checks("FAILURE")))
        self.assertEqual(flow.owners(p), ["bob"])
        self.assertEqual(flow.pr_balls(p), [("bob", "ci_red", T2)])
        self.assertIn("assignee: bob, Copilot", flow.pr_facts(p, "dave"))
        alice = flow.pr_facts(p, "alice")
        self.assertIn("担当に渡した PR（担当は bob）", alice)
        self.assertIn("assignee: Copilot", alice)
        kept = pr(assignees=conn(user("alice"), bot("Copilot")))
        self.assertEqual(flow.pr_balls(kept), [("alice", "unrequested", T1)])

    def test_two_human_reviewers_each_see_someone_else_can_move_it(self):
        self.assertEqual(tiers(pr(reviewRequests=requests(user("bob"), user("carol")))), {"bob": 1, "carol": 1, "alice": 3})
        self.assertEqual(tiers(pr(reviewRequests=requests(user("bob"), bot()))), {"bob": 0, "alice": 3})

    def test_tier_shared_review_second_and_waiting_last(self):
        def t(kinds, reviewers, waiting, shared=False, who="bob", **kw):
            return flow.tier(pr(**kw), who, kinds, reviewers, waiting, shared)

        self.assertEqual(t(["review"], 2, False), 1)
        self.assertEqual(t(["review"], 1, False), 0)
        self.assertEqual(t(["review_requested"], 3, False), 0)
        self.assertEqual(t(["recheck"], 3, False), 0)
        self.assertEqual(t(["ci_red", "review"], 3, False), 0)
        # 相手の返事待ちは、依頼先が何人でも最後
        self.assertEqual(t(["review"], 1, True), 3)
        self.assertEqual(t(["review"], 2, True), 3)
        self.assertEqual(t(["rerequest"], 1, True), 3)
        # 相手にも返すターンが残っているなら、その人が全部片づけても PR は終わらない
        self.assertEqual(t(["recheck"], 1, False, True), 1)
        self.assertEqual(t(["thread_reply"], 1, False, True), 1)
        # 渡していない PR は誰も待っていないが、動かせるのは本人だけ。相手待ちより上
        self.assertEqual(t(["unrequested"], 0, False, who="alice"), 2)
        self.assertEqual(t(["draft"], 0, False, who="alice"), 2)

    def test_tier_drops_follow_up_when_only_the_author_can_clear_the_blocker(self):
        def t(who, **kw):
            return flow.tier(pr(**kw), who, ["recheck"], 1, False)

        self.assertEqual(t("bob"), 0)
        # main 未追従・衝突・CI 赤はブランチを持つ作者しか外せない。残りが再確認だけなら最後
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
                ["review", "recheck"],
                1,
                False,
            ),
            0,
        )
        # 相手の返事待ちは shared より強い
        self.assertEqual(flow.tier(pr(), "bob", ["review"], 1, True, True), 3)

    def test_owes_thread_covers_both_directions_of_unresolved_threads(self):
        self.assertTrue(flow.owes_thread(["recheck"]))
        self.assertTrue(flow.owes_thread(["merge", "thread_reply"]))
        self.assertFalse(flow.owes_thread(["rerequest", "review"]))

    def test_shared_balls_needs_two_people_with_thread_turns(self):
        both = {
            "alice": (["merge", "thread_reply"], T1),
            "bob": (["recheck"], T2),
            "carol": (["review"], T3),
        }
        self.assertEqual(flow.shared_balls(both), {"alice", "bob"})
        one_side = {
            "alice": (["rerequest", "thread_reply"], T1),
            "bob": (["review"], T2),
        }
        self.assertEqual(flow.shared_balls(one_side), set())
        two_openers = {"bob": (["recheck"], T1), "carol": (["recheck"], T2)}
        self.assertEqual(flow.shared_balls(two_openers), {"bob", "carol"})
        self.assertEqual(flow.shared_balls({}), set())

    def test_same_name_rerun_uses_the_last_run(self):
        p = pr(commits=rollup(runs(("chk", "FAILURE", T1), ("chk", "SUCCESS", T2))))
        self.assertNotIn("ci_red", [r[1] for r in flow.pr_balls(p)])

    def test_same_name_rerun_that_fails_last_is_red(self):
        p = pr(commits=rollup(runs(("chk", "SUCCESS", T1), ("chk", "FAILURE", T2))))
        self.assertEqual(flow.pr_balls(p), [("alice", "ci_red", T2)])

    def test_running_rerun_outranks_the_old_failure(self):
        p = pr(commits=rollup(runs(("chk", "FAILURE", T2), ("chk", None, None))))
        self.assertNotIn("ci_red", [r[1] for r in flow.pr_balls(p)])

    def test_different_names_are_not_collapsed(self):
        p = pr(commits=rollup(runs(("a", "SUCCESS", T2), ("b", "FAILURE", T1))))
        self.assertEqual(flow.pr_balls(p), [("alice", "ci_red", T1)])

    def test_merge_rows_joins_kinds_and_keeps_oldest(self):
        rows = [
            ("a", "rerequest", T2),
            ("a", "thread_reply", T1),
            ("b", "recheck", T3),
        ]
        self.assertEqual(
            flow.merge_rows(rows),
            {"a": (["rerequest", "thread_reply"], T1), "b": (["recheck"], T3)},
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
        self.assertEqual(rows["alice"][0], ["rerequest"])
        self.assertTrue(flow.waiting_on_others(p, "alice", rows["alice"][0]))
        # 同じ PR でも、確認するターンのスレッドを持つ側は待っていない
        self.assertFalse(flow.waiting_on_others(p, "bob", rows["bob"][0]))

    def test_reviewer_who_asked_a_question_is_waiting(self):
        p = pr(
            reviewRequests=requests(user("bob")),
            comments=conn(comment(user("bob"), T2, "これは顧客テナントですか")),
        )
        rows = flow.merge_rows(flow.pr_balls(p))
        self.assertEqual(rows["bob"][0], ["review"])
        self.assertTrue(flow.waiting_on_others(p, "bob", rows["bob"][0]))

    def test_author_who_still_owes_thread_replies_is_not_waiting(self):
        p = pr(
            reviews=conn(review(user("bob"), "COMMENTED", T1, "見た")),
            reviewThreads=conn(thread(comment(user("bob"), T1))),
            comments=conn(comment(user("alice"), T3, "main を取り込みました")),
        )
        kinds = flow.merge_rows(flow.pr_balls(p))["alice"][0]
        self.assertIn("thread_reply", kinds)
        self.assertFalse(flow.waiting_on_others(p, "alice", kinds))

    def test_authors_unrelated_comment_does_not_take_back_the_ball(self):
        """自分が立てたスレッドに作者が未返信なら、作者が別件で喋っても作者のターン"""
        p = pr(
            reviewThreads=conn(thread(comment(user("bob"), T1, "ここが変"))),
            comments=conn(comment(user("alice"), T3, "別件のメモです")),
        )
        self.assertTrue(flow.waiting_on_others(p, "bob", ["review"]))
        # 作者の側は逆で、返すターンがあるので相手待ちではない
        self.assertFalse(flow.waiting_on_others(p, "alice", ["thread_reply"]))

    def test_reviewer_who_has_not_spoken_is_not_waiting(self):
        p = pr(
            reviewRequests=requests(user("bob")),
            comments=conn(comment(user("alice"), T2, "レビューをお願いします")),
        )
        self.assertFalse(flow.waiting_on_others(p, "bob", ["review"]))

    def test_no_post_at_all_is_not_waiting(self):
        self.assertFalse(flow.waiting_on_others(pr(), "alice", ["unrequested"]))

    def test_bot_post_does_not_end_the_conversation(self):
        p = pr(
            comments=conn(comment(user("alice"), T1, "扱いはお任せします")),
            reviews=conn(review(bot(), "COMMENTED", T3, "自動レビュー")),
        )
        self.assertTrue(flow.waiting_on_others(p, "alice", ["unrequested"]))


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
            [r for r in flow.pr_balls(p) if r[1] == "thread_reply"],
            [("alice", "thread_reply", T1)],
        )

    def test_a_deleted_writer_is_not_counted_under_a_living_authors_name(self):
        note = thread(comment(user("alice"), T1, "自分メモ"), comment(None, T2, "同感"))
        self.assertIn("未解決 1 スレッド（人は alice, 退会済み だけ 1）", flow.pr_facts(pr(reviewThreads=conn(note))))

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
        p = pr(body="入口の検査を足します。", additions=3, deletions=1, changedFiles=2,
               assignees=conn(user("bob"), user("carol")))
        alice = flow.pr_facts(p, "alice", intro=True)
        self.assertIn("担当に渡した PR（担当は bob, carol）", alice)
        self.assertEqual([f for f in alice if f.startswith(("作者:", "担当として", "本文:", "規模:"))], [])
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
        red = pr(commits=rollup(checks("FAILURE")), assignees=conn(user("bob"), user("carol")))
        for reader in ("alice", "dave"):
            self.assertIn("CI 赤: chk0。外せるのは担当の bob, carol だけ", flow.pr_facts(red, reader))
        self.assertIn("CI 赤: chk0", flow.pr_facts(red, "bob"))
        self.assertTrue(flow.blocked_by_others(red, "alice", ["recheck"]))
        self.assertFalse(flow.blocked_by_others(red, "bob", ["recheck"]))

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
            # alice が返すターンのスレッド。alice の最後の発言は T1 で、その後に carol が通りすがる
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
        received = pr(assignees=conn(user("bob")), timelineItems=conn(assigned("bob", T1)), reviewThreads=question)
        self.assertIn("bob は 08-02 00:00 以降 発言なし（この PR で発言が無い）", flow.pr_facts(received, "carol"))
        unknown = pr(assignees=conn(user("bob")), reviewThreads=question)
        self.assertIn("bob は 08-01 00:00 以降 発言なし（この PR で発言が無い）", flow.pr_facts(unknown, "carol"))
        held = pr(assignees=conn(user("alice")), timelineItems=conn(assigned("alice", T1)), reviewThreads=question)
        # 作者は作成日に本文を書いている
        self.assertIn("alice は 08-01 00:00 以降 発言なし", flow.pr_facts(held, "carol"))
        by_bot = pr(author=bot("dependabot"), reviewThreads=question)
        self.assertEqual([f for f in flow.pr_facts(by_bot, "carol") if "発言なし" in f], [])

    def test_silence_past_a_cut_off_window_says_only_what_was_seen(self):
        question = conn(thread(comment(user("carol"), T2, "これは？")))
        for cut_off in (dict(comments=conn(comment(user("dave"), T1), total=180)), dict(reviews=conn(total=130))):
            for owner, received in (("bob", conn(user("bob"))), ("alice", conn())):
                with self.subTest(cut_off=list(cut_off), owner=owner):
                    p = pr(assignees=received, reviewThreads=question, **cut_off)
                    self.assertIn(f"{owner} は 08-01 00:00 以降 発言なし（見た範囲で発言が無い）", flow.pr_facts(p, "carol"))

    def test_silence_past_a_cut_history_says_only_what_was_seen(self):
        question = conn(thread(comment(user("carol"), T2, "これは？")))
        lost = pr(assignees=conn(user("bob")), timelineItems=full_history(), reviewThreads=question)
        self.assertIn("bob は 08-01 00:00 以降 発言なし（見た範囲で発言が無い）", flow.pr_facts(lost, "carol"))
        kept = pr(assignees=conn(user("bob")), timelineItems=full_history(assigned("bob", T1)), reviewThreads=question)
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
                p = pr(assignees=received, reviewThreads=question, comments=conn(comment(user(reader), T3, "別件です")))
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
        # 下書きは carol の指摘を隠さない。作者が答えるターンのままで、bob には移らない
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")], ["送信済みの指摘"]
        )
        self.assertEqual(flow.turn_threads(p, "bob"), [])

    def test_unsent_review_is_its_own_ball_and_is_not_waiting_on_anyone(self):
        p = self.draft()
        flow.drop_pending(p)
        self.assertIn(("bob", "pending_review", T2), flow.pr_balls(p))
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
        self.assertEqual(flow.tier(p, "bob", ["pending_review"], 0, False), 2)

    def test_unsent_review_does_not_hide_the_authors_own_ball(self):
        """未送信は別人の行。作者の形式上の行（マージ・未依頼）を押しのけてはいけない"""
        p = self.draft()
        p["reviewDecision"] = "APPROVED"
        p["reviews"]["nodes"].append(review(user("carol"), "APPROVED", T1))
        flow.drop_pending(p)
        rows = flow.pr_balls(p)
        self.assertIn(("alice", "merge", T1), rows)
        self.assertIn(("bob", "pending_review", T2), rows)

    def test_unsent_review_survives_draft(self):
        p = self.draft()
        p["isDraft"] = True
        flow.drop_pending(p)
        self.assertIn(("bob", "pending_review", T2), flow.pr_balls(p))

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

    def test_pr_prefix_and_japanese_before_the_number_count(self):
        """PR#12・issue#12 は人がよく書く形。日本語の直後（対応は#12）も番号として読む"""
        self.assertEqual(flow.issue_refs("PR#12 で直した", self.REPO), {12})
        self.assertEqual(flow.issue_refs("issue#7 の続き", self.REPO), {7})
        self.assertEqual(flow.issue_refs("対応は#12", self.REPO), {12})

    def test_url_fragment_and_char_reference_are_not_numbers(self):
        """x.html#12 は URL の fragment、&#123; は文字参照で、どちらも issue の番号ではない"""
        self.assertEqual(flow.issue_refs("x.html#12 を見て", self.REPO), set())
        self.assertEqual(flow.issue_refs("&#123; を書く", self.REPO), set())
        self.assertEqual(flow.issue_refs("word#12", self.REPO), set())


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

    def test_login_case_does_not_matter(self):
        p = pr(
            comments=conn(
                comment(user("bob"), T1, "@Alice ここどうしますか"),
                comment(user("alice"), T2, "別件ですが CI を直しました"),
            )
        )
        self.assertEqual(len(flow.unverified_replies(p, "alice")), 1)

    def test_a_call_with_no_reply_is_not_counted(self):
        """それは呼びかけのセクションが拾う。ここは『返したことになっている』分だけ"""
        p = pr(comments=conn(comment(user("bob"), T1, "@alice ここどうしますか")))
        self.assertEqual(flow.unverified_replies(p, "alice"), [])

    def test_thread_comments_are_not_counted(self):
        """スレッドは返信が紐づくので機械が誰のターンか決められる"""
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
        # 相手が答えたスレッドは立てた人が再確認するターン、答えていないスレッドは作者のターン
        self.assertEqual(
            [(t["path"], c["body"]) for t, c in flow.turn_threads(p, "bob")],
            [("a.py", "d151bbee で直しました")],
        )
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")],
            ["これはどうなりますか"],
        )

    def test_a_reviewer_reply_in_the_authors_own_note_is_the_authors_turn(self):
        # 作者の自注に bob が問いを返した: 作者が答えるターンで、bob は返事待ち（/catchup と同じ判定）
        p = pr(reviewThreads=conn(thread(comment(user("alice"), T1, "メモ"), comment(user("bob"), T2, "Y ではだめ？"))))
        self.assertEqual([c["body"] for _, c in flow.turn_threads(p, "alice")], ["Y ではだめ？"])
        self.assertEqual(flow.turn_threads(p, "bob"), [])
        # 側の外の人が返していない自注は、これまでどおり誰のターンにもしない
        quiet = pr(reviewThreads=conn(thread(comment(user("alice"), T1, "メモ"), comment(user("alice"), T2, "追記"))))
        self.assertEqual(flow.turn_threads(quiet, "alice"), [])
        # 返答できない作者（Mannequin）の自注に carol が返しても、返す人がいない。作者にターンを立てず、carol の返事待ちも残さない
        mute = pr(author=mannequin("mq"),
                  reviewThreads=conn(thread(comment(mannequin("mq"), T1, "メモ"), comment(user("carol"), T2, "これは？"))))
        self.assertEqual(flow.thread_turns(mute), [])

    def test_bot_only_thread_belongs_to_nobody(self):
        p = pr(reviewThreads=conn(thread(comment(bot(), T1, "[block] fail-open です"))))
        self.assertEqual(flow.turn_threads(p, "alice"), [])
        self.assertEqual(flow.turn_threads(p, "bob"), [])

    def test_a_second_reviewer_adds_a_turn_instead_of_taking_one(self):
        """レビュアーが 2 人入るとターンは 2 人に載る。1 人に潰すと、潰した側の指摘が黙って落ちる"""
        p = pr(
            reviewThreads=conn(
                thread(
                    comment(user("bob"), T0, "ここが壊れています"),
                    comment(user("alice"), T1, "d151bbee で直しました"),
                    comment(user("carol"), T2, "別ケースだと戻りませんか"),
                )
            )
        )
        # bob は作者の修正を再確認するターン。carol の発言では消えない
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "bob")],
            ["d151bbee で直しました"],
        )
        # 作者は carol に答えるターン。渡る材料は bob の指摘ではなく carol の発言
        self.assertEqual(
            [c["body"] for _, c in flow.turn_threads(p, "alice")],
            ["別ケースだと戻りませんか"],
        )
        self.assertEqual(flow.turn_threads(p, "carol"), [])
        self.assertEqual(flow.answered_threads(p), ([("bob", T1, False)], [("alice", T2, False)]))
        self.assertEqual(
            flow.conversation_balls(p),
            [
                ("bob", "recheck", T1),
                ("alice", "thread_reply", T2),
                ("carol", "awaiting_reply", T2),
            ],
        )
        # 再確認するターンの bob は今日動ける。答えを待っている carol は作者待ち
        self.assertFalse(flow.waiting_on_others(p, "bob", ["recheck"]))
        self.assertTrue(flow.waiting_on_others(p, "carol", ["awaiting_reply"]))

    def test_a_third_party_does_not_take_over_the_original_turn(self):
        """相槌でもターンは増えるだけ。立てた人の再確認が消えて材料が相槌に化けてはいけない"""
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
                ("alice", "thread_reply", T2),
                ("bob", "awaiting_reply", T2),
                ("carol", "awaiting_reply", T2),
                ("dave", "awaiting_reply", T2),
            ],
        )
        for who in ("bob", "carol", "dave"):
            self.assertTrue(flow.waiting_on_others(p, who, ["awaiting_reply"]), who)


    # ---- 作者以外の人だけが assignee の PR: 答える側は作者と受けた人

    def test_the_assignees_reply_answers_a_third_partys_thread(self):
        by_bob = thread(comment(user("carol"), T0, "ここが変"), comment(user("bob"), T1, "直しました"))
        by_alice = thread(comment(user("carol"), T0, "これは？"), comment(user("alice"), T1, "意図どおり"))
        p = pr(assignees=conn(user("bob")), reviewThreads=conn(by_bob, by_alice))
        self.assertEqual(flow.conversation_balls(p), [("carol", "recheck", T1)])

    def test_a_third_partys_open_question_is_the_assignees_turn(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("dave"), T1, "これは？"))),
        )
        self.assertEqual(
            flow.conversation_balls(p),
            [("bob", "thread_reply", T1), ("carol", "thread_reply", T1), ("dave", "awaiting_reply", T1)],
        )
        self.assertIn("未解決 1 スレッド（bob が返答 1・carol が返答 1）", flow.pr_facts(p))

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
            [("alice", "thread_reply", T1), ("bob", "thread_reply", T1), ("alice", "awaiting_reply", T1)],
        )
        answered = pr(
            assignees=conn(user("bob")),
            reviewThreads=conn(
                thread(comment(user("alice"), T1, "ここは別の関数に？"), comment(user("bob"), T2, "分けました")),
                thread(comment(user("bob"), T1, "この仕様で合っていますか"), comment(user("alice"), T2, "合っています")),
            ),
        )
        self.assertEqual(flow.conversation_balls(answered), [("alice", "recheck", T2), ("bob", "recheck", T2)])

    def test_a_third_party_joining_the_authors_question_also_waits_on_the_assignee(self):
        p = pr(
            assignees=conn(user("bob")),
            reviewThreads=conn(thread(comment(user("alice"), T0, "ここは？"), comment(user("dave"), T1, "同じ疑問です"))),
        )
        self.assertEqual(
            flow.conversation_balls(p),
            [("bob", "thread_reply", T1), ("alice", "awaiting_reply", T1), ("dave", "awaiting_reply", T1)],
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
                self.assertIn("未解決 2 スレッド（人は bob だけ 1・人は bob, carol だけ 1）", facts)
                self.assertEqual(flow.pr_tiers(p)["bob"][0], 2)
                third = pr(
                    author=author,
                    assignees=conn(user("bob")),
                    reviewThreads=conn(thread(comment(user("carol"), T1, "これは？"))),
                )
                self.assertEqual(
                    flow.conversation_balls(third), [("bob", "thread_reply", T1), ("carol", "awaiting_reply", T1)]
                )

    def test_two_assignees_ask_each_other_too(self):
        p = pr(
            assignees=conn(user("bob"), user("carol")),
            reviewThreads=conn(thread(comment(user("bob"), T1, "ここは任せます"), comment(user("carol"), T2, "引き取りました"))),
        )
        self.assertEqual(flow.conversation_balls(p), [("bob", "recheck", T2)])

    def test_the_authors_own_note_is_skipped_only_while_the_author_holds_it(self):
        note = thread(comment(user("alice"), T1, "自分メモ"))
        self.assertEqual(flow.conversation_balls(pr(reviewThreads=conn(note))), [])
        self.assertIn("未解決 1 スレッド（人は alice だけ 1）", flow.pr_facts(pr(reviewThreads=conn(note))))
        handed = pr(assignees=conn(user("bob")), reviewThreads=conn(note))
        self.assertIn(("bob", "thread_reply", T1), flow.conversation_balls(handed))
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
        "timelineItems": conn(*timeline),
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

    def test_tilde_fences_are_ignored_too(self):
        """GFM のコードブロックは ~~~ でも囲める。中の @name と #12 は数えない。囲みは開いた文字と同じ文字で閉じる"""
        self.assertEqual(flow.mentions("~~~\n@pytest.fixture\n~~~\n@real"), {"real"})
        self.assertEqual(flow.mentions("```\n~~~\n@fence\n```\n@real"), {"real"})
        self.assertEqual(flow.repo_refs("~~~\n#123\n~~~\n#7", "o/r"), {7})

    def test_fences_follow_gfm(self):
        # 行の頭の ```npm test``` は行内のコードで囲みではない。リストの中の字下げした囲みと、閉じの無い囲みは消す
        self.assertEqual(flow.mentions("```npm test``` は失敗\n@bob 見て\n```\nlog\n```"), {"bob"})
        self.assertEqual(flow.mentions("1. a\n   - b:\n     ```python\n     @pytest.fixture\n     ```\n@ann"), {"ann"})
        self.assertEqual(flow.mentions("log:\n```\n@dave\n"), set())
        self.assertEqual(flow.mentions("ありがとう~~~ @gina ~~~"), {"gina"})
        # GitHub の画面で書いた本文は改行が \r\n。閉じの行の \r で閉じを見失い、囲みの後ろを全部消した（3 巡目の直しの戻り）
        self.assertEqual(flow.mentions("Repro:\r\n```\r\nnpm test\r\n```\r\n@bob can you check?"), {"bob"})
        self.assertEqual(flow.repo_refs("```\r\n#3\r\n```\r\n#12", "o/r"), {12})
        # 閉じは開きと同じ字で開き以上の長さ。別の字や後ろに字の付いた行は閉じでない
        self.assertEqual(flow.mentions("````\ncode\n`````\n@hana"), {"hana"})
        self.assertEqual(flow.mentions("~~~\nx\n~~~~\n@hana"), {"hana"})
        self.assertEqual(flow.mentions("```\n@a\n```~\n@hana"), set())

    def test_unanswered_until_mentioned_person_comments(self):
        posts = flow.posts_of_issue(issue(comments=[(user("alice"), T1, "@bob 見て")]))
        self.assertEqual(flow.unanswered(posts)["bob"]["since"], T1)
        posts = flow.posts_of_issue(
            issue(
                comments=[(user("alice"), T1, "@bob 見て"), (user("bob"), T2, "見た")]
            )
        )
        self.assertEqual(flow.unanswered(posts), {})

    def test_mention_matches_login_case_insensitively(self):
        """@Bob は bob を呼んでいる。返した判定も自己言及の判定も大文字小文字を区別しない"""
        posts = flow.posts_of_issue(
            issue(
                comments=[
                    (user("bob"), T1, "質問です"),
                    (user("alice"), T2, "@Bob 見て"),
                    (user("carol"), T3, "@Alice @BOB"),
                ]
            )
        )
        out = flow.unanswered(posts)
        # キーは発言者の綴り（bob）。打たれたまま（Bob）では出ない
        self.assertEqual(sorted(out), ["alice", "bob"])
        self.assertEqual(out["bob"]["since"], T2)
        self.assertTrue(out["bob"]["reply_to_own"])
        self.assertEqual(out["bob"]["excerpt"], "@Bob 見て")
        # 本人のコメントが後にあれば、打たれた綴りが違っても返したことになる
        replied = flow.posts_of_issue(
            issue(comments=[(user("alice"), T1, "@BOB 見て"), (user("bob"), T2, "見た")])
        )
        self.assertEqual(flow.unanswered(replied), {})
        # 自己言及も同じ
        own = flow.posts_of_issue(issue(body="@ALICE @bob", author=user("alice")))
        self.assertEqual(list(flow.unanswered(own)), ["bob"])
        # 発言のない人は打たれた綴りのまま。呼ぶ側が知っている login（known）があればその綴り
        quiet = flow.posts_of_issue(issue(comments=[(user("alice"), T1, "@Dave 見て")]))
        self.assertEqual(list(flow.unanswered(quiet)), ["Dave"])
        self.assertEqual(list(flow.unanswered(quiet, ["dave"])), ["dave"])

    def test_unknown_logins_typed_in_two_cases_are_one_person(self):
        """発言の無い人を @Dave と @dave で呼んでも 1 人。綴りは最初に打たれた物"""
        posts = flow.posts_of_issue(
            issue(comments=[(user("alice"), T1, "@Dave 見て"), (user("carol"), T2, "@dave ping")])
        )
        out = flow.unanswered(posts)
        self.assertEqual(list(out), ["Dave"])
        self.assertEqual(out["Dave"]["since"], T1)

    def test_fences_open_only_at_line_start(self):
        """文の中の ~~~（ありがとう~~~）はコードブロックの囲みではない。間の @name を消さない"""
        self.assertEqual(flow.mentions("ありがとう~~~ @bob レビューお願いします~~~"), {"bob"})
        self.assertEqual(flow.mentions("  ```\n@fixture\n  ```\n@real"), {"real"})
        self.assertEqual(flow.mentions("````\n```\n@inner\n```\n````\n@real"), {"real"})

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
        flow.gh = lambda *_args, **_kw: json.dumps(payload)
        try:
            limits = flow.fill_reactions(waits)
        finally:
            flow.gh = original
        self.assertTrue(waits[0][1]["reacted"])
        self.assertFalse(waits[1][1]["reacted"])
        self.assertEqual(limits, ["C2: リアクション 60 件のうち 50 件しか見ていない"])

    def test_fill_reactions_matches_login_case_insensitively(self):
        waits = [("Bob", {"post_id": "C1", "reacted": False}, None)]
        payload = {"data": {"nodes": [{"id": "C1", "reactions": {"totalCount": 1, "nodes": [{"user": {"login": "bob"}}]}}]}}
        original = flow.gh
        flow.gh = lambda *_args, **_kw: json.dumps(payload)
        try:
            flow.fill_reactions(waits)
        finally:
            flow.gh = original
        self.assertTrue(waits[0][1]["reacted"])

    def test_fill_reactions_skips_not_found_but_stops_on_other_errors(self):
        """取得の間に発言が消えると nodes の該当が null で NOT_FOUND が付く。それで report 全体を落とさない"""
        waits = [("bob", {"post_id": "C1", "reacted": False}, None)]
        gone = {"data": {"nodes": [None]}, "errors": [{"type": "NOT_FOUND", "path": ["nodes", 0]}]}
        seen = []

        def fake(*_args, **kw):
            seen.append(kw)
            return json.dumps(gone)

        original = flow.gh
        flow.gh = fake
        try:
            self.assertEqual(flow.fill_reactions(waits), [])
            self.assertFalse(waits[0][1]["reacted"])
            self.assertEqual(seen, [{"graphql_errors": True}])
            gone["errors"].append({"type": "FORBIDDEN"})
            with self.assertRaises(SystemExit):
                flow.fill_reactions(waits)
        finally:
            flow.gh = original


def gh_runs(calls, *responses):
    """subprocess.run の偽。(終了コード, 本文[, stderr]) を順に返す。本文は文字列ならそのまま、ほかは JSON。
    stderr を省くと、本物の gh の GraphQL のエラーと同じく gh: <message>（成功なら空）"""
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
                    self.assertEqual(flow.gh("api", "graphql", graphql_errors=True), "{}")
                self.assertEqual(len(calls), 2)

    def test_other_graphql_errors_still_stop(self):
        for body in (missing("isDraft"), {"errors": [{"message": "Resource limits exceeded"}]}):
            with self.subTest(body=body), self.assertRaises(SystemExit):
                self.fetch((1, body))

    def test_errors_stop_in_gh_unless_the_caller_reads_them(self):
        """ほかの呼び手（/catchup など）は今までどおり gh の失敗で止まる"""
        with (
            mock.patch.object(flow.shutil, "which", return_value="gh"),
            mock.patch.object(flow.subprocess, "run", gh_runs([], (1, missing("assignedActors")))),
            self.assertRaises(SystemExit),
        ):
            flow.gh("api", "graphql")


class Truncation(unittest.TestCase):
    def test_pr_limits_cover_each_reviewers_latest_opinion(self):
        """切れていると指摘対応を集約値どおり残す（turn.owes_change_requests）ので、そのことを見ていないものに出す"""
        p = pr(latestOpinionatedReviews=conn({"state": "CHANGES_REQUESTED", "author": user("bob")}, total=31))
        self.assertIn("#1: 人ごとの意見 31 件のうち 1 件しか見ていない", flow.limits_of_pr(p))

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
            timelineItems=conn(
                total=51
            ),  # 履歴は検査しない（totalCount が itemTypes で絞る前の総数のため）
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
            ],
        )


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
    legacy は assignedActors の無い GitHub（フィールドが無いと返す）"""

    def fetch_all(query, _owner, _name, field, optional=()):
        if legacy and "assignedActors" in query:
            assert "assignedActors" in optional
            raise flow.MissingField()
        return list(prs) if field == "pullRequests" else list(issues)

    def gh(*_args, **_kw):  # 呼びかけがあるとき fill_reactions が引くリアクション。空で返す
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
    """報告は段を出さず「自分の番 / 相手の番」の 2 つのセクションに分ける。段は並びの鍵としてだけ残る。"""

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
        # 相手にも返すターンがあっても、自分の分は今日できる。待ちには落とさない
        for who in ("bob", "alice"):
            self.assertEqual(self.bucket(self.render(p, who=who)), "自分の番", who)

    def test_one_sided_thread_turn_is_my_ball(self):
        p = pr(reviewThreads=conn(thread(comment(user("bob"), T2))))
        self.assertEqual(self.bucket(self.render(p, who="alice")), "自分の番")
        # 指摘した側は返事を待っている
        self.assertEqual(self.bucket(self.render(p, who="bob")), "相手の番")

    def test_assignee_counts_as_handing_the_pr_over(self):
        """レビュー依頼を押さずに assignee で渡す運用がある。作者以外の人だけが assignee なら、
        作者の一覧からは外れ、受けた人のまだ誰にも渡していないターンになる"""
        handed = pr(
            number=1,
            assignees=conn(user("bob")),
            comments=conn(comment(user("alice"), T3, "扱いはお任せします")),
        )
        self.assertEqual(self.bucket(self.render(handed, who="alice")), "無し")
        self.assertEqual(self.bucket(self.render(handed, who="bob")), "自分の番")

    def test_draft_stays_undelivered_when_the_author_is_also_assigned(self):
        """draft は作者が自分で「まだ出さない」と印を付けた状態"""
        out = self.render(
            pr(number=1, isDraft=True, assignees=conn(user("alice"), user("bob"))), who="alice"
        )
        self.assertEqual(self.bucket(out), "自分の番")

    def test_a_pr_given_only_to_bots_or_deleted_accounts_stays_with_the_author(self):
        for nobody in (bot("Copilot"), None, mannequin("old-bob")):
            with self.subTest(assignee=nobody):
                p = pr(number=1, assignees=conn(nobody), comments=conn(comment(user("alice"), T3, "Copilot に頼みました")))
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
                self.assertEqual(flow.merge_rows(flow.pr_balls(p)), {"alice": (["ci_red"], T2), other: (["assigned"], T0)})
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
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["alice"][0], ["unrequested", "thread_reply"])
        self.assertEqual(tiers(p)["alice"], 0)

    def test_received_draft_and_never_asked_stay_mine_whoever_spoke_last(self):
        """受けた人が「了解、積みます」と返した直後でも、受けた人の自分の番から落とさない——
        落とすと誰の一覧にも出ない（実測 #1928 は draft のまま渡していた）"""
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
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"][0], ["merge"])
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
        self.assertEqual(flow.merge_rows(flow.pr_balls(p))["bob"], (["merge"], T3))
        self.assertEqual(flow.pr_tiers(p)["bob"], (0, T3))
        # 持ち主でない人には返答待ちが立ち、段と日数を決める
        asked = pr(reviewThreads=conn(thread(comment(user("carol"), T0, "これは？"))))
        asked["pendingReview"] = {"by": "carol", "comments": 1, "since": T2}
        self.assertEqual(flow.pr_tiers(asked)["carol"], (3, T0))

    def test_a_reply_in_the_holders_question_thread_counts_like_one_in_the_body(self):
        """持ち主の問いのスレッドで外すのは持ち主本人の発言だけ。相手がそこに書いた答えは本文の答えと同じく数える"""
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

    def test_never_asked_with_the_author_also_assigned_stays_undelivered(self):
        """作者も assignee に残っていれば作者が持っていて、まだ誰にも渡していない（/catchup も依頼先を決めるのは私）。
        誰が最後に発言しても、種別が取れない GitHub でも同じ"""
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
        # 行の頭の ```npm test``` は行内のコードで、囲みの始まりではない（後ろを全部飛ばして空になった）
        self.assertEqual(flow.intro_line("```npm test``` が落ちるのを直す。ほか"), "npm test が落ちるのを直す。")
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
        # bob には #1 が自分の番、#2 が相手の番。どちらのセクションでも番号の次の行が URL
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
        self.assertEqual(
            self.line_after(lines, "  #4 "), "    https://example.invalid/issues/4"
        )

    def test_pr_mentions_carry_the_role_under_the_url(self):
        """呼びかけの番号は、読む側が自分の番へ移すことがある。役割を引き直させない"""
        called = pr(number=1, comments=conn(comment(user("alice"), T1, "@bob 見て")))
        lines = self.render(prs=[called], who="bob")
        i = lines.index("    https://example.invalid/pull/1")
        self.assertTrue(lines[i - 1].startswith("  #1 "))
        self.assertEqual(lines[i + 1], "    作者: alice")
        received = pr(number=2, assignees=conn(user("bob")), comments=conn(comment(user("alice"), T1, "@bob 見て")))
        lines = self.render(prs=[received], who="bob")
        heads = [n for n, line in enumerate(lines) if line.startswith("  #2 ") and "から" in line]
        self.assertEqual(lines[heads[0] + 2], "    担当として受けた PR（起票は alice）")
        # issue に PR の役割は無い。URL の次はすぐ呼びかけの抜粋
        asked = issue(number=3, comments=[(user("alice"), T1, "@bob 見て")])
        lines = self.render(issues=[asked], who="bob")
        self.assertTrue(self.line_after(lines, "    https://example.invalid/issues/3").startswith("         alice: 「"))

    def test_all_mode_keeps_the_url_under_each_row(self):
        lines = self.render(prs=[pr(number=1, reviewRequests=requests(user("bob")))],
                            args=("--all",))
        self.assertEqual(
            self.line_after(lines, "    #1 "), "      https://example.invalid/pull/1"
        )

class Json(unittest.TestCase):
    """--json は「自分の番」のセクションと同じ集合・同じ順を、機械が読む形で出す（works の dispatch が読む）"""

    def test_json_lists_my_turn_prs_with_head_and_role(self):
        mine = pr(number=7, title="直す", headRefName="feat/7", author=user("bob"), isDraft=True)
        theirs = pr(number=8, headRefName="feat/8", author=user("bob"),
                    reviewRequests=requests(user("alice")))
        out = json.loads(report(mine, theirs, who="bob", args=("--json",)))
        self.assertEqual(out["schema"], 1)
        self.assertEqual(out["repo"], "o/n")
        self.assertEqual(out["login"], "bob")
        self.assertEqual([p["number"] for p in out["prs"]], [7])
        got = out["prs"][0]
        self.assertEqual(got["head"], "feat/7")
        self.assertEqual(got["role"], "implementer")
        self.assertEqual(got["title"], "直す")
        self.assertEqual(got["url"], "https://example.invalid/pull/7")
        self.assertIsInstance(got["days"], int)

    def test_json_role_is_reviewer_for_others_pr(self):
        p = pr(number=9, author=user("alice"), reviewRequests=requests(user("bob")))
        out = json.loads(report(p, who="bob", args=("--json",)))
        self.assertEqual([(x["number"], x["role"]) for x in out["prs"]], [(9, "reviewer")])

    def test_json_role_follows_who_holds_the_pr(self):
        """担当として受けた人は直す側（implementer）、担当に渡した作者は直す側ではない"""
        p = pr(number=9, assignees=conn(user("bob")), reviewThreads=conn(thread(comment(user("bob"), T1, "これで合っていますか"))))
        bob = json.loads(report(p, who="bob", args=("--json",)))
        self.assertEqual([x["role"] for x in bob["prs"]], ["implementer"])
        self.assertEqual([x["role"] for x in bob["sections"][0]["mine"]], ["implementer"])
        alice = json.loads(report(p, who="alice", args=("--json",)))
        self.assertEqual([(x["number"], x["role"]) for x in alice["prs"]], [(9, "reviewer")])

    def test_json_matches_text_report_set_and_order(self):
        prs = [pr(number=n, author=user("bob"), isDraft=True, createdAt=t)
               for n, t in ((3, T2), (4, T0), (5, T1))]
        text = report(*prs, who="bob")
        head = text.partition("## 相手の番")[0]
        order = [int(m) for m in re.findall(r"^  #(\d+)", head, re.M)]
        out = json.loads(report(*prs, who="bob", args=("--json",)))
        self.assertEqual([x["number"] for x in out["prs"]], order)

    def test_json_lists_limited_prs_even_outside_my_turn(self):
        # 上限に当たった PR は、自分の番かの判定が取りこぼしの上に立っている。prs に無くても番号で引けるように出す
        cut = pr(number=11, author=user("alice"), reviews=conn(total=70))
        whole = pr(number=12, author=user("bob"), isDraft=True)
        out = json.loads(report(cut, whole, who="bob", args=("--json",)))
        self.assertEqual(out["schema"], 1)
        self.assertEqual(out["limited"], [11])
        self.assertEqual([p["number"] for p in out["prs"]], [12])

    def test_json_limited_counts_a_full_timeline_as_cut(self):
        # 履歴は last: 100 で取る。100 件ちょうどなら古い方（レビュー依頼など）が切れている恐れがある
        full = pr(number=13, author=user("alice"),
                  timelineItems=conn(*([event("ConvertToDraftEvent", T0)] * flow.TIMELINE_LAST)))
        short = pr(number=14, author=user("alice"),
                   timelineItems=conn(*([event("ConvertToDraftEvent", T0)] * (flow.TIMELINE_LAST - 1))))
        out = json.loads(report(full, short, who="bob", args=("--json",)))
        self.assertEqual(out["limited"], [13])

    def test_json_limited_ignores_reaction_limits(self):
        # リアクションは呼びかけの一覧にだけ効き、ターンの判定には効かないので、取り切れなくても入れない
        ask = comment(user("alice"), T1, body="@bob 見てほしい")
        p = pr(number=15, author=user("alice"), comments=conn(ask))
        cut = {"data": {"nodes": [{"id": ask["id"], "reactions": {"totalCount": 60, "nodes": []}}]}}
        buf = io.StringIO()
        with (
            mock.patch.object(flow, "fetch_all", lambda _q, _o, _n, field, optional=(): [p] if field == "pullRequests" else []),
            mock.patch.object(flow, "gh", lambda *_a, **_kw: json.dumps(cut)),
            contextlib.redirect_stdout(buf),
        ):
            flow.main(["bob", "--repo", "o/n", "--json"])
        self.assertEqual(json.loads(buf.getvalue())["limited"], [])
        text = report(p, who="bob")  # 報告の「走査の上限」には今までどおり出る（偽の gh が空を返す回は出ない）
        self.assertIn("走査の上限に当たったもの", text)

    def test_json_limited_is_empty_when_nothing_was_cut(self):
        out = json.loads(report(pr(number=7, author=user("bob"), isDraft=True), who="bob", args=("--json",)))
        self.assertEqual(out["limited"], [])

    def test_json_sections_match_the_text_report(self):
        # スキルは文の報告ではなく --json の鍵で読む。人ごとのセクションの集合と並びは文の報告と同じ
        prs = [pr(number=n, author=user("bob"), isDraft=True, createdAt=t)
               for n, t in ((3, T2), (4, T0), (5, T1))]
        theirs = pr(number=6, author=user("alice"), reviewThreads=conn(thread(comment(user("bob"), T2))))
        text = report(*prs, theirs, who="bob")
        mine_text, _, rest = text.partition("## 相手の番")
        out = json.loads(report(*prs, theirs, who="bob", args=("--json",)))
        (me,) = out["sections"]
        self.assertEqual(me["who"], "bob")
        self.assertEqual([x["number"] for x in me["mine"]], [int(m) for m in re.findall(r"^  #(\d+)", mine_text, re.M)])
        self.assertEqual([x["number"] for x in me["theirs"]], [6])
        self.assertEqual([x["number"] for x in out["prs"]], [x["number"] for x in me["mine"]])
        self.assertEqual(me["theirs"][0]["url"], "https://example.invalid/pull/6")
        self.assertEqual((me["theirs"][0]["author"], me["theirs"][0]["role"]), ("alice", "reviewer"))
        self.assertEqual(out["scope"], {"open_prs": 4, "open_issues": 0, "unassigned_issues": 0})

    def test_json_carries_intro_and_size_only_for_others_pr_in_my_turn(self):
        p = pr(number=9, author=user("alice"), reviewRequests=requests(user("bob")),
               body="直す。続き。", changedFiles=3, additions=10, deletions=2)
        (me,) = json.loads(report(p, who="bob", args=("--json",)))["sections"]
        self.assertEqual(me["mine"][0]["intro"], "直す。")
        self.assertEqual(me["mine"][0]["size"], {"files": 3, "additions": 10, "deletions": 2})
        own = pr(number=10, author=user("bob"), isDraft=True)
        (me,) = json.loads(report(own, who="bob", args=("--json",)))["sections"]
        self.assertNotIn("intro", me["mine"][0])

    def test_json_waits_issues_and_blind_spots(self):
        called = issue(number=3, comments=[(user("alice"), T1, "@bob 見て")])
        assigned = issue(number=4, assignees=["bob"])
        out = json.loads(report(issues=[called, assigned], who="bob", args=("--json",)))
        (w,) = out["waits"]
        self.assertEqual((w["who"], w["kind"], w["number"], w["by"]), ("bob", "issue", 3, "alice"))
        self.assertEqual(w["url"], "https://example.invalid/issues/3")
        self.assertNotIn("text", w)  # 全文は --materials のときだけ
        self.assertEqual([i["number"] for i in out["assigned_issues"]], [4])
        self.assertEqual(out["blind_spots"], {"team_review_requests": 0, "unverified_replies": []})
        self.assertIn("見ていないもの:", out["not_seen"])
        self.assertEqual(out["limits"], [])

    def test_json_waits_carry_the_role_of_a_pr(self):
        called = issue(number=3, comments=[(user("alice"), T1, "@bob 見て")])
        mine = pr(number=5, assignees=conn(user("bob")), comments=conn(comment(user("alice"), T1, "@bob 見て")))
        theirs = pr(number=6, comments=conn(comment(user("alice"), T1, "@bob 見て")))
        out = json.loads(report(mine, theirs, issues=[called], who="bob", args=("--json",)))
        self.assertEqual({w["number"]: w["role"] for w in out["waits"]}, {3: None, 5: "implementer", 6: "reviewer"})

    def test_json_a_draft_mention_without_a_request_stays_a_wait(self):
        # draft・依頼なしで呼ばれただけの人は、機械のセクションには出ない（中身がレビューの頼みかは AI が決め、
        # reply.md の「呼びかけから」の行で自分の番に立てる）。呼びかけには残り、draft へ戻す前かを添える
        ask = comment(user("alice"), T2, "@bob 設計書のレビューをお願いします")
        fresh = pr(number=5, isDraft=True, comments=conn(ask))
        stale = pr(number=6, isDraft=True, comments=conn(comment(user("alice"), T1, "@bob 見て")),
                   timelineItems=conn(event("ConvertToDraftEvent", T2)))
        out = json.loads(report(fresh, stale, who="bob", args=("--json",)))
        (me,) = out["sections"]
        self.assertEqual((me["mine"], me["theirs"]), ([], []))
        self.assertEqual({w["number"]: w["before_draft"] for w in out["waits"]}, {5: False, 6: True})
        self.assertIn("draft へ戻す前", report(fresh, stale, who="bob"))

    def test_json_a_mention_typed_in_other_case_is_a_wait_for_that_person(self):
        # @Bob は bob の呼びかけ。出力の login は GitHub の綴り（bob）で、打たれた綴り（Bob）にしない
        called = pr(number=5, comments=conn(comment(user("alice"), T1, "@Bob 見て"), comment(user("bob"), T0, "先に")))
        out = json.loads(report(called, who="bob", args=("--json",)))
        self.assertEqual([(w["number"], w["who"]) for w in out["waits"]], [(5, "bob")])

    def test_json_a_mention_after_going_back_to_draft_keeps_one_spelling(self):
        # bob は戻す前に発言し、戻した後に @Bob と呼ばれた。戻した後の発言だけを見る回でも bob の 1 人にする
        back = event("ConvertToDraftEvent", T1)
        p = pr(number=5, isDraft=True, timelineItems=conn(back),
               comments=conn(comment(user("bob"), T0, "先に"),
                             comment(user("alice"), T2, "@Bob 設計書のレビューをお願いします")))
        out = json.loads(report(p, who="bob", args=("--json",)))
        self.assertEqual([(w["number"], w["who"]) for w in out["waits"]], [(5, "bob")])

    def test_a_mention_after_going_back_to_draft_keeps_the_reply_to_own_flag(self):
        # bob の指摘 → draft へ戻す → alice が @bob と返す。直前は bob の発言なので reply_to_own は真のまま
        back = event("ConvertToDraftEvent", T1)
        p = pr(number=5, isDraft=True, timelineItems=conn(back),
               comments=conn(comment(user("bob"), T0, "ここを直して"),
                             comment(user("alice"), T2, "@bob 直しました。もう一度見て")))
        self.assertTrue(flow.pr_unanswered(p)["bob"]["reply_to_own"])

    def test_json_a_mention_of_the_silent_author_uses_the_authors_spelling(self):
        # 作者 carol は発言していない。@Carol は作者への呼びかけで、別の人（レビュアー）にしない
        p = pr(number=5, author=user("carol"), comments=conn(comment(user("alice"), T1, "@Carol これは準備できた？")))
        out = json.loads(report(p, who="carol", args=("--json", "--all")))
        self.assertEqual([(w["number"], w["who"]) for w in out["waits"]], [(5, "carol")])

    def test_json_a_mention_after_going_back_to_draft_is_not_set_aside(self):
        # ready → draft へ戻す → 呼びかけ: 戻した後の頼み。戻す前の呼びかけが残っていても、後の頼みを材料にする
        back = event("ConvertToDraftEvent", T1)
        later = pr(number=5, isDraft=True, timelineItems=conn(back),
                   comments=conn(comment(user("alice"), T2, "@bob 設計書のレビューをお願いします")))
        both = pr(number=6, isDraft=True, timelineItems=conn(back),
                  comments=conn(comment(user("alice"), T0, "@bob 見て"),
                                comment(user("alice"), T3, "@bob 設計書のレビューをお願いします")))
        out = json.loads(report(later, both, who="bob", args=("--json", "--materials")))
        self.assertEqual({w["number"]: (w["before_draft"], w["since"]) for w in out["waits"]},
                         {5: (False, T2), 6: (False, T3)})
        self.assertIn("設計書", [w for w in out["waits"] if w["number"] == 6][0]["text"])

    def test_json_a_draft_request_is_the_reviewers_turn(self):
        # 実測 #2233 の形: 最初から draft で Team と持ち主へ依頼。依頼された人の自分の番で、Team は死角の確認へ渡す
        p = pr(number=7, isDraft=True, reviewRequests=requests(team("o/t"), user("bob")),
               timelineItems=conn(requested(team("o/t"), T1), requested(user("bob"), T2)))
        out = json.loads(report(p, who="bob", args=("--json",)))
        self.assertEqual([x["number"] for x in out["prs"]], [7])
        self.assertEqual(out["prs"][0]["role"], "reviewer")
        self.assertEqual(out["blind_spots"]["team_review_requests"], 1)
        self.assertIn("レビュー依頼: bob, o/t", out["sections"][0]["mine"][0]["facts"])

    def test_json_requests_before_going_back_to_draft_are_set_aside(self):
        p = pr(number=8, isDraft=True, reviewRequests=requests(team("o/t"), user("bob")),
               timelineItems=conn(requested(team("o/t"), T1), requested(user("bob"), T1),
                                  event("ConvertToDraftEvent", T2)))
        out = json.loads(report(p, who="bob", args=("--json",)))
        self.assertEqual(out["prs"], [])
        self.assertEqual(out["sections"][0]["theirs"], [])
        self.assertEqual(out["blind_spots"]["team_review_requests"], 0)
        facts = flow.pr_facts(p)
        self.assertIn("draft へ戻す前のレビュー依頼（作者が ready にするまで数えない）: bob, o/t", facts)
        self.assertEqual(sum("bob" in f for f in facts), 1)  # 数える依頼の行には出ない

    def test_a_cut_timeline_of_a_draft_is_named_in_limits(self):
        # draft では戻した時で依頼を数えるかが変わる。履歴が切れていれば文の上限の行にも出す（draft でなければ limited だけ）
        draft = pr(number=9, isDraft=True, timelineItems=full_history())
        ready = pr(number=10, timelineItems=full_history())
        out = json.loads(report(draft, ready, who="bob", args=("--json",)))
        self.assertEqual(out["limited"], [9, 10])
        (line,) = out["limits"]
        self.assertTrue(line.startswith("#9:"), line)

    def test_json_with_materials_carries_full_texts(self):
        called = issue(number=3, comments=[(user("alice"), T1, "@bob 見て。全文")])
        p = pr(reviewThreads=conn(thread(comment(user("bob"), T1, "ここ"), comment(user("alice"), T2, "直しました"),
                                         path="a.py", line=7)))
        out = json.loads(report(p, issues=[called], who="bob", args=("--json", "--materials")))
        self.assertIn("全文", out["waits"][0]["text"])
        (t,) = out["threads"]
        self.assertEqual((t["who"], t["number"], t["path"], t["line"], t["author"]), ("bob", 1, "a.py", 7, "alice"))
        self.assertIn("直しました", t["text"])
        self.assertNotIn(flow.MATERIALS_MARK, json.dumps(out, ensure_ascii=False))

    def test_json_all_lists_everyone(self):
        p = pr(number=1, author=user("alice"), reviewRequests=requests(user("bob")))
        out = json.loads(report(p, who="bob", args=("--json", "--all")))
        self.assertTrue(out["all"])
        self.assertEqual(sorted(x["who"] for x in out["sections"]), ["alice", "bob"])

    def test_json_goes_to_a_file_with_out(self):
        buf = io.StringIO()
        with (
            mock.patch.object(flow, "fetch_all", lambda _q, _o, _n, field, optional=(): [pr(number=1)] if field == "pullRequests" else []),
            mock.patch.object(flow, "gh", lambda *_a, **_kw: json.dumps({"data": {"nodes": []}})),
            contextlib.redirect_stdout(buf),
        ):
            flow.main(["bob", "--repo", "o/n", "--json", "--out"])
        path = re.search(r"報告は (\S+) に書いた", buf.getvalue()).group(1)
        try:
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["schema"], 1)
        finally:
            os.unlink(path)

class AgreesWithCatchup(unittest.TestCase):
    """依頼が残っていない PR で、依頼先を決めるターンの持ち主と種別を、/catchup と同じに出す（受付 e199f8）。
    同じ材料を両方の形に直して当てる。/catchup は人ごとの最新のレビュー（latestReviews）と依頼の出来事だけの窓
    （requestEvents）を読み、/whose-turn は reviews と timelineItems を読む"""

    KINDS = ("rerequest", "review_requested", "unrequested")

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("catchup", ROOT / "attention" / "scripts" / "catchup.py")
        cls.catchup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.catchup)

    def as_catchup(self, p):
        latest = {}
        for r in sorted(p["reviews"]["nodes"], key=lambda r: r["submittedAt"] or ""):
            latest[flow.login(r["author"])] = r
        events = [e for e in p["timelineItems"]["nodes"] if e["__typename"] == "ReviewRequestedEvent"]
        return dict(p, __typename="PullRequest", mergeable="MERGEABLE",
                    latestReviews=conn(*latest.values()), requestEvents=conn(*events))

    def both(self, p):
        whose = {who: kind for who, kind, _ in flow.pr_balls(p) if kind in self.KINDS}
        node = self.as_catchup(p)
        kinds, _ = self.catchup.formal_state(node)
        held = {who: kind for who, kind in kinds.items() if kind in self.KINDS}
        # 理由の表で、担当の印でない理由（ターンの根拠）を持つ人も同じ
        table = self.catchup.reason_table(node, False)
        owes = {who for who, rs in table.items() if any(r != self.catchup.ASSIGNED for r in rs)}
        return whose, held, owes

    def test_the_owner_is_the_same_on_both(self):
        carol_review = conn(review(user("carol"), "COMMENTED", T2))
        asked_carol = conn(requested(user("carol"), T1))
        for name, kw, want in (
            # 受付 e199f8 の例: 作者 alice・担当 bob・依頼は無し・carol のコメントのレビューが 1 件
            ("handed_reviewed", dict(assignees=conn(user("bob")), reviews=carol_review), {"bob": "rerequest"}),
            ("handed_asked", dict(assignees=conn(user("bob")), timelineItems=asked_carol),
             {"bob": "review_requested"}),
            ("handed_both", dict(assignees=conn(user("bob")), reviews=carol_review, timelineItems=asked_carol),
             {"bob": "rerequest"}),
            ("handed_own_review", dict(assignees=conn(user("bob")), reviews=conn(review(user("bob"), "COMMENTED", T2))),
             {"bob": "unrequested"}),
            ("handed_two", dict(assignees=conn(user("bob"), user("dave")), reviews=carol_review),
             {"bob": "rerequest", "dave": "rerequest"}),
            ("kept", dict(reviews=carol_review), {"alice": "rerequest"}),
            ("co_assigned", dict(assignees=conn(user("alice"), user("bob")), timelineItems=asked_carol),
             {"alice": "review_requested"}),
            ("bot_assigned", dict(assignees=conn(bot("Copilot")), reviews=carol_review), {"alice": "rerequest"}),
            ("bot_review", dict(assignees=conn(user("bob")), reviews=conn(review(bot(), "COMMENTED", T2))),
             {"bob": "unrequested"}),
            ("legacy", dict(assignees=conn({"login": "bob"}), reviews=carol_review, assigneeKindsUnknown=True),
             {"alice": "rerequest"}),
        ):
            with self.subTest(name):
                whose, held, owes = self.both(pr(**kw))
                self.assertEqual(whose, want)
                self.assertEqual(held, want)
                self.assertEqual(owes, set(want))


if __name__ == "__main__":
    unittest.main(verbosity=1)
