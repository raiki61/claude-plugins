#!/usr/bin/env python3
"""open な PR と issue の全件から、あなたのターンの件と判断材料を機械で取り切って出す。

〈目的〉「自分の番の PR は」「担当 issue は」「呼ばれて返していないのは」に答える材料を、
GitHub から取れる範囲で全部、決定的に集める。判断（返信が要るか・急ぎか）はしない——
それは読む人か、/whose-turn の AI の仕事。母集団と、見ていないものを必ず併記する。
各行の 2 行目はその PR / issue の URL——読む側が番号をリンクにするための材料。

〈PR のターン〉1 つの PR が複数人に載る。形式上の状態と会話の状態を別の信号として出す。信号は
ASCII のキーで持ち（判定が比べるだけで、印字はしない）、括弧の中は日本語の呼び名。
返答できる人は User のアカウント（Bot・Mannequin・Organization・退会済みでない人）。持ち主は、
返答できる assignee がいて作者がその中にいなければその全員（作者は渡し終えている）、それ以外は作者。
assignee の種別が取れない GitHub（assignedActors が無い）では作者。
持ち主の側は作者と持ち主で、スレッドではこの側が答える:
  draft              持ち主。draft のまま
  ci_red（CI 赤）    持ち主。head commit のチェックに SUCCESS / NEUTRAL / SKIPPED / PENDING /
                     EXPECTED / CANCELLED / STALE 以外の結論がある（未知の値は赤に倒す）
  changes_requested（指摘対応）
                     持ち主。reviewDecision が CHANGES_REQUESTED で、最新の意見が変更要求の人のうち
                     レビュー依頼が出ていない人がいる（全員に再依頼が出ていればターンはレビュアー）
  review（レビュー） 依頼先。Bot 以外（人か Team）へのレビュー依頼が未消化（copilot 等の Bot 宛は数えない）
  awaiting_review（レビュー待ち）
                     持ち主。その依頼が残っている間。持ち主に動かせることは無いが、行を立てないと
                     open な PR が持ち主のどの段にも出ず、依頼を出したことごと一覧から消える
  merge（マージ）    持ち主。APPROVED で依頼も残っていない（main 未追従なら併記）
  rerequest（再依頼）持ち主。持ち主の側でない人のレビューが付いて依頼が消えたまま
  review_requested（レビュー依頼）
                     持ち主。Bot 以外へ依頼を出したが、レビューが付かないまま依頼も消えた
  unrequested（未依頼）
                     持ち主。Bot 以外へレビューを依頼したことが一度も無い。相手はこの PR を知らないので、
                     「待ち」は作成日ではなく最後に動かした日（head commit）から数える
  unclassified（分類なし）
                     持ち主。reviewDecision が上のどれでもない値
  pending_review（未送信）
                     レビューを書いた人。下書き（PENDING）のまま送っていない。相手には届いていない
  awaiting_reply（返答待ち）
                     指摘した人。未解決スレッドで自分の指摘の後に答える側がまだ返していない。持ち主が
                     自分で立てた問いには立てない
  thread_reply（スレッド返答）
                     持ち主（側の人が立てたスレッドでは、側の残りの人）。未解決スレッドで答える側の
                     最後の発言の後に指摘が来ている
  recheck（再確認）  指摘した人。未解決スレッドで自分の指摘の後に答える側が返した（再依頼は押されていない）
  assigned（担当）   返答できる assignee のうち持ち主でない人（作者も assignee の PR の、作者と別の人）。
                     種別が取れない GitHub では作者以外の assignee 全員
持ち主の側の人が立てたスレッドは、側の残りの人への問いとして扱う（渡した作者が受けた人の実装を
レビューする形と、受けた人が作者に聞く形）。側の残りに返答できる人がいなければ自注で、ターンを立てない。
付け替わった PR では、持ち主の行の「待ち」をその人が assignee になった日より前へは戻さない。
「待ち」はその信号が出た日からの日数。PR の作成日ではない。信号の名前は報告に出さない——
読む人が要るのは「今日動かせるか」と、行に添えた事実の方で、語彙を覚えることではない。
並びは「その人が動けば進むか」の 4 段。各段の中では待ちの古い順:
  あなたを待っている人がいる            相手がその人のターンで止まっている。動かせるのはその人だけ
  あなたを待っている人がいる（動ける人はほかにもいる）
                                        同上だが、Bot 以外の依頼先が 2 人以上いるレビュー、持ち主が
                                        2 人以上いる PR で持ち主どうしが共有する行（CI 赤・指摘対応・
                                        マージなど。draft・未依頼だけの行は下の段）、または同じ PR の
                                        相手にも返すターンが残っているもの
  まだ誰にも渡していない                draft・未依頼・未送信のレビュー。待っている人はいないが、
                                        動かせるのはその人だけ
  相手が動くまで進まない                その人が最後に発言してターンも無い（レビューを依頼されている人は
                                        依頼より後の発言だけ数え、本人が解決済みスレッドに書いた
                                        発言は数えない）、依頼したレビューが返って
                                        きていない、または持ち主しか外せない障害（その人が持ち主で
                                        ない PR の main 未追従・衝突・CI 赤）が残っていて、その人の
                                        残りが再確認だけ、または assignee の種別が取れない GitHub で
                                        作者が自分を入れずに assignee を付けた未依頼の PR の作者
上 2 段と 3 段目を分けるのは、渡していない PR は誰も待っていないが動かせるのは本人だけで、
「相手待ち」と混ぜると本当に動かせる件が沈むため。最下段は形式上の状態だけで信号が立ち続け、
待ちの日数だけが伸びるので、混ぜると上を占めて実際に人を止めている行が沈む。

〈呼びかけ〉issue の本文・コメント、PR のコメント・レビュー・スレッドで @login と呼ばれ、
その後に本人のコメントが無いもの。Bot の呼びかけと、コード・引用（>）の中は数えない。
要返信かは判定せず、抜粋・本人の 👍・直前が本人の発言か・参照する open PR を添える。

〈材料〉--materials は呼びかけの全文に加え、返すターンがあるスレッドの最後の発言も全文で出す。
数だけでは「相手が直した報告（見て resolve するだけ）」と「相手が問いを返した（答えないと
止まる）」が区別できず、読む側が段の言い直ししか書けなくなる。

〈出力先〉材料を付けた出力は Claude Code の Bash の 1 回あたりの上限（約 30,000 バイト）を
越える。上限はバイトで測るので、日本語はおよそ 1 万文字で当たる（実測 2026-09-16: 21,870 文字
＝39,375 バイトが退避された）。越えても中身は欠けずツール側がファイルへ退避してパスを返すが、
走らせてから気づく形になり、gh の呼び出しごと 2 回走る。--out は最初からファイルへ書いて
パスだけ返すので、実行が 1 回で済む。読み戻しは Read で行う——cat で読むと同じ量が再び
Bash の出力に乗って、また退避される。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/whose-turn.py、写しは works-dispatch/dispatch/vendor/whose-turn.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/whose-turn.py。

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import outfile  # noqa: E402 — 報告をファイルへ逃がす共通部。/catchup と共用
from ghcli import gh  # noqa: E402 — gh を呼ぶ共通部。/catchup と共用
from ghtext import DONE_NOT_RED, is_bot, mentions, readable, repo_refs  # noqa: E402 — 発言の読み方。/catchup と共用
import turn  # noqa: E402 — PR のターンの持ち主と指摘対応の判定。/catchup と共用
from turn import answerable, assigned_people, login, owner_side, owners  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 赤でないもの。終わって赤でない物（lib/ghtext.py）に、実行中（PENDING と空文字）を足す——ここは
# 「作者が今直すものがあるか」を見るので、まだ終わっていない実行は赤に数えない
GREEN = DONE_NOT_RED | {"PENDING", ""}

MATERIALS_MARK = "==== ここから下は判定の材料。貼らない ===="

# 持ち主しか外せないマージの障害。BEHIND は取り込み、DIRTY は衝突解消で、どちらもブランチを持つ側の仕事
OWNER_ONLY_MERGE = {"BEHIND", "DIRTY"}

# tier() が返す段。0〜2 は今日動かせる（自分の番）、3 は相手が動くまで進まない（相手の番）。
# 報告は 2 つに分けて出し、段そのものは並びのキーとしてだけ使う——動かせる中での優先順は
# 「その人しか動かせない」→「動ける人はほかにもいる」→「まだ誰にも渡していない」の順
MINE = (0, 1, 2)
# (キー, 見出し, 段の選び方)。比べるのはキーで、見出しは印字にだけ使う
BUCKETS = (("mine", "自分の番", lambda t: t in MINE), ("theirs", "相手の番", lambda t: t not in MINE))

# 信号（pr_balls が立てる行の種類）は ASCII のキーで持つ。一覧はファイル冒頭の docstring。日本語の表示の語
# （「再確認 N 件」）で持って startswith で比べていた頃は、語を言い換えると判定が黙って変わった
# （docs/standards/machine-readable-values.md の決まり 3）
# まだ誰にも渡していない状態。待っている人はいないが、動かせるのは本人だけ
HANDOFF = {"draft", "unrequested", "pending_review"}

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
    別リポジトリの行き先は見ない{kinds}"""

