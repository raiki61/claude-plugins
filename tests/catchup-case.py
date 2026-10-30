#!/usr/bin/env python3
"""catchup.py の判定を、GitHub に触らず固定の材料で回す。

テストに載せるのは「材料 → 出力」の規則だけ。取得（gh / GraphQL）は対象外で、ここで
モックしても検査になるのは自分で書いたモックの方になる。"""

import importlib.util
import pathlib
import sys

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の出力が UnicodeEncodeError で落ちる。
# 報告そのものが日本語なので、落ちるとツールが丸ごと使えない。UTF-8 に固定する
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
        "latestReviews": conn([]),
        "latestOpinionatedReviews": conn([]),
        "reviewThreads": conn([]),
        "allCommits": conn([]),
        "head": {"nodes": []},
        "requestEvents": conn([]),
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


# QUERY の requestedReviewer は User{login} と Team{name} しか取らないので、Bot 宛は login を持たない
BOT_REVIEWER = {"__typename": "Bot"}


def review(t, login, state="COMMENTED", bot=False):
    return {"submittedAt": None if state == "PENDING" else t, "state": state, "body": "見ました",
            "author": user(login, bot), "commit": {"oid": "abc1234"}}


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


def verdict(tag, want, detail):
    """want の値がどれも真なら「<tag>_OK」、偽が在れば「<tag>_NG <偽の名前,…>」の行に detail を続ける。"""
    bad = [k for k, v in want.items() if not v]
    return tag + "_OK" if not bad else tag + "_NG " + ",".join(bad) + "\n" + detail


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
        requestEvents=conn([review_requested(T2, "other", ME)]),
        reviewRequests=conn([{"requestedReviewer": user(ME)}]),
    ))


@case("ask-prefers-text")
def _ask_prefers_text():
    """本文の依頼を、中身の無いレビュー依頼ボタンより優先する。"""
    return render(pr(
        comments=conn([comment(T1, "other", "@me この一文だけ見てください")]),
        requestEvents=conn([review_requested(T2, "other", ME)]),
    ))


@case("waiting")
def _waiting():
    """依頼も担当も無ければ「私の番」ではない。誰待ちかを出す。"""
    return render(pr(reviewRequests=conn([{"requestedReviewer": user("someone")}])))


@case("ci-unknown-conclusion")
def _ci_unknown():
    """知らない conclusion は赤に倒す。作者が自分なら「私の番」の理由になる。"""
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


@case("thread-turn-rules")
def _thread_turn_rules():
    """スレッドの「私が返すターン」は、1 行目の理由（threads_awaiting）・依頼（find_ask）・指摘の材料（unresolved_threads）で
    同じ式。bot の発言は数えない（私の返事の後に bot が「Thanks!」と書いても相手のターン）。人の PR で私の入っていない
    他の人同士のスレッドは私のターンでない。自分の PR の新しい指摘は私のターン。待つスレッドが 2 つなら新しい返事の方を依頼にする。"""
    bot = comment(T3, "coderabbitai", "Thanks!")
    bot["author"] = user("coderabbitai", bot=True)
    after_bot = pr(reviewThreads=conn([thread("app/a.py", False, comment(T1, "rev", "nit"), comment(T2, ME, "fixed"), bot)]))
    others = pr(reviewThreads=conn([thread("app/b.py", False, comment(T1, "bob", "なぜ？"), comment(T2, "alice", "理由は…"))]))
    own_new = pr(author=user(ME), reviewThreads=conn([thread("app/c.py", False, comment(T1, "rev", "ここ直して"))]))
    two = pr(reviewThreads=conn([
        thread("app/old.py", False, comment(T1, ME, "q1"), comment(T2, "rev", "古い返事")),
        thread("app/new.py", False, comment(T1, ME, "q2"), comment(T4, "rev", "新しい返事"))]))

    def turns(node):
        return [th["my_turn"] for th in catchup.unresolved_threads(node, ME)]
    ev, _, _ = catchup.collect_events(two, ME, "")
    ask = catchup.find_ask(ev, two, ME, None, False)
    want = {
        "bot_last_not_mine": not catchup.threads_awaiting(after_bot, ME) and turns(after_bot) == [False],
        "others_thread_not_mine": turns(others) == [False],
        "own_new_thread_mine": turns(own_new) == [True],
        "newest_ask": bool(ask) and ask["text"] == "新しい返事",
    }
    return verdict("THREAD_RULES", want, str(want) + str(ask))


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
    """自分の PR で assignee にもなっているのは普通の運用で、それだけでは「私の番」にならない
    （レビュー依頼を出していれば相手待ち）。"""
    return render(pr(author=user(ME), assignees=conn([user(ME)]),
                     reviewRequests=conn([{"requestedReviewer": user("someone")}])))


@case("issue-assignee")
def _issue_assignee():
    """issue では担当がターンの根拠。立場も「担当」。"""
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
    return verdict("ISSUE_UNSEEN", want, tail)


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
    return verdict("BODY", want, out + "\n" + seen)


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
    return verdict("REFS", want, out)


@case("split-words")
def _split_words():
    """引数の語を対象と焦点に分ける。焦点だけなら今のブランチ、無ければ今のブランチ。
    焦点は英語の鍵（threads・map・ci）でも、大文字小文字を問わず受ける。"""
    got = [catchup.split_words(w) for w in (["1569", "指摘"], ["指摘"], [],
                                            ["this", "ci", "地図"], ["https://x/o/r/pull/3"],
                                            ["1569", "threads", "Map"], ["CI"])]
    want = [("1569", {"threads"}), ("this", {"threads"}), ("this", set()),
            ("this", {"ci", "map"}), ("https://x/o/r/pull/3", set()),
            ("1569", {"threads", "map"}), ("this", {"ci"})]
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
    return verdict("WORDING", want, out)


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
        "theirs_turn": "=== 1/4 app/main.py:10  ← 私が最後に発言している（相手のターン）" in out,
        "my_turn": "=== 2/4 app/main.py:10  ← 私が返すターン （言語名 python）" in out,
        "body": "[block] ここは握り潰し" in out and "引用は落とす" not in out,
        "window": "|    5 line 5" in out and "|   15 line 15" in out and "line 16" not in out,
        "gone": "=== 3/4 app/gone.py  ←" in out and "今の head に無い" in out,
        "outside": "行 10 は head のファイル（3 行）の外" in out and "|    1 a" not in out,
        "skip": "util.py" not in out and "only-me" not in out,
        "human_count": len(catchup.unresolved_threads(node, ME)) == 4,
    }
    return verdict("THREADS", want, out)


