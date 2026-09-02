#!/usr/bin/env python3
"""catchup.py の判定を、GitHub に触らず固定の材料で回す。

網に載せるのは「材料 → 出力」の規則だけ。取得（gh / GraphQL）は対象外で、ここで
モックしても検査になるのは自分で書いたモックの方になる。"""

import datetime as dt
import importlib.util
import pathlib
import sys

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の出力が UnicodeEncodeError で落ちる。
# 報告そのものが日本語なので、落ちると道具が丸ごと使えない。UTF-8 に固定する
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "catchup", ROOT / "attention" / "scripts" / "catchup.py")
catchup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catchup)

ME = "me"
T1, T2, T3, T4 = (f"2026-09-01T0{n}:00:00Z" for n in (1, 2, 3, 4))


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


def issue(**over):
    node = {
        "__typename": "Issue",
        "number": 2, "title": "テスト用の issue", "url": "https://example.invalid/issues/2",
        "state": "OPEN", "createdAt": "2026-09-01T00:00:00Z", "body": "",
        "author": user("other"),
        "assignees": conn([]),
        "labels": conn([]),
        "comments": conn([]),
        "timelineItems": conn([]),
    }
    node.update(over)
    return node


def checks(*contexts):
    return {"nodes": [{"commit": {"statusCheckRollup": {
        "contexts": conn(list(contexts))}}}]}


def check_run(name, conclusion, status="COMPLETED", url=""):
    return {"__typename": "CheckRun", "name": name,
            "conclusion": conclusion, "status": status, "detailsUrl": url}


def thread(path, resolved, *comments):
    return {"isResolved": resolved, "path": path, "line": 10,
            "comments": conn(list(comments))}


def review_requested(t, actor, to):
    return {"__typename": "ReviewRequestedEvent", "createdAt": t,
            "actor": {"login": actor},
            "requestedReviewer": {"__typename": "User", "login": to}}


def cross_ref(t, number, title):
    return {"__typename": "CrossReferencedEvent", "createdAt": t,
            "source": {"__typename": "PullRequest", "number": number,
                       "title": title, "state": "OPEN", "url": ""}}


def commit(t, oid, msg, login=None, name="", email=""):
    # GitHub に結び付いていないメールで commit すると user が null になり、名前とメールだけ残る
    return {"commit": {"oid": oid, "committedDate": t, "messageHeadline": msg,
                       "additions": 1, "deletions": 0,
                       "author": {"user": {"login": login} if login else None,
                                  "name": name, "email": email}}}


def render(node, full=False, my_email=""):
    ev, refs, unlinked = catchup.collect_events(node, ME, my_email)
    anchor, kind = catchup.find_anchor(ev, node, ME)
    return catchup.render(node, ME, ev, refs, unlinked, anchor, kind, full, 12,
                          catchup.collect_caps(node))


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("mine")
def _mine():
    """自分が最後に発言していれば、そこが「私が最後にしたこと」になり、その後の依頼が別枠で出る。"""
    return render(pr(comments=conn([
        comment(T1, ME, "レビュー結果です。block が 1 件あります"),
        comment(T2, "other", "@me 直しました。再確認をお願いします"),
    ])))


@case("ask-before-handover")
def _ask_before_handover():
    """依頼の本文が「渡された時点」より前でも拾う（基準で切ると丸ごと消えた）。"""
    return render(pr(
        comments=conn([comment(T1, "other", "@me 人にしか判断できない 3 点を見てください")]),
        timelineItems=conn([review_requested(T2, "other", ME)]),
        reviewRequests=conn([{"requestedReviewer": user(ME)}]),
    ))


@case("ask-prefers-text")
def _ask_prefers_text():
    """本文の依頼を、中身の無いレビュー依頼ボタンより優先する。"""
    return render(pr(
        comments=conn([comment(T1, "other", "@me この一文だけ見てください")]),
        timelineItems=conn([review_requested(T2, "other", ME)]),
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


@case("ci-red-url")
def _ci_red_url():
    """赤いチェックには行き先の URL を添える。理由への道が無いと読む人が探しに行く。"""
    return render(pr(author=user(ME), head=checks(
        check_run("lint", "FAILURE", url="https://example.invalid/runs/1"))))


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
        comment(T1, ME, "ここは握り潰しになっていませんか"),
        comment(T2, "other", "意図的です。理由は次のとおりで…"))])))


