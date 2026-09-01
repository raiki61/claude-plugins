#!/usr/bin/env python3
"""open な PR と issue の全件から、あなたのボールと判断材料を機械で取り切って出す。

〈目的〉「私のボールの PR は」「担当 issue は」「呼ばれて返していないのは」に答える材料を、
GitHub から取れる範囲で全部、決定的に集める。判断（返信が要るか・急ぎか）はしない——
それは読む人か、/whoseturn の AI の仕事。母集団と、見ていないものを必ず併記する。

〈PR のボール〉1 つの PR が複数人に載る。形式上の状態と会話の状態を別の信号として出す:
  draft         作者。draft のまま
  CI 赤         作者。head commit のチェックに SUCCESS / NEUTRAL / SKIPPED / PENDING /
                EXPECTED / CANCELLED / STALE 以外の結論がある（未知の値は赤に倒す）
  指摘対応      作者。reviewDecision が CHANGES_REQUESTED
  レビュー      依頼先。Bot 以外（人か Team）へのレビュー依頼が未消化（copilot 等の Bot 宛は数えない）
  レビュー待ち  作者。その依頼が残っている間。作者に動かせることは無いが、行を立てないと
                open な PR が作者のどの段にも出ず、依頼を出したことごと一覧から消える
  マージ        作者。APPROVED で依頼も残っていない（main 未追従なら併記）
  再依頼        作者。作者以外の人のレビューが付いて依頼が消えたまま
  レビュー依頼  作者。Bot 以外へ依頼を出したが、レビューが付かないまま依頼も消えた
  未依頼        作者。Bot 以外へレビューを依頼したことが一度も無い。相手はこの PR を知らないので、
                「待ち」は作成日ではなく最後に動かした日（head commit）から数える
  未送信        レビューを書いた人。下書き（PENDING）のまま送っていない。相手には届いていない
  返答待ち      指摘した人。未解決スレッドで自分の指摘の後に作者がまだ返していない
  スレッド返答  作者。未解決スレッドで自分の最後の発言の後に指摘が来ている
  再確認        指摘した人。未解決スレッドで自分の指摘の後に作者が返した（再依頼は押されていない）
  担当          assignee。作者と別の人が assignee
「待ち」はその信号が出た日からの日数。PR の作成日ではない。信号の名前は報告に出さない——
読む人が要るのは「今日動かせるか」と、行に添えた事実の方で、語彙を覚えることではない。
並びは「その人が動けば進むか」の 4 段。各段の中では待ちの古い順:
  あなたを待っている人がいる            相手がその人の番で止まっている。動かせるのはその人だけ
  あなたを待っている人がいる（動ける人はほかにもいる）
                                        同上だが、Bot 以外の依頼先が 2 人以上いるレビュー、または
                                        同じ PR の相手にも返す番が残っているもの
  まだ誰にも渡していない                draft・未依頼。待っている人はいないが、動かせるのはその人だけ
  相手が動くまで進まない                その人が最後に発言して番も無い、依頼したレビューが返って
                                        きていない、または作者しか外せない障害（その人が作者でない
                                        PR の main 未追従・衝突・CI 赤）が残っていて、その人の
                                        残りが再確認だけ
上 2 段と 3 段目を分けるのは、渡していない PR は誰も待っていないが動かせるのは本人だけで、
「相手待ち」と混ぜると本当のボールが沈むため。最下段は形式上の状態だけで信号が立ち続け、
待ちの日数だけが伸びるので、混ぜると上を占めて実際に人を止めている行が沈む。

〈呼びかけ〉issue の本文・コメント、PR のコメント・レビュー・スレッドで @login と呼ばれ、
その後に本人のコメントが無いもの。Bot の呼びかけと、コード・引用（>）の中は数えない。
要返信かは判定せず、抜粋・本人の 👍・直前が本人の発言か・参照する open PR を添える。

〈材料〉--materials は呼びかけの全文に加え、返す番があるスレッドの最後の発言も全文で出す。
数だけでは「相手が直した報告（見て resolve するだけ）」と「相手が問いを返した（答えないと
止まる）」が区別できず、読む側が段の言い直ししか書けなくなる。
"""

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import unicodedata

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# CANCELLED / STALE は新しい push に打ち切られた実行で、作者が直すものではない。空文字は実行中
GREEN = {
    "SUCCESS",
    "NEUTRAL",
    "SKIPPED",
    "PENDING",
    "EXPECTED",
    "CANCELLED",
    "STALE",
    "",
}

MATERIALS_MARK = "==== ここから下は判定の材料。貼らない ===="

# 作者しか外せないマージの障害。BEHIND は取り込み、DIRTY は衝突解消で、どちらもブランチを持つ側の仕事
AUTHOR_ONLY_MERGE = {"BEHIND", "DIRTY"}

# tier() が返す段。0〜2 は今日動かせる（私のボール）、3 は相手が動くまで進まない（待ち）。
# 報告は 2 つに分けて出し、段そのものは並びの鍵としてだけ使う——動かせる中での優先順は
# 「その人しか動かせない」→「動ける人はほかにもいる」→「まだ誰にも渡していない」の順
MINE = (0, 1, 2)
BUCKETS = (("私のボール", lambda t: t in MINE), ("待ち", lambda t: t not in MINE))

# まだ誰にも渡していない状態。待っている人はいないが、動かせるのは本人だけ
HANDOFF = {"draft", "未依頼", "未送信"}

NOT_SEEN = """\
見ていないもの:
  - 呼びかけの中身（質問か FYI か）と、返信が要るかの判断。抜粋と事実だけ出す
  - GitHub の外（チャット・口頭）での返答
  - Projects のフィールドと通知 API（トークンに read:project / notifications が無い）
  - Team 宛のレビュー依頼の所属展開{teams}
  - どこにも記録されていない担当（assignee 未設定の件数は上に出す）
  - 本文コメントで来た指摘と返信の噛み合い。スレッドと違い返信が紐づかないので、最後の
    発言者しか見ていない（相手の指摘の後に別の話で発言すると、返したことになる）{unverified}
  - スレッドの材料は最後の発言だけ。そこまでの経緯が要るなら gh で読む
  - 逃がした先は「この PR より後に立った open な issue / PR」に限る。close 済み・
    別リポジトリの行き先は見ない"""

ACTOR = "{ login __typename }"
REVIEWER = "{ __typename ... on User { login } ... on Team { combinedSlug } }"