# assignedActors の無い GitHub（GHES。cli/cli の featuredetection も actor の API を github.com に限る）
KINDS_NOT_SEEN = """
  - PR の assignee が人か Bot か（この GitHub は assignedActors を返さない。assignee の種別が
    取れないので、作者のターンを assignee へ移さず起票者が持つ形で出した。Bot の assignee も人として
    数えて担当の行を立て、起票者が入っていない assignee がいる未依頼の PR は、渡した扱いにして起票者の
    「相手の番」に置いた）"""

ACTOR = "{ login __typename }"
REVIEWER = "{ __typename ... on User { login } ... on Team { combinedSlug } }"

def pr_query(assignees):
    return f"""
query($owner: String!, $name: String!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    pullRequests(first: 10, states: OPEN, after: $cursor) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number title url headRefName isDraft reviewDecision mergeStateStatus createdAt updatedAt
        body additions deletions changedFiles
        author {ACTOR}
        {assignees}
        reviewRequests(first: 20) {{ totalCount nodes {{ requestedReviewer {REVIEWER} }} }}
        reviews(last: 100) {{ totalCount nodes {{ id state createdAt submittedAt body author {ACTOR} }} }}
        {turn.OPINIONS}
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


PR_QUERY = pr_query(turn.ASSIGNEES)
LEGACY_PR_QUERY = pr_query(turn.LEGACY_ASSIGNEES)

# 呼びかけ候補の投稿だけ、本人のリアクション（👍 で済ませた返答）を後から引く。
# 本体クエリに入れると GraphQL の資源上限に当たる（実測: issue 40 件/ページで "Resource limits exceeded"）
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
        id number title url createdAt updatedAt body
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


class MissingField(Exception):
    """問い合わせたフィールドをその GitHub が持たない（graphql-ruby の静的検証の undefinedField）"""


def fetch_all(query, owner, name, field, optional=()):
    """field の全ページ。optional に挙げたフィールドが無いと返ったときだけ MissingField を投げ、ほかのエラーは止める"""
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
        data = json.loads(gh(*args, graphql_errors=bool(optional)))
        errors = data.get("errors")
        if turn.missing_only(errors, optional):
            raise MissingField()
        if errors:
            sys.exit(
                "GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False)
            )
        conn = data["data"]["repository"][field]
        nodes += conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


def fetch_prs(owner, name):
    """open な PR の全件。assignedActors の無い GitHub では種別なしで取り直す——止めると、その GitHub では
    /whose-turn が丸ごと走らない。取り直した PR には assigneeKindsUnknown の印を付ける"""
    try:
        return fetch_all(PR_QUERY, owner, name, "pullRequests", optional={turn.KINDS_FIELD})
    except MissingField:
        prs = fetch_all(LEGACY_PR_QUERY, owner, name, "pullRequests")
        for p in prs:
            p["assigneeKindsUnknown"] = True
        return prs


# ---- 判定（純粋関数。tests/whose-turn-suite.py が規則を pin する） ------------------


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
    自分の下書きが「相手が返すターン」に化け、実際のボール——送ること——が待ちの側へ沈む。
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


def team_slug(node):
    return node["combinedSlug"] if (node or {}).get("__typename") == "Team" else None


def reviewer(node):
    # User → login / Team → org/slug / それ以外（copilot 等の Bot）→ None
    return team_slug(node) or answerable(node)


def latest(values):
    values = [v for v in values if v]
    return max(values) if values else None


def to_owners(pr, rows):
    """作者の名義で積んだ行を持ち主へ写す（持ち主が 2 人なら 2 人とも）"""
    holders = owners(pr)
    author = login(pr["author"])
    return [(o, kind, since) for who, kind, since in rows for o in (holders if who == author else [who])]


def received_at(pr, who):
    """その人がこの PR を受けた日。作者は作成日、ほかは assign された日（履歴に無ければ None）。
    作者が自分を assign した日へ寄せない——自分で書いた PR の待ちは assign で始まらない。"""
    return pr["createdAt"] if who == login(pr["author"]) else assigned_at(pr, who)


def not_before_received(pr, rows):
    """渡した PR で、持ち主の行（写した形式上の行も、スレッドの行も）の待ちを受けた日より前に戻さない——
    渡される前の日数まで背負わせると、受けたばかりの PR が放置に見える。merge_rows が同じ人の行の
    最も古い日を取るので、1 行でも残すと表示の日数がそこへ戻る。"""
    holders = owners(pr)
    if holders == [login(pr["author"])]:
        return rows
    received = {o: received_at(pr, o) for o in holders}
    return [(who, kind, latest((since, received.get(who)))) for who, kind, since in rows]


def pr_balls(pr):
    """[(誰のターンか, 種別, いつから)]。形式上の状態と会話の状態を別々に出し、同じ人は呼び出し側でまとめる。"""
    rows = to_owners(pr, formal_rows(pr))
    conv = conversation_balls(pr)
    # awaiting_review は、持ち主に他の行が 1 本も無いときだけ残す——既にある行に足すと merge_rows が since を
    # min() で倒し、直近に動かした PR の日数が依頼日まで引き戻されて放置に見える（実測 2026-08-26・
    # IL-SW-AI/guided-resolver: 無条件に積むと #1207 が 4 日 → 29 日、#1450 が 2 日 → 4 日になった）。
    # 持ち主へ写した後で見る——写す前の名義（作者）で見ると、受けた人の行が有っても無いことになる
    busy = {who for who, kind, _ in rows + conv if kind != "awaiting_review"}
    rows = [r for r in rows if r[1] != "awaiting_review" or r[0] not in busy]
    return not_before_received(pr, rows + conv)


def formal_rows(pr):
    """形式上の状態の行。持ち主の分は作者の名義で積み、pr_balls が持ち主へ写す。"""
    author = login(pr["author"])
    created = pr["createdAt"]
    events = pr["timelineItems"]["nodes"]

    def last_event(kind):
        return latest(e["createdAt"] for e in events if e["__typename"] == kind)

    # 持ち主の側がレビューコメントに返信すると、その人の名義の COMMENTED レビューができる。それを
    # 「人のレビュー」に数えると、誰にも頼んでいない PR が rerequest に化ける
    side = owner_side(pr)
    reviews = [r for r in pr["reviews"]["nodes"] if login(r["author"]) not in side]

    def last_review(pred):
        return latest(r["submittedAt"] for r in reviews if pred(r))

    rows = []
    # draft は形式上の状態だけを止める。会話と assignee の行は pr_balls が別に積む——作者が下書きに
    # 戻しても、人が付けた未解決の指摘は生きたままで、返すターンは消えない（実測 2026-08-23・
    # IL-SW-AI/guided-resolver #1308: draft のため、作者が返すターンの 21 スレッドが誰の一覧にも出ていなかった）
    if pr["isDraft"]:
        return [(author, "draft", last_event("ConvertToDraftEvent") or created)]

    red = red_checks(pr)
    if red:
        since = latest(c.get("completedAt") or c.get("createdAt") for c in red)
        rows.append(
            (
                author,
                "ci_red",
                since or pr["commits"]["nodes"][0]["commit"]["committedDate"],
            )
        )
    elif turn.owes_change_requests(pr):
        since = last_review(lambda r: r["state"] == "CHANGES_REQUESTED")
        rows.append((author, "changes_requested", since or created))

    pending = []
    for rq in pr["reviewRequests"]["nodes"]:
        who = reviewer(rq["requestedReviewer"])
        if who is None:
            continue
        asked = requested_at(pr, who)
        pending.append(asked or created)
        rows.append((who, "review", asked or created))

    # 形式上の状態（依頼が残っていなければ持ち主のターン）。CI 赤・指摘対応があればそちらが持ち主の行
    if not pending and not rows:
        if pr["reviewDecision"] == "APPROVED":
            rows.append(
                (
                    author,
                    "merge",
                    last_review(lambda r: r["state"] == "APPROVED") or created,
                )
            )
        # reviewDecision はレビューが 1 件も無い間 null で、Bot の COMMENTED が 1 件付いた
        # 瞬間に REVIEW_REQUIRED になる（実測 2026-08-23・IL-SW-AI/guided-resolver: レビュー 0 件の
        # #1478 は null、Copilot の COMMENTED だけ付いた #1476 は REVIEW_REQUIRED）。null を
        # unclassified に落とすと、立てたばかりの PR が unrequested ではなく最上段に出る
        elif pr["reviewDecision"] in ("REVIEW_REQUIRED", None, ""):
            human = last_review(lambda r: not is_bot(r["author"]))
            asked = latest(
                e["createdAt"]
                for e in events
                if e["__typename"] == "ReviewRequestedEvent"
                and reviewer(e.get("requestedReviewer"))
            )
            if human:
                rows.append((author, "rerequest", human))
            elif asked:
                rows.append((author, "review_requested", asked))
            else:
                # 誰にも頼んでいない PR には待たせている相手がいない。作成日から数えると、書きかけを
                # 寝かせた期間まで「待ち」に入る（実測: #1276 は作成 21 日前・最後の push は 3 日前で、
                # 21 日と出ると放置に見える）。最後に動かした日から数えて、本当に止まった分だけ伸ばす
                rows.append(
                    (
                        author,
                        "unrequested",
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
            rows.append((author, "unclassified", created))

    # 依頼が生きている間、上の分岐は持ち主に 1 行も積まない。そのままだと open な PR が持ち主の
    # どの段にも出ず、一覧から丸ごと消える（実測 2026-08-26・IL-SW-AI/guided-resolver
    # #1413 #1492 #1494: 依頼を出した瞬間に作者の一覧から落ち、出したこと自体が見えなくなった）。
    # 他の行があれば pr_balls が外す
    if pending:
        rows.append((author, "awaiting_review", latest(pending) or created))
    return rows


def requested_at(pr, who):
    """その依頼先に最後にレビューを依頼した日時。履歴に無ければ None"""
    return latest(
        e["createdAt"]
        for e in pr["timelineItems"]["nodes"]
        if e["__typename"] == "ReviewRequestedEvent"
        and reviewer(e.get("requestedReviewer")) == who
    )


def review_since(pr, who):
    """レビューを依頼されている人（formal_rows の review の行と同じ条件）のターンが始まった日時。ほかは None"""
    if pr["isDraft"] or who not in {reviewer(rq["requestedReviewer"]) for rq in pr["reviewRequests"]["nodes"]}:
        return None
    return requested_at(pr, who)


def turn_posts(pr, who):
    """その人のターンを決める発言。依頼された人のターンは依頼した時点で始まるので、依頼より前の発言と、依頼の後に
    本人が解決済みスレッドに書いた発言は数えない。依頼より前の本人の発言（変更要求の本文など）や、解決済みの
    スレッドの「確認しました」で相手待ちに下げると、再依頼した PR が依頼した側にもされた側にも相手のターンに
    なり、誰の自分の番にも出ない（実測 #1843）。依頼の日時が履歴に無ければ全部の発言で見る"""
    posts = posts_of_pr(pr)
    since = review_since(pr, who)
    if since is None:
        return posts
    settled = {c["id"] for t in pr["reviewThreads"]["nodes"] if t["isResolved"] for c in t["comments"]["nodes"]}
    return [p for p in posts if p["at"] >= since and not (p["id"] in settled and login(p["author"]) == who)]


