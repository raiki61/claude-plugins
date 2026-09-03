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


def render(node, full=False, my_email="", tails=False):
    """tails=True なら main() と同じ経路（焦点なし）で末尾の材料の有無を決めて渡す。既定の False は
    材料を 1 つも付けない呼び方で、焦点で外したときの文言を見る。"""
    ev, refs, unlinked = catchup.collect_events(node, ME, my_email)
    anchor, kind = catchup.find_anchor(ev, node, ME)
    flags = {}
    if tails:
        is_pr = node["__typename"] == "PullRequest"
        m, t, c = catchup.pick_tails(is_pr, set(), bool(catchup.unresolved_threads(node, ME)),
                                     bool(catchup.check_state(node)[0]) if is_pr else False)
        flags = {"with_map": m, "with_threads": t, "with_ci": c}
    return catchup.render(node, ME, ev, refs, unlinked, anchor, kind, full, 12,
                          catchup.collect_caps(node), **flags)


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
        and "（続きは gh issue view 5 で見る）" in out,
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
        and "  | 行 12" in out and "行 13" not in out and "（続きは gh issue view 1078 で見る）" in out,
        "pr": "=== 本文が指す PR #1105 権限（closed。本文の冒頭 2 行／2 行）" in out and "続きは gh pr view" not in out,
        "missing": "=== 本文が指す #2000: 取れなかった（gh issue view 2000 で見る）" in out,
        "rest": "（本文が指す番号は他に 1 件）" in out,
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
        "my_turn": "=== 2/4 app/main.py:10  ← 私が返す番" in out,
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
        "external": "=== ext  https://ci.example.invalid/x" in out and "run ではない" in out,
        "green_hidden": "=== ok" not in out,
    }
    bad = [k for k, v in want.items() if not v]
    return "CI_OK" if not bad else "CI_NG " + ",".join(bad) + "\n" + out


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: catchup-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