PR_QUERY = f"""
query($owner: String!, $name: String!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequests(first: 10, states: OPEN, after: $cursor) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number title headRefName isDraft reviewDecision mergeStateStatus createdAt updatedAt
        author {{ login }}
        assignees(first: 10) {{ totalCount nodes {{ login }} }}
        reviewRequests(first: 20) {{ totalCount nodes {{ requestedReviewer {REVIEWER} }} }}
        reviews(last: 100) {{ totalCount nodes {{ id state createdAt submittedAt body author {ACTOR} }} }}
        comments(last: 100) {{ totalCount nodes {{ id createdAt body author {ACTOR} }} }}
        reviewThreads(first: 50) {{ totalCount nodes {{ isResolved isOutdated path line
          comments(first: 30) {{ totalCount nodes {{ id state createdAt body author {ACTOR} }} }} }} }}
        timelineItems(last: 100, itemTypes: [REVIEW_REQUESTED_EVENT, READY_FOR_REVIEW_EVENT,
                                             CONVERT_TO_DRAFT_EVENT, ASSIGNED_EVENT]) {{
          nodes {{ __typename
            ... on ReviewRequestedEvent {{ createdAt requestedReviewer {REVIEWER} }}
            ... on ReadyForReviewEvent {{ createdAt }}
            ... on ConvertToDraftEvent {{ createdAt }}
            ... on AssignedEvent {{ createdAt assignee {{ ... on User {{ login }} }} }} }} }}
        commits(last: 1) {{ nodes {{ commit {{ committedDate statusCheckRollup {{
          contexts(first: 100) {{ totalCount nodes {{
            ... on CheckRun {{ name conclusion completedAt }}
            ... on StatusContext {{ context state createdAt }} }} }} }} }} }} }}
      }} }} }} }}
"""

# 呼びかけ候補の投稿だけ、本人のリアクション（👍 で済ませた返答）を後から引く。
# 本体クエリに入れると GraphQL の資源上限に当たる（実測: issue 40 件/頁で "Resource limits exceeded"）
REACTIONS_QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) { id
    ... on Issue { reactions(first: 50) { totalCount nodes { user { login } } } }
    ... on IssueComment { reactions(first: 50) { totalCount nodes { user { login } } } }
    ... on PullRequestReview { reactions(first: 50) { totalCount nodes { user { login } } } }
    ... on PullRequestReviewComment { reactions(first: 50) { totalCount nodes { user { login } } } } } }
"""

ISSUE_QUERY = f"""
query($owner: String!, $name: String!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    issues(first: 40, states: OPEN, after: $cursor) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        id number title createdAt updatedAt body
        author {ACTOR}
        assignees(first: 20) {{ totalCount nodes {{ login }} }}
        comments(last: 100) {{ totalCount nodes {{ id createdAt body author {ACTOR} }} }}
        timelineItems(last: 100, itemTypes: [ASSIGNED_EVENT, CROSS_REFERENCED_EVENT]) {{
          nodes {{ __typename
            ... on AssignedEvent {{ createdAt assignee {{ ... on User {{ login }} }} }}
            ... on CrossReferencedEvent {{ source {{ __typename
              ... on PullRequest {{ number state }} }} }} }} }}
      }} }} }} }}
"""


# ---- 時刻 ------------------------------------------------------------------

# GitHub の時刻は UTC（Z 終端）。見出しだけローカル（%Z 付き）にして各行を生のまま出すと、
# 同じ報告の中で 9 時間ずれる（実測 2026-09-01・JST: 見出し 06:32 JST、行は 21:32 のまま）。
# 全部ローカルへ寄せる。None は「この機械のローカル」で、夏時間のある地域でも時刻ごとに
# 正しいオフセットが付く（now().astimezone().tzinfo だと今の固定オフセットになり、冬の
# 時刻を夏に見ると 1 時間ずれる）。検査はこの値を UTC に固定して回す
LOCAL_TZ = None


def local_time(ts, fmt="%m-%d %H:%M"):
    """ISO 8601（UTC）をローカル時刻で整形する"""
    at = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return at.astimezone(LOCAL_TZ).strftime(fmt)


# ---- 取得 ------------------------------------------------------------------


def gh(*args):
    exe = shutil.which("gh")
    if not exe:
        sys.exit("gh が見つからない（PATH に通す）")
    # GraphQL の 504 は過負荷時に単発で出る（実測）。1 回だけ再試行し、2 回目も落ちたら赤で止める
    for attempt in (1, 2):
        r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はこのファイル内のリテラルと GraphQL のカーソルだけ
            [exe, *args], capture_output=True, text=True
        )
        if r.returncode == 0:
            return r.stdout
        if "504" not in r.stderr or attempt == 2:
            sys.exit(f"gh {' '.join(args[:2])} が失敗: {r.stderr.strip()}")
    return None


def fetch_all(query, owner, name, field):
    nodes, cursor = [], None
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            "query=" + query,
            "-f",
            "owner=" + owner,
            "-f",
            "name=" + name,
        ]
        if cursor:
            args += ["-f", "cursor=" + cursor]
        data = json.loads(gh(*args))
        if data.get("errors"):
            sys.exit(
                "GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False)
            )
        conn = data["data"]["repository"][field]
        nodes += conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


# ---- 判定（純粋関数。tests/whoseturn-suite.py が規則を pin する） ------------------


def keep(conn, pred):
    """接続から条件に合わない要素を落とし、落とした数を返す。

    totalCount も一緒に減らす。取得上限の検査が totalCount と件数の差で判定しているので、
    減らさないと落とした分がそのまま「上限に当たった」に化ける。"""
    kept = [n for n in conn["nodes"] if pred(n)]
    dropped = len(conn["nodes"]) - len(kept)
    conn["nodes"], conn["totalCount"] = kept, conn["totalCount"] - dropped
    return dropped


def drop_pending(pr):
    """未送信のレビュー（PENDING）を判定から外し、pr["pendingReview"] に畳む。

    下書きのレビューは API では書いた本人にだけ見える。相手には届いていないので、判定に混ぜると
    自分の下書きが「相手が返す番」に化け、実際のボール——送ること——が待ちの側へ沈む。
    GraphQL は PENDING の submittedAt を null で返すため、落とさないと発言を時刻で並べる所で
    落ちる（実測 2026-08-23・IL-SW-AI/guided-resolver #1450: 下書き 16 件で全体が TypeError）。"""
    pending = [r for r in pr["reviews"]["nodes"] if r["state"] == "PENDING"]
    keep(pr["reviews"], lambda r: r["state"] != "PENDING")
    n = sum(
        keep(t["comments"], lambda c: c.get("state") != "PENDING")
        for t in pr["reviewThreads"]["nodes"]
    )
    keep(pr["reviewThreads"], lambda t: t["comments"]["nodes"])
    pr["pendingReview"] = (
        {
            "by": login(pending[0]["author"]),
            "comments": n,
            "since": min(r["createdAt"] for r in pending),
        }
        if pending
        else None
    )
    return pr["pendingReview"]


def login(actor):
    # 退会済みユーザーの author は null で返る
    return (actor or {}).get("login")


def is_bot(actor):
    return (actor or {}).get("__typename") == "Bot"


def reviewer(node):
    # User → login / Team → org/slug / それ以外（copilot 等の Bot）→ None。
    # login の有無で見分けると、クエリのフラグメントに Bot { login } を足した途端 Bot が人になる
    kind = (node or {}).get("__typename")
    if kind == "User":
        return node["login"]
    if kind == "Team":
        return node["combinedSlug"]
    return None