@case("threads-since")
def _threads_since():
    """私が返すターンで相手が私の発言の後に返している件は、私の発言以降のこの file の変更を今の姿に帯で出し（-U0 の
    hunk を head の関数の範囲に重ねる）、今の姿だけの行は重ねない。file が変わっていない・関数が変わっていない・
    diff が取れないはそれぞれそう言う。行の無い指摘は変わった所ごとにその関数。私が未発言の件は今の姿で、共通の
    字下げを落として見出しに桁数を書き、代入の文字列リテラルの中は畳む。字下げのある def も関数の境目。"""
    flat = [f"line {i}" for i in range(1, 30)]
    files = {
        "app/main.py": flat, "app/util.py": flat, "app/other.py": flat, "app/nogit.py": flat,
        "app/deep.py": ["class A:", "    def f(self):"] + [f"        x{i} = {i}" for i in range(12)]
                       + ["", "    def g(self):", "        pass"],
        "app/sql.py": ["def q():", '    query = """', "    INSERT INTO t ("] + [f"        c{i}," for i in range(12)]
                      + ["    ) VALUES (%s)", '    """', "    return query"],
        "app/whole.py": ["def a():", "    return 1", "", "def b():", "    return 2"],
    }

    def diff(path, start, old, new):
        return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
                f"@@ -{start} +{start} @@\n-{old}\n+{new}\n")
    diffs = {
        "app/main.py": diff("app/main.py", 10, "old 10", "line 10"),
        "app/util.py": "",                                              # 変わっていない
        "app/other.py": diff("app/other.py", 25, "old 25", "line 25"),  # 関数（窓 5〜15）の外
        "app/nogit.py": None,                                           # 手元に commit が無い
        "app/whole.py": diff("app/whole.py", 2, "    return 0", "    return 1"),
    }

    def replied(path):
        return thread(path, False, comment(T1, "other", "[block] 直して"), comment(T2, ME, "こう直す"),
                      comment(T3, "other", "直しました"))
    whole = replied("app/whole.py")
    whole["line"] = None
    deep = thread("app/deep.py", False, comment(T1, "other", "[nit] 字下げ"))
    deep["line"] = 5
    sql = thread("app/sql.py", False, comment(T1, "other", "[nit] SQL"))
    sql["line"] = 5
    node = pr(author=user("other"), headRefOid="bbb",
              allCommits=conn([commit(T1, "aaa", "最初"), commit(T3, "bbb", "直した")]),
              reviewThreads=conn([replied("app/main.py"), replied("app/util.py"), replied("app/other.py"),
                                  replied("app/nogit.py"), whole, deep, sql]))
    out = catchup.render_threads(node, ME, lambda p: files.get(p), diff_since=lambda p, b, h: diffs.get(p))
    seg = {blk.split("\n", 1)[0].split()[0]: blk for blk in out.split("=== ")[1:]}   # "n/N" → セクション
    main, util, other, nogit, whole_s, deep_s, sql_s = (seg[f"{i}/7"] for i in range(1, 8))
    want = {
        "framed": f"私の発言（{catchup.hhmm(catchup.ts(T2))}）以降のこの file の変更（作者側の commit 1 本）" in main
                  and "飛び先 app/main.py:5（head の 5〜15 行）" in main
                  and "  | #│ old 10" in main and "  | line 10" in main and "┏━━ 変更" in main,
        "no_plain_when_framed": "（指摘の行の前後 5 行）" not in main and "|   10 line 10" not in main,
        "file_unchanged": "以降、この file は変わっていない（作者側の commit 1 本）" in util and "|   10 line 10" in util,
        "func_unchanged": "この関数は変わっていない（file の他の所に 1 枠。作者側の commit 1 本）" in other
                          and "|   10 line 10" in other,
        "no_diff": "以降の変更: 出せない（手元にこの PR の commit が無い" in nogit and "|   10 line 10" in nogit,
        # 2 行の関数は窓（前後 5 行）より小さいので file 全体（1〜5 行）が範囲。行の無い指摘は変わった所の関数
        "file_level": "飛び先 app/whole.py:1（head の 1〜5 行）" in whole_s and "  | #│  return 0" in whole_s
                      and "  |     return 1" in whole_s and "（指摘の行の前後 5 行）" not in whole_s,
        "dedent": "head の 2〜14 行（指摘の行を含む関数まるごと）（共通の字下げ 4 桁を落とした）" in deep_s
                  and "|    2 def f(self):" in deep_s and "|    5     x2 = 2" in deep_s and "class A:" not in deep_s,
        "literal_fold": "文字列の中 10 行省略" in sql_s and "|    5         c1," in sql_s and "c5," not in sql_s
                        and "|   16     ) VALUES (%s)" in sql_s and "|   18     return query" in sql_s,
        "silent_me_no_since": "私の発言" not in deep_s and "私の発言" not in sql_s,
    }
    return verdict("SINCE", want, out)