def conversation_balls(pr):
    """未解決スレッド・未送信のレビュー・assignee から立つ行。形式上の状態と違い、draft でも消えない。

    1 つのスレッドは 2 人に載る——返す側と、返事を待っている側。待っている側の行を立てないと、
    自分の指摘が何日返ってこなくても、その PR は自分の一覧のどこにも出ない。

    持ち主には担当の行を立てない。持ち主には写された形式上の行があり、そこへ担当を足すと draft・
    未依頼が「まだ誰にも渡していない」段から外れる。"""
    holders = owners(pr)
    created = pr["createdAt"]
    rows = []
    # 下書きのレビューは相手を待たせないが、送れるのは書いた本人だけ。行を立てないと、
    # 依頼が既に消えている PR では 16 件書いたまま誰の一覧にも出ない。持ち主が書いた下書きは
    # pr_balls の「まだ行が無い」判定で持ち主の行に数える——awaiting_review を足すと merge_rows が
    # since を依頼日へ倒し、書きかけを送るだけの PR が放置に見える。段は届いていない下書きの段 2
    draft = pr.get("pendingReview")
    if draft:
        rows.append((draft["by"], "pending_review", draft["since"]))
    turns = thread_turns(pr)
    for kind, owes in (("recheck", False), ("thread_reply", True)):
        for who in sorted({w for _, w, _, ps in turns if bool(ps) == owes}, key=str):
            rows.append((who, kind, min(c["createdAt"] for _, w, c, ps in turns if w == who and bool(ps) == owes)))
    # 持ち主が 2 人いて両方に返すターンが立っても、待っている側から見れば 1 スレッド。持ち主が自分で
    # 立てた問いには立てない——持ち主の形式上の行（draft・マージなど）は持ち主にしか動かせず、問いを
    # 1 本投げただけで相手の番へ沈めたり、日数を問いの日へ戻したりすると誰も動かさない
    owed = list({id(t): (c, ps) for t, _, c, ps in turns if ps}.values())
    for p in sorted({p for _, waiting in owed for p in waiting} - set(holders), key=str):
        rows.append((p, "awaiting_reply", min(c["createdAt"] for c, waiting in owed if p in waiting)))

    for a in assigned_people(pr):
        if a not in holders:
            rows.append((a, "assigned", received_at(pr, a) or created))
    return rows