def latest(values):
    values = [v for v in values if v]
    return max(values) if values else None


def pr_balls(pr):
    """[(誰の番か, 種別, いつから)]。形式上の状態と会話の状態を別々に出し、同じ人は呼び出し側でまとめる。"""
    author = login(pr["author"])
    created = pr["createdAt"]
    events = pr["timelineItems"]["nodes"]

    def last_event(kind):
        return latest(e["createdAt"] for e in events if e["__typename"] == kind)

    # 作者がレビューコメントに返信すると、作者名義の COMMENTED レビューができる。それを
    # 「人のレビュー」に数えると、誰にも頼んでいない PR が「再依頼」に化ける
    reviews = [r for r in pr["reviews"]["nodes"] if login(r["author"]) != author]

    def last_review(pred):
        return latest(r["submittedAt"] for r in reviews if pred(r))

    rows = []
    # draft は形式上の状態だけを止める。会話と assignee の行はこの後で積む——作者が下書きに
    # 戻しても、人が付けた未解決の指摘は生きたままで、返す番は消えない（実測 2026-08-23・
    # IL-SW-AI/guided-resolver #1308: draft のため、作者が返す番の 21 スレッドが誰の一覧にも出ていなかった）
    if pr["isDraft"]:
        rows.append((author, "draft", last_event("ConvertToDraftEvent") or created))
        return rows + conversation_balls(pr)

    red = red_checks(pr)
    if red:
        since = latest(c.get("completedAt") or c.get("createdAt") for c in red)
        rows.append(
            (
                author,
                "CI 赤",
                since or pr["commits"]["nodes"][0]["commit"]["committedDate"],
            )
        )
    elif pr["reviewDecision"] == "CHANGES_REQUESTED":
        since = last_review(lambda r: r["state"] == "CHANGES_REQUESTED")
        rows.append((author, "指摘対応", since or created))

    pending = []
    for rq in pr["reviewRequests"]["nodes"]:
        who = reviewer(rq["requestedReviewer"])
        if who is None:
            continue
        asked = latest(
            e["createdAt"]
            for e in events
            if e["__typename"] == "ReviewRequestedEvent"
            and reviewer(e.get("requestedReviewer")) == who
        )
        pending.append(asked or created)
        rows.append((who, "レビュー", asked or created))

    # 形式上の状態（依頼が残っていなければ作者の番）。CI 赤・指摘対応があればそちらが作者の行
    if not pending and not rows:
        if pr["reviewDecision"] == "APPROVED":
            rows.append(
                (
                    author,
                    "マージ",
                    last_review(lambda r: r["state"] == "APPROVED") or created,
                )
            )
        # reviewDecision はレビューが 1 件も無い間 null で、Bot の COMMENTED が 1 件付いた
        # 瞬間に REVIEW_REQUIRED になる（実測 2026-08-23・IL-SW-AI/guided-resolver: レビュー 0 件の
        # #1478 は null、Copilot の COMMENTED だけ付いた #1476 は REVIEW_REQUIRED）。null を
        # 分類なしに落とすと、立てたばかりの PR が「未依頼」ではなく最上段に出る
        elif pr["reviewDecision"] in ("REVIEW_REQUIRED", None, ""):
            human = last_review(lambda r: not is_bot(r["author"]))
            asked = latest(
                e["createdAt"]
                for e in events
                if e["__typename"] == "ReviewRequestedEvent"
                and reviewer(e.get("requestedReviewer"))
            )
            if human:
                rows.append((author, "再依頼", human))
            elif asked:
                rows.append((author, "レビュー依頼", asked))
            else:
                # 誰にも頼んでいない PR には待たせている相手がいない。作成日から数えると、書きかけを
                # 寝かせた期間まで「待ち」に入る（実測: #1276 は作成 21 日前・最後の push は 3 日前で、
                # 21 日と出ると放置に見える）。最後に動かした日から数えて、本当に止まった分だけ伸ばす
                rows.append(
                    (
                        author,
                        "未依頼",
                        latest(
                            (
                                last_event("ReadyForReviewEvent"),
                                pr["commits"]["nodes"][0]["commit"]["committedDate"],
                                created,
                            )
                        ),
                    )
                )
        else:
            rows.append((author, f"分類なし({pr['reviewDecision']})", created))

    conv = conversation_balls(pr)
    # 依頼が生きている間、上の分岐は作者に 1 行も積まない。そのままだと open な PR が作者の
    # どの段にも出ず、一覧から丸ごと消える（実測 2026-08-26・IL-SW-AI/guided-resolver
    # #1413 #1492 #1494: 依頼を出した瞬間に作者の一覧から落ち、出したこと自体が見えなくなった）。
    # 作者に他の行が 1 本も無いときだけ積む——既にある行に足すと merge_rows が since を min() で
    # 倒し、直近に動かした PR の日数が依頼日まで引き戻されて放置に見える（同日の実測:
    # 無条件に積むと #1207 が 4 日 → 29 日、#1450 が 2 日 → 4 日になった）
    if pending and not any(who == author for who, _, _ in rows + conv):
        rows.append((author, "レビュー待ち", latest(pending) or created))
    return rows + conv


def conversation_balls(pr):
    """未解決スレッド・未送信のレビュー・assignee から立つ行。形式上の状態と違い、draft でも消えない。

    1 つのスレッドは 2 人に載る——返す側と、返事を待っている側。待っている側の行を立てないと、
    自分の指摘が何日返ってこなくても、その PR は自分の一覧のどこにも出ない。"""
    author = login(pr["author"])
    created = pr["createdAt"]
    rows = []
    # 下書きのレビューは相手を待たせないが、送れるのは書いた本人だけ。行を立てないと、
    # 依頼が既に消えている PR では 16 件書いたまま誰の一覧にも出ない。作者の形式上の行とは
    # 別人の行なので、そちらの「まだ行が無い」判定には混ぜない
    draft = pr.get("pendingReview")
    if draft:
        rows.append((draft["by"], "未送信", draft["since"]))
    turns = thread_turns(pr)
    for who in sorted({w for _, w, _, _ in turns if w != author}, key=str):
        ats = [c["createdAt"] for _, w, c, _ in turns if w == who]
        rows.append((who, f"再確認 {len(ats)} 件", min(ats)))
    owed = [(c, waiting) for _, w, c, waiting in turns if w == author]
    if owed:
        rows.append(
            (
                author,
                f"スレッド返答 {len(owed)} 件",
                min(c["createdAt"] for c, _ in owed),
            )
        )
    for p in sorted({p for _, waiting in owed for p in waiting}, key=str):
        ats = [c["createdAt"] for c, waiting in owed if p in waiting]
        rows.append((p, f"返答待ち {len(ats)} 件", min(ats)))

    for a in pr["assignees"]["nodes"]:
        if a["login"] != author:
            assigned = latest(
                e["createdAt"]
                for e in pr["timelineItems"]["nodes"]
                if e["__typename"] == "AssignedEvent"
                and (e.get("assignee") or {}).get("login") == a["login"]
            )
            rows.append((a["login"], "担当", assigned or created))
    return rows


