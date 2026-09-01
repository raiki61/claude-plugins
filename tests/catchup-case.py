#!/usr/bin/env python3
"""catchup.py の判定を、GitHub に触らず固定の材料で回す。

網に載せるのは「材料 → 出力」の規則だけ。取得（gh / GraphQL）は対象外で、ここで
モックしても検査になるのは自分で書いたモックの方になる。"""

import datetime as dt
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "catchup", ROOT / "attention" / "scripts" / "catchup.py")
catchup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catchup)

ME = "me"


def user(login, bot=False):
    return {"__typename": "Bot" if bot else "User", "login": login}


def comment(t, login, body):
    return {"createdAt": t, "body": body, "author": user(login)}


def conn(nodes, total=None):
    return {"totalCount": len(nodes) if total is None else total, "nodes": nodes}


def pr(**over):
    node = {
        "__typename": "PullRequest",
        "number": 1, "title": "テスト用の PR", "url": "https://example.invalid/pull/1",
        "state": "OPEN", "isDraft": False, "createdAt": "2026-09-01T00:00:00Z",
        "body": "", "additions": 10, "deletions": 2, "changedFiles": 3,
        "mergeable": "MERGEABLE", "reviewDecision": "REVIEW_REQUIRED",
        "author": user("other"),
        "assignees": conn([]),
        "reviewRequests": conn([]),
        "closingIssuesReferences": conn([]),
        "comments": conn([]),
        "reviews": conn([]),
        "reviewThreads": conn([]),
        "allCommits": conn([]),
        "head": {"nodes": []},
        "timelineItems": conn([]),
    }
    node.update(over)
    return node


def checks(*contexts):
    return {"nodes": [{"commit": {"statusCheckRollup": {
        "contexts": conn(list(contexts))}}}]}


def check_run(name, conclusion, status="COMPLETED"):
    return {"__typename": "CheckRun", "name": name,
            "conclusion": conclusion, "status": status}


def thread(path, resolved, *comments):
    return {"isResolved": resolved, "path": path, "line": 10,
            "comments": conn(list(comments))}


def review_requested(t, actor, to):
    return {"__typename": "ReviewRequestedEvent", "createdAt": t,
            "actor": {"login": actor},
            "requestedReviewer": {"__typename": "User", "login": to}}


def render(node, full=False):
    ev = catchup.collect_events(node, ME)
    anchor, kind = catchup.find_anchor(ev, node, ME)
    return catchup.render(node, ME, ev, anchor, kind, full, 12,
                          catchup.collect_caps(node))


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("mine")
def _mine():
    """自分が最後に発言していれば、そこが基準点になり、その後の依頼が別枠で出る。"""
    return render(pr(comments=conn([
        comment("2026-09-01T01:00:00Z", ME, "レビュー結果です。block が 1 件あります"),
        comment("2026-09-01T02:00:00Z", "other", "@me 直しました。再確認をお願いします"),
    ])))


@case("ask-before-handover")
def _ask_before_handover():
    """依頼の本文が「渡された時点」より前でも拾う（基準点で切ると丸ごと消えた）。"""
    return render(pr(
        comments=conn([comment("2026-09-01T01:00:00Z", "other",
                               "@me 人にしか判断できない 3 点を見てください")]),
        timelineItems=conn([review_requested("2026-09-01T02:00:00Z", "other", ME)]),
        reviewRequests=conn([{"requestedReviewer": user(ME)}]),
    ))


@case("ask-prefers-text")
def _ask_prefers_text():
    """本文の依頼を、中身の無いレビュー依頼ボタンより優先する。"""
    return render(pr(
        comments=conn([comment("2026-09-01T01:00:00Z", "other",
                               "@me この一文だけ見てください")]),
        timelineItems=conn([review_requested("2026-09-01T02:00:00Z", "other", ME)]),
    ))


@case("waiting")
def _waiting():
    """依頼も担当も無ければ私の番ではない。誰待ちかを出す。"""
    return render(pr(reviewRequests=conn([{"requestedReviewer": user("someone")}])))


@case("ci-unknown-conclusion")
def _ci_unknown():
    """知らない conclusion は赤に倒す。作者が自分なら私の番の理由になる。"""
    return render(pr(author=user(ME), head=checks(
        check_run("lint", "SUCCESS"), check_run("deploy", "ACTION_REQUIRED"))))


@case("ci-running")
def _ci_running():
    """走っている最中は赤でも緑でもない。"""
    return render(pr(head=checks(check_run("build", None, status="IN_PROGRESS"))))


@case("pending-review")
def _pending():
    """未送信のレビューは相手に届いていない。時系列に混ぜず、自分の宿題として出す。"""
    return render(pr(reviews=conn([
        {"submittedAt": None, "state": "PENDING", "body": "書きかけの本文",
         "author": user(ME)}])))


@case("thread-turn")
def _thread_turn():
    """自分が入っている未解決スレッドに相手が返していれば、それが依頼にあたる。"""
    return render(pr(reviewThreads=conn([thread(
        "app/main.py", False,
        comment("2026-09-01T01:00:00Z", ME, "ここは握り潰しになっていませんか"),
        comment("2026-09-01T02:00:00Z", "other", "意図的です。理由は次のとおりで…"))])))


@case("no-checks")
def _no_checks():
    """チェックが 1 本も無い状態を「全 pass」と言わない。"""
    return render(pr())


@case("cap")
def _cap():
    """取得上限に当たったら黙って切らずに申告する。"""
    return render(pr(comments=conn(
        [comment("2026-09-01T01:00:00Z", "other", "本文")], total=140)))


@case("quote-only")
def _quote_only():
    """引用だけの返信を自分の発言として扱わない（抜粋から引用行を落とす）。"""
    return render(pr(comments=conn([
        comment("2026-09-01T01:00:00Z", ME, "> 引用しかない本文")])))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