@case("no-checks")
def _no_checks():
    """チェックが 1 本も無い状態を「全 pass」と言わない。まだ何もしていない件はそう言う。"""
    return render(pr())


@case("cap")
def _cap():
    """取得上限に当たったら黙って切らず、何を見落としうるかまで申告する。"""
    return render(pr(comments=conn([comment(T1, "other", "本文")], total=140)))


@case("quote-only")
def _quote_only():
    """引用だけの返信を自分の発言として扱わない（抜粋から引用行を落とす）。"""
    return render(pr(comments=conn([comment(T1, ME, "> 引用しかない本文")])))


_UNLINKED_PUSH = pr(
    author=user(ME),
    comments=conn([comment(T1, ME, "対応しました")]),
    allCommits=conn([commit(T2, "abc123456", "指摘を直した",
                            name="me-git", email="me@example.invalid")]),
)


@case("push-alias")
def _push_alias():
    """login に結び付いていない commit でも、手元の git config の user.email と一致すれば自分の push。"""
    return render(_UNLINKED_PUSH, my_email="me@example.invalid")


@case("push-stranger")
def _push_stranger():
    """メールが一致しなければ結び付いていない commit は名前のまま他人として出し、末尾で申告する。
    名前が一致しても照合しない（同名の他人の push を私にしてしまう）。"""
    return render(_UNLINKED_PUSH, my_email="someone-else@example.invalid")


@case("ask-on-my-item-empty")
def _ask_on_my_item_empty():
    """自分の件でも、本文なしの承認と解決済みスレッドの発言は「求められていること」に拾わない。"""
    return render(pr(
        author=user(ME),
        comments=conn([comment(T1, ME, "対応しました")]),
        reviews=conn([{"submittedAt": T2, "state": "APPROVED", "body": "", "author": user("other")}]),
        reviewThreads=conn([thread("app/main.py", True,
                                   comment(T1, "other", "ここ直して"),
                                   comment(T3, "other", "直りましたね"))]),
        reviewRequests=conn([{"requestedReviewer": user("someone")}]),
    ))


@case("own-pr-unrequested")
def _own_pr_unrequested():
    """自分の PR でレビュー依頼が誰にも出ていなければ、渡すのは私（待ちに落とさない）。"""
    return render(pr(author=user(ME)))


@case("mentioned-outsider")
def _mentioned_outsider():
    """作者でもレビュアーでも担当でもなく、発言もしていない人が名指しで呼ばれた件。立場は「未参加」。"""
    return render(pr(comments=conn([comment(T1, "other", "@me ここだけ見てほしい")])))


@case("push-not-cutoff")
def _push_not_cutoff():
    """push は返事ではない。最後の痕跡が push でも、依頼は最後の発言より後から探す。"""
    return render(pr(
        comments=conn([comment(T1, ME, "レビュー結果です"),
                       comment(T2, "other", "@me 再確認をお願いします")]),
        allCommits=conn([commit(T3, "def123456", "直した", login=ME)]),
    ))


@case("ask-on-my-item")
def _ask_on_my_item():
    """自分の件では、名指しの無い発言も最後の 1 件を拾い、名指しが無いことを断る。"""
    return render(pr(
        author=user(ME),
        comments=conn([comment(T1, ME, "対応しました"),
                       comment(T2, "other", "main を取り込むと lint が赤になります。合わせてください")]),
    ))


@case("refs-not-events")
def _refs_not_events():
    """参照（他の PR がこの番号を書いた）は出来事に数えず、つながっている先にだけ置く。"""
    return render(pr(
        comments=conn([comment(T1, ME, "レビュー結果です")]),
        timelineItems=conn([cross_ref(T2, 99, "別の PR")]),
    ))


@case("assignee-own-pr")
def _assignee_own_pr():
    """自分の PR で assignee にもなっているのは普通の運用で、それだけでは私の番にならない
    （レビュー依頼を出していれば相手待ち）。"""
    return render(pr(author=user(ME), assignees=conn([user(ME)]),
                     reviewRequests=conn([{"requestedReviewer": user("someone")}])))


@case("issue-assignee")
def _issue_assignee():
    """issue では担当が手番の根拠。立場も「担当」。"""
    return render(issue(assignees=conn([user(ME)])))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