def owes_thread(kinds):
    """未解決スレッドに返す番が残っているか。形式上の状態（再依頼・レビュー）と違い実際に何かを負う"""
    return any(k.startswith(("スレッド返答", "再確認")) for k in kinds)


def shared_balls(rows):
    """merge_rows の結果から、相手にも返す番が残っている人を返す。

    会話のボールが 2 人以上に立っている PR は、その 1 人が全部片づけても終わらない。作者は
    「スレッド返答」、スレッドを立てた人は「再確認」を負うので、両方が立てば両者が該当する。"""
    owing = {who for who, (kinds, _) in rows.items() if owes_thread(kinds)}
    return owing if len(owing) > 1 else set()


def waiting_on_others(pr, who, kinds):
    """その人が最後に発言していて、未解決スレッドに返す番も残っていない＝相手の返事待ち。

    「再依頼」「レビュー」は形式上の状態（依頼が残っているか）だけで立つので、指摘に全部返した後も、
    レビュアーが質問を投げて答えを待っている間も消えない。日数だけが伸びて上を占めるため段を分ける。
    """
    if owes_thread(kinds):
        return False
    # 未解決スレッドで自分が作者の返事を待っているなら、最後に喋ったのが誰でも作者の番。
    # 最後の発言者だけで見ると、作者が別件のコメントを 1 つ挟むだけでボールが自分に戻る。
    # 待っている人からは作者が除かれているので、この節が作者の行で立つことはない
    if any(who in waiting for _, _, _, waiting in thread_turns(pr)):
        return True
    last = latest_human_post(posts_of_pr(pr))
    return bool(last) and login(last["author"]) == who


def blocked_by_others(pr, who, kinds):
    """作者しか外せない障害が残っていて、その人の残りが再確認だけか。

    作者でない人にとって main 未追従・衝突・CI 赤はどれも手が出せない。それでも
    「再確認 N 件」は立ち続けるので、上段に置くと本当に動かせる行を押し下げる。
    残りが再確認だけのときに限る——同じ PR に未消化のレビュー依頼があるなら、
    作者が詰まっていてもその人にしかできない仕事が残っている。

    相手にも返す番が残っているだけなら降ろさない（それは shared の 1 段目）。答えの
    返ってきたスレッドを閉じるのは、相手を待たずに今できる仕事だから。"""
    if login(pr["author"]) == who or not kinds:
        return False
    if not all(k.startswith(("再確認", "返答待ち")) for k in kinds):
        return False
    return bool(pr["mergeStateStatus"] in AUTHOR_ONLY_MERGE or red_checks(pr))


def tier(pr, who, kinds, reviewers, waiting, shared=False):
    """0 = あなたを待っている人がいて、動かせるのはその人だけ / 1 = 同じだが動ける人がほかにもいる /
    2 = まだ誰にも渡していない（draft・未依頼） / 3 = 相手が動くまで進まない。

    1 になるのは「レビュー」だけの行で同じ PR に Bot 以外（人か Team）のレビュー依頼先が
    2 つ以上あるとき、または同じ PR の相手にも返す番が残っているとき（shared）。後者を 0 に
    置くと「その人しか動かせない」が偽になる。相手が自分のスレッドに答えるまで、その人が
    全部再確認しても PR は終わらない。

    2 を 3 から分けるのは、渡していない PR は誰も待っていないが動かせるのは本人だけで、
    相手待ちと同じ段に置くと本当のボールが沈むため。"""
    # 「未依頼」でも作者以外の assignee がいれば、レビュー依頼のボタンを押さずに人へ渡してある。
    # 渡していない扱いにすると、相手が閉じるか進めるかを決める番の PR が自分の一覧に出続ける
    # （実測 2026-08-23・IL-SW-AI/guided-resolver #1403: assignee を付けて「扱いはお任せします、
    # 不要だったら閉じてください」と書いた PR が 6 日「まだ誰にも渡していない」に居座っていた）。
    # draft は例外にしない——作者が自分で「まだ出さない」と印を付けた状態だから
    handed = kinds == ["未依頼"] and any(
        a["login"] != login(pr["author"]) for a in pr["assignees"]["nodes"]
    )
    # 渡していない判定が先。draft・未依頼は誰も待っていないので waiting も立つが、
    # 動かせるのは本人だけで、相手待ちと同じ段に入れると本当のボールが沈む
    if set(kinds) <= HANDOFF and not handed:
        return 2
    # 依頼中の作者は相手が返すまで手が無い。waiting は「最後に発言したのが本人」で判定するので、
    # 依頼を出しただけでまだ誰も発言していない PR では立たず、既定の 0（私のボール）に落ちる
    if kinds == ["レビュー待ち"]:
        return 3
    if waiting or blocked_by_others(pr, who, kinds):
        return 3
    if shared or (kinds == ["レビュー"] and reviewers > 1):
        return 1
    return 0


def merge_rows(rows):
    """同じ人の行をまとめる。{誰: ([種別...], 最も古い日時)}"""
    out = {}
    for who, kind, since in rows:
        kinds, old = out.get(who, ([], None))
        out[who] = (kinds + [kind], min(since, old) if old else since)
    return out


def check_time(c):
    # 実行中の再実行には completedAt が無い。時刻の無いものを最新に倒さないと古い失敗が残る
    return c.get("completedAt") or c.get("createdAt") or "\uffff"


def red_checks(pr):
    """緑でないチェック。同じ名前が複数あるときは最後の実行だけを見る。

    rollup は名前ごとに 1 件ではなく check suite ごとに 1 件返す。ラベル付与や再実行で
    workflow がもう一度走ると、同じ名前の古い失敗と新しい成功が並んで入る（実測: #1468 の
    head a17e8a25 で cloud-render-invariance が failure 2026-08-21T08:52:08Z と
    success 08:55:11Z の 2 件。08:54:43 の cloud-render-change ラベル付与による再実行で
    通っている）。全件を走査すると古い方を拾い、その PR は永久に赤のままになる。

    別々の workflow が同名の job を持つと畳んでしまうが、必須チェックは名前で指定するもので、
    その状態は元から区別がつかない。
    """
    rollup = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
    checks = rollup["contexts"]["nodes"] if rollup else []
    newest = {}
    for c in checks:
        key = c.get("name") or c.get("context")
        if key not in newest or check_time(c) > check_time(newest[key]):
            newest[key] = c
    return [
        c
        for c in newest.values()
        if (c.get("conclusion") or c.get("state") or "") not in GREEN
    ]