@case("threads-since-big")
def _threads_since_big():
    """私の発言以降の変更の最初の枠は、1 枠で上限（THREAD_DIFF_CAP 行）を超えても出す（render_map と同じ）。前は
    何も出さずに「残り 1 枠」だけ言い、枠を出した扱いで今の姿の窓も飛ばしたので、スレッドにコードが 1 行も出なかった。"""
    body = [f"    x{i} = {i}" for i in range(1, 195)]
    files = {"app/big.py": ["def f():"] + body + ["", "def g():", "    pass"]}
    hunks = "".join(f"@@ -{n} +{n} @@\n-    old{n}\n+{files['app/big.py'][n - 1]}\n" for n in (10, 50, 100, 150))
    text = "diff --git a/app/big.py b/app/big.py\n--- a/app/big.py\n+++ b/app/big.py\n" + hunks
    th = thread("app/big.py", False, comment(T1, "other", "[block] 直して"), comment(T2, ME, "こう直す"),
                comment(T3, "other", "直しました"))
    node = pr(author=user("other"), headRefOid="bbb",
              allCommits=conn([commit(T1, "aaa", "最初"), commit(T3, "bbb", "直した")]),
              reviewThreads=conn([th]))
    out = catchup.render_threads(node, ME, lambda p: files.get(p), diff_since=lambda p, b, h: text)
    want = {
        "first_frame": "飛び先 app/big.py:1（head の 1〜195 行" in out and "  | #│  old10" in out,
        "no_rest_note": "残り" not in out,
    }
    return verdict("SINCE_BIG", want, out)


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
    """--switch の結果の行は見出しの URL の直下（コマンドの本文が「URL は見出しの下の行から写す」で位置に依存する）。
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
    """issue の移る先（純関数）。名前に番号を持つ手元のブランチが 1 本のときだけ。0 本・2 本以上は理由に候補名。
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
    return verdict("CI", want, out)


@case("stacked")
def _stacked():
    """取り込み先が既定ブランチでなければ、そのブランチとブランチの PR（同じリポジトリのものだけ。fork の同名のブランチは
    出さない）を出す。このブランチを base にする open PR（上に積む）は main() が取って渡す。4 件目があれば
    「他にもある」と言う（数は分からない）。"""
    node = pr(author=user(ME), baseRefName="feat/x",
              baseRef=assoc(base_pr(1590, cross=False), base_pr(1591, cross=True, author="forker")))
    out = render(node, stacked=[{"number": 1601, "title": "上の PR"}])
    four = render(node, stacked=[{"number": n, "title": f"PR {n}"} for n in (1601, 1602, 1603, 1604)])
    gone = render(pr(baseRefName="feat/x", baseRef=None))
    none = render(pr(baseRefName="feat/x", baseRef=assoc()))
    # 同じブランチの PR が 4 件（古い→新しい）。新しい順に 3 件で、私のものは「作者 私」。総数 9 なら残りを断る
    many = render(pr(baseRefName="feat/x", baseRef=assoc(
        base_pr(1580, cross=False), base_pr(1585, cross=False, author=ME, state="MERGED", decision=None),
        base_pr(1590, cross=False), base_pr(1595, cross=False), total=9)))
    forks = render(pr(baseRefName="feat/x", baseRef=assoc(base_pr(1591, cross=True), total=748)))
    want = {
        "base": "  取り込み先: feat/x（既定 main ではない）" in out,
        "base_pr": "  そのブランチの PR: #1590 open・まだ承認されていない（REVIEW_REQUIRED）・作者 hanako" in out,
        "fork_hidden": "#1591" not in out,
        "stacked": "## つながっている先" in out and "  上に積む  #1601 上の PR" in out,
        "fourth": "#1603" in four and "#1604" not in four and "上に積む PR は他にもある" in four,
        "gone": "  取り込み先: feat/x（ブランチは消えている）" in gone and "そのブランチの PR" not in gone,
        "none": "  そのブランチの PR: 無い" in none,
        "newest_first": many.index("#1595") < many.index("#1590") < many.index("#1585"),
        "cap": "#1580" not in many and "  （そのブランチの PR は他に 6 件。fork の分も含む。gh pr list --head feat/x --state all で見る）" in many,
        "mine": "  そのブランチの PR: #1585 merged・承認・要修正の判定なし（reviewDecision なし——まだ誰もレビューして"
                "いないか、承認の規則が無い base。後者では承認しても付かない）・作者 私" in many,
        "forks_only": "  そのブランチの PR: 新しい 1 件は fork の同名のブランチの分（全 748 件。gh pr list --head feat/x --state all で見る）" in forks,
        "no_section_without": "## つながっている先" not in render(node),
    }
    return verdict("STACKED", want, out)


@case("stacked-default")
def _stacked_default():
    """取り込み先が既定ブランチなら、取り込み先の行は出ない。"""
    out = render(pr(baseRefName="main", baseRef=dict(assoc(), name="main")))
    return "STACKED_OK" if "取り込み先" not in out and "そのブランチの PR" not in out else "STACKED_NG\n" + out


@case("suggested")
def _suggested():
    """依頼先の候補（GitHub の suggestedReviewers）は、持ち主の PR でレビュー依頼が今は誰にも出ておらず、人に依頼した
    ことが無いか、依頼が外れてレビューが付いていないときに出す。根拠（発言あり・commit 者）を添え、空なら「なし」。
    依頼が出ている・依頼した後にレビューが付いた、なら出さない。作者以外の人だけが担当の PR では、
    作者でなく担当の人に出す。"""
    sugg = [{"isAuthor": False, "isCommenter": True, "reviewer": user("enj")},
            {"isAuthor": True, "isCommenter": False, "reviewer": user("pmengelbert")},
            {"isAuthor": True, "isCommenter": True, "reviewer": user("both")},
            {"isAuthor": False, "isCommenter": False, "reviewer": user("plain")}]
    out = render(pr(author=user(ME), suggestedReviewers=sugg))
    empty = render(pr(author=user(ME)))
    asked = conn([review_requested(T1, ME, "rev")])
    hidden = [render(pr(**{"author": user(ME), "suggestedReviewers": sugg, **over})) for over in (
        {"reviewRequests": conn([{"requestedReviewer": user("someone")}])},
        {"isDraft": True}, {"reviewDecision": "CHANGES_REQUESTED"}, {"reviewDecision": "APPROVED"},
        {"author": user("other")},
        # GitHub はレビューを送った人を依頼の一覧から外す（#1901）。依頼した記録があれば渡し済み
        {"latestReviews": conn([review(T1, "rev")]), "requestEvents": asked},
        {"latestReviews": conn([review(T1, "rev")]), "requestEvents": asked, "reviewDecision": None},
        {"assignees": conn([user("rev")])})]
    received = render(pr(author=user("other"), assignees=conn([user(ME)]), suggestedReviewers=sugg))
    want = {
        "line": "  依頼先の候補（GitHub の提案。決めるのは私）: enj（この PR に発言あり）、"
                "pmengelbert（変更 file の commit 者）、both（発言あり・commit 者）、plain" in out,
        "reason": "レビュー依頼が誰にも出ていない（依頼先を決めるのは私）" in out,
        "empty": "  依頼先の候補（GitHub の提案）: なし" in empty,
        # 依頼あり・下書き・要修正・承認済み・他人の PR・依頼後のレビュー・作者以外だけの担当では、理由の行も候補の行も出ない
        "hidden": all("依頼先の候補" not in h and "依頼先を決めるのは私" not in h for h in hidden),
        "received": "  依頼先の候補（GitHub の提案。決めるのは私）: enj" in received,
    }
    return verdict("SUGGESTED", want, out)


