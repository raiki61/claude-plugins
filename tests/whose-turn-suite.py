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
        "author": {"login": "alice"},
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
    return p


def requests(*actors):
    return conn(*({"requestedReviewer": a} for a in actors))


class PrBalls(unittest.TestCase):
    def test_draft_is_author_since_converted(self):
        p = pr(isDraft=True, timelineItems=conn(event("ConvertToDraftEvent", T2)))
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
            timelineItems=conn(requested(user("carol"), T3)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "指摘対応", T1), ("carol", "レビュー", T3)]
        )

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
            timelineItems=conn(requested(user("bob"), T2)),
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
            timelineItems=conn(
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
        p = pr(timelineItems=conn(requested(user("bob"), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "レビュー依頼", T2)])

    def test_team_request_counts_as_asking(self):
        p = pr(timelineItems=conn(requested(team(), T2)))
        self.assertEqual(flow.pr_balls(p), [("alice", "レビュー依頼", T2)])

    def test_bot_only_request_history_is_still_never_asked(self):
        # Copilot だけに頼んだ PR は、人から見れば誰にも渡っていない
        p = pr(timelineItems=conn(requested(bot(), T2)))
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
            assignees=conn({"login": "alice"}, {"login": "bob"}),
            timelineItems=conn(assigned("bob", T2)),
        )
        self.assertEqual(
            flow.pr_balls(p), [("alice", "未依頼", T1), ("bob", "担当", T2)]
        )

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

    def test_deleted_author_falls_back_to_the_role_word(self):
        p = pr(
            author=None,
            reviewThreads=conn(thread(comment(user("bob"), T1))),
        )
        self.assertIn("未解決 1 スレッド（作者 が返答 1）", flow.pr_facts(p))

    def test_assignee_fact(self):
        self.assertIn(
            "assignee: bob", flow.pr_facts(pr(assignees=conn({"login": "bob"})))
        )

    def test_author_is_named_only_when_the_reader_is_not_the_author(self):
        self.assertIn("作者: alice", flow.pr_facts(pr(), "bob"))
        self.assertNotIn("作者: alice", flow.pr_facts(pr(), "alice"))
        self.assertIn("作者: 退会済み", flow.pr_facts(pr(author=None), "bob"))

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
        self.assertEqual(flow.answered_threads(p, by_author=True), [("bob", T1, False)])
        self.assertEqual(
            flow.answered_threads(p, by_author=False), [("alice", T2, False)]
        )
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


def report(*prs, issues=(), who="bob", args=()):
    """固定の材料で main を回し、報告の全文を返す。GitHub には触らない"""

    def fetch_all(_query, _owner, _name, field):
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
        """レビュー依頼を押さずに assignee で渡す運用がある。渡っていれば相手の番"""
        handed = pr(
            number=1,
            assignees=conn({"login": "bob"}),
            comments=conn(comment(user("alice"), T3, "扱いはお任せします")),
        )
        self.assertEqual(self.bucket(self.render(handed, who="alice")), "相手の番")

    def test_draft_stays_undelivered_even_with_an_assignee(self):
        """draft は作者が自分で「まだ出さない」と印を付けた状態で、渡したことにはならない"""
        out = self.render(
            pr(number=1, isDraft=True, assignees=conn({"login": "bob"})), who="alice"
        )
        self.assertEqual(self.bucket(out), "自分の番")

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
        self.assertEqual(
            self.line_after(lines, "  #4 "), "    https://example.invalid/issues/4"
        )

    def test_all_mode_keeps_the_url_under_each_row(self):
        lines = self.render(prs=[pr(number=1, reviewRequests=requests(user("bob")))],
                            args=("--all",))
        self.assertEqual(
            self.line_after(lines, "    #1 "), "      https://example.invalid/pull/1"
        )

if __name__ == "__main__":
    unittest.main(verbosity=1)