def thread_turns(pr):
    """未解決スレッドで返す番がある人と、その人が読むべき発言。
    [(スレッド, 番の人, 読む発言, その人の返事を待っている人)]。4 つ目は作者の行だけ非空。

    番は人数で決まらない。1 つのスレッドが同時に複数人に載る——作者は自分の最後の発言より後に
    来た指摘に答える番、レビュアーは自分の指摘の後に作者が返した内容を再確認する番で、レビュアーが
    2 人以上入ると両方が同時に立つ。作者が bob に答えた後 carol が別の問いを足したら、bob は
    再確認する番で、作者は carol に答える番である。

    ここを「スレッドごとに 1 人」に潰すと、潰した側が黙って落ちる。最後の発言者で決めると
    carol の相槌ひとつで bob の再確認が消え（材料も bob の指摘から carol の相槌に化ける）、
    立てた人と作者の往復だけで決めると carol の問いが誰の一覧にも出ない。

    作者が立てたスレッドは見ない。指摘ではなく自注で、返す義務の起点にならない。"""
    author = login(pr["author"])
    out = []
    for t in pr["reviewThreads"]["nodes"]:
        humans = [c for c in t["comments"]["nodes"] if not is_bot(c["author"])]
        if t["isResolved"] or not humans or login(humans[0]["author"]) == author:
            continue
        mine = [i for i, c in enumerate(humans) if login(c["author"]) == author]
        after = humans[mine[-1] + 1 :] if mine else humans
        waiting = {login(c["author"]) for c in after}
        if after:
            out.append((t, author, after[-1], waiting))
        others = {login(c["author"]) for c in humans} - {author} - waiting
        for p in sorted(others, key=str):
            out.append((t, p, humans[mine[-1]], set()))
    return out


def answered_threads(pr, by_author):
    """未解決スレッドのうち、レビュアーが再確認する番の（by_author=True）/
    作者が答える番の（False）もの。

    [(その番の人, 読む発言の日時, 差分が動いたか)]。3 つ目は isOutdated——「指摘の後にその行を
    触った」印で、対応済みとは限らない（相手が別の理由で動かした行にも付く）。誰の番かは変えず、
    内訳に数だけ添える。判定に使うのは読む側。"""
    author = login(pr["author"])
    return [
        (who, c["createdAt"], t["isOutdated"])
        for t, who, c, _ in thread_turns(pr)
        if (who != author) == by_author
    ]


def turn_threads(pr, who):
    """その人に返す番がある未解決スレッド。[(スレッド, 読む発言)]。

    数だけでは「相手が直した報告（見て resolve するだけ）」と「相手が問いを返した（答えないと
    止まる）」が区別できない。分けるのに要るのは発言の本文なので、材料として渡す。"""
    return [(t, c) for t, w, c, _ in thread_turns(pr) if w == who]


def pr_facts(pr, who=None, targets=None, repo=""):
    """判断材料。who を渡すと、その人から見た事実（作者は誰か・自分のレビュー・相手の沈黙）も足す。"""
    author = login(pr["author"])
    facts = []
    if pr["isDraft"]:
        facts.append("下書き")
    # 一覧には自分の PR と人の PR が混ざる。やること（直す・依頼する / 読む・答える・resolve する）が
    # 別物なので、作者が自分でないことは行から読めないといけない
    if who and author != who:
        facts.append(f"作者: {author or '退会済み'}")
    asked = [reviewer(rq["requestedReviewer"]) for rq in pr["reviewRequests"]["nodes"]]
    asked = [a for a in asked if a]
    if asked:
        facts.append("レビュー依頼: " + ", ".join(sorted(asked)))
    pending = pr.get("pendingReview")
    if pending and who in (None, pending["by"]):
        facts.append(
            f"未送信のレビュー {pending['comments']} 件。書いただけで相手には届いていない"
        )
    if pr["reviewDecision"] == "CHANGES_REQUESTED":
        facts.append("変更要求が付いている")
    # 承認したのが読んでいる本人なら review_state_fact が同じことをより詳しく言う
    elif pr["reviewDecision"] == "APPROVED" and not review_state_fact(pr, who):
        facts.append("承認済み")
    red = red_checks(pr)
    if red:
        facts.append(
            "CI 赤: "
            + ", ".join(c.get("name") or c.get("context") or "?" for c in red)
            + only_author_can(who, author)
        )
    # main 未追従はマージの段で初めて効く（branch protection の strict）。それ以前の PR に出すと全件に付いて読めなくなる
    if pr["reviewDecision"] == "APPROVED" and pr["mergeStateStatus"] == "BEHIND":
        facts.append(
            "main 未追従（BEHIND）。マージ前に取り込みが要る"
            + only_author_can(who, author)
        )
    others = [
        a["login"]
        for a in pr["assignees"]["nodes"]
        if a["login"] != login(pr["author"])
    ]
    if others:
        facts.append("assignee: " + ", ".join(others))
    unresolved = [t for t in pr["reviewThreads"]["nodes"] if not t["isResolved"]]
    if unresolved:
        humans = [
            [
                login(c["author"])
                for c in t["comments"]["nodes"]
                if not is_bot(c["author"])
            ]
            for t in unresolved
        ]
        # 行は人ごとに出るので、内訳も「作者 / 相手」ではなく誰の番かで書く。作者でない人の行に
        # 「相手の発言で止まっている」と出すと、その「相手」は読んでいる本人を指してしまう
        answered = answered_threads(pr, by_author=True)
        waiting = answered_threads(pr, by_author=False)
        name = author or "作者"  # 退会済みは login が None

        def part(n, label, moved=0):
            if not n:
                return None
            return f"{label} {n}" + (f"（{moved} は差分が動いた）" if moved else "")

        parts = [
            part(
                sum(1 for o, _, _ in answered if o == opener),
                f"{opener or '退会済み'} が再確認",
                sum(1 for o, _, m in answered if o == opener and m),
            )
            for opener in sorted({o for o, _, _ in answered}, key=str)
        ]
        parts += [
            part(len(waiting), f"{name} が返答", sum(1 for _, _, m in waiting if m)),
            part(
                sum(1 for h in humans if h and set(h) == {author}), f"人は {name} だけ"
            ),
            # Bot だけのスレッドにも差分が動いた数を添える。人が誰も発言していないので誰の番でも
            # なく、指摘した行が動いていれば対応済みで resolve するだけ——数に混ざったまま
            # 「未解決 N」を膨らませると、生きている指摘が何件なのかが読めなくなる
            part(
                sum(1 for h in humans if not h),
                "Bot だけ",
                sum(1 for t, h in zip(unresolved, humans) if not h and t["isOutdated"]),
            ),
        ]
        detail = "・".join(p for p in parts if p)
        facts.append(
            f"未解決 {len(unresolved)} スレッド" + (f"（{detail}）" if detail else "")
        )
    facts += review_state_fact(pr, who)
    facts += last_speaker_facts(pr, who)
    facts += stale_reference_facts(pr, targets, repo)
    return facts


def only_author_can(who, author):
    """作者しか外せない障害に添える持ち主。自分が作者なら余計なので付けない"""
    if who and author != who:
        return f"。外せるのは作者の {author or '退会済み'} だけ"
    return ""