def owes_thread(kinds):
    """未解決スレッドに返すターンが残っているか。形式上の状態（rerequest・review）と違い実際に何かを負う"""
    return any(k in ("thread_reply", "recheck") for k in kinds)


def shared_balls(rows):
    """merge_rows の結果から、相手にも返すターンが残っている人を返す。

    会話のボールが 2 人以上に立っている PR は、その 1 人が全部片づけても終わらない。答える側は
    thread_reply、スレッドを立てた人は recheck を負うので、両方が立てば両者が該当する。"""
    owing = {who for who, (kinds, _) in rows.items() if owes_thread(kinds)}
    return owing if len(owing) > 1 else set()


def waiting_on_others(pr, who, kinds):
    """その人が最後に発言していて、未解決スレッドに返すターンも残っていない＝相手の返事待ち。

    rerequest・reviewは形式上の状態（依頼が残っているか）だけで立つので、指摘に全部返した後も、
    レビュアーが質問を投げて答えを待っている間も消えない。日数だけが伸びて上を占めるため段を分ける。
    """
    if owes_thread(kinds):
        return False
    # 未解決スレッドで自分が答える側の返事を待っているなら、最後に喋ったのが誰でも答える側のターン。
    # 最後の発言者だけで見ると、答える側が別件のコメントを 1 つ挟むだけでボールが自分に戻る。
    # 待っている人からはそのスレッドで答える側が除かれているので、返すターンの人の行では立たない
    asked = [t for t, _, _, waiting in thread_turns(pr) if who in waiting]
    if asked and who not in owners(pr):
        return True
    # 持ち主の問いは、awaiting_reply を立てない（conversation_balls）のと同じ理由で段を決めない。本人の発言だけを
    # 最後の発言者に数えない——スレッドごと外すと、相手がそこに書いた答えまで消える
    skip = {c["id"] for t in asked for c in t["comments"]["nodes"] if login(c["author"]) == who}
    last = latest_human_post([p for p in turn_posts(pr, who) if p["id"] not in skip])
    return bool(last) and login(last["author"]) == who


def blocked_by_others(pr, who, kinds):
    """持ち主しか外せない障害が残っていて、その人の残りが再確認だけか。

    持ち主でない人（渡し終えた作者も含む）にとって main 未追従・衝突・CI 赤はどれも手が出せない。
    それでも recheck は立ち続けるので、上段に置くと本当に動かせる行を押し下げる。
    残りが再確認だけのときに限る——同じ PR に未消化のレビュー依頼があるなら、
    持ち主が詰まっていてもその人にしかできない仕事が残っている。

    相手にも返すターンが残っているだけなら降ろさない（それは shared の 1 段目）。答えの
    返ってきたスレッドを閉じるのは、相手を待たずに今できる仕事だから。"""
    if who in owners(pr) or not kinds:
        return False
    if not all(k in ("recheck", "awaiting_reply") for k in kinds):
        return False
    return bool(pr["mergeStateStatus"] in OWNER_ONLY_MERGE or red_checks(pr))


def tier(pr, who, kinds, reviewers, waiting, shared=False):
    """0 = あなたを待っている人がいて、動かせるのはその人だけ / 1 = 同じだが動ける人がほかにもいる /
    2 = まだ誰にも渡していない（draft・未依頼・未送信） / 3 = 相手が動くまで進まない。

    1 になるのは review だけの行で同じ PR に Bot 以外（人か Team）のレビュー依頼先が
    2 つ以上あるとき、持ち主が 2 人以上いる PR で持ち主の全員へ写した形式上の行（draft・未依頼・
    awaiting_review を除く）を持つとき、または同じ PR の相手にも返すターンが残っているとき（shared）。
    これらを 0 に置くと「その人しか動かせない」が偽になる。相手が自分のスレッドに答えるまで、
    その人が全部再確認しても PR は終わらない。

    2 を 3 から分けるのは、渡していない PR は誰も待っていないが動かせるのは本人だけで、
    相手待ちと同じ段に置くと本当のボールが沈むため。"""
    holders = owners(pr)
    # 作者が自分を入れずに assignee を付けた未依頼の PR は、レビュー依頼のボタンを押さずに人へ渡してある
    # （turn.author_holds_handed。作者が持ち主のまま残るのは assignee の種別が取れない GitHub だけ）。誰も発言して
    # いなくても相手が閉じるか進めるかを決めるターンで、作者には相手の番。作者も assignee に入っていれば作者が
    # 持っていて、まだ誰にも渡していない（段 2）。受けた側の draft・未依頼は、最後に誰が喋っても段 2——外すと
    # 誰の「自分の番」にも出ない。draft は例外にしない——作者が自分で「まだ出さない」と印を付けた状態だから
    if kinds == ["unrequested"] and turn.author_holds_handed(pr):
        return 3
    # 渡していない判定が先。draft・未依頼は誰も待っていないので waiting も立つが、
    # 動かせるのは本人だけで、相手待ちと同じ段に入れると本当のボールが沈む
    if set(kinds) <= HANDOFF:
        return 2
    # 依頼中の持ち主は相手が返すまで手が無い。waiting は「最後に発言したのが本人」で判定するので、
    # 依頼を出しただけでまだ誰も発言していない PR では立たず、既定の 0（自分の番）に落ちる
    if kinds == ["awaiting_review"]:
        return 3
    if waiting or blocked_by_others(pr, who, kinds):
        return 3
    if shared or (kinds == ["review"] and reviewers > 1):
        return 1
    if len(holders) > 1:
        # 共有する行は持ち主にしか立たないので、持ち主かは見なくてよい。本人だけの行（自分の問いの再確認など）は段 0
        author = login(pr["author"])
        shared_rows = {k for w, k, _ in formal_rows(pr) if w == author} - HANDOFF - {"awaiting_review"}
        if shared_rows & set(kinds):
            return 1
    return 0


