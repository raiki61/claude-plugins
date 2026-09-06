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
        "baseRepository": {"defaultBranchRef": {"name": "main"}},
        "baseRefName": "main", "isCrossRepository": False, "baseRef": None,
        "suggestedReviewers": [],
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


def commit(t, oid, msg, login=None, name="", email="", parents=1):
    # GitHub に結び付いていないメールで commit すると user が null になり、名前とメールだけ残る。
    # parents が 2 以上なら取り込み（merge）
    return {"commit": {"oid": oid, "committedDate": t, "messageHeadline": msg,
                       "additions": 1, "deletions": 0, "parents": {"totalCount": parents},
                       "author": {"user": {"login": login} if login else None,
                                  "name": name, "email": email}}}


def render(node, full=False, my_email="", tails=False, stacked=(), since=None):
    """tails=True なら main() と同じ経路（焦点なし）で末尾の材料の有無を決めて渡す。既定の False は
    材料を 1 つも付けない呼び方で、焦点で外したときの文言を見る。stacked / since は main() が取る材料を
    そのまま渡す口。"""
    ev, refs, unlinked = catchup.collect_events(node, ME, my_email)
    anchor, kind = catchup.find_anchor(ev, node, ME)
    flags = {}
    if tails:
        is_pr = node["__typename"] == "PullRequest"
        m, t, c = catchup.pick_tails(is_pr, set(), bool(catchup.unresolved_threads(node, ME)),
                                     bool(catchup.check_state(node)[0]) if is_pr else False)
        flags = {"with_map": m, "with_threads": t, "with_ci": c}
    return catchup.render(node, ME, ev, refs, unlinked, anchor, kind, full, 12,
                          catchup.collect_caps(node), stacked=stacked, since=since, **flags)


def base_pr(number, cross, author="hanako", state="OPEN", decision="REVIEW_REQUIRED"):
    return {"number": number, "title": "下の PR", "state": state, "reviewDecision": decision,
            "isCrossRepository": cross, "author": user(author)}


def assoc(*prs, total=None):
    """baseRef.associatedPullRequests。GraphQL は古い順で、新しい 5 件を取る（last:5）。"""
    return {"name": "feat/x", "associatedPullRequests": conn(list(prs), total=total)}


def anchored(node, get_git=lambda base, head: None, get_gh=lambda sha: None):
    """私の痕跡（find_anchor の mine）を基準に collect_since を回す。経路は差し替え可能。"""
    ev, _, _ = catchup.collect_events(node, ME, "")
    anchor, kind = catchup.find_anchor(ev, node, ME)
    assert kind == "mine", kind
    return catchup.collect_since(node, anchor, get_git, get_gh)


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


@case("issue-not-seen")
def _issue_not_seen():
    """issue の「見ていないもの」に diff を書かない。本文は末尾の材料に出るので、上限で切れた分だけ申告する。"""
    tail = render(issue(assignees=conn([user(ME)]))).split("見ていないもの:")[1]
    long = render(issue(body="\n".join(f"行 {i}" for i in range(1, 100))))
    want = {
        "no_diff": "diff" not in tail and "gh pr" not in tail,
        "no_body_line": "本文" not in tail,
        "cut": "本文の残り 39 行（--full か gh issue view で見る）" in long,
    }
    bad = [k for k, v in want.items() if not v]
    return "ISSUE_UNSEEN_OK" if not bad else "ISSUE_UNSEEN_NG " + ",".join(bad) + "\n" + tail


@case("body-material")
def _body_material():
    """本文の材料: 作者の本文を 60 行まで（--full で全部）、閉じる issue は冒頭 12 行。空ならそう言う。
    行は 1 文字も変えない（引用も HTML コメントも残す）。切れた分は「見ていないもの」に出る。"""
    body = "## 何を\n> 引用も残す\n<!-- コメントも -->\n" + "\n".join(
        f"本文 {i}" for i in range(1, 71)) + "\n\n"
    linked = conn([
        {"number": 5, "title": "困りごと", "state": "OPEN", "url": "",
         "body": "\n".join(f"issue 行 {i}" for i in range(1, 21))},
        {"number": 6, "title": "空の issue", "state": "OPEN", "url": "", "body": ""},
        {"number": 7, "title": "3 つ目", "state": "OPEN", "url": "", "body": "c"},
        {"number": 8, "title": "4 つ目（上限の外）", "state": "OPEN", "url": "", "body": "d"},
    ])
    node = pr(author=user(ME), body=body, closingIssuesReferences=linked)
    out = catchup.render_body(node, full=False)
    full = catchup.render_body(node, full=True)
    empty = catchup.render_body(issue(body="   \n"), full=False)
    seen = render(node)
    want = {
        "count": "=== PR の本文（73 行）" in out,
        "verbatim": "  | > 引用も残す" in out and "  | <!-- コメントも -->" in out,
        "cap": "  | 本文 57" in out and "本文 58" not in out
        and "（本文はあと 13 行。--full か gh pr view で見る）" in out,
        "full": "  | 本文 70" in full and "本文はあと" not in full,
        "issue_head": "=== 閉じる issue #5 困りごと（本文の冒頭 12 行／20 行）" in out
        and "  | issue 行 12" in out and "issue 行 13" not in out
        and "（続きは --full か gh issue view 5 で見る）" in out,
        "issue_cap": "閉じる issue #8" not in out and "（閉じる issue は他に 1 件。--full で全部）" in out,
        "issue_cap_full": "=== 閉じる issue #8 4 つ目（上限の外）" in full and "閉じる issue は他に" not in full,
        "quotes_full": catchup.excerpt("> [!CAUTION]\n> 引用だけ", 0) == "（本文なし）"
        and catchup.excerpt("> [!CAUTION]\n> 引用だけ", 0, keep_quotes=True) == "> [!CAUTION] > 引用だけ",
        "issue_empty": "=== 閉じる issue #6 空の issue（本文なし）" in out,
        "issue_full": "  | issue 行 20" in full and "続きは gh issue view" not in full,
        "empty": "=== issue の本文: （本文なし）" in empty,
        "unseen": "本文の残り 13 行（--full か gh pr view で見る）" in seen
        and "本文と diff" not in seen and "diff の中身（gh pr diff で見る" in seen,
        "unseen_full": "本文の残り" not in render(node, full=True),
    }
    bad = [k for k, v in want.items() if not v]
    return "BODY_OK" if not bad else "BODY_NG " + ",".join(bad) + "\n" + out + "\n" + seen