def review_state_fact(pr, who):
    """その人が既に出しているレビュー。承認済みなら残りは resolve 操作で、読む前とは重さが違う"""
    if not who:
        return []
    # COMMENTED は「読んだ」以上を言わないので数えない。判定を出したかどうかだけが効く
    mine = [
        r
        for r in pr["reviews"]["nodes"]
        if login(r["author"]) == who and r["state"] in ("APPROVED", "CHANGES_REQUESTED")
    ]
    if not mine:
        return []
    last = max(mine, key=lambda r: r["submittedAt"])
    return [f"{who} のレビュー: {last['state']}（{local_time(last['submittedAt'])}）"]


def last_speaker_facts(pr, who):
    """最後に発言した人と、その人が最後なら相手がいつから黙っているか。

    自分が最後という事実だけでは催促の宛先も根拠も出ない。宛先は「返す番を負っている人」で、
    最後に喋った人ではない——別件で通りすがりに発言した人を宛先にすると、実際に止めている
    相手が隠れる。誰も番を負っていないときだけ、直近に発言した相手に落とす。"""
    posts = posts_of_pr(pr)
    last = latest_human_post(posts)
    if not last:
        return []
    facts = [
        f"最後の発言: {login(last['author'])}（{local_time(last['at'])}）"
    ]
    if not who or login(last["author"]) != who:
        return facts
    owing = {o for o, _, _ in answered_threads(pr, by_author=True)} - {who}
    if answered_threads(pr, by_author=False):
        owing.add(login(pr["author"]))
    # 同じ人が二度喋れば上書きされ、その人の最新の発言だけが残る
    said = {}
    for p in posts:
        if not is_bot(p["author"]) and login(p["author"]) not in (who, None):
            said[login(p["author"])] = p["at"]
    owing.discard(None)  # 退会済みは催促の宛先にならない
    if not owing and said:
        owing = {max(said, key=said.get)}
    for target in sorted(owing & set(said), key=str):
        facts.append(
            f"{target} は {local_time(said[target])} 以降 発言なし"
        )
    return facts


def stale_reference_facts(pr, targets, repo):
    """未解決スレッドが「別に #N を立てた」と逃がした先のうち、参照後に動いていないもの。

    「別で追います」で閉じた話は、行き先が動かなければ落ちる。targets は open な issue と PR。
    PR も入れるのは、逃がし先が issue とは限らないため（実測 2026-08-23・#1360: 9 ジョブの
    上限を PR #1452 へ委ねており、行き先が止まればこの PR の指摘ごと止まる）。

    絞りは 2 つ。解決済みスレッドは追跡の合意が済んでいるので見ない。この PR より前からある
    行き先も見ない——元からある追跡先で、参照しただけで動く義務は無い。この PR のレビュー中に
    立った行き先だけが「逃がした先」で、それが止まっているのは指摘が落ちた印。"""
    if not targets:
        return []
    stale = set()
    for t in pr["reviewThreads"]["nodes"]:
        if t["isResolved"]:
            continue
        for c in t["comments"]["nodes"]:
            for n in issue_refs(c["body"], repo):
                to = targets.get(n)
                if (
                    to
                    and n != pr["number"]
                    and to["createdAt"] > pr["createdAt"]
                    and to["updatedAt"] <= c["createdAt"]
                ):
                    stale.add((to.get("headRefName") is not None, n))
    if not stale:
        return []
    return [
        "スレッドが逃がした先で、参照後に動いていないもの: "
        + ", ".join(f"{'PR ' if is_pr else ''}#{n}" for is_pr, n in sorted(stale))
    ]


# ---- 呼びかけ -------------------------------------------------------------------


def posts_of_issue(issue):
    posts = [post(issue["id"], issue["author"], issue["createdAt"], issue["body"])]
    posts += [
        post(c["id"], c["author"], c["createdAt"], c["body"])
        for c in issue["comments"]["nodes"]
    ]
    return posts


def posts_of_pr(pr):
    posts = [
        post(c["id"], c["author"], c["createdAt"], c["body"])
        for c in pr["comments"]["nodes"]
    ]
    posts += [
        post(r["id"], r["author"], r["submittedAt"], r["body"])
        for r in pr["reviews"]["nodes"]
        if r.get("body")
    ]
    for t in pr["reviewThreads"]["nodes"]:
        posts += [
            post(c["id"], c["author"], c["createdAt"], c["body"])
            for c in t["comments"]["nodes"]
        ]
    return sorted(posts, key=lambda p: p["at"])


def post(node_id, actor, at, body):
    return {"id": node_id, "author": actor, "at": at, "body": body or ""}


def latest_human_post(posts):
    humans = [p for p in posts if not is_bot(p["author"])]
    return humans[-1] if humans else None


_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTE = re.compile(r"^[ \t]*>.*$", re.M)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# メールアドレスの @ と @org/team は除く。末尾の lookahead が無いと @org/team を org/tea... まで
# 後退して拾ってしまう
_MENTION = re.compile(
    r"(?<![A-Za-z0-9_.@/])@([A-Za-z0-9][A-Za-z0-9_-]*)(?![A-Za-z0-9_/-])"
)
# #1466 と、完全 URL（CLAUDE.md が短縮参照を禁じている箇所は URL でしか書かれない）の両方。
# URL は自リポジトリのものだけ——他所の URL を拾うと番号空間が重なって別物を指す
# （実測 2026-08-23・#1424: argoproj/argo-cd の issues/7673 を自分の 7673 として拾っていた）
_ISSUE_REF = r"(?:#|{}/(?:issues|pull)/)(\d{{1,7}})(?!\d)"


def clean(text):
    return _LINK.sub(r"\1", _QUOTE.sub("", _INLINE.sub("", _FENCE.sub("", text or ""))))


def readable(text):
    """材料として読む用。引用（>）とコードブロックだけ落とし、インラインコードは残す。

    mentions() が使う clean() はインラインコードまで落とす——コードの中の @name を呼びかけに
    数えないため。材料で同じことをすると、指摘の主語（ファイル名・コミット SHA・設定キー）が
    消えて「を新設しました」だけが残り、読んでも何の話か判定できない。"""
    return " ".join(
        _LINK.sub(r"\1", _QUOTE.sub("", _FENCE.sub("", text or ""))).split()
    )


def mentions(text):
    return set(_MENTION.findall(clean(text)))


def issue_refs(text, repo):
    """本文が指す自リポジトリの issue / PR の番号。コード・引用の中は数えない（clean が落とす）"""
    pattern = re.compile(_ISSUE_REF.format(re.escape(repo)))
    return {int(n) for n in pattern.findall(clean(text))}


def unverified_replies(pr, who):
    """本文コメントで who が呼ばれ、その後に who が発言しているもの。返したかは見ていない。

    呼びかけは「後に本人の発言があれば返した」で倒している。スレッドと違い本文コメントは
    返信が紐づかないので、別の話で発言しただけでも返したことになる。ここは機械では決められ
    ないので、件数と在り処だけ出して読む側が見に行けるようにする（黙って倒したままにすると、
    見ていないことが報告のどこにも残らない）。"""
    posts = [p for p in posts_of_pr(pr) if not is_bot(p["author"])]
    body = {c["id"] for c in pr["comments"]["nodes"]}
    return [
        p
        for i, p in enumerate(posts)
        if p["id"] in body
        and login(p["author"]) != who
        and who in mentions(p["body"])
        and any(login(q["author"]) == who for q in posts[i + 1 :])
    ]