def pr_tiers(pr):
    """{誰: (段, いつから)}。PR 1 件の行を人ごとにまとめて段を決める"""
    rows = merge_rows(pr_balls(pr))
    owing = shared_balls(rows)
    reviewers = sum("review" in kinds for kinds, _ in rows.values())
    return {
        who: (tier(pr, who, kinds, reviewers, waiting_on_others(pr, who, kinds), who in owing), since)
        for who, (kinds, since) in rows.items()
    }


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
    """未解決スレッドで返すターンがある人と、その人が読むべき発言。
    [(スレッド, ターンの人, 読む発言, その人の返事を待っている人)]。4 つ目は返すターンの行だけ非空で、
    再確認の行は空。

    ターンは人数で決まらない。1 つのスレッドが同時に複数人に載る——答える側は自分たちの最後の発言より
    後に来た指摘に答えるターン、レビュアーは自分の指摘の後に答える側が返した内容を再確認するターンで、
    レビュアーが 2 人以上入ると両方が同時に立つ。作者が bob に答えた後 carol が別の問いを足したら、
    bob は再確認するターンで、作者は carol に答えるターンである。

    ここを「スレッドごとに 1 人」に潰すと、潰した側が黙って落ちる。最後の発言者で決めると
    carol の相槌ひとつで bob の再確認が消え（材料も bob の指摘から carol の相槌に化ける）、
    立てた人と作者の往復だけで決めると carol の問いが誰の一覧にも出ない。

    答える側は持ち主の側（作者と持ち主）で、側の誰が返しても返したことになる——受けた assignee の
    返信で、渡す前に作者が返した分も含めて済む。返すターンは持ち主に立つ。側の人が立てたスレッドは
    側の残りの人への問いで、答えるのも返すターンを負うのも残りの人（作者も含む）。残りに返答できる人
    （answerable）がいないスレッドは自注で、返す義務の起点にならないので見ない——持ち主が作者で
    作者が立てたものと、返答できない作者（退会済み・Bot・Mannequin）の PR で受けた人が立てたもの。
    返答できない名義にターンを立てても誰も読まず、立てた人には来ない返事の返答待ちが残る。"""
    holders = owners(pr)
    side = owner_side(pr)
    mute = set() if answerable(pr["author"]) else {login(pr["author"])}
    out = []
    for t in pr["reviewThreads"]["nodes"]:
        humans = [c for c in t["comments"]["nodes"] if not is_bot(c["author"])]
        if t["isResolved"] or not humans:
            continue
        opener = login(humans[0]["author"])
        if opener in side:
            answer = owe = side - {opener} - mute
        else:
            answer, owe = side, set(holders)
        if not answer:
            continue
        mine = [i for i, c in enumerate(humans) if login(c["author"]) in answer]
        after = humans[mine[-1] + 1 :] if mine else humans
        waiting = {login(c["author"]) for c in after}
        if after:
            out += [(t, o, after[-1], waiting) for o in sorted(owe, key=str)]
        others = {login(c["author"]) for c in humans} - answer - waiting
        for p in sorted(others, key=str):
            out.append((t, p, humans[mine[-1]], set()))
    return out


def answered_threads(pr):
    """未解決スレッドのターンを、(答える側が返してレビュアーが再確認するターン, 答える側が返すターン) に分ける。

    どちらも [(そのターンの人, 読む発言の日時, 差分が動いたか)]。3 つ目は isOutdated——「指摘の後にその行を
    触った」印で、対応済みとは限らない（相手が別の理由で動かした行にも付く）。誰のターンかは変えず、
    内訳に数だけ添える。判定に使うのは読む側。"""
    rechecks, owed = [], []
    for t, who, c, waiting in thread_turns(pr):
        (owed if waiting else rechecks).append((who, c["createdAt"], t["isOutdated"]))
    return rechecks, owed


def turn_threads(pr, who):
    """その人に返すターンがある未解決スレッド。[(スレッド, 読む発言)]。

    数だけでは「相手が直した報告（見て resolve するだけ）」と「相手が問いを返した（答えないと
    止まる）」が区別できない。分けるのに要るのは発言の本文なので、材料として渡す。"""
    return [(t, c) for t, w, c, _ in thread_turns(pr) if w == who]


def intro_line(body):
    """本文の最初の 1 文。見出し・空行・HTML コメント・コードブロックを飛ばし、句点か行末で
    切る。無ければ空。"""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    text = text.split("<!--", 1)[0]  # 閉じていないコメントは以降を捨てる（テンプレートの残骸）
    fenced = False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("```"):
            fenced = not fenced
            continue
        # 見出し（# 概要）は題であって説明ではない。囲いの中はコードで、説明ではない
        if fenced or not t or t.startswith(("#", "<", "|")):
            continue
        t = re.sub(r"\*\*|`", "", t)
        # 句点・感嘆・疑問で切る。半角ピリオドは後ろが空白か行末のときだけ（v1.2 を切らない）で、
        # e.g. / i.e. / etc. / cf. / vs. の直後は切らない
        m = re.match(
            r"(.+?(?:[。．！？!?]|(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bcf)(?<!\bvs)\.(?=\s|$)))", t)
        return cut(m.group(1) if m else t, 90)
    return ""