@case("formal-state")
def _formal_state():
    """依頼の一覧が空な自分の PR の分け方（rerequest・review_requested・assigned・unrequested）と、reviewDecision が null
    でも意見から導かないこと。再依頼の理由を人宛の依頼の記録の有無で言い分けること、Bot 宛と人宛が混ざった依頼の
    出来事。判定が頼る QUERY の選択と、依頼の出来事の窓が切れたか（件数と hasPreviousPage の両方）の申告と、その
    PR の分け方に添える読み違い（#1901）。"""
    def mine(**over):
        return render(pr(**{"author": user(ME), **over}))

    def events(nodes, prev):
        # prev が None なら pageInfo を持たない材料（無ければ件数だけで切れたと見る）
        return dict(conn(nodes), **({} if prev is None else {"pageInfo": {"hasPreviousPage": prev}}))

    reason = "レビュー依頼が誰にも出ていない（依頼先を決めるのは私）"
    rereq = "作者以外の人のレビューが付き、依頼は残っていない（再依頼か指摘対応は私）"
    norec = "作者以外の人のレビューが付いた。人宛のレビュー依頼を出した記録は無い（依頼先を決めるか指摘対応は私）"
    merge = "承認済みで依頼も残っていない（マージは私）"
    person_ev = review_requested(T1, ME, "rev")
    asked = conn([person_ev])
    rev = conn([review(T1, "rev")])
    team = {"__typename": "Team", "name": "core"}
    bot_req = conn([{"requestedReviewer": BOT_REVIEWER}])
    bot_ev = dict(review_requested(T2, ME, "x"), requestedReviewer=BOT_REVIEWER)
    bot_event = conn([bot_ev])
    # 実物の形は 依頼 → レビュー → 依頼が外れる。古いレビューの窓（reviews）が空でも人ごとの最新から読む
    reviewed = [mine(latestReviews=rev, requestEvents=asked),
                mine(latestReviews=rev, requestEvents=asked, reviewDecision=None)]
    # 人宛の依頼の出来事が無いので、再依頼のターンでも候補は出る
    passerby = [mine(latestReviews=rev), mine(latestReviews=rev, reviewDecision=None),
                mine(latestReviews=rev, requestEvents=bot_event)]
    team_event = mine(requestEvents=conn([dict(review_requested(T1, ME, "x"), requestedReviewer=team)]),
                      assignees=conn([user("rev")]))
    # 担当に渡した PR は、渡す前のレビューや依頼の記録があっても、依頼先を決めるのは担当（/whose-turn と同じ。
    # 受けた担当のレビューは数えない）
    handed_before = [mine(latestReviews=rev, requestEvents=asked, assignees=conn([user("rev")])),
                     mine(latestReviews=rev, assignees=conn([user("rev")])),
                     mine(requestEvents=asked, assignees=conn([user("rev")])),
                     mine(latestReviews=conn([review(T1, "carol")]), assignees=conn([user("rev")])),
                     team_event]
    bot_event_only = mine(requestEvents=bot_event)
    # 依頼先が削除済みのアカウントだと requestedReviewer は null で返る
    null_reviewer = mine(reviewRequests=conn([{"requestedReviewer": None}]),
                         requestEvents=conn([dict(review_requested(T1, ME, "x"), requestedReviewer=None)]))
    kept = [mine(requestEvents=asked),
            mine(latestReviews=conn([review(T1, ME)])),
            mine(latestReviews=conn([review(T1, "copilot", bot=True)])),
            mine(reviewRequests=bot_req),
            bot_event_only,
            null_reviewer,
            mine(assignees=conn([user(ME), user("rev")]))]
    assigned = [mine(assignees=conn([user("rev")])),
                mine(assignees=conn([user("rev")]), reviewRequests=bot_req),
                mine(assignees=conn([user("rev")]), requestEvents=bot_event)]
    team_req = mine(reviewRequests=conn([{"requestedReviewer": team}]))
    # 担当に渡しても、私が入ったスレッドで相手が返していれば、返すターンは私に残る
    thread_turn = mine(assignees=conn([user("rev")]), reviewThreads=conn([thread(
        "a.py", False, comment(T1, ME, "ここはどうしますか"), comment(T2, "rev", "直します"))]))
    # 承認の規則が無い base では承認しても null のまま。/whose-turn と同じく REVIEW_REQUIRED と同じに扱う
    approved_on_null = mine(reviewDecision=None, latestReviews=conn([review(T1, "rev", "APPROVED")]),
                            requestEvents=asked)
    bot_left = mine(reviewDecision="APPROVED", reviewRequests=bot_req)
    # 人宛の依頼が Bot 宛の前でも後でも、依頼したと読む
    orders = ([person_ev, bot_ev], [bot_ev, person_ev])
    mixed_reviewed = [mine(latestReviews=rev, requestEvents=conn(o)) for o in orders]
    mixed_assigned = [mine(assignees=conn([user("rev")]), requestEvents=conn(o)) for o in orders]
    window = catchup.REQUEST_WINDOW
    bots = [bot_ev] * window
    full_window = mine(requestEvents=conn([person_ev] * window))
    cut = [mine(requestEvents=events(bots, True)), mine(requestEvents=events(bots, None))]
    not_cut = [mine(requestEvents=events(bots, False)), mine(requestEvents=events(bots[1:], True))]
    cut_rereq = mine(latestReviews=rev, requestEvents=events(bots, True))
    cut_assigned = mine(assignees=conn([user("rev")]), requestEvents=events(bots, True))
    cut_asked = mine(latestReviews=rev, requestEvents=events([person_ev] + bots[1:], True))
    cut_others = render(pr(latestReviews=rev, requestEvents=events(bots, True)))
    cap_line = f"  - レビュー依頼の出来事の古い方（新しい {window} 件で窓が埋まり、それより前が有りうる。"
    note = "前に人へ依頼していれば"
    cand = "  依頼先の候補（GitHub の提案"
    fix = "要修正が付いている（指摘対応は私）"

    # 変更要求の全員に人として依頼し直していれば、ターンはレビュアー（#1843）
    def changes(asked, *by):
        return mine(reviewDecision="CHANGES_REQUESTED",
                    latestOpinionatedReviews=conn([review(T1, b, "CHANGES_REQUESTED") for b in by]),
                    reviewRequests=conn([{"requestedReviewer": user(a)} for a in asked]))
    rerequested = changes(["rev"], "rev")
    partly = [changes(["rev"], "rev", "rev2"), changes([], "rev"),
              mine(reviewDecision="CHANGES_REQUESTED", reviewRequests=conn([{"requestedReviewer": team}]),
                   latestOpinionatedReviews=conn([review(T1, "rev", "CHANGES_REQUESTED")])),
              mine(reviewDecision="CHANGES_REQUESTED", reviewRequests=conn([{"requestedReviewer": user("rev")}]),
                   latestOpinionatedReviews=conn([review(T1, "rev", "CHANGES_REQUESTED")], total=31))]
    # 持ち主は /whose-turn と同じ turn.owners。持ち主しか外せないターンは渡した担当の人へ
    red = checks(check_run("lint", "FAILURE"))
    copilot = user("copilot-swe-agent", bot=True)
    not_people = [mine(assignees=conn([copilot])),
                  mine(assignees=conn([{"__typename": "Mannequin", "login": "old-user"}]))]
    handed_red = mine(assignees=conn([user("rev"), copilot]), head=red)
    received_red = render(pr(author=user("alice"), assignees=conn([user(ME)]), head=red))
    third = render(pr(author=user("alice"), assignees=conn([user("rev")])))
    before = [dict(requestEvents=conn([review_requested(T1, "alice", "carol")])),
              dict(latestReviews=conn([review(T1, "carol")]))]
    third_before = [render(pr(author=user("alice"), assignees=conn([user("rev")]), **kw)) for kw in before]
    third_before_red = render(pr(author=user("alice"), assignees=conn([user("rev")]), head=red, **before[0]))
    third_deleted_before = render(pr(author=None, assignees=conn([user("rev")]), **before[1]))
    # 依頼の記録がある渡した PR も、依頼先を決めるのと CI 赤は担当の人が持つ
    before_red = mine(requestEvents=asked, assignees=conn([user("rev")]), head=red)

    def received(**over):
        return render(pr(**{"author": user("alice"), "assignees": conn([user(ME)]), **over}))
    received_asking = received(reviewRequests=conn([{"requestedReviewer": user("carol")}]))
    received_unasked = received()
    cut_received = received(requestEvents=events(bots, True))
    # 受けた担当の私のレビューは数えない。渡す前の依頼は、外れたままなら依頼先を決め直すのは私
    received_before = [received(latestReviews=conn([review(T1, ME)])),
                       received(requestEvents=conn([review_requested(T1, "alice", "carol")]))]
    # 受付 e199f8 の例: 作者 alice・担当の私・依頼は無し・carol のコメントのレビューが 1 件
    received_reviewed = received(latestReviews=conn([review(T1, "carol")]))
    received_draft_conflict = received(isDraft=True, mergeable="CONFLICTING")
    handed_draft_conflict = mine(assignees=conn([user("rev")]), isDraft=True, mergeable="CONFLICTING")
    received_changes = received(reviewDecision="CHANGES_REQUESTED",
                                latestOpinionatedReviews=conn([review(T1, "carol", "CHANGES_REQUESTED")]))
    received_merge = received(reviewDecision="APPROVED")
    two = conn([user("bob"), user("carol")])
    two_assignees = [render(pr(author=user("alice"), assignees=two)),
                     render(pr(author=user("alice"), assignees=two, head=red))]
    two_with_me = [render(pr(author=user("alice"), assignees=conn([user(ME), user("carol")]))),
                   render(pr(author=user("alice"), assignees=conn([user("carol"), user(ME)]), head=red))]
    deleted_author = [render(pr(author=None)), render(pr(author=None, isDraft=True)),
                      render(pr(author=None, head=red))]
    deleted_handed = render(pr(author=None, assignees=conn([user(ME)]),
                               latestReviews=conn([dict(review(T1, "x"), author=None)])))
    deleted_reviewed = render(pr(author=None, assignees=conn([user(ME)]), latestReviews=conn([review(T1, "carol")])))
    co_assignee = render(pr(author=user("alice"), assignees=conn([user("alice"), user(ME)])))
    issue_waits = [render(issue(author=user("alice"), assignees=conn([user("bob")]))),
                   render(issue(author=user(ME), assignees=conn([user("bob")])))]

    def legacy(node):
        # assignedActors の無い GitHub で取り直した形。assignee は login しか持たない
        return render(dict(node, assigneeKindsUnknown=True))
    legacy_handed = legacy(pr(author=user(ME), assignees=conn([{"login": "copilot"}])))
    legacy_red = legacy(pr(author=user(ME), assignees=conn([{"login": "rev"}]), head=red))
    legacy_issue = legacy(issue(assignees=conn([{"login": ME}])))
    legacy_third = legacy(pr(author=user("alice"), assignees=conn([{"login": "bob"}])))
    legacy_third_red = legacy(pr(author=user("alice"), assignees=conn([{"login": "bob"}]), head=red))
    legacy_unassigned = [legacy(pr(author=user(ME))), legacy(pr(author=user(ME), assignees=conn([{"login": ME}])))]
    legacy_cut = legacy(pr(author=user(ME), assignees=conn([{"login": "rev"}]), requestEvents=events(bots, True)))
    kinds_line = "  - assignee が人か Bot か（この GitHub は assignedActors を返さない。"
    opinions_line = "  - 人ごとの意見の残り 30 件（31 件中、1 件だけ取った）。変更要求の全員に依頼し直したかを見ずに"
    query = catchup.QUERY
    want = {
        "rereq": all(rereq in h and "● 私の番" in h and reason not in h and norec not in h
                     and "依頼先の候補" not in h for h in reviewed),
        "passerby": all(norec in h and rereq not in h and reason not in h and "依頼先の候補" in h
                        for h in passerby),
        "mixed_events": all(rereq in h and norec not in h and "依頼先の候補" not in h for h in mixed_reviewed)
        and all("○ 待ち — 担当 rev 待ち" in h and "依頼先の候補" not in h for h in mixed_assigned),
        "null_is_rereq": rereq in approved_on_null and merge not in approved_on_null
        and "要修正が付いている（指摘対応は私）" not in approved_on_null
        and "  承認: 承認・要修正の判定なし" in approved_on_null,
        "bot_left_merge": merge in bot_left,
        # 材料は手組みなので、判定が読むフィールドを QUERY が取っているかは字面で確かめる
        "query_fields": all(f in query for f in (
            "reviewRequests(first:20){nodes{requestedReviewer{__typename",
            f"requestEvents: timelineItems(last:{window}, itemTypes:[REVIEW_REQUESTED_EVENT]){{\n"
            "          pageInfo{hasPreviousPage} nodes{__typename",
            "requestedReviewer{__typename ... on User{login} ... on Team{name}}}}}",
            "latestReviews(first:100){nodes{author{__typename login}}}", catchup.turn.OPINIONS))
        and query.count(catchup.turn.ASSIGNEES) == 2,
        "legacy_query": catchup.LEGACY_QUERY.count(catchup.turn.LEGACY_ASSIGNEES) == 2
        and catchup.turn.KINDS_FIELD not in catchup.LEGACY_QUERY
        and catchup.turn.OPINIONS in catchup.LEGACY_QUERY,
        "rerequested": fix not in rerequested and "○ 待ち — レビュー待ち: rev" in rerequested
        and all(fix in h for h in partly) and opinions_line in partly[-1]
        and all("人ごとの意見の残り" not in h for h in partly[:-1] + [rerequested]),
        "not_people": all(reason in h and cand in h and "○ 待ち" not in h for h in not_people),
        "handed_red": "○ 待ち — 担当 rev 待ち" in handed_red and "CI 赤は" not in handed_red,
        "received_red": "CI 赤は担当（私）しか外せない" in received_red and "私が担当（assignee）" not in received_red,
        "received_asking": "○ 待ち — レビュー待ち: carol" in received_asking
        and "私が担当（assignee）" not in received_asking,
        "received_unasked": f"● 私の番 — {reason}" in received_unasked and cand in received_unasked
        and "私が担当（assignee）" not in received_unasked,
        "received_before": all(f"● 私の番 — {reason}" in h and cand in h and "私が担当（assignee）" not in h
                               for h in received_before)
        and f"● 私の番 — {norec}" in received_reviewed and cand in received_reviewed,
        "handed_before": all("○ 待ち — 担当 rev 待ち" in h and "● 私の番" not in h and cand not in h
                             for h in handed_before),
        "received_draft_conflict": all(r in received_draft_conflict
                                       for r in ("● 私の番", "下書きのまま（渡すのは私）", "衝突の解消は担当（私）"))
        and "○ 待ち — 担当 rev 待ち" in handed_draft_conflict
        and all(r not in handed_draft_conflict for r in ("下書きのまま（渡すのは私）", "衝突の解消は")),
        "received_changes": f"● 私の番 — {fix}" in received_changes,
        "received_merge": f"● 私の番 — {merge}" in received_merge,
        "two_assignees": all("○ 待ち — 担当 bob, carol 待ち" in h for h in two_assignees)
        and f"● 私の番 — {reason}" in two_with_me[0] and cand in two_with_me[0]
        and "CI 赤は担当（私）しか外せない" in two_with_me[1],
        "deleted_author": all("○ 待ち — 作者 （不明） 待ち" in h for h in deleted_author)
        and f"● 私の番 — {reason}" in deleted_handed and f"● 私の番 — {norec}" in deleted_reviewed,
        "co_assignee": "● 私の番 — 私が担当（assignee）" in co_assignee,
        "issue_waits": "○ 待ち — 起票者 alice 待ち" in issue_waits[0]
        and "○ 待ち — 待っている相手は記録に無い" in issue_waits[1],
        "third_party": "○ 待ち — 担当 rev 待ち" in third and "○ 待ち — 作者 other 待ち" in render(pr()),
        "third_before": all("○ 待ち — 担当 rev 待ち" in h for h in third_before + [third_before_red, third_deleted_before]),
        "before_red": "○ 待ち — 担当 rev 待ち" in before_red and all(
            r not in before_red for r in (reason, cand, "CI 赤は")),
        "legacy": "○ 待ち — 担当 copilot 待ち" in legacy_handed and cand not in legacy_handed
        and "CI 赤は作者（私）しか外せない" in legacy_red
        and "○ 待ち — 担当 bob 待ち" in legacy_third and "○ 待ち — 作者 alice 待ち" in legacy_third_red
        and all(kinds_line in h for h in (legacy_handed, legacy_red, legacy_third))
        and all(kinds_line not in h for h in [legacy_issue, handed_red] + legacy_unassigned),
        "query_one_type": query.count("REVIEW_REQUESTED_EVENT") == 1
        and query.count("requestedReviewer{__typename") == 2,
        "kept": all(reason in h and "依頼先の候補" in h and rereq not in h for h in kept),
        "assigned": all("○ 待ち — 担当 rev 待ち" in h and "依頼先の候補" not in h for h in assigned),
        "team_requested": "○ 待ち — レビュー待ち: core" in team_req and reason not in team_req,
        "team_event_text": "→ core" in team_event and "（依頼に数えない）" not in team_event,
        "bot_event_text": "→ Bot（依頼に数えない）" in bot_event_only and "（不明）" not in bot_event_only,
        "null_reviewer": "レビュー待ち" not in null_reviewer,
        "request_cap": cap_line in full_window and all(cap_line not in h for h in reviewed + kept),
        # 窓いっぱいでも前が無いと GitHub が言えば出さない。pageInfo が無ければ件数だけで出す
        "window_cut": all(cap_line in h and note not in h for h in cut)
        and all(cap_line not in h for h in not_cut),
        "cap_note": cap_line in cut_rereq and f"{note}再依頼のターンで、出している依頼先の候補は要らない" in cut_rereq
        and norec in cut_rereq and "依頼先の候補" in cut_rereq
        and cap_line in legacy_cut and f"{note}、担当に渡したと分けたのは誤り" in legacy_cut
        and cand in cut_received
        and all(cap_line in h and note not in h for h in (cut_assigned, cut_received))
        and all(cap_line in h and note not in h for h in (cut_asked, cut_others, full_window))
        and rereq in cut_asked,
        "thread_turn": "未解決スレッド 1 件で相手が返している（私が返すターン）" in thread_turn,
    }
    bad = [k for k, v in want.items() if not v]
    return "FORMAL_OK" if not bad else "FORMAL_NG " + ",".join(bad) + "\n" + "\n".join(
        reviewed + passerby + kept + assigned + mixed_reviewed + mixed_assigned + cut + not_cut
        + [team_req, thread_turn, approved_on_null, bot_left, full_window, cut_rereq, cut_assigned, cut_asked,
           cut_others, rerequested] + partly + not_people
        + [handed_red, received_red, third] + third_before + [third_before_red, third_deleted_before]
        + [before_red, received_asking, received_unasked, cut_received, received_reviewed, legacy_cut]
        + received_before + handed_before
        + [received_draft_conflict, handed_draft_conflict, received_changes, received_merge]
        + two_assignees + two_with_me + deleted_author + [deleted_handed, deleted_reviewed, co_assignee] + issue_waits
        + [legacy_handed, legacy_red, legacy_issue, legacy_third, legacy_third_red] + legacy_unassigned)