def excerpt(body, who, width=60):
    text = readable(body)
    i = text.find("@" + who)
    return cut(text[max(i, 0) :], width)


def unanswered(posts):
    """{呼ばれた login: 材料}。その後に本人のコメントがあれば外す。材料は最初の未返信の呼びかけのもの。"""
    out = {}
    for n, p in enumerate(posts):
        if is_bot(p["author"]):
            continue
        later = {login(q["author"]) for q in posts[n + 1 :]}
        prev = latest_human_post(posts[:n])
        for who in mentions(p["body"]):
            if who == login(p["author"]) or who in later or who in out:
                continue
            out[who] = {
                "post_id": p["id"],
                "since": p["at"],
                "by": login(p["author"]),
                "excerpt": excerpt(p["body"], who),
                "text": readable(p["body"]),
                "reacted": False,  # 後から REACTIONS_QUERY で埋める
                "reply_to_own": bool(prev) and login(prev["author"]) == who,
            }
    return out


def open_prs_referencing(issue, prs=()):
    """issue を相互参照している open PR と、ブランチ名か題名に issue 番号を含む open PR。
    後者は本文で参照していない PR（例: feature/1127-… から作った PR）を拾うため。"""
    refs = {
        e["source"]["number"]
        for e in issue["timelineItems"]["nodes"]
        if e["__typename"] == "CrossReferencedEvent"
        and (e.get("source") or {}).get("__typename") == "PullRequest"
        and e["source"].get("state") == "OPEN"
    }
    token = re.compile(rf"(?<!\d){issue['number']}(?!\d)")
    refs |= {
        p["number"] for p in prs if token.search(p["headRefName"] + " " + p["title"])
    }
    return sorted(refs)


def assigned_at(issue, who):
    return latest(
        e["createdAt"]
        for e in issue["timelineItems"]["nodes"]
        if e["__typename"] == "AssignedEvent"
        and (e.get("assignee") or {}).get("login") == who
    )


def truncated(conn, what, where):
    """取得上限に当たったら、その旨の 1 行。全件取れていれば None。"""
    if conn["totalCount"] > len(conn["nodes"]):
        return f"{where}: {what} {conn['totalCount']} 件のうち {len(conn['nodes'])} 件しか見ていない"
    return None


# timelineItems は上限検査に入れない。totalCount が itemTypes で絞る前の総数を返すため
# （実測: #1471 は履歴 5 件のうち対象 1 件）、比べても常に「足りない」になる。代わりに last: 100 で取る
def limits_of_pr(pr):
    where = f"#{pr['number']}"
    conns = [
        (pr["assignees"], "assignee"),
        (pr["reviewRequests"], "レビュー依頼"),
        (pr["reviews"], "レビュー"),
        (pr["comments"], "コメント"),
        (pr["reviewThreads"], "スレッド"),
    ]
    conns += [
        (t["comments"], "スレッド内コメント") for t in pr["reviewThreads"]["nodes"]
    ]
    rollup = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
    if rollup:
        conns.append((rollup["contexts"], "チェック"))
    return [truncated(c, w, where) for c, w in conns]


def limits_of_issue(issue):
    where = f"#{issue['number']}"
    conns = [
        (issue["assignees"], "担当"),
        (issue["comments"], "コメント"),
    ]
    return [truncated(c, w, where) for c, w in conns]


def fill_reactions(waits):
    """呼びかけ候補の投稿に、呼ばれた本人がリアクションしているかを埋める。戻り値は上限到達の行。"""
    ids = sorted({info["post_id"] for _, info, _ in waits})
    reactors, limits = {}, []
    for start in range(0, len(ids), 50):
        batch = ids[start : start + 50]
        args = ["api", "graphql", "-f", "query=" + REACTIONS_QUERY] + [
            a for i in batch for a in ("-f", f"ids[]={i}")
        ]
        data = json.loads(gh(*args))
        if data.get("errors"):
            sys.exit(
                "GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False)
            )
        for node in data["data"]["nodes"]:
            if not node:
                continue
            reactors[node["id"]] = {
                login(r["user"]) for r in node["reactions"]["nodes"]
            }
            limits.append(truncated(node["reactions"], "リアクション", node["id"]))
    for who, info, _ in waits:
        info["reacted"] = who in reactors.get(info["post_id"], set())
    return [w for w in limits if w]