@case("body-refs")
def _body_refs():
    """本文が # で指す番号の冒頭: 出た順・重複なし・3 件まで。自分と閉じる issue は除き、URL の fragment
    （…/y#42）や word#12 は番号にしない。PR は PR と言う。取れなければそう言う。"""
    body = ("背景は #1078 と #1105。#1 は自分で #5 は閉じる。#1078 は再掲。https://x/y#42 は URL。"
            " word#12 も違う。#2000 と #2001 で 4 件目・5 件目")
    linked = conn([{"number": 5, "title": "閉じる", "state": "OPEN", "url": "", "body": "x"}])
    node = pr(author=user(ME), body=body, closingIssuesReferences=linked)
    asked = []

    def get_ref(n):
        asked.append(n)
        return {1078: {"number": 1078, "title": "困りごと", "body": "\n".join(f"行 {i}" for i in range(1, 21)),
                       "kind": "issue", "state": "open"},
                1105: {"number": 1105, "title": "権限", "body": "a\nb", "kind": "PR", "state": "closed"},
                2000: None}.get(n)

    out = catchup.render_body(node, full=False, get_ref=get_ref)
    want = {
        "order_and_cap": asked == [1078, 1105, 2000],
        "refs": catchup.body_refs(body, 1, {5}) == [1078, 1105, 2000, 2001],
        "issue": "=== 本文が指す issue #1078 困りごと（open。本文の冒頭 12 行／20 行）" in out
        and "  | 行 12" in out and "行 13" not in out and "（続きは --full か gh issue view 1078 で見る）" in out,
        "pr": "=== 本文が指す PR #1105 権限（closed。本文の冒頭 2 行／2 行）" in out and "続きは gh pr view" not in out,
        "missing": "=== 本文が指す #2000: 取れなかった（gh issue view 2000 で見る）" in out,
        "rest": "（本文が指す番号は他に 1 件。--full で全部）" in out,
        "no_fetch_without_hook": "本文が指す" not in catchup.render_body(node, full=False),
    }
    bad = [k for k, v in want.items() if not v]
    return "REFS_OK" if not bad else "REFS_NG " + ",".join(bad) + "\n" + out


@case("split-words")
def _split_words():
    """引数の語を対象と焦点に分ける。焦点だけなら今のブランチ、無ければ今のブランチ。"""
    got = [catchup.split_words(w) for w in (["1569", "指摘"], ["指摘"], [],
                                            ["this", "ci", "地図"], ["https://x/o/r/pull/3"])]
    want = [("1569", {"threads"}), ("this", {"threads"}), ("this", set()),
            ("this", {"ci", "map"}), ("https://x/o/r/pull/3", set())]
    return "SPLIT_OK" if got == want else f"SPLIT_NG {got}"


@case("tails-by-existence")
def _tails_by_existence():
    """末尾の材料は有れば出す——地図は PR なら常に（自分の PR でも）、指摘は人が入っている未解決
    スレッドが有れば、CI は赤が有れば。焦点はその 1 つに絞り、無くても出す。issue には無い。"""
    got = [catchup.pick_tails(*a) for a in (
        (True, set(), False, False),        # 自分の PR に材料が無くても地図は出る
        (True, set(), True, True),          # 指摘と赤が有れば全部
        (True, set(), True, False),         # 指摘だけ有る（CI と取り違えない）
        (True, set(), False, True),         # 赤だけ有る
        (True, {"threads"}, False, False),  # 焦点は絞る。無くても出して「無い」と言わせる
        (True, {"ci", "map"}, True, False),
        (True, {"map"}, True, True),        # 焦点は、有る材料も落とす
        (False, set(), True, True),         # issue には何も無い
        (False, {"map"}, False, False),
    )]
    want = [(True, False, False), (True, True, True), (True, True, False), (True, False, True),
            (False, True, False), (True, False, True), (True, False, False),
            (False, False, False), (False, False, False)]
    return "TAILS_OK" if got == want else f"TAILS_NG {got}"