@case("fetch-legacy")
def _fetch_legacy():
    """assignedActors の無い GitHub（undefinedField）では種別なしで取り直して印を付け、ほかの GraphQL エラーと gh の
    失敗では止まる。504 は本文に errors があってもやり直す。"""
    import json
    import subprocess
    ghcli = sys.modules["ghcli"]  # catchup の gh は lib/ghcli.py の物
    calls = []

    def runs(*responses):
        it = iter(responses)

        def run(argv, **_kw):
            calls.append(argv)
            code, body, err = next(it)
            return subprocess.CompletedProcess(argv, code, body if isinstance(body, str) else json.dumps(body), err)
        return run

    missing = {"errors": [{"message": "Field 'assignedActors' doesn't exist on type 'PullRequest'", "extensions": {
        "code": "undefinedField", "typeName": "PullRequest", "fieldName": "assignedActors"}}]}
    node = {"__typename": "PullRequest", "number": 1}
    page = {"data": {"repository": {"issueOrPullRequest": node}}}

    def go(*responses):
        calls.clear()
        ghcli.subprocess.run = runs(*responses)
        try:
            got = catchup.fetch("o", "n", 1)
        except SystemExit as e:
            got = f"EXIT {e}"
        return got, [next(a for a in argv if a.startswith("query=")) for argv in calls]

    saved = (ghcli.shutil.which, ghcli.subprocess.run)
    ghcli.shutil.which = lambda _name: "gh"
    try:
        legacy, legacy_q = go((1, missing, "gh: Field 'assignedActors' doesn't exist on type 'PullRequest'"),
                              (0, page, ""))
        plain, plain_q = go((0, page, ""))
        other, _ = go((1, {"errors": [{"message": "Resource limits exceeded"}]}, "gh: Resource limits exceeded"))
        retried, retried_q = go((1, {"errors": [{"message": "Something went wrong"}]}, "gh: HTTP 504: Gateway Timeout"),
                                (0, page, ""))
        failed, _ = go((1, "", "gh: HTTP 401: Bad credentials"))
        twice, _ = go((1, "", "gh: HTTP 504: Gateway Timeout"), (1, "", "gh: HTTP 504: Gateway Timeout"))
    finally:
        ghcli.shutil.which, ghcli.subprocess.run = saved
    query, again = "query=" + catchup.QUERY, "query=" + catchup.LEGACY_QUERY
    want = {
        "legacy": legacy == dict(node, assigneeKindsUnknown=True) and legacy_q == [query, again],
        "plain": plain == node and plain_q == [query],
        "other_stops": str(other).startswith("EXIT GraphQL エラー"),
        "retry_504": retried == node and retried_q == [query, query],
        "plain_failure_stops": str(failed).startswith("EXIT gh api graphql が失敗"),
        "second_504_stops": str(twice).startswith("EXIT gh api graphql が失敗"),
    }
    return verdict("FETCH", want, repr((legacy, plain, other, retried, failed)))


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
    return verdict("SINCE", want, out)