# ---- 表示 ------------------------------------------------------------------


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cut(s, w):
    out = ""
    for c in s:
        if width(out + c) > w:
            return out + "…"
        out += c
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__ + "\n" + NOT_SEEN.format(teams="", unverified=""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "login", nargs="?", help="対象の GitHub ログイン（省略時は gh の認証ユーザー）"
    )
    ap.add_argument("--repo", help="OWNER/NAME（省略時はカレントリポジトリ）")
    ap.add_argument("--all", action="store_true", help="自分ではなく全員分を人別に出す")
    ap.add_argument(
        "--materials",
        action="store_true",
        help="末尾に、呼びかけの投稿と、返す番があるスレッドの最後の発言の全文を判定の材料として付ける（印より下は貼らない前提。gh で読み直さずに済む）",
    )
    a = ap.parse_args(argv)

    repo = (
        a.repo
        or gh(
            "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"
        ).strip()
    )
    owner, name = repo.split("/", 1)
    me = a.login or gh("api", "user", "--jq", ".login").strip()
    now = dt.datetime.now(dt.timezone.utc)

    def days(ts):
        return (now - dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))).days

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        prs_f = pool.submit(fetch_all, PR_QUERY, owner, name, "pullRequests")
        issues_f = pool.submit(fetch_all, ISSUE_QUERY, owner, name, "issues")
        prs, issues = prs_f.result(), issues_f.result()

    # 判定に入る前に一度だけ落とす。読む側が 1 箇所でも生データを見ると、そこだけ下書きが混ざる
    for p in prs:
        drop_pending(p)

    limits = []
    balls = {}  # (who, pr number) -> ([kinds], since)
    idle = {}  # (who, pr number) -> 相手の返事待ちか
    shared = {}  # (who, pr number) -> 相手にも返す番が残っているか
    pr_waits = []  # (who, info, pr)
    for p in prs:
        limits += limits_of_pr(p)
        rows = merge_rows(pr_balls(p))
        owing = shared_balls(rows)
        for who, (kinds, since) in rows.items():
            balls[(who, p["number"])] = (kinds, since)
            idle[(who, p["number"])] = waiting_on_others(p, who, kinds)
            shared[(who, p["number"])] = who in owing
        pr_waits += [(who, info, p) for who, info in unanswered(posts_of_pr(p)).items()]
    issue_waits = []
    for i in issues:
        limits += limits_of_issue(i)
        issue_waits += [
            (who, info, i) for who, info in unanswered(posts_of_issue(i)).items()
        ]
    limits += fill_reactions(pr_waits + issue_waits)
    limits = [w for w in limits if w]
    unassigned = sum(1 for i in issues if not i["assignees"]["nodes"])
    by_number = {p["number"]: p for p in prs}
    # 逃がした先は issue とは限らない。open な PR も行き先として引ける形にする
    targets = {x["number"]: x for x in issues + prs}

    reviewers = {}  # PR 番号 -> Bot 以外（人か Team）のレビュー依頼先の数
    for (_, n), (kinds, _) in balls.items():
        reviewers[n] = reviewers.get(n, 0) + ("レビュー" in kinds)

    def pr_rows(who):
        """(段, いつから, 番号) を段の順・古い順で。段は並びの鍵で、印字はしない"""
        rows = []
        for (w, n), (kinds, since) in balls.items():
            if w != who:
                continue
            t = tier(
                by_number[n],
                who,
                kinds,
                reviewers[n],
                idle[(who, n)],
                shared[(who, n)],
            )
            rows.append((t, since, n))
        return sorted(rows)

    def pr_lines(who, rows, indent=""):
        lines = []
        for _, since, n in rows:
            p = by_number[n]
            lines.append(
                f"{indent}  #{n:<5} {days(since):>3} 日  {cut(p['title'], 62)}"
            )
            for f in pr_facts(p, who, targets, repo):
                lines.append(f"{indent}    {f}")
        return lines

    def wait_lines(waits, indent=""):
        lines = []
        for who, info, item in sorted(waits, key=lambda w: w[1]["since"]):
            tags = []
            if info["reply_to_own"]:
                tags.append("直前はあなたの発言")
            if info["reacted"]:
                tags.append("あなたが 👍 済み")
            refs = (
                open_prs_referencing(item, prs)
                if "comments" in item and "reviewThreads" not in item
                else []
            )
            if refs:
                tags.append("open PR " + ", ".join(f"#{r}" for r in refs) + " が参照")
            lines.append(
                f"{indent}  #{item['number']:<5} {local_time(info['since'], '%Y-%m-%d')} から {days(info['since']):>3} 日  {cut(item['title'], 56)}"
            )
            lines.append(
                f"{indent}         {info['by']}: 「{info['excerpt']}」"
                + (f"  [{' / '.join(tags)}]" if tags else "")
            )
        return lines

    def issue_lines(items, indent=""):
        lines = []
        for i in sorted(items, key=lambda i: assigned_at(i, me) or i["createdAt"]):
            at = assigned_at(i, me)
            stamp = f"{days(at):>3} 日" if at else f"最終更新 {local_time(i['updatedAt'], '%Y-%m-%d')}"
            refs = open_prs_referencing(i, prs)
            lines.append(
                f"{indent}  #{i['number']:<5} {stamp}  {cut(i['title'], 62)}"
                + (
                    f"  [open PR {', '.join('#' + str(r) for r in refs)} が参照]"
                    if refs
                    else ""
                )
            )
        return lines

    print(
        f"# 残件 — {repo} — {'全員' if a.all else me} — {now.astimezone(LOCAL_TZ):%Y-%m-%d %H:%M %Z}"
    )
    print(
        f"  open PR {len(prs)} 件・open issue {len(issues)} 件を全件判定"
        f"（issue の担当未設定 {unassigned} 件は誰の一覧にも出ない）。"
        "N 日 = 今の状態になってからの日数"
    )
    if a.all:
        for title, keep in BUCKETS:
            print(f"\n## {title} — PR")
            for who in sorted({w for w, _ in balls}, key=str):
                rows = [r for r in pr_rows(who) if keep(r[0])]
                if not rows:
                    continue
                print(f"  {who} — {len(rows)} 件")
                print("\n".join(pr_lines(who, rows, "  ")))
        print("\n## 返していない呼びかけ")
        for who in sorted({w for w, _, _ in pr_waits + issue_waits}):
            mine = [w for w in pr_waits + issue_waits if w[0] == who]
            print(f"  {who} — {len(mine)} 件")
            print("\n".join(wait_lines(mine, "  ")))
    else:
        rows = pr_rows(me)
        for title, keep in BUCKETS:
            bucket = [r for r in rows if keep(r[0])]
            print(f"\n## {title} — PR {len(bucket)} 件")
            print("\n".join(pr_lines(me, bucket)))
        # PR と issue は番号が 1 本なので、呼びかけは種別で分けずに古い順に並べる
        mine = [w for w in pr_waits + issue_waits if w[0] == me]
        print(f"\n## 返していない呼びかけ — {len(mine)} 件")
        print("\n".join(wait_lines(mine)))
        asg = [i for i in issues if me in {x["login"] for x in i["assignees"]["nodes"]}]
        print(f"\n## 担当 issue — {len(asg)} 件")
        print("\n".join(issue_lines(asg)))
    print("\n走査の上限に当たったもの: " + ("なし" if not limits else ""))
    for w in limits:
        print("  " + w)
    teams = sum(
        1
        for p in prs
        for r in p["reviewRequests"]["nodes"]
        if (r["requestedReviewer"] or {}).get("__typename") == "Team"
    )
    unverified = {}
    for who in sorted({w for w, _ in balls}, key=str) if a.all else [me]:
        for p in prs:
            n = len(unverified_replies(p, who))
            if n:
                unverified[p["number"]] = unverified.get(p["number"], 0) + n
    print(
        "\n"
        + NOT_SEEN.format(
            teams=f"（該当 {teams} 件）",
            unverified=(
                "\n    該当 {} 件（返したことにしている分の在り処）: {}".format(
                    sum(unverified.values()),
                    " ".join(f"#{n}" for n in sorted(unverified)),
                )
                if unverified
                else "（該当 0 件）"
            ),
        )
    )
    if a.materials:
        waits = (
            pr_waits + issue_waits
            if a.all
            else [w for w in pr_waits + issue_waits if w[0] == me]
        )
        print(f"\n{MATERIALS_MARK}")
        for who, info, item in sorted(waits, key=lambda w: w[1]["since"]):
            kind = "PR" if "reviewThreads" in item else "issue"
            print(
                f"\n### {kind} #{item['number']} → {who}  {info['by']} {local_time(info['since'], '%Y-%m-%d')}"
            )
            print(cut(info["text"], 1500))
        for who in sorted({w for w, _ in balls} if a.all else {me}, key=str):
            for n in sorted(n for w, n in balls if w == who):
                for t, last in turn_threads(by_number[n], who):
                    where = t["path"] + (f":{t['line']}" if t["line"] else "")
                    moved = "・差分が動いた" if t["isOutdated"] else ""
                    print(
                        f"\n### PR #{n} スレッド → {who}  {where}"
                        f"  {login(last['author'])} {local_time(last['createdAt'], '%Y-%m-%d')}{moved}"
                    )
                    print(cut(readable(last["body"]), 1500))


if __name__ == "__main__":
    main()