def pr_facts(pr, who=None, targets=None, repo="", intro=False):
    """判断材料。who を渡すと、その人から見た事実（作者は誰か・自分のレビュー・相手の沈黙）も足す。
    intro は自分の番の人の PR にだけ付ける「何の PR か」（作者の本文の 1 文）と規模——件名だけでは
    次の問いが「内容は？」になる（実測）。相手の番には付けない（読まない件で行が増える）。"""
    author = login(pr["author"])
    holders = owners(pr)
    facts = []
    if pr["isDraft"]:
        facts.append("下書き")
    facts += role_facts(pr, who)
    # 担当に渡した作者は自分の PR でも直す側ではないが、本文は自分が書いたので添えない
    if who and author != who:
        if intro:
            line = intro_line(pr.get("body"))
            if line:
                facts.append("本文: " + line)
            if pr.get("changedFiles") is not None:
                facts.append(
                    f"規模: {pr['changedFiles']} ファイル "
                    f"+{pr.get('additions', 0)}/-{pr.get('deletions', 0)}"
                )
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
            + only_owner_can(who, pr)
        )
    # main 未追従はマージの段で初めて効く（branch protection の strict）。それ以前の PR に出すと全件に付いて読めなくなる
    if pr["reviewDecision"] == "APPROVED" and pr["mergeStateStatus"] == "BEHIND":
        facts.append(
            "main 未追従（BEHIND）。マージ前に取り込みが要る"
            + only_owner_can(who, pr)
        )
    # 事実の行なので Bot の assignee も並べる。役割の行（担当に渡した／担当として受けた）で名指した人は重ねない
    named = {author}
    if who and who == author:
        named |= set(holders)
    elif who in holders:
        named.add(who)
    others = [n for n in map(login, pr["assignees"]["nodes"]) if n and n not in named]
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
        # 行は人ごとに出るので、内訳も「作者 / 相手」ではなく誰のターンかで書く。作者でない人の行に
        # 「相手の発言で止まっている」と出すと、その「相手」は読んでいる本人を指してしまう。
        # 返すターンも持ち主が 2 人なら人ごとに書く——名前を 1 つに結ぶと、内訳の区切りと見分けられない
        rechecks, owed = answered_threads(pr)

        def part(n, label, moved=0):
            if not n:
                return None
            return f"{label} {n}" + (f"（{moved} は差分が動いた）" if moved else "")

        def per_person(turns, label):
            return [
                part(sum(o == w for o, _, _ in turns), label(w), sum(o == w and m for o, _, m in turns))
                for w in sorted({o for o, _, _ in turns}, key=str)
            ]

        # 退会済みは login が None
        parts = per_person(rechecks, lambda w: f"{w or '退会済み'} が再確認")
        parts += per_person(owed, lambda w: f"{w or '作者'} が返答")
        # 人が書いたのにターンが 1 つも立たないスレッドは、答えられる人のいない自注（thread_turns）。
        # 書いた人の名で数える——数えないと「未解決 N」の合計にだけ入り、内訳のどこにも出ない。
        # 退会済みの書き手を作者の名へ寄せるのは、作者自身が退会済みのときだけ
        turned = {id(t) for t, _, _, _ in thread_turns(pr)}
        notes = {}
        for t, h in zip(unresolved, humans):
            if h and id(t) not in turned:
                label = ", ".join(sorted({w or ("退会済み" if author else "作者") for w in h}))
                notes[label] = notes.get(label, 0) + 1
        parts += [part(n, f"人は {label} だけ") for label, n in sorted(notes.items())]
        parts += [
            # Bot だけのスレッドにも差分が動いた数を添える。人が誰も発言していないので誰のターンでも
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


def role_facts(pr, who):
    """読む人から見た役割の行。

    一覧には自分の PR と人の PR が混ざる。やること（直す・依頼する / 読む・答える・resolve する）が
    別物なので、作者が自分でないことは行から読めないといけない。担当として受けた PR は作者が
    別でも直す側なので、`作者:` と同じ字面にしない（読む側は `作者:` の有無で役割を分ける）。"""
    if not who:
        return []
    author = login(pr["author"])
    holders = owners(pr)
    if author == who:
        return [] if who in holders else [f"担当に渡した PR（担当は {', '.join(holders)}）"]
    if who in holders:
        return [f"担当として受けた PR（起票は {author or '退会済み'}）"]
    return [f"作者: {author or '退会済み'}"]


def only_owner_can(who, pr):
    """持ち主しか外せない障害に添える持ち主。自分が持ち主なら余計なので付けない"""
    holders = owners(pr)
    if not who or who in holders:
        return ""
    author = login(pr["author"])
    if holders == [author]:
        return f"。外せるのは作者の {author or '退会済み'} だけ"
    return f"。外せるのは担当の {', '.join(holders)} だけ"


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

    自分が最後という事実だけでは催促の宛先も根拠も出ない。宛先は「返すターンを負っている人」で、
    最後に喋った人ではない——別件で通りすがりに発言した人を宛先にすると、実際に止めている
    相手が隠れる。誰もターンを負っていないときだけ、直近に発言した相手に落とす。

    自分が最後かは、段と同じく自分のターンを決める発言（turn_posts）で見る——再依頼された人の依頼より前の
    発言を起点にすると、段は自分の番なのに相手の無言を催促する行が出る。"""
    posts = posts_of_pr(pr)
    last = latest_human_post(posts)
    if not last:
        return []
    facts = [
        f"最後の発言: {login(last['author'])}（{local_time(last['at'])}）"
    ]
    mine = latest_human_post(turn_posts(pr, who)) if who else None
    if not mine or login(mine["author"]) != who:
        return facts
    rechecks, owed = answered_threads(pr)
    owing = {o for o, _, _ in rechecks} - {who}
    owing |= {o for o, _, _ in owed}
    # 同じ人が二度喋れば上書きされ、その人の最新の発言だけが残る
    said = {}
    for p in posts:
        if not is_bot(p["author"]) and login(p["author"]) not in (who, None):
            said[login(p["author"])] = p["at"]
    owing.discard(None)  # 退会済みは催促の宛先にならない
    if not owing and said:
        owing = {max(said, key=said.get)}
    author = login(pr["author"])
    cut_off = any(truncated(c, w, "") for c, w in post_conns(pr))
    for target in sorted(owing - {who}, key=str):
        # 本文の無いレビュー（承認だけなど）も、その PR に居た印
        spoke = latest(
            [said.get(target)] + [r["submittedAt"] for r in pr["reviews"]["nodes"] if login(r["author"]) == target]
        )
        if spoke:
            facts.append(f"{target} は {local_time(spoke)} 以降 発言なし")
            continue
        if target == author and not answerable(pr["author"]):
            continue  # 返答できない作者は催促の宛先にならない（Bot は発言にも数えないので、いつも「発言が無い」になる）
        # 一度も発言していない人は、受けた日から黙っている
        received = received_at(pr, target)
        # 取れた窓の外に発言か受けた日が残っていれば、無いと言えるのは見た範囲だけ。作者は作成日に本文を
        # 書いているので、この PR で発言が無いとは言えない（「作成日 以降 発言なし」だけで真）
        if cut_off or (received is None and timeline_cut(pr)):
            tail = "（見た範囲で発言が無い）"
        else:
            tail = "" if target == author else "（この PR で発言が無い）"
        facts.append(f"{target} は {local_time(received or pr['createdAt'])} 以降 発言なし{tail}")
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


def issue_refs(text, repo):
    """本文が指す自リポジトリの issue / PR の番号。#1466 と、完全 URL（CLAUDE.md が短縮参照を禁じている
    箇所は URL でしか書かれない）の両方。読み方は lib/ghtext.py に 1 つだけ置く。"""
    return repo_refs(text, repo)


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


def assigned_at(item, who):
    return latest(
        e["createdAt"]
        for e in item["timelineItems"]["nodes"]
        if e["__typename"] == "AssignedEvent"
        and (e.get("assignee") or {}).get("login") == who
    )


def truncated(conn, what, where):
    """取得上限に当たったら、その旨の 1 行。全件取れていれば None。"""
    if conn["totalCount"] > len(conn["nodes"]):
        return f"{where}: {what} {conn['totalCount']} 件のうち {len(conn['nodes'])} 件しか見ていない"
    return None


TIMELINE_LAST = 100  # PR_QUERY の timelineItems(last: …) と同じ数


def timeline_cut(item):
    """履歴（timelineItems の last: 100）の古い方が切れている恐れがあるか。100 件ちょうど取れたら切れているとみなす"""
    return len(item["timelineItems"]["nodes"]) >= TIMELINE_LAST


def post_conns(pr):
    """発言を運ぶ接続（posts_of_pr が読む物）と、上限の行に出す名前"""
    conns = [
        (pr["reviews"], "レビュー"),
        (pr["comments"], "コメント"),
        (pr["reviewThreads"], "スレッド"),
    ]
    return conns + [
        (t["comments"], "スレッド内コメント") for t in pr["reviewThreads"]["nodes"]
    ]


# timelineItems は上限検査に入れない。totalCount が itemTypes で絞る前の総数を返すため
# （実測: #1471 は履歴 5 件のうち対象 1 件）、比べても常に「足りない」になる。代わりに last: 100 で取る
def limits_of_pr(pr):
    where = f"#{pr['number']}"
    conns = [
        (pr["assignees"], "assignee"),
        (pr["reviewRequests"], "レビュー依頼"),
        # 切れていると指摘対応を集約値どおり残す（turn.owes_change_requests）
        (pr["latestOpinionatedReviews"], "人ごとの意見"),
    ] + post_conns(pr)
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


def parser():
    ap = argparse.ArgumentParser(
        description=__doc__ + "\n" + NOT_SEEN.format(teams="", unverified="", kinds=""),
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
        help="末尾に、呼びかけの投稿と、返すターンがあるスレッドの最後の発言の全文を判定の材料として付ける（印より下は貼らない前提。gh で読み直さずに済む）",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="「自分の番」の PR だけを機械が読む JSON で出す（番号・URL・タイトル・head のブランチ・役割・日数）。"
        "集合と並びは報告の「自分の番」のセクションと同じ。limited に、判定に使う材料（コメント・レビュー・スレッド・チェック・"
        "履歴）が走査の上限に当たった open な PR の番号（自分の番かの判定が取りこぼしで外れうる物。prs に無い物も含む）。"
        "--materials・--all・--out と一緒に使え、報告と同じ中身（人ごとのセクション・呼びかけ・担当 issue・上限・見ていないもの・材料）を鍵で出す",
    )
    outfile.add_flag(ap)
    return ap


def main(argv=None):
    ap = parser()
    a = ap.parse_args(argv)
    if not a.out:
        return report(a)
    return outfile.run_to_file(
        lambda: report(a), "whose-turn", stop=(MATERIALS_MARK, "材料")
    )


def report(a):
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
        prs_f = pool.submit(fetch_prs, owner, name)
        issues_f = pool.submit(fetch_all, ISSUE_QUERY, owner, name, "issues")
        prs, issues = prs_f.result(), issues_f.result()

    # 判定に入る前に一度だけ落とす。読む側が 1 箇所でも生データを見ると、そこだけ下書きが混ざる
    for p in prs:
        drop_pending(p)

    limits = []
    limited = set()  # 走査の上限に当たった PR の番号（--json の limited。判定が取りこぼしの上に立っている）
    balls = {}  # (who, pr number) -> (段, いつから)
    pr_waits = []  # (who, info, pr)
    for p in prs:
        hit = [w for w in limits_of_pr(p) if w]
        # 履歴（timelineItems）は上限の行に出さない（totalCount が使えない）が、ターンの判定はレビュー依頼などの出来事で
        # 決まるので、last: 100 で 100 件ちょうど取れたら古い方が切れている恐れがあるとして limited に入れる
        if hit or timeline_cut(p):
            limited.add(p["number"])
        limits += hit
        for who, ball in pr_tiers(p).items():
            balls[(who, p["number"])] = ball
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

    def pr_rows(who):
        """(段, いつから, 番号) を段の順・古い順で。段は並びのキーで、印字はしない"""
        return sorted((t, since, n) for (w, n), (t, since) in balls.items() if w == who)

    # 各行の 2 行目は URL。読む側が番号をリンクにする材料で、番号から組み立てさせない——
    # GHES では host が違い、issue と PR で path も違う（/issues と /pull）
    def pr_lines(who, rows, indent="", intro=False):
        lines = []
        for _, since, n in rows:
            p = by_number[n]
            lines.append(
                f"{indent}  #{n:<5} {days(since):>3} 日  {cut(p['title'], 62)}"
            )
            lines.append(f"{indent}    {p['url']}")
            for f in pr_facts(p, who, targets, repo, intro=intro):
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
            lines.append(f"{indent}    {item['url']}")
            # PR の呼びかけには役割の行を添える。読む側がその番号を自分の番へ移すとき、役割を引き直さずに済む
            if "reviewThreads" in item:
                lines += [f"{indent}    {f}" for f in role_facts(item, who)]
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
            lines.append(f"{indent}    {i['url']}")
        return lines

    # 自分の番か・誰のスレッドかなどの見出しの外の値（日数・役割・URL・数）は、ここで構造に組んでから出す。
    # --json は全部を構造で、文の報告は同じ値から人向けに組む（docs/standards/machine-readable-values.md の決まり 1）
    people = sorted({w for w, _ in balls}, key=str) if a.all else [me]
    waits_all = pr_waits + issue_waits
    waits = waits_all if a.all else [w for w in waits_all if w[0] == me]
    teams = sum(
        1
        for p in prs
        for r in p["reviewRequests"]["nodes"]
        if (r["requestedReviewer"] or {}).get("__typename") == "Team"
    )
    unverified = {}
    for who in people:
        for p in prs:
            n = len(unverified_replies(p, who))
            if n:
                unverified[p["number"]] = unverified.get(p["number"], 0) + n
    not_seen = NOT_SEEN.format(
        kinds=KINDS_NOT_SEEN if any(p.get("assigneeKindsUnknown") for p in prs) else "",
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

    if a.json:
        def pr_item(who, since, n, intro):
            p = by_number[n]
            author = login(p["author"])
            item = {
                "number": n,
                "url": p["url"],
                "title": p["title"],
                "head": p["headRefName"],
                "author": author,
                # 直す側（持ち主。担当として受けた人も）か、それ以外か。担当に渡した作者は直す側ではない
                "role": "implementer" if who in owners(p) else "reviewer",
                "days": days(since),
                # 文の報告の各行の下に並ぶ事実の行（人向けの文。読む側が写す物で、語で分岐しない）
                "facts": pr_facts(p, who, targets, repo, intro=intro),
            }
            if intro and author != who:
                item["intro"] = intro_line(p.get("body")) or None
                item["size"] = (
                    {"files": p["changedFiles"], "additions": p.get("additions", 0), "deletions": p.get("deletions", 0)}
                    if p.get("changedFiles") is not None else None
                )
            return item

        def wait_item(who, info, item):
            kind = "pr" if "reviewThreads" in item else "issue"
            refs = open_prs_referencing(item, prs) if kind == "issue" else []
            out = {
                "who": who,
                "kind": kind,
                "number": item["number"],
                "url": item["url"],
                "title": item["title"],
                "since": info["since"],
                "days": days(info["since"]),
                "by": info["by"],
                "excerpt": info["excerpt"],
                "reply_to_own": bool(info["reply_to_own"]),
                "reacted": bool(info["reacted"]),
                "referenced_by_open_prs": refs,
                # PR の呼びかけの役割（sections の role と同じ決め方）。issue には PR の役割が無いので null
                "role": ("implementer" if who in owners(item) else "reviewer") if kind == "pr" else None,
            }
            if a.materials:
                out["text"] = cut(info["text"], 1500)
            return out

        asg = [i for i in issues if me in {x["login"] for x in i["assignees"]["nodes"]}]
        data = {
            "schema": 1,
            "repo": repo,
            "login": me,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            # 「自分の番」の PR（読む側: works-dispatch の dispatch）。集合と並びは sections の me の mine と同じ
            "prs": [
                {
                    "number": n,
                    "url": by_number[n]["url"],
                    "title": by_number[n]["title"],
                    "head": by_number[n]["headRefName"],
                    "role": "implementer" if me in owners(by_number[n]) else "reviewer",
                    "days": days(since),
                }
                for t, since, n in pr_rows(me) if t in MINE
            ],
            # 走査の上限に当たった open な PR の番号（prs に無い物も含む）。自分の番かの判定が取りこぼしで外れうる。
            # 判定に効かないリアクションの上限は入れない
            "limited": sorted(limited),
            "all": bool(a.all),
            "scope": {"open_prs": len(prs), "open_issues": len(issues), "unassigned_issues": unassigned},
            # 人ごとの 2 つのセクション。並びは文の報告と同じ（段の順・古い順）。--all でなければ me だけ
            "sections": [
                {
                    "who": who,
                    **{
                        key: [pr_item(who, since, n, key == "mine") for t, since, n in pr_rows(who) if keep(t)]
                        for key, _title, keep in BUCKETS
                    },
                }
                for who in people
            ],
            # 返していない呼びかけ（古い順）。--materials なら text に投稿の全文（1500 字まで）
            "waits": [wait_item(*w) for w in sorted(waits, key=lambda w: w[1]["since"])],
            # 担当 issue（me の分。文の報告は --all のときは出さない）
            "assigned_issues": [
                {
                    "number": i["number"],
                    "url": i["url"],
                    "title": i["title"],
                    "assigned_days": days(assigned_at(i, me)) if assigned_at(i, me) else None,
                    "updated_at": i["updatedAt"],
                    "referenced_by_open_prs": open_prs_referencing(i, prs),
                }
                for i in sorted(asg, key=lambda i: assigned_at(i, me) or i["createdAt"])
            ],
            "limits": limits,
            # 見ていないもの。死角の確認（スキルの手順 5）が引く数は blind_spots に、全文は not_seen に
            "blind_spots": {
                "team_review_requests": teams,
                "unverified_replies": [{"number": n, "count": unverified[n]} for n in sorted(unverified)],
            },
            "not_seen": not_seen,
        }
        if a.materials:
            # 返すターンがあるスレッドの、相手の最後の発言の全文（1500 字まで）
            data["threads"] = [
                {
                    "who": who,
                    "number": n,
                    "url": by_number[n]["url"],
                    "path": t["path"],
                    "line": t["line"],
                    "outdated": bool(t["isOutdated"]),
                    "author": login(last["author"]),
                    "at": last["createdAt"],
                    "text": cut(readable(last["body"]), 1500),
                }
                for who in people
                for n in sorted(n for w, n in balls if w == who)
                for t, last in turn_threads(by_number[n], who)
            ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(
        f"# 残件 — {repo} — {'全員' if a.all else me} — {now.astimezone(LOCAL_TZ):%Y-%m-%d %H:%M %Z}"
    )
    print(
        f"  open PR {len(prs)} 件・open issue {len(issues)} 件を全件判定"
        f"（issue の担当未設定 {unassigned} 件は誰の一覧にも出ない）。"
        "N 日 = 今の状態になってからの日数"
    )
    if a.all:
        for key, title, keep in BUCKETS:
            print(f"\n## {title} — PR")
            for who in sorted({w for w, _ in balls}, key=str):
                rows = [r for r in pr_rows(who) if keep(r[0])]
                if not rows:
                    continue
                print(f"  {who} — {len(rows)} 件")
                print("\n".join(pr_lines(who, rows, "  ", intro=key == "mine")))
        print("\n## 返していない呼びかけ")
        for who in sorted({w for w, _, _ in pr_waits + issue_waits}):
            mine = [w for w in pr_waits + issue_waits if w[0] == who]
            print(f"  {who} — {len(mine)} 件")
            print("\n".join(wait_lines(mine, "  ")))
    else:
        rows = pr_rows(me)
        for key, title, keep in BUCKETS:
            bucket = [r for r in rows if keep(r[0])]
            print(f"\n## {title} — PR {len(bucket)} 件")
            print("\n".join(pr_lines(me, bucket, intro=key == "mine")))
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
    print("\n" + not_seen)
    if a.materials:
        print(f"\n{MATERIALS_MARK}")
        for who, info, item in sorted(waits, key=lambda w: w[1]["since"]):
            kind = "PR" if "reviewThreads" in item else "issue"
            print(
                f"\n### {kind} #{item['number']} → {who}  {info['by']} {local_time(info['since'], '%Y-%m-%d')}"
            )
            print(cut(info["text"], 1500))
        for who in people:
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