@case("since-approx")
def _since_approx():
    """基準が本文コメント（commit 無し）なら、その時刻以前の最新の commit で置く（近似）。見出しと
    「見ていないもの」に近似の断り。発言が最初の commit より前なら基準を置けず、セクションは出ない。"""
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
    return verdict("SINCE", want, out)


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
    return verdict("SINCE", want, out)


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
    return verdict("SINCE", want, out)


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
    return verdict("MAP_JUMPS", want, out)


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
    return verdict("NO_TARGET", want, out)


@case("git-failed")
def _git_failed():
    """git が読めなかった（15 秒の timeout など）とき、「変更なし」「未コミットの変更なし」と断定せず、
    読めなかったと書く。commit_tree・working_tree は失敗を (None, None) で返す。"""
    cm = catchup.changemap
    saved = (cm.commit_tree, cm.working_tree, cm.git, cm.default_branch_ref)
    cm.commit_tree = lambda rev, cwd=None: (None, None)
    cm.working_tree = lambda cwd=None: (None, None)
    cm.default_branch_ref = lambda cwd=None: "origin/main"
    cm.git = lambda *a, cwd=None: "3\n" if a[0] == "rev-list" else "mmmmmmm3\n" if a[0] == "merge-base" else ""
    try:
        rng = catchup.render_range("aaaaaaa1..bbbbbbb2")
        ahead = catchup.ahead_of_default()
        local = catchup.render_local(why="確かめ", wt=cm.working_tree())
    finally:
        cm.commit_tree, cm.working_tree, cm.git, cm.default_branch_ref = saved
    want = {
        "range": "分からない ファイル" in rng and "変更の地図: 出せない" in rng and "変更なし" not in rng,
        "ahead": "読めない（git diff が失敗した）" in "\n".join(ahead) and "変更なし" not in "\n".join(ahead),
        "local": "未コミットの変更: 読めなかった" in local and "未コミットの変更なし" not in local,
    }
    return verdict("GIT_FAILED", want, rng + "\n".join(ahead) + local)


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
    return verdict("RANGE", want, out)


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
        branch = catchup.resolve_target("feat/x", None)     # ブランチの名前は commit より先に「移る」対象
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
    return verdict("COMMIT", want, out)