@case("tails-default-wording")
def _tails_default_wording():
    """焦点なしの既定の「見ていないもの」: 赤なら CI の材料が末尾に付くので「落ちた理由は見ていない」と
    断らず、PR なら地図が付くので「diff の全文（下の地図は…）」と言う。人が入っている未解決スレッドが
    有れば「スレッドの経緯（下の指摘は…）」。焦点で外したときの断り文は出ない。"""
    node = pr(author=user(ME),
              head=checks(check_run("lint", "FAILURE", url="https://example.invalid/runs/1")),
              reviewThreads=conn([thread("app/main.py", False, comment(T1, "other", "[nit] 表記"))]))
    out = render(node, tails=True)
    want = {
        "ci_material_attached": "CI が落ちた理由（上の URL" not in out and "CI を付けて呼ぶと" not in out,
        "map_attached": "diff の全文（下の地図は" in out and "地図 を付けて呼ぶと" not in out,
        "threads_attached": "スレッドの経緯（下の指摘は" in out and "指摘 を付けて呼ぶと" not in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "WORDING_OK" if not bad else "WORDING_NG " + ",".join(bad) + "\n" + out


@case("threads-material")
def _threads_material():
    """指摘の材料: 人が入っている未解決スレッドごとに、相手の最後の発言の全文と head のその行の前後。
    解決済み・私しか発言していないスレッドは出さない。行の無いスレッドはそう言う。"""
    gone = thread("app/gone.py", False, comment(T1, "other", "消えた行の件"))
    gone["line"], gone["isOutdated"] = None, True
    node = pr(author=user(ME), reviewThreads=conn([
        thread("app/main.py", False, comment(T1, "other", "[block] ここは握り潰し\n> 引用は落とす"),
               comment(T2, ME, "直します")),
        thread("app/main.py", False, comment(T1, "other", "[nit] 表記")),
        thread("app/util.py", True, comment(T1, "other", "済み")),
        thread("app/only-me.py", False, comment(T1, ME, "自分が出した指摘")),
        gone,
        thread("app/short.py", False, comment(T1, "other", "短い file の外の行")),
    ]))
    files = {"app/main.py": [f"line {i}" for i in range(1, 30)], "app/short.py": ["a", "b", "c"]}
    out = catchup.render_threads(node, ME, lambda p: files.get(p))
    want = {
        "theirs_turn": "=== 1/4 app/main.py:10  ← 私が最後に発言している（相手の番）" in out,
        "my_turn": "=== 2/4 app/main.py:10  ← 私が返す番 （言語名 python）" in out,
        "body": "[block] ここは握り潰し" in out and "引用は落とす" not in out,
        "window": "|    5 line 5" in out and "|   15 line 15" in out and "line 16" not in out,
        "gone": "=== 3/4 app/gone.py  ←" in out and "今の head に無い" in out,
        "outside": "行 10 は head のファイル（3 行）の外" in out and "|    1 a" not in out,
        "skip": "util.py" not in out and "only-me" not in out,
        "human_count": len(catchup.unresolved_threads(node, ME)) == 4,
    }
    bad = [k for k, v in want.items() if not v]
    return "THREADS_OK" if not bad else "THREADS_NG " + ",".join(bad) + "\n" + out


@case("branch-number")
def _branch_number():
    """ブランチ名の番号は区切りに挟まれた数字だけ。版の数字を番号にせず、1 桁は通す。"""
    got = {b: catchup.branch_number(b) for b in (
        "chore/1513-fold-remainders", "fix/7-typo", "issue-9", "chore/python3.12",
        "renovate/node-20.x", "feat/#1487-standing", "main", "")}
    want = {"chore/1513-fold-remainders": 1513, "fix/7-typo": 7, "issue-9": 9,
            "chore/python3.12": None, "renovate/node-20.x": None, "feat/#1487-standing": 1487,
            "main": None, "": None}
    return "BRANCH_OK" if got == want else f"BRANCH_NG {got}"


@case("branch-line")
def _branch_line():
    """--switch の結果の行は見出しの URL の直下（命令書が「URL は見出しの下の行から写す」で位置に依存する）。
    無ければ何も足さない。"""
    def draw(**flags):
        node = pr()
        ev, refs, unlinked = catchup.collect_events(node, ME, "")
        anchor, kind = catchup.find_anchor(ev, node, ME)
        return catchup.render(node, ME, ev, refs, unlinked, anchor, kind, False, 12,
                              catchup.collect_caps(node), **flags).splitlines()
    with_line = draw(branch_lines=["ブランチ feat/1: main から移った", "    note"])
    without = draw()
    i = with_line.index("  https://example.invalid/pull/1")
    want = {"after_url": with_line[i + 1] == "  ブランチ feat/1: main から移った",
            "note_indented": with_line[i + 2] == "      note",
            "absent": without[without.index("  https://example.invalid/pull/1") + 1] == ""}
    bad = [k for k, v in want.items() if not v]
    return "LINE_OK" if not bad else f"LINE_NG {','.join(bad)}\n" + "\n".join(with_line[:8])


@case("issue-branch")
def _issue_branch():
    """issue の移る先（純関数）。名前に番号を持つ手元の枝が 1 本のときだけ。0 本・2 本以上は理由に候補名。
    版の数字（python3.12）は候補外。PR は head の名前の有無だけなので純関数を持たない。"""
    local = {"feat/12-a": "", "fix/12-b": "", "chore/python3.12": "", "chore/1513-x": "", "main": ""}
    one, two, zero = (catchup.issue_branch(n, local) for n in (1513, 12, 99))
    want = {
        "one": one == ("chore/1513-x", ""),
        "two": two[0] is None and "feat/12-a, fix/12-b" in two[1],
        "zero": zero[0] is None and "#99" in zero[1],
        "version_not_number": catchup.issue_branch(12, {"chore/python3.12": ""})[0] is None,
    }
    bad = [k for k, v in want.items() if not v]
    return "ISSUE_OK" if not bad else f"ISSUE_NG {','.join(bad)} {(one, two, zero)}"


@case("ci-material")
def _ci_material():
    """CI の材料: Actions の run だけログを取り、行頭の job・step・時刻を落として最後の ##[error] まで。
    それ以外の URL はログを取らずに指す。緑は出さない。"""
    node = pr(author=user(ME), head=checks(
        check_run("lint", "FAILURE", url="https://github.com/o/r/actions/runs/11/job/22"),
        check_run("ext", "FAILURE", url="https://ci.example.invalid/x"),
        check_run("ok", "SUCCESS")))
    seen = []

    def run_log(run, job):
        seen.append((run, job))
        rows = [f"lint\tstep\t2026-09-02T00:00:00.0Z L{i}" for i in range(1, 50)]
        rows[40] = "lint\tstep\t2026-09-02T00:00:00.0Z ##[error]Process completed with exit code 1."
        return "\n".join(rows)

    out = catchup.render_ci(node, "o", "r", run_log=run_log)
    want = {
        "called": seen == [("11", "22")],
        "ends_at_error": out.rstrip().splitlines()[-1] != "  | L49"
        and "##[error]Process completed" in out and "L42" not in out,
        "prefix_dropped": "| L40" in out and "2026-09-02T" not in out,
        "tail": "L12" in out and "L11" not in out,
        "external": "=== ext  https://ci.example.invalid/x （言語名 plaintext）" in out and "run ではない" in out,
        "lang": "=== lint  https://github.com/o/r/actions/runs/11/job/22 （言語名 plaintext）" in out,
        "green_hidden": "=== ok" not in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "CI_OK" if not bad else "CI_NG " + ",".join(bad) + "\n" + out


@case("stacked")
def _stacked():
    """取り込み先が既定ブランチでなければ、その枝と枝の PR（同じリポジトリのものだけ。fork の同名の枝は
    出さない）を出す。この枝を base にする open PR（上に積む）は main() が取って渡す。4 件目があれば
    「他にもある」と言う（数は分からない）。"""
    node = pr(author=user(ME), baseRefName="feat/x",
              baseRef=assoc(base_pr(1590, cross=False), base_pr(1591, cross=True, author="forker")))
    out = render(node, stacked=[{"number": 1601, "title": "上の PR"}])
    four = render(node, stacked=[{"number": n, "title": f"PR {n}"} for n in (1601, 1602, 1603, 1604)])
    gone = render(pr(baseRefName="feat/x", baseRef=None))
    none = render(pr(baseRefName="feat/x", baseRef=assoc()))
    # 同じ枝の PR が 4 件（古い→新しい）。新しい順に 3 件で、私のものは「作者 私」。総数 9 なら残りを断る
    many = render(pr(baseRefName="feat/x", baseRef=assoc(
        base_pr(1580, cross=False), base_pr(1585, cross=False, author=ME, state="MERGED", decision=None),
        base_pr(1590, cross=False), base_pr(1595, cross=False), total=9)))
    forks = render(pr(baseRefName="feat/x", baseRef=assoc(base_pr(1591, cross=True), total=748)))
    want = {
        "base": "  取り込み先: feat/x（既定 main ではない）" in out,
        "base_pr": "  その枝の PR: #1590 open・まだ承認されていない（REVIEW_REQUIRED）・作者 hanako" in out,
        "fork_hidden": "#1591" not in out,
        "stacked": "## つながっている先" in out and "  上に積む  #1601 上の PR" in out,
        "fourth": "#1603" in four and "#1604" not in four and "上に積む PR は他にもある" in four,
        "gone": "  取り込み先: feat/x（枝は消えている）" in gone and "その枝の PR" not in gone,
        "none": "  その枝の PR: 無い" in none,
        "newest_first": many.index("#1595") < many.index("#1590") < many.index("#1585"),
        "cap": "#1580" not in many and "  （その枝の PR は他に 6 件。fork の分も含む。gh pr list --head feat/x --state all で見る）" in many,
        "mine": "  その枝の PR: #1585 merged・レビューがまだ 1 件も無い・作者 私" in many,
        "forks_only": "  その枝の PR: 新しい 1 件は fork の同名の枝の分（全 748 件。gh pr list --head feat/x --state all で見る）" in forks,
        "no_section_without": "## つながっている先" not in render(node),
    }
    bad = [k for k, v in want.items() if not v]
    return "STACKED_OK" if not bad else "STACKED_NG " + ",".join(bad) + "\n" + out


@case("stacked-default")
def _stacked_default():
    """取り込み先が既定ブランチなら、取り込み先の行は出ない。"""
    out = render(pr(baseRefName="main", baseRef=dict(assoc(), name="main")))
    return "STACKED_OK" if "取り込み先" not in out and "その枝の PR" not in out else "STACKED_NG\n" + out


@case("suggested")
def _suggested():
    """依頼先の候補（GitHub の suggestedReviewers）は、自分の PR でレビュー依頼が誰にも出ていないときだけ
    出す。根拠（発言あり・commit 者）を添え、空なら「なし」。依頼が出ていれば出さない。"""
    sugg = [{"isAuthor": False, "isCommenter": True, "reviewer": user("enj")},
            {"isAuthor": True, "isCommenter": False, "reviewer": user("pmengelbert")},
            {"isAuthor": True, "isCommenter": True, "reviewer": user("both")},
            {"isAuthor": False, "isCommenter": False, "reviewer": user("plain")}]
    out = render(pr(author=user(ME), suggestedReviewers=sugg))
    empty = render(pr(author=user(ME)))
    hidden = [render(pr(**{"author": user(ME), "suggestedReviewers": sugg, **over})) for over in (
        {"reviewRequests": conn([{"requestedReviewer": user("someone")}])},
        {"isDraft": True}, {"reviewDecision": "CHANGES_REQUESTED"}, {"reviewDecision": "APPROVED"},
        {"author": user("other")})]
    want = {
        "line": "  依頼先の候補（GitHub の提案。決めるのは私）: enj（この PR に発言あり）、"
                "pmengelbert（変更 file の commit 者）、both（発言あり・commit 者）、plain" in out,
        "reason": "レビュー依頼が誰にも出ていない（依頼先を決めるのは私）" in out,
        "empty": "  依頼先の候補（GitHub の提案）: なし" in empty,
        # 依頼あり・下書き・要修正・承認済み・他人の PR では、理由の行も候補の行も出ない
        "hidden": all("依頼先の候補" not in h and "依頼先を決めるのは私" not in h for h in hidden),
    }
    bad = [k for k, v in want.items() if not v]
    return "SUGGESTED_OK" if not bad else "SUGGESTED_NG " + ",".join(bad) + "\n" + out


_SINCE_COMMITS = conn([
    commit(T1, "aaa1111", "最初", login="other"),
    commit(T2, "bbb2222", "レビュー時点", login="other"),
    commit(T3, "ccc3333", "指摘を直した", login="other"),
    commit(T3, "ddd4444", "main を取り込み", login="other", parents=2),
    commit(T4, "eee5555", "もう 1 つ", login="other"),
])
_SINCE_FILES = {
    "ccc3333": "modified\t3\t1\tapp/main.py\nadded\t9\t0\tapp/new.py",
    "eee5555": "removed\t0\t5\tapp/new.py\nrenamed\t0\t0\tapp/util2.py",
}


@case("since-review")
def _since_review():
    """基準がレビュー（commit 付き）なら厳密。その後の作者側の commit だけ file を取り、取り込みは数だけ。
    同じ path は最後の status。gh 経路は commit ごとの TSV を合成し、status を git の 1 文字に寄せる。"""
    node = pr(allCommits=_SINCE_COMMITS,
              reviews=conn([{"submittedAt": T2, "state": "COMMENTED", "body": "見た", "author": user(ME),
                             "commit": {"oid": "bbb2222"}}]))
    asked = []

    def get_gh(sha):
        asked.append(sha)
        return _SINCE_FILES.get(sha)

    since = anchored(node, get_gh=get_gh)
    out = render(node, since=since)
    base, approx = catchup.since_base({"oid": "bbb2222", "t": catchup.ts(T2)}, node)
    # 上限: 1 commit の file が 300 件・作者側 21 本（新しい 20 本だけ取る）・file 21 件（20 行＋ほか 1）
    many = pr(allCommits=conn([commit(T1, "aaa1111", "最初", login="other")]
                              + [commit(T3, f"c{i:07d}", f"c{i}", login="other") for i in range(21)]),
              reviews=conn([{"submittedAt": T2, "state": "COMMENTED", "body": "見た", "author": user(ME),
                             "commit": {"oid": "aaa1111"}}]))
    asked_many = []
    big = "\n".join(f"modified\tf{i}.py" for i in range(300))
    capped = anchored(many, get_gh=lambda sha: asked_many.append(sha) or big)
    capped_out = render(many, since=capped)
    # スレッドの最初の発言と自分の push は厳密（commit 付き）。返信は元の commit を継ぐので近似に落とす
    threaded = pr(allCommits=_SINCE_COMMITS, reviewThreads=conn([thread(
        "app/main.py", False,
        dict(comment(T2, ME, "ここ"), originalCommit={"oid": "bbb2222"}),
        dict(comment(T3, "other", "直した"), originalCommit={"oid": "bbb2222"}),
        dict(comment(T4, ME, "確認した"), originalCommit={"oid": "bbb2222"}))]))
    pushed = pr(allCommits=conn([commit(T1, "aaa1111", "最初", login="other"),
                                 commit(T2, "bbb2222", "私の push", login=ME),
                                 commit(T3, "ccc3333", "続き", login="other")]))
    want = {
        "base": (base, approx) == ("bbb2222", False),
        "commits": catchup.since_commits(node, "bbb2222") == (["ccc3333", "eee5555"], 1, False),
        "asked": asked == ["ccc3333", "eee5555"],
        "cap_commits": capped["skipped"] == 1 and len(asked_many) == 20 and "c0000000" not in asked_many
        and "  - 私の痕跡以降の古い方の commit 1 本の file（上限 20 本）" in capped_out,
        "cap300": capped["cap300"] and "  - 1 commit の file が 300 件で切れている" in capped_out,
        "cap_files": "  …ほか 280 file" in capped_out and "  M  f20.py" not in capped_out
        and "  M  f109.py" in capped_out,
        "thread_reply_approx": anchored(threaded)["approx"] and anchored(threaded)["base"] == "eee5555",
        "thread_first_exact": catchup.since_base({"oid": "bbb2222", "t": catchup.ts(T2)}, threaded) == ("bbb2222", False),
        "push_exact": anchored(pushed)["base"] == "bbb2222" and not anchored(pushed)["approx"],
        "heading": "## 私の痕跡以降に変わった file — 3 件（作者側の commit 2 本。取り込み 1 本の分は含めない）" in out
        and "近似" not in out,
        "files": "  M  app/main.py" in out and "  D  app/new.py" in out and "  R  app/util2.py" in out,
        "position": out.index("## その後に起きたこと") < out.index("## 私の痕跡以降") < out.index("## いまの状態"),
        "git_path": anchored(node, get_git=lambda b, h: [("M", "x.py")])["files"] == [("M", "x.py")],
        "none": "  なし（取り込み 1 本だけ）" in render(node, since=dict(since, files=[], commits=0)),
        "failed": "  （commit 1 本の file は取れなかった。gh api が失敗した）"
        in render(node, since=anchored(node, get_gh=lambda sha: _SINCE_FILES.get(sha) if sha != "eee5555" else None)),
    }
    bad = [k for k, v in want.items() if not v]
    return "SINCE_OK" if not bad else "SINCE_NG " + ",".join(bad) + "\n" + out


@case("since-approx")
def _since_approx():
    """基準が本文コメント（commit 無し）なら、その時刻以前の最新の commit で置く（近似）。見出しと
    「見ていないもの」に近似の断り。発言が最初の commit より前なら基準を置けず、節は出ない。"""
    node = pr(allCommits=_SINCE_COMMITS, comments=conn([comment(T2, ME, "ここまで見た")]))
    since = anchored(node, get_gh=lambda sha: _SINCE_FILES.get(sha))
    out = render(node, since=since)
    early = pr(allCommits=_SINCE_COMMITS, comments=conn([comment("2026-09-01T00:30:00Z", ME, "先に一言")]))
    want = {
        "base": since["base"] == "bbb2222" and since["approx"],
        "heading": "取り込み 1 本の分は含めない）（基準は commit の日付で置いた近似）" in out,
        "unseen": "  - 変わった file の基準は commit の日付で置いた近似。rebase や merge で前後していれば数件ずれる" in out,
        "too_early": anchored(early) is None,
    }
    bad = [k for k, v in want.items() if not v]
    return "SINCE_OK" if not bad else "SINCE_NG " + ",".join(bad) + "\n" + out


@case("since-rewritten")
def _since_rewritten():
    """基準の commit が allCommits に無ければ（rebase / amend）、その 1 行だけ。file は取りに行かない。"""
    node = pr(allCommits=_SINCE_COMMITS, comments=conn([comment(T2, ME, "見た")]),
              reviews=conn([{"submittedAt": T3, "state": "COMMENTED", "body": "再度", "author": user(ME),
                             "commit": {"oid": "0ld0ld0ld"}}]))
    asked = []
    since = anchored(node, get_gh=lambda sha: asked.append(sha))
    out = render(node, since=since)
    sect = out.split("## 私の痕跡以降に変わった file")[1].split("\n\n")[0]
    want = {
        "rewritten": since["rewritten"] and not asked,
        "line": sect.strip() == "基準の commit 0ld0ld0 は今の head の履歴に無い（履歴が書き換えられた）。git range-diff で見る",
        "no_count": "件（作者側" not in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "SINCE_OK" if not bad else "SINCE_NG " + ",".join(bad) + "\n" + out


@case("since-outside")
def _since_outside():
    """allCommits は新しい 100 本しか取らない。基準が窓に無いとき、窓が切れていれば「書き換え」と断定せず
    「取った分より前」と言う（切れていなければ書き換え）。本文コメントが窓の先頭より前でも同じ。"""
    window = conn([commit(T3, f"c{i:07d}", f"c{i}", login="other") for i in range(3)], total=150)
    node = pr(allCommits=window,
              reviews=conn([{"submittedAt": T2, "state": "COMMENTED", "body": "見た", "author": user(ME),
                             "commit": {"oid": "0ld0ld0ld"}}]))
    asked = []
    since = anchored(node, get_gh=lambda sha: asked.append(sha))
    out = render(node, since=since)
    early = anchored(pr(allCommits=window, comments=conn([comment(T2, ME, "先に一言")])))
    early_out = render(node, since=early)
    want = {
        "outside": since["outside"] and not since["rewritten"] and not asked,
        "line": "  基準（0ld0ld0）は取った新しい 3 本より前（commit 150 本中）。履歴の書き換えかどうかは分からず、"
                "古い方の commit は見ていない" in out,
        "no_rewrite_word": "書き換えられた" not in out,
        "early": early["outside"] and "  基準（私の痕跡の時点）は取った新しい 3 本より前（commit 150 本中）" in early_out,
        "unseen_silent": "近似" not in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "SINCE_OK" if not bad else "SINCE_NG " + ",".join(bad) + "\n" + out


_MAP_DIFF = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,4 @@
 def f():
+    y = 2
     return 1
diff --git a/docs/guide.md b/docs/guide.md
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -8,3 +8,4 @@
 # 手順
+足した行
 本文
diff --git a/src/n.py b/src/n.py
new file mode 100644
--- /dev/null
+++ b/src/n.py
@@ -0,0 +1,2 @@
+\"\"\"new one\"\"\"
+def g():
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""


@case("map-jumps")
def _map_jumps():
    """地図の既存ファイルの変更: 各枠の前に「飛び先 path:行」、見出しの括弧に断り。散文（md）も枠で出て、
    新規は先頭の材料の頭に path:1。飛び先が無いのは file ごと削除された file だけ。
    gh と手元の git は差し替えて呼ぶ。"""
    node = pr(number=7, files=conn([
        {"path": "src/a.py", "changeType": "MODIFIED", "additions": 1, "deletions": 0},
        {"path": "docs/guide.md", "changeType": "MODIFIED", "additions": 1, "deletions": 0},
        {"path": "src/n.py", "changeType": "ADDED", "additions": 2, "deletions": 0},
        {"path": "gone.py", "changeType": "DELETED", "additions": 0, "deletions": 2}]))
    saved = (catchup.pr_function_diff, catchup.sibling_dirs, catchup.merged_size_context)
    catchup.pr_function_diff = lambda owner, name, node, get_text: (_MAP_DIFF, "")
    catchup.sibling_dirs = lambda owner, name, paths: None
    catchup.merged_size_context = lambda owner, name: None
    try:
        out = catchup.render_map(node, "o", "r")
    finally:
        catchup.pr_function_diff, catchup.sibling_dirs, catchup.merged_size_context = saved
    want = {
        "jump": "    飛び先 src/a.py:1\n    | def f():" in out,
        "note": "各枠の前の『飛び先 path:行』は head（手元）の行番号" in out,
        "prose_framed": "    飛び先 docs/guide.md:8\n" in out and "    | 足した行" in out
                        and "枠は出さない" not in out,
        "new_jump": "    飛び先 src/n.py:1\n" in out,
        "deleted_no_jump": "飛び先 gone.py" not in out and "削除" in out,
        "lang": "=== src/a.py  (MODIFIED +1/-0) （言語名 python）" in out
                and "=== docs/guide.md  (MODIFIED +1/-0) （言語名 markdown）" in out
                and "=== src/n.py  (" in out and "行) （言語名 python）" in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "MAP_JUMPS_OK" if not bad else "MAP_JUMPS_NG " + ",".join(bad) + "\n" + out


@case("no-target")
def _no_target():
    """PR も番号も無いブランチ（main 等）でも止まらず、手元のブランチだけを出す。GitHub には聞かない
    （gh を呼んだら落ちるスタブで確かめる）。--frame と焦点の語はその旨を書く。"""
    cm = catchup.changemap
    saved = (catchup.current_pr_url, cm.current_branch, catchup.render_local, cm.working_tree,
             cm.frames_section, catchup.ahead_of_default)
    catchup.current_pr_url = lambda: ""            # 今のブランチに PR は無い（gh は通った）
    # 既定ブランチより先の差は実物の git で見るので、このリポジトリの push 状態で結果が変わる。
    # 手元の main が origin より 1 commit 進んでいると frames_section が paths と rev で呼ばれ、
    # 下の未コミット用のスタブ（cwd, dirty, frame_cmd）が TypeError で落ちた（2026-09-06 実測）。
    # この検査が見るのは未コミットの中身の出し方なので、先の差は無い状態に固定する
    catchup.ahead_of_default = lambda cwd=None: []
    cm.current_branch = lambda cwd=None: "main"
    catchup.render_local = lambda **kw: "## 手元のブランチ main（" + kw["why"] + "）\n  未コミット 1 件"
    cm.working_tree = lambda cwd=None: (["src/a.py"], [" work/", "~  src/a.py  +1"])
    seen = {}
    cm.frames_section = lambda cwd, dirty, frame_cmd="--frame": (
        seen.update(dirty=dirty, cmd=frame_cmd) or ["  変更の中身（…）:", "    === src/a.py",
                                                    "    飛び先 src/a.py:1", "    | def f():"])
    try:
        target = catchup.resolve_target("this", None)
        out = catchup.render_no_target()
    finally:
        (catchup.current_pr_url, cm.current_branch, catchup.render_local, cm.working_tree,
         cm.frames_section, catchup.ahead_of_default) = saved
    want = {
        "resolved": target == (None, None, None, "none"),
        "head": out.startswith("# 今のブランチ main（PR も、名前の番号も無い）"),
        "says_github_untouched": "GitHub 側は見ていない——この呼び方で出るのは手元の git だけ" in out,
        "local": "## 手元のブランチ main（this で呼んだので出す）" in out,
        "unseen": "番号か URL を渡せば出る" in out and "what-am-i-doing.py で出る" in out,
        "frames": "    飛び先 src/a.py:1\n    | def f():" in out,   # 木だけでなく中身も出す
        "frame_cmd": seen == {"dirty": ["src/a.py"], "cmd": "what-am-i-doing.py --frame"},
    }
    bad = [k for k, v in want.items() if not v]
    return "NO_TARGET_OK" if not bad else "NO_TARGET_NG " + ",".join(bad) + "\n" + out


@case("range")
def _range():
    """commit の範囲 A..B（A...B は merge-base から）を渡すと、1 commit と同じ形で範囲の差を出す——commit の
    一覧（古い順）・木・変更の中身（枠と飛び先は B の版）。--frame はその 1 file を上限なしで。"""
    cm = catchup.changemap
    saved = (catchup.gh_try, cm.commit_oid, cm.commit_tree, cm.frames_section, cm.git, cm.frame_diff,
             cm.framed_diff, cm.frame_lines, cm.branch_exists)
    catchup.gh_try = lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh を呼んだ"))
    cm.branch_exists = lambda token, cwd=None: False
    oids = {"aaa": "aaaaaaa1", "bbb": "bbbbbbb2", "HEAD": "bbbbbbb2", "aaa^": "0000000a"}
    cm.commit_oid = lambda token, cwd=None: oids.get(token)
    cm.commit_tree = lambda rev, cwd=None: (["src/a.py", "docs/x.md"], [" work/", "~  src/a.py  +1", "~  docs/x.md  +2"])
    calls = []

    def git(*args, cwd=None):
        calls.append(args)
        if args[0] == "log":
            return "bbbbbbb\t2026-09-06\traiki61\t新しい方\naaaaaaa\t2026-09-05\traiki61\t古い方\n"
        if args[0] == "merge-base":
            return "mmmmmmm3\n"
        return ""
    cm.git = git
    seen = {}
    cm.frames_section = lambda cwd, paths, rev="HEAD", frame_cmd="--frame", new_from_file=True, jump_note="": (
        seen.update(rev=rev, cmd=frame_cmd, new_from_file=new_from_file, jump=jump_note)
        or ["  変更の中身（…）:", "    === src/a.py （言語名 python）", "    飛び先 src/a.py:1", "    | def f():"])
    cm.frame_diff = lambda cwd=None, rev="HEAD", paths=(): "diff"
    cm.framed_diff = lambda text: {"src/a.py": {"new": False, "blocks": [["def f():"]], "gaps": [], "starts": [1]}}
    cm.frame_lines = lambda path, info, cap=None, **kw: ["    | def f():"]
    try:
        target = catchup.resolve_target("aaa..bbb", None)
        caret = catchup.resolve_target("aaa^..HEAD", None)
        three = catchup.resolve_target("aaa...bbb", None)
        try:
            catchup.resolve_target("aaa..nope", None)
            refused = ""
        except SystemExit as e:
            refused = str(e)
        out = catchup.render_range("aaaaaaa1..bbbbbbb2")
        one = catchup.render_range("aaaaaaa1..bbbbbbb2", frame="src/a.py")
    finally:
        (catchup.gh_try, cm.commit_oid, cm.commit_tree, cm.frames_section, cm.git, cm.frame_diff,
         cm.framed_diff, cm.frame_lines, cm.branch_exists) = saved
    want = {
        "resolved": target == (None, None, "aaaaaaa1..bbbbbbb2", "range"),
        "caret": caret == (None, None, "0000000a..bbbbbbb2", "range"),
        "merge_base": three == (None, None, "mmmmmmm3..bbbbbbb2", "range"),
        "refused": "両端が手元の commit に解けない" in refused,
        "head": out.startswith("# aaaaaaa..bbbbbbb commit 2 件（aaaaaaa → bbbbbbb。aaaaaaa は範囲の外）\n  2 ファイル · 差は aaaaaaa の版と bbbbbbb の版の間"),
        "no_github": "GitHub 側は見ていない" in out,
        "commits_oldest_first": out.index("| aaaaaaa  2026-09-05  raiki61  古い方") < out.index("| bbbbbbb  2026-09-06  raiki61  新しい方"),
        "tree": "~  docs/x.md  +2" in out,
        "frames": "    飛び先 src/a.py:1" in out,
        "range_and_cmd": seen == {"rev": "aaaaaaa1..bbbbbbb2", "cmd": "catchup.py aaaaaaa..bbbbbbb --frame",
                                  "new_from_file": False, "jump": seen.get("jump")}
        and "commit bbbbbbb の版の行番号（git show bbbbbbb:path で開く）" in seen.get("jump", ""),
        "frame_one": one.startswith("    === src/a.py （") and "| def f():" in one and "）（言語名 python）\n" in one
                     and "commit bbbbbbb の版" in one,
        "unseen": "範囲の外の commit（aaaaaaa より前と bbbbbbb より後）" in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "RANGE_OK" if not bad else "RANGE_NG " + ",".join(bad) + "\n" + out


@case("commit")
def _commit():
    """commit（sha・HEAD~2・タグ・ブランチ名）を渡すと、GitHub に聞かずにその commit を出す——題と
    本文・変更ファイルの木・変更の中身（枠と飛び先）。--frame はその 1 file を上限なしで。"""
    cm = catchup.changemap
    saved = (catchup.gh_try, cm.commit_oid, cm.commit_range, cm.commit_tree, cm.frames_section,
             cm.git, cm.frame_diff, cm.framed_diff, cm.frame_lines, cm.branch_exists)
    catchup.gh_try = lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh を呼んだ"))
    cm.branch_exists = lambda token, cwd=None: token == "feat/x"
    cm.commit_oid = lambda token, cwd=None: "2971ea2f" if token in ("2971ea2", "HEAD~2", "1234567") else None
    cm.commit_range = lambda oid, cwd=None: f"parent..{oid}"
    cm.commit_tree = lambda rev, cwd=None: (["src/a.py"], [" work/", "~  src/a.py  +1"])
    seen = {}
    cm.frames_section = lambda cwd, paths, rev="HEAD", frame_cmd="--frame", new_from_file=True, jump_note="": (
        seen.update(rev=rev, cmd=frame_cmd, new_from_file=new_from_file, jump=jump_note)
        or ["  変更の中身（…）:", "    === src/a.py", "    飛び先 src/a.py:1", "    | def f():"])
    cm.git = lambda *a, cwd=None: "2971ea2\nraiki61\n2026-09-06\n題です\n本文 1 行目\n"
    cm.frame_diff = lambda cwd=None, rev="HEAD", paths=(): "diff"
    cm.framed_diff = lambda text: {"src/a.py": {"new": False, "blocks": [["def f():"]],
                                                "gaps": [], "starts": [1]}}
    cm.frame_lines = lambda path, info, cap=None, **kw: ["    | def f():"]
    try:
        target = catchup.resolve_target("2971ea2", None)
        digits = catchup.resolve_target("1234567", None)   # 数字だけでも 7 桁以上で commit に解ければ commit
        branch = catchup.resolve_target("feat/x", None)     # 枝の名前は commit より先に「移る」対象
        out = catchup.render_commit("2971ea2f")
        one = catchup.render_commit("2971ea2f", frame="src/a.py")
    finally:
        (catchup.gh_try, cm.commit_oid, cm.commit_range, cm.commit_tree, cm.frames_section,
         cm.git, cm.frame_diff, cm.framed_diff, cm.frame_lines, cm.branch_exists) = saved
    want = {
        "resolved": target == (None, None, "2971ea2f", "commit"),
        "digits_sha": digits == (None, None, "2971ea2f", "commit"),
        "branch_name": branch == (None, None, "feat/x", "branchname"),
        "func_span": catchup.func_span(["def f():"] + ["    x"] * 14 + ["def g():"], 5) == (1, 15, True)
        and catchup.func_span(["    a", "    b", "    c"], 2) == (1, 3, False)     # 境目が無い
        and catchup.func_span([f"k{i}: v" for i in range(30)], 15) == (10, 20, False)  # 平らな file は窓
        and catchup.func_span(["x"] + ["    y"] * 300, 150)[2] is False,             # 長すぎる
        "head": out.startswith("# 2971ea2 題です\n  raiki61 · 2026-09-06 · 1 ファイル"),
        "no_github": "GitHub 側は見ていない——手元の git の commit として出す" in out,
        "body": "  | 本文 1 行目" in out,
        "tree": "~  src/a.py  +1" in out,
        "frames": "    飛び先 src/a.py:1" in out,
        "range_and_cmd": seen == {"rev": "parent..2971ea2f", "cmd": "catchup.py 2971ea2 --frame",
                                  "new_from_file": False, "jump": seen.get("jump")}
        and "commit 2971ea2 の版の行番号（git show 2971ea2:path で開く）" in seen.get("jump", ""),
        "frame_jump": "commit 2971ea2 の版の行番号" in one and "head（手元）" not in one,
        "unseen": "範囲は親との差 1 つだけ" in out,
        "frame_one": one.startswith("    === src/a.py （") and "| def f():" in one
                     and "変更の地図" not in one and "）（言語名 python）\n" in one,
    }
    bad = [k for k, v in want.items() if not v]
    return "COMMIT_OK" if not bad else "COMMIT_NG " + ",".join(bad) + "\n" + out


@case("main-wiring")
def _main_wiring():
    """main() の受け口の配線。commit・PR も番号も無い枝（none）で、焦点の断りは人の語（指摘・地図・CI）で
    出て内部 key（threads / map / ci）は出ない、commit の 地図 は出ているので断らない、none の --frame は
    PR か commit に案内して止まる、commit の --switch は移る先が無いと言う。描く関数は差し替えて、配線だけ見る。"""
    import contextlib
    import io
    saved = (catchup.resolve_target, catchup.render_commit, catchup.render_no_target)
    kind = {"local": "commit"}
    catchup.resolve_target = lambda token, repo: (None, None, "oid", kind["local"])
    catchup.render_commit = lambda oid, cwd=None, frame=None, full=False: f"COMMIT full={full} frame={frame}"
    catchup.render_no_target = lambda cwd=None: "NONE"

    def run(argv):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = catchup.main(argv)
        except SystemExit as e:
            return None, str(e)
        return rc, buf.getvalue()
    try:
        rc1, out1 = run(["HEAD", "指摘", "CI"])
        rc2, out2 = run(["HEAD", "地図"])
        rc3, out3 = run(["HEAD", "--switch", "--full"])
        kind["local"] = "none"
        rc4, out4 = run(["this", "地図"])
        rc5, out5 = run(["this", "--frame", "x.py"])
        rc6, out6 = run(["this", "--switch"])
    finally:
        catchup.resolve_target, catchup.render_commit, catchup.render_no_target = saved
    want = {
        "commit_note_in_ja": rc1 == 0 and "（指摘・CI の材料は PR / issue のもの。commit には無い）" in out1
                             and "threads" not in out1 and "COMMIT" in out1,
        "commit_map_no_note": rc2 == 0 and "材料は PR / issue のもの" not in out2,
        "commit_switch_full": rc3 == 0 and "移る先が無い" in out3 and "full=True" in out3,
        "none_note_in_ja": rc4 == 0 and "（地図 の材料は PR / issue のもの。今のブランチには PR が無い）" in out4
                           and "map" not in out4 and "NONE" in out4,
        "none_frame_stops": rc5 is None and "PR か commit" in out5 and "what-am-i-doing.py --frame" in out5,
        "none_switch_note": rc6 == 0 and "ブランチ: this では移らない（今のブランチのまま）" in out6,
    }
    bad = [k for k, v in want.items() if not v]
    return "WIRING_OK" if not bad else "WIRING_NG " + ",".join(bad) + "\n" + out1 + out4 + (out5 or "")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