@case("main-wiring")
def _main_wiring():
    """main() の受け口の配線。commit・PR も番号も無いブランチ（none）で、焦点の断りは人の語（指摘・地図・CI）で
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
    return verdict("WIRING", want, out1 + out4 + (out5 or ""))


@case("branch-wiring")
def _branch_wiring():
    """ブランチ名で呼んだときの report() の配線。origin にだけ在って PR も無いブランチ（移らない回）は、短い名前で
    引けない tip を origin/<名前> から引いて commit として出す（前は oid が None のまま描いて TypeError で止まった）。
    両方に無ければ例外でなく理由を言って止まる。移れた先に PR も番号も無いときは、移った行を出し「移らない」とは言わず、
    HTML の手元の欄にも移った行を残す（前は「this では移らない」と出て、移った行が落ちていた）。"""
    import argparse
    import contextlib
    import io
    names = ("resolve_target", "switch_to_branch", "gh_try", "render_commit", "page_commit", "render_no_target",
             "render_local", "plain_diff", "local_slug")
    saved = {n: getattr(catchup, n) for n in names}
    saved_oid, saved_branch = catchup.changemap.commit_oid, catchup.changemap.current_branch
    state = {"moved": False, "oids": {"refs/remotes/origin/feat-x": "OID"}}
    catchup.resolve_target = lambda token, repo: ((None, None, None, "none") if token == "this"
                                                  else (None, None, "feat-x", "branchname"))
    catchup.switch_to_branch = lambda name, cwd=None: (
        (["ブランチ feat-x: main から移った"], True) if state["moved"]
        else (["ブランチ feat-x: 未コミットの変更 1 件があるので移らない（手元は main のまま）"], False))
    catchup.gh_try = lambda *args, **kw: ""
    catchup.changemap.commit_oid = lambda token, cwd=None: state["oids"].get(token)
    catchup.changemap.current_branch = lambda cwd=None: "feat-x"
    catchup.render_commit = lambda oid, cwd=None, frame=None, full=False: f"COMMIT {oid}"
    catchup.page_commit = lambda oid, cwd=None: {"local": ""}
    catchup.render_no_target = lambda cwd=None: "NONE"
    catchup.render_local = lambda *args, **kw: "LOCAL"
    catchup.plain_diff = lambda *args, **kw: ""
    catchup.local_slug = lambda cwd=None: ("o/r", "o/r")

    def run():
        a = argparse.Namespace(words=["feat-x"], repo=None, switch=True, frame=None, full=False)
        sink, buf = {}, io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = catchup.report(a, sink)
        except SystemExit as e:
            return None, str(e), sink
        return rc, buf.getvalue(), sink
    try:
        rc1, out1, _ = run()
        state["oids"] = {}
        rc2, out2, _ = run()
        state["moved"] = True
        rc3, out3, sink3 = run()
    finally:
        for n, f in saved.items():
            setattr(catchup, n, f)
        catchup.changemap.commit_oid, catchup.changemap.current_branch = saved_oid, saved_branch
    local3 = (sink3.get("page") or {}).get("local", "")
    want = {
        "origin_only_tip": rc1 == 0 and "COMMIT OID" in out1,
        "no_tip_stops": rc2 is None and "tip の commit が引けない" in out2,
        "moved_line": rc3 == 0 and "ブランチ feat-x: main から移った" in out3 and "移らない" not in out3
                      and "NONE" in out3,
        "moved_in_page": local3.startswith("ブランチ feat-x: main から移った") and "LOCAL" in local3,
    }
    return verdict("BRANCH_WIRING", want, out1 + out2 + out3 + local3 + str(sink3.get("error")))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
