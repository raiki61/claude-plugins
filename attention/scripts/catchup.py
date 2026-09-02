#!/usr/bin/env python3
"""1 件の PR / issue について「前回自分が触ってから何が起きたか」を機械で取り切り、短く出す。

〈目的〉並行作業から戻ったときに「この作業のどこで止まっていたか」を思い出す。判定（次に何を
するか）はしない——それは読む人か /catchup の AI の仕事。

〈私が最後にしたこと〉この道具の中心は diff ではなく**自分の最後の痕跡**である。本文コメント・
レビュー・レビュースレッド・push を全部見て最も新しい自分の痕跡を「私が最後にしたこと」に置き、
その後に起きたことだけを並べる。自分がまだ一度も触っていないときは、自分に渡された時点
（レビュー依頼・assign・メンションのうち最も新しいもの）に落とし、それも無ければ作成時に落とす。

〈依頼を探す範囲〉push は返事ではない。私宛の依頼を探す範囲は、最後の push ではなく最後の
**発言**（コメント・レビュー・スレッド）より後で切る。push で切ると、push の前に来ていた問いが
答えたことになって消える。

〈commit の主〉GitHub は commit の author をメールで人に結び付ける。結び付いていないメールで
commit していると author の login は空で、名前とメールだけが残る。手元の git config の user.email と
一致する commit は自分の push として扱う——これを怠ると、自分の push が「その後に起きたこと」に
他人の出来事として混ざり、「私が最後にしたこと」が実際より古くなる（実測: 個人メールで commit
している PR で 1 か月ずれた）。名前では照合しない（同名の他人の push を私にしてしまう）。照合に
使う config は実行した場所のものなので、一致しなかった結び付き無しの commit は末尾で申告する。

〈参照は出来事ではない〉他の PR / issue がこの番号を書いた（CrossReferenced）だけでは、この件の
状態は変わらない。時系列に混ぜると表示上限を食い、本当の出来事（コメント・レビュー）を押し出す。
「つながっている先」にだけ置く。

〈変更の地図〉行の要約は出さない。それは思い出す助けにならず、AI が要約すると実物と違う言葉に
なる。自分の PR に戻るとき失われているのは「何を変える PR か」（本文に書いてある）ではなく、会話の
どこで自分が止まったかの方である。ただし作者が私でない PR（レビューで渡された件）では逆で、失われて
いるのは「何の PR か」の方なので、その場合だけ末尾に地図の材料——置き場所・骨組み・配線——を機械で
出す（--map で強制・抑止）。地図でも判断はせず、行は 1 文字も変えない。

〈短さ〉既定の出力は画面 1 つに収める。全文が要るときだけ --full を付ける。長い抜粋を既定に
すると、思い出すための道具が読み直しの作業になり、目的と衝突する。
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の出力が UnicodeEncodeError で落ちる。
# 報告そのものが日本語なので、落ちると道具が丸ごと使えない。UTF-8 に固定する
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# CheckRun.conclusion / StatusContext.state のうち、赤ではないもの。未知の値は赤に倒す
# （CI の結論は増える。知らない値を緑に倒すと、増えた瞬間に検査が黙って甘くなる）
GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED", "EXPECTED", "CANCELLED", "STALE"}

# API の値をそのまま出さず、中身を先に書いて括弧で原語を添える。戻ってきた人が読む報告で
# REVIEW_REQUIRED と書かれても、承認が無いのか承認が要らないのかは読み取れない。原語を残すのは
# grep で追えるようにするためで、消すと GitHub の画面や他の道具の出力と突き合わせられなくなる
APPROVAL = {
    "REVIEW_REQUIRED": "まだ承認されていない（REVIEW_REQUIRED）",
    "CHANGES_REQUESTED": "要修正が付いている（CHANGES_REQUESTED）",
    "APPROVED": "承認済み（APPROVED）",
    None: "レビューがまだ 1 件も無い",
}

MERGEABLE = {
    "MERGEABLE": "衝突なし（MERGEABLE）",
    "CONFLICTING": "衝突あり。解消しないと入らない（CONFLICTING）",
    "UNKNOWN": "GitHub が判定中（UNKNOWN）",
}

# 出来事の種別。spoken だけが「発言」で、依頼を探す範囲の切れ目になる。push は痕跡だが返事ではない
SPOKEN, PUSH, EVENT = "spoken", "push", "event"

QUERY = """
query($owner:String!,$name:String!,$num:Int!){
  repository(owner:$owner,name:$name){
    issueOrPullRequest(number:$num){
      __typename
      ... on PullRequest {
        number title url state isDraft createdAt body
        additions deletions changedFiles mergeable reviewDecision
        files(first:100){totalCount nodes{path changeType additions deletions}}
        author { __typename login }
        assignees(first:10){nodes{login}}
        reviewRequests(first:20){nodes{requestedReviewer{__typename
          ... on User{login} ... on Team{name}}}}
        closingIssuesReferences(first:10){nodes{number title state url}}
        comments(last:100){totalCount nodes{createdAt body author{__typename login}}}
        reviews(last:60){totalCount nodes{submittedAt state body author{__typename login}}}
        reviewThreads(last:80){totalCount nodes{isResolved path line
          comments(first:60){nodes{createdAt body author{__typename login}}}}}
        allCommits: commits(last:100){totalCount nodes{commit{
          oid committedDate messageHeadline additions deletions
          author{user{login} name email}}}}
        head: commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){
          totalCount nodes{__typename
            ... on CheckRun{name conclusion status detailsUrl}
            ... on StatusContext{context state targetUrl}}}}}}}
        timelineItems(last:100, itemTypes:[REVIEW_REQUESTED_EVENT, ASSIGNED_EVENT,
            READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT, CROSS_REFERENCED_EVENT]){
          nodes{__typename
            ... on ReviewRequestedEvent{createdAt actor{login}
              requestedReviewer{__typename ... on User{login} ... on Team{name}}}
            ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}}
            ... on ReadyForReviewEvent{createdAt actor{login}}
            ... on ConvertToDraftEvent{createdAt actor{login}}
            ... on CrossReferencedEvent{createdAt source{__typename
              ... on PullRequest{number title state url}
              ... on Issue{number title state url}}}}}
      }
      ... on Issue {
        number title url state createdAt body
        author { __typename login }
        assignees(first:10){nodes{login}}
        labels(first:20){nodes{name}}
        comments(last:100){totalCount nodes{createdAt body author{__typename login}}}
        timelineItems(last:100, itemTypes:[ASSIGNED_EVENT, CROSS_REFERENCED_EVENT]){
          nodes{__typename
            ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}}
            ... on CrossReferencedEvent{createdAt source{__typename
              ... on PullRequest{number title state url}
              ... on Issue{number title state url}}}}}
      }
    }
  }
}
"""


# ---- 取得 ------------------------------------------------------------------


def gh(*args):
    exe = shutil.which("gh")
    if not exe:
        sys.exit("gh が見つからない（PATH に通す）")
    # GraphQL の 504 は過負荷時に単発で出る。1 回だけ再試行し、2 回目も落ちたら赤で止める
    for attempt in (1, 2):
        # 復号を UTF-8 に固定する。text=True だけだと Windows では locale の code page で復号し、
        # 日本語のタイトルや本文が化けるか UnicodeDecodeError で落ちる
        r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はこのファイル内のリテラルと番号だけ
            [exe, *args], capture_output=True, encoding="utf-8", errors="replace"
        )
        if r.returncode == 0:
            return r.stdout
        if "504" not in r.stderr or attempt == 2:
            sys.exit(f"gh {' '.join(args[:2])} が失敗: {r.stderr.strip()}")
    return None


def local_email():
    """手元の git config の user.email（小文字）。GitHub の login に結び付いていない commit を
    自分のものと見分けるのに使う。git が無い・未設定なら空文字で、その場合は照合しない。"""
    exe = shutil.which("git")
    if not exe:
        return ""
    r = subprocess.run([exe, "config", "--get", "user.email"],  # noqa: S603 — git は which で解決
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.stdout.strip().lower() if r.returncode == 0 else ""


def resolve_target(token, repo_opt):
    """番号か URL から (owner, name, number) を決める。URL なら -R は要らない。"""
    m = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/(?:pull|issues)/(\d+)", token)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    if not token.lstrip("#").isdigit():
        sys.exit(f"番号か PR / issue の URL を渡す（受け取った値: {token}）")
    slug = repo_opt or gh("repo", "view", "--json", "nameWithOwner",
                          "-q", ".nameWithOwner").strip()
    if "/" not in slug:
        sys.exit("リポジトリを特定できない（-R owner/repo を渡すか、リポジトリ内で実行する）")
    owner, name = slug.split("/", 1)
    return owner, name, int(token.lstrip("#"))


def fetch(owner, name, num):
    out = gh("api", "graphql", "-f", "query=" + QUERY, "-f", "owner=" + owner,
             "-f", "name=" + name, "-F", "num=%d" % num)
    data = json.loads(out)
    if data.get("errors"):
        sys.exit("GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False))
    node = data["data"]["repository"]["issueOrPullRequest"]
    if not node:
        sys.exit(f"{owner}/{name} に #{num} が無い")
    return node


# ---- 整形の小道具 ------------------------------------------------------------


def ts(raw):
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()


def hhmm(t):
    return t.strftime("%m-%d %H:%M")


def excerpt(body, limit):
    """本文を 1 行に畳む。引用（>）は落とす——引用だけの返信が自分の発言に化けるため。"""
    lines = [ln for ln in (body or "").splitlines() if not ln.lstrip().startswith(">")]
    s = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if limit and len(s) > limit:
        return s[:limit] + "…"
    return s or "（本文なし）"


def login_of(actor):
    return (actor or {}).get("login") or "（不明）"


def is_bot(actor):
    return (actor or {}).get("__typename") == "Bot"


# ---- 出来事の並び ------------------------------------------------------------


def collect_events(node, me, my_email=""):
    """全部の発言・push・受け渡しを 1 本の時系列にする。基準探しも表示もこれを使う。

    戻り値は (出来事, 参照, 結び付き無し)。参照（他の PR / issue がこの番号を書いた）は出来事に
    混ぜない——この件の状態を変えないのに表示枠を食う。my_email は手元の git config の
    user.email（小文字）で、login に結び付いていない commit をこれで自分のものと見分ける。
    結び付き無しは、それでも誰のものか決められなかった commit の author 名（申告用）。"""
    ev, refs, unlinked = [], [], set()

    def add(t, who, kind, text, cat, bot=False):
        ev.append({"t": ts(t), "who": who, "kind": kind, "text": text,
                   "bot": bot, "cat": cat})

    for c in node["comments"]["nodes"]:
        add(c["createdAt"], login_of(c["author"]), "コメント", c["body"], SPOKEN,
            is_bot(c["author"]))

    for r in node.get("reviews", {}).get("nodes", []):
        # 未送信（PENDING）は submittedAt が null で、相手にも届いていない。時系列には入れず
        # 「止めているもの」側で自分の宿題として扱う
        if r["state"] == "PENDING" or not r["submittedAt"]:
            continue
        label = {"APPROVED": "レビュー（承認）",
                 "CHANGES_REQUESTED": "レビュー（要修正）"}.get(r["state"], "レビュー")
        add(r["submittedAt"], login_of(r["author"]), label, r["body"], SPOKEN,
            is_bot(r["author"]))

    for th in node.get("reviewThreads", {}).get("nodes", []):
        where = th["path"] + (f":{th['line']}" if th["line"] else "")
        state = "解決済" if th["isResolved"] else "未解決"
        for c in th["comments"]["nodes"]:
            add(c["createdAt"], login_of(c["author"]), f"スレッド {where}（{state}）",
                c["body"], SPOKEN, is_bot(c["author"]))

    for n in node.get("allCommits", {}).get("nodes", []):
        c = n["commit"]
        actor = c.get("author") or {}
        who = (actor.get("user") or {}).get("login")
        if not who:
            name, email = (actor.get("name") or "（不明）"), (actor.get("email") or "").lower()
            if my_email and email == my_email:
                who = me
            else:
                who = name
                unlinked.add(name)
        add(c["committedDate"], who, "push",
            f"{c['oid'][:9]} {c['messageHeadline']} (+{c['additions']}/-{c['deletions']})",
            PUSH)

    for it in node.get("timelineItems", {}).get("nodes", []):
        k = it["__typename"]
        if k == "ReviewRequestedEvent":
            r = it.get("requestedReviewer") or {}
            add(it["createdAt"], login_of(it.get("actor")), "レビュー依頼",
                "→ " + (r.get("login") or r.get("name") or "（不明）"), EVENT)
        elif k == "AssignedEvent":
            add(it["createdAt"], login_of(it.get("actor")), "担当",
                "→ " + login_of(it.get("assignee")), EVENT)
        elif k == "ReadyForReviewEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書き解除", "", EVENT)
        elif k == "ConvertToDraftEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書きへ戻す", "", EVENT)
        elif k == "CrossReferencedEvent":
            s = it.get("source") or {}
            if s.get("number"):
                refs.append({"t": ts(it["createdAt"]),
                             "text": f"#{s['number']} {s.get('title', '')}"})

    ev.sort(key=lambda e: e["t"])
    refs.sort(key=lambda e: e["t"])
    return ev, refs, sorted(unlinked)


def find_anchor(ev, node, me):
    """「私が最後にしたこと」を決める。戻り値は (出来事 or None, 種別)。種別は
    mine（私の痕跡）/ handover（私に渡された時点）/ created（作成時）。

    自分の痕跡 → 自分に渡された時点 → 作成時、の順に落とす。渡された時点まで落とすのは、
    まだ一度も触っていない件（依頼が来たきり）でも「何がいつ自分に来たか」は思い出す助けに
    なるため。ここを作成時に直行させると、依頼の存在が出力から消える。"""
    mine = [e for e in ev if e["who"] == me and e["cat"] in (SPOKEN, PUSH)]
    if mine:
        return mine[-1], "mine"

    handover = []
    for e in ev:
        if e["kind"] in ("レビュー依頼", "担当") and e["text"].endswith(me):
            handover.append(e)
        elif e["cat"] == SPOKEN and re.search(r"@" + re.escape(me) + r"\b", e["text"] or ""):
            handover.append(e)
    if handover:
        return handover[-1], "handover"
    return None, "created"


def last_spoken(ev, me):
    """私の最後の発言（push は含まない）。私宛の依頼を探す範囲はここで切る。"""
    mine = [e for e in ev if e["who"] == me and e["cat"] == SPOKEN]
    return mine[-1] if mine else None


# ---- 状態 --------------------------------------------------------------------


def check_state(node):
    """head commit のチェックを ([(赤の名前, URL)], 実行中の数, 緑の数) に畳む。"""
    heads = node.get("head", {}).get("nodes", [])
    rollup = (heads[0]["commit"].get("statusCheckRollup") if heads else None)
    if not rollup:
        return [], 0, 0
    red, running, green = [], 0, 0
    for c in rollup["contexts"]["nodes"]:
        if c["__typename"] == "CheckRun":
            if c["status"] != "COMPLETED":
                running += 1
            elif c["conclusion"] in GREEN:
                green += 1
            else:
                red.append((c["name"], c.get("detailsUrl") or ""))
        else:
            if c["state"] in ("PENDING", "EXPECTED"):
                running += 1
            elif c["state"] == "SUCCESS":
                green += 1
            else:
                red.append((c["context"], c.get("targetUrl") or ""))
    return red, running, green


def role_of(node, me, ev):
    """この件での私の立場。戻ったとき真っ先に要るのがこれで、会話からは読み取りにくい。

    「どちらでもない」と断定しない——名指しで呼ばれただけの件で「どちらでもない · 私の番」と並ぶと
    1 行目の中で食い違って見える。発言していれば参加者、していなければ未参加。"""
    is_pr = node["__typename"] == "PullRequest"
    if login_of(node["author"]) == me:
        return "実装者（作者）" if is_pr else "起票者"
    if is_pr:
        req = [r["requestedReviewer"] for r in node["reviewRequests"]["nodes"]
               if r["requestedReviewer"]]
        reviewed = any(login_of(r["author"]) == me for r in node["reviews"]["nodes"]) \
            or any(login_of(c["author"]) == me
                   for th in node["reviewThreads"]["nodes"] for c in th["comments"]["nodes"])
        if any(r.get("login") == me for r in req) or reviewed:
            return "レビュアー"
    if any(a["login"] == me for a in node["assignees"]["nodes"]):
        return "担当"
    if any(e["who"] == me and e["cat"] == SPOKEN for e in ev):
        return "参加者"
    return "未参加"


def my_turn(node, me, ev, red):
    """「なぜ今それが私の番なのか」を機械で列挙する。空なら私の番ではない。

    理由を出すのは、手番だけ告げられても戻れないため——戻ったときに要るのは、自分が何を
    期待されているかの中身の方である。"""
    is_pr = node["__typename"] == "PullRequest"
    author = login_of(node["author"])
    reasons = []

    if is_pr:
        req = [r["requestedReviewer"] for r in node["reviewRequests"]["nodes"]
               if r["requestedReviewer"]]
        if any(r.get("login") == me for r in req):
            reasons.append("レビュー依頼が私に来ている")
        if any(r["state"] == "PENDING" and login_of(r["author"]) == me
               for r in node["reviews"]["nodes"]):
            reasons.append("書きかけのレビューが未送信（相手には届いていない）")

        waiting = 0
        for th in node["reviewThreads"]["nodes"]:
            if th["isResolved"]:
                continue
            cs = th["comments"]["nodes"]
            if any(login_of(c["author"]) == me for c in cs) \
                    and login_of(cs[-1]["author"]) != me:
                waiting += 1
        if waiting:
            reasons.append(f"未解決スレッド {waiting} 件で相手が返している（私が返す番）")

        if author == me:
            if node["isDraft"]:
                reasons.append("下書きのまま（渡すのは私）")
            if red:
                reasons.append("CI 赤は作者（私）しか外せない")
            if node["mergeable"] == "CONFLICTING":
                reasons.append("衝突の解消は作者（私）")
            if node["reviewDecision"] == "CHANGES_REQUESTED":
                reasons.append("要修正が付いている（指摘対応は私）")
            elif node["reviewDecision"] == "APPROVED" and not req:
                reasons.append("承認済みで依頼も残っていない（マージは私）")
            elif not req and not node["isDraft"]:
                # 誰にも渡していない PR は、渡すまで誰も動けない。ここを「待ち」に落とすと、
                # 自分が止めている件が相手の番に見える
                reasons.append("レビュー依頼が誰にも出ていない（依頼先を決めるのは私）")
    # 自分の PR で assignee にもなっているのは普通の運用で、それだけでは私の番の理由にならない
    # （理由になるのは上の CI・衝突・要修正の側）。issue と人の PR では担当が手番の根拠
    if any(a["login"] == me for a in node["assignees"]["nodes"]) \
            and not (is_pr and author == me):
        reasons.append("私が担当（assignee）")
    return reasons


def waiting_on(node, me):
    is_pr = node["__typename"] == "PullRequest"
    author = login_of(node["author"])
    if is_pr:
        req = [r["requestedReviewer"] for r in node["reviewRequests"]["nodes"]
               if r["requestedReviewer"]]
        names = [r.get("login") or r.get("name") for r in req]
        if names:
            return "レビュー待ち: " + ", ".join(names)
        if author != me:
            return f"作者 {author} 待ち"
    elif author != me:
        return f"起票者 {author} 待ち"
    return "待っている相手は記録に無い"


# ---- 出力 --------------------------------------------------------------------


def find_ask(ev, node, me, cutoff, own):
    """最後に私へ向けられた依頼を 1 つ返す。cutoff より後だけを見る（None なら全期間）。

    自分の最後の発言だけでは戻れない——「相手が今その件で私に何を求めているか」が要る。
    メンション・レビュー依頼・私が返す番の未解決スレッドを同じ土俵で見て、最も新しいものを取る。

    cutoff を None にできるのが要点。自分がまだ発言していない件では、依頼は「渡された時点」より
    前に来ていることがある（本文で頼まれた後にレビュー依頼ボタンが押される順序）。基準より後に
    限ると、その依頼が丸ごと消えて「依頼は来ていない」と出る（実測: レビュー依頼の 27 分前に
    本文で 3 点を名指しで委ねられていた PR で発生）。

    own（自分の PR / 担当の issue）では、名指しの無い発言も最後の 1 件だけ拾う。自分の件への
    発言は宛先を書かないのが普通で（実測: 「main を取り込むと lint が赤になるので合わせて
    ほしい」が @ 無しで来ていた）、名指しだけを待つと丸ごと落ちる。unaddressed=True を付けて
    返し、表示側で「名指しは無い」と断る。拾うのは本文のある発言だけで、解決済みスレッドは
    見ない——本文なしの承認や、push で直して閉じたスレッドが「求められていること」に化ける。"""
    at_me = re.compile(r"@" + re.escape(me) + r"\b")
    later = [e for e in ev if cutoff is None or e["t"] > cutoff]
    hits = [e for e in later if (
        (e["cat"] == SPOKEN and at_me.search(e["text"] or ""))
        or (e["kind"] == "レビュー依頼" and e["text"].endswith(me)))]
    if hits:
        # 本文を持つ発言を、レビュー依頼ボタンより優先する。ボタンは中身が無く、押された順序も
        # 本文の依頼と前後する（本文で頼んでからボタンを押す運用が普通）。新しい方を機械的に
        # 取ると、実際の用件が書いてある方が消える
        spoken = [h for h in hits if h["cat"] == SPOKEN]
        chosen = spoken[-1] if spoken else hits[-1]
        buttons = [h for h in hits if h["cat"] != SPOKEN and h["t"] > chosen["t"]]
        if buttons:
            chosen = dict(chosen, followup=buttons[-1])
        return chosen

    # 名指しが無くても、私が入っている未解決スレッドに相手が返していれば、それが依頼にあたる
    for th in node.get("reviewThreads", {}).get("nodes", []):
        if th["isResolved"]:
            continue
        cs = th["comments"]["nodes"]
        if any(login_of(c["author"]) == me for c in cs) \
                and login_of(cs[-1]["author"]) != me:
            where = th["path"] + (f":{th['line']}" if th["line"] else "")
            return {"t": ts(cs[-1]["createdAt"]), "who": login_of(cs[-1]["author"]),
                    "kind": f"スレッド {where}（未解決）", "text": cs[-1]["body"],
                    "bot": is_bot(cs[-1]["author"]), "cat": SPOKEN}

    if own:
        others = [e for e in later if e["cat"] == SPOKEN and e["who"] != me and not e["bot"]
                  and "（解決済）" not in e["kind"] and excerpt(e["text"], 0) != "（本文なし）"]
        if others:
            return dict(others[-1], unaddressed=True)
    return None


def render(node, me, ev, refs, unlinked, anchor, anchor_kind, full, limit, caps, with_map=False):
    is_pr = node["__typename"] == "PullRequest"
    author = login_of(node["author"])
    out = []
    w = out.append

    def name(who):
        return "私" if who == me else who

    red, running, green = check_state(node) if is_pr else ([], 0, 0)
    reasons = my_turn(node, me, ev, red)

    anchor_t = anchor["t"] if anchor else ts(node["createdAt"])
    spoke = last_spoken(ev, me)
    own = author == me or any(a["login"] == me for a in node["assignees"]["nodes"])
    ask = find_ask(ev, node, me, spoke["t"] if spoke else None, own)
    # 名指しで頼まれて返していない状態は、依頼ボタンも未解決スレッドも無いまま成立する。
    # 形式の信号が 1 つも立たないときの取りこぼしを、これで塞ぐ。他の理由があっても足す——
    # 別の事実で、片方だけ告げると依頼の存在が 1 行目から消える。名指しの無い発言（unaddressed）は
    # 問いかどうか機械では決められないが、自分の件で相手が最後に発言していれば少なくとも読むのは私
    if ask:
        reasons.append("私の件に相手の発言があり、その後に私は発言していない（問いかは本文で確かめる）"
                       if ask.get("unaddressed") else
                       "私宛の依頼が来ていて、その後に私は発言していない")

    kind = "PR" if is_pr else "issue"
    w(f"# #{node['number']} {node['title']}")
    role = role_of(node, me, ev)
    # 理由が 1 つなら 1 行、複数なら箇条書き。／で繋ぐと 3 つで 100 字を超え、端末で折り返して
    # 1 行目の役目（一目で手番と理由）を失う
    if not reasons:
        w(f"  {role} · ○ 待ち — " + waiting_on(node, me))
    elif len(reasons) == 1:
        w(f"  {role} · ● 私の番 — " + reasons[0])
    else:
        w(f"  {role} · ● 私の番")
        for r in reasons:
            w(f"    - {r}")
    head = [f"{kind} {node['state'].lower()}"]
    if author != me:
        head.append(f"作者 {author}")
    if is_pr:
        if node["isDraft"]:
            head.append("下書き")
        head.append(f"{node['changedFiles']} ファイル "
                    f"+{node['additions']}/-{node['deletions']}")
    w("  " + " · ".join(head))
    w("  " + node["url"])
    w("")

    w("## 私が最後にしたこと")
    if anchor_kind == "mine":
        w(f"  {hhmm(anchor['t'])}  {anchor['kind']}")
        w("  " + excerpt(anchor["text"], 0 if full else 220))
    else:
        w("  この件で私はまだ何もしていない")
        if anchor_kind == "handover":
            w(f"  {hhmm(anchor['t'])}  {name(anchor['who'])} の {anchor['kind']} で私に渡された")
        else:
            w(f"  {hhmm(anchor_t)}  作成")
    w("")

    w("## 私に求められていること")
    if ask:
        note = "（名指しは無い。私の件への発言）" if ask.get("unaddressed") else ""
        w(f"  {hhmm(ask['t'])}  {name(ask['who'])} の {ask['kind']}{note}")
        # 依頼の抜粋だけ長めに取る。220 字だと結論の前で切れて用件が読めない（実測: 対象ファイルの
        # パスの途中で切れ、初見の読み手 2 人が「何を直せばよいか分からない」で止まった）
        w("  " + excerpt(ask["text"], 0 if full else 400))
        f = ask.get("followup")
        if f:
            w(f"  （その後 {hhmm(f['t'])} に {name(f['who'])} が {f['kind']} を出している）")
    elif spoke:
        w(f"  私の最後の発言（{hhmm(spoke['t'])}）より後には無い"
          + ("（名指しも、私の件への発言も）" if own else ""))
    else:
        w("  無い")
    w("")

    after = [e for e in ev if e["t"] > anchor_t]
    shown = after if full else after[-limit:]
    w(f"## その後に起きたこと — {len(after)} 件"
      + ("" if len(shown) == len(after) else f"（新しい方から {len(shown)} 件だけ表示）"))
    if not after:
        w("  なし")
    for e in shown:
        who = f"{name(e['who'])} が " if e["who"] else ""
        tag = "[bot] " if e["bot"] else ""
        w(f"  {hhmm(e['t'])}  {tag}{who}{e['kind']}")
        body = excerpt(e["text"], 0 if full else 110)
        if body != "（本文なし）":
            w(f"      {body}")
    w("")

    state = []
    st = state.append
    if is_pr:
        st("  承認: " + APPROVAL.get(node["reviewDecision"], str(node["reviewDecision"]))
           + " ／ 取り込み: " + MERGEABLE.get(node["mergeable"], str(node["mergeable"])))
        # チェックが 1 本も無い状態を「全 pass」と言うと、検査が無いことが緑に化ける
        if not (red or running or green):
            st("  CI: 報告なし")
        else:
            parts = []
            if red:
                names = ", ".join(n for n, _ in red[:3]) + ("…" if len(red) > 3 else "")
                parts.append(f"赤 {len(red)} 件（{names}）")
            if running:
                parts.append(f"実行中 {running} 件")
            if green:
                parts.append(f"緑 {green}")
            st("  CI: " + ("／".join(parts) if red or running else f"全 pass（緑 {green}）"))
            # 赤の行き先を出す。「CI 赤は作者しか外せない」と告げておいて理由への道が無いと、
            # 読む人は自分で探しに行くことになる
            for n, url in red[:3]:
                if url:
                    st(f"      {n}  {url}")
        unresolved = [t for t in node["reviewThreads"]["nodes"] if not t["isResolved"]]
        human = [t for t in unresolved
                 if any(not is_bot(c["author"]) for c in t["comments"]["nodes"])]
        st(f"  未解決スレッド: {len(unresolved)} 件"
           f"（うち人が入っているもの {len(human)} 件）")
    else:
        labels = [lb["name"] for lb in node.get("labels", {}).get("nodes", [])]
        if labels:
            st("  ラベル: " + ", ".join(labels))
    assignees = [a["login"] for a in node["assignees"]["nodes"]]
    # 自分だけが担当の行は、1 行目の立場と重なるので出さない
    if any(a != me for a in assignees):
        st("  担当: " + ", ".join(name(a) for a in assignees))
    if state:
        w("## いまの状態")
        out.extend(state)
        w("")

    linked = node.get("closingIssuesReferences", {}).get("nodes", []) if is_pr else []
    if linked or refs:
        w("## つながっている先")
        for i in linked:
            w(f"  閉じる  #{i['number']} {i['state'].lower()}  {i['title']}")
        # 参照は新しい 3 件だけ。5 件出したら初見の読み手 3 人中 2 人が「読まなくてよかった」と言った。
        # 残すのは、この PR から分かれた後続の PR がここに出るため
        for r in refs[-3:]:
            w(f"  参照    {hhmm(r['t'])}  {r['text']}")
        if len(refs) > 3:
            w(f"  （参照は他に {len(refs) - 3} 件）")
        w("")

    w("見ていないもの:")
    # 上限は「何件切れたか」ではなく「それで何を見落としうるか」まで書く。件数だけでは、
    # 読む人がこの報告のどこを疑えばよいか分からない
    for label, total, got in caps:
        w(f"  - {label}の古い方 {total - got} 件（{total} 件中、新しい {got} 件だけ取った）。"
          "私の痕跡や私宛の依頼がそこにあれば見落とす")
    w("  - GitHub の外（チャット・口頭・メール）でのやり取り")
    if is_pr:
        w(("  - diff の全文（下の地図は置き場所と骨組みと抜粋。gh pr diff で見る）" if with_map
           else "  - 本文と diff の中身（gh pr diff で見る）")
          + ("、CI が落ちた理由（上の URL か gh pr checks で見る）" if red else ""))
    else:
        w("  - 本文の中身（gh issue view で見る）")
    if unlinked:
        w(f"  - GitHub の login に結び付いていない commit（名前: {', '.join(unlinked)}）が誰のものか。"
          "自分のものなら「私が最後にしたこと」は実際より古い（手元の git config の user.email と"
          "一致すれば私の push と数える）")
    w("  - 名指しの無い発言が私への問いかどうか"
      + ("（私の件なので、最後の 1 件だけは上に出した）" if ask and ask.get("unaddressed") else ""))
    if not full:
        w("  - 発言の全文。--full で出る")
    return "\n".join(out)


# ---- 変更の地図（材料） --------------------------------------------------------
#
# 作者が私でない PR を渡されたとき、失われているのは「会話のどこで止まったか」より「何の PR か」の
# 方である。それでも行の要約は出さない（思い出す助けにならず、AI が要約すると実物と違う言葉に
# なる）。出すのは置き場所・骨組み・配線の材料で、判断はしない。AI はここから選んで並べ、散文だけ
# 自分で書く。部品は scripts/lib/changemap.py（/what-am-i-doing と共用）。
#
# 出すもの:
#   - 変更ファイルの一覧（種別と ±行数）と、直近マージの規模の目安
#   - 変更ファイルの木（周辺の既存を薄く並べたもの。そのまま diff の枠に貼れる）
#   - 名前の言及（追加行が他の変更ファイルの名前を含む関係と、その行。呼び出しの当たり）
#   - 新規ファイルの先頭コメント / docstring（作者の自己紹介）と骨組み（step 名・def・上位 key）
#   - 既存ファイルの hunk（変更が小さいものはそのまま。大きいものは @@ の見出しと追加行の骨組み）
#
# 行は 1 文字も変えずに `| ` の後ろに出す。AI が写す元になるので、ここで整えると写した先が実物と
# 違ってしまう。

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402

MAP_HEAD_LINES = changemap.HEAD_LINES
MAP_HUNK_LIMIT = changemap.HUNK_LIMIT
MAP_OUTLINE_CAP = changemap.OUTLINE_CAP
MAP_SIBLINGS_CAP = 40    # 同じ階層の名前の上限（材料の一覧。木は lib が数件に絞る）
MAP_DIFF_CAP = 400_000   # gh pr diff がこの文字数を超えたら中身の抽出をやめる
split_diff, added_lines, file_head = changemap.split_diff, changemap.added_lines, changemap.file_head
outline, call_refs, modified_hunks = changemap.outline, changemap.call_refs, changemap.modified_hunks
unquote_git_path = changemap.unquote_git_path


def gh_try(*args):
    """gh を呼ぶが、失敗しても止めない。地図の材料は無くても本体の報告は成り立つ。"""
    exe = shutil.which("gh")
    if not exe:
        return None
    r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はこのファイル内のリテラルと番号だけ
        [exe, *args], capture_output=True, encoding="utf-8", errors="replace"
    )
    return r.stdout if r.returncode == 0 else None


def sibling_dirs(owner, name, paths):
    """手元の checkout が同じリポジトリなら、変更ファイルと同じ階層の追跡ファイル名を返す。
    違えば None。中身は手元の HEAD のもので、PR の head ではない。"""
    top = changemap.repo_top()
    if not top or not changemap.origin_matches(top, owner, name):
        return None
    sib = changemap.siblings_for(top, paths)
    return [(d, sib[d]) for d in sorted(sib)]


def merged_size_context(owner, name):
    """直近マージ 60 本の行数（追加＋削除）の中央値と上位 25%。「大きい PR か」の目安。"""
    out = gh_try("pr", "list", "-R", f"{owner}/{name}", "--state", "merged",
                 "--limit", "60", "--json", "additions,deletions")
    if not out:
        return None
    sizes = sorted(p["additions"] + p["deletions"] for p in json.loads(out))
    if not sizes:
        return None
    n = len(sizes)
    return n, sizes[n // 2], sizes[min(n - 1, (3 * n) // 4)]


def render_map(node, owner, name):
    out = []
    w = out.append
    files = node.get("files") or {}
    nodes = sorted(files.get("nodes") or [], key=lambda f: f["path"])
    paths = [f["path"] for f in nodes]
    kinds = {f["path"]: f["changeType"] for f in nodes}

    w("## 変更の地図（材料。作者が私でない PR のとき出る。--map no で止める）")
    w("  `| ` の後ろは 1 文字も変えていない。写すときはそのまま使う")
    size = f"{node['changedFiles']} ファイル +{node['additions']}/-{node['deletions']}"
    ctx = merged_size_context(owner, name)
    if ctx:
        size += f" ／ 直近マージ {ctx[0]} 本の中央値 {ctx[1]} 行、上位 25% {ctx[2]} 行"
    w("  規模: " + size)
    if files.get("totalCount", 0) > len(nodes):
        w(f"  変更ファイルは {files['totalCount']} 件中、先頭の {len(nodes)} 件だけ取った")
    w("  変更ファイル（ADDED = 新規）:")
    for f in nodes:
        w(f"    {f['changeType']:9} {'+%d/-%d' % (f['additions'], f['deletions']):<12} {f['path']}")

    sib = sibling_dirs(owner, name, paths)
    if sib is None:
        w("  同じ階層の既存: 出せない（手元がこのリポジトリの checkout ではない）")
    else:
        w("  同じ階層の既存（手元の HEAD が追跡しているファイル。変更ファイル自身も含む）:")
        for d, names in sib:
            if names is None:
                w(f"    {d}/: 手元に無い階層")
                continue
            shown = names[:MAP_SIBLINGS_CAP]
            more = f" …ほか {len(names) - len(shown)}" if len(names) > len(shown) else ""
            w(f"    {d}/ ({len(names)}): " + " ".join(shown) + more)

    entries = []
    for f in nodes:
        mark = {"ADDED": "+", "DELETED": "-"}.get(f["changeType"], "~")
        a, d = f["additions"], f["deletions"]
        note = f"-{d}" if mark == "-" else (f"+{a}" if not d else f"+{a}/-{d}")
        entries.append({"path": f["path"], "mark": mark, "note": note})
    w("  変更ファイルの木（行頭 + が新規・~ が変更・- が削除。そのまま diff の枠に貼る）:")
    for ln in changemap.render_tree(entries, dict(sib) if sib else None, root_label=name):
        w(ln)

    text = gh_try("pr", "diff", str(node["number"]), "-R", f"{owner}/{name}")
    if text is None:
        w("  中身: 出せない（gh pr diff が失敗した）")
        return "\n".join(out)
    if len(text) > MAP_DIFF_CAP:
        w(f"  中身: 出さない（diff が {len(text)} 文字で上限 {MAP_DIFF_CAP} を超える）")
        return "\n".join(out)
    hunks, renames = split_diff(text)

    rel = call_refs([p for p in paths if not p.endswith((".adoc", ".md", ".txt"))], hunks)
    if rel:
        w("  名前の言及（追加行が他の変更ファイルの名前を含む。下の行が uses:・run:・-f・import なら"
          "呼び出し、コメントなら言及だけ）:")
        for a in sorted(rel):
            for b, hits in sorted(rel[a]):
                w(f"    {a} → {b}")
                for ln in hits:
                    w("    | " + ln)

    new = [p for p in paths if kinds[p] == "ADDED"]
    if new:
        w("  新規ファイルの先頭と骨組み:")
        for p in new:
            lines = added_lines(hunks.get(p, []))
            w(f"    === {p}  ({len(lines)} 行)")
            if not lines:
                w("    | （中身が diff に無い。バイナリか空）")
                continue
            head, cut = file_head(p, lines)
            for ln in head:
                w("    | " + ln)
            if not head:
                w("    （先頭にコメントも docstring も無い）")
            elif cut:
                w(f"    （先頭は {MAP_HEAD_LINES} 行で切った。続きは gh pr diff で見る。"
                  "切れた文を作者の言葉として写さない）")
            ol = outline(p, lines)
            if ol:
                w("    骨組み:")
                for ln in ol[:MAP_OUTLINE_CAP]:
                    w("    | " + ln)
                if len(ol) > MAP_OUTLINE_CAP:
                    w(f"    （骨組みは他に {len(ol) - MAP_OUTLINE_CAP} 行）")

    mod = [f for f in nodes if f["changeType"] != "ADDED"]
    if mod:
        w(f"  既存ファイルの変更（{MAP_HUNK_LIMIT} 行以内は hunk をそのまま。"
          "超える分は @@ の見出しだけ）:")
        for f in mod:
            old = renames.get(f["path"])
            frm = f"  旧: {old}" if old else ""
            w(f"    === {f['path']}  ({f['changeType']} +{f['additions']}/-{f['deletions']}){frm}")
            for prefix, ln in modified_hunks(f["path"], hunks.get(f["path"], []),
                                             f["additions"], f["deletions"]):
                w("    " + prefix + ln)
    return "\n".join(out)


def collect_caps(node):
    caps = []
    for field, label in (("comments", "コメント"), ("reviews", "レビュー"),
                         ("reviewThreads", "スレッド"), ("allCommits", "コミット")):
        conn = node.get(field)
        if conn and conn.get("totalCount", 0) > len(conn["nodes"]):
            caps.append((label, conn["totalCount"], len(conn["nodes"])))
    return caps


def main(argv=None):
    p = argparse.ArgumentParser(
        description="1 件の PR / issue について、前回自分が触ってから何が起きたかを出す")
    p.add_argument("target", help="番号、または PR / issue の URL")
    p.add_argument("-R", "--repo", help="owner/repo（URL を渡すときは不要）")
    p.add_argument("--me", help="基準にする login（既定は gh の認証ユーザ）。指定すると、"
                   "手元の git config の user.email による commit の照合はしない")
    p.add_argument("--full", action="store_true", help="発言を全文で出す")
    p.add_argument("--limit", type=int, default=12,
                   help="その後に起きたことの表示件数（既定 12）")
    p.add_argument("--map", choices=("auto", "yes", "no"), default="auto",
                   help="末尾に変更の地図の材料を付けるか。auto は作者が私でない PR のときだけ")
    a = p.parse_args(argv)

    owner, name, num = resolve_target(a.target, a.repo)
    me = a.me or gh("api", "user", "--jq", ".login").strip()
    # 他人を基準にするときは、手元の git config はその人のものではないので照合しない
    my_email = "" if a.me else local_email()
    node = fetch(owner, name, num)
    ev, refs, unlinked = collect_events(node, me, my_email)
    anchor, anchor_kind = find_anchor(ev, node, me)
    is_pr = node["__typename"] == "PullRequest"
    with_map = is_pr and (a.map == "yes" or (a.map == "auto" and login_of(node["author"]) != me))
    print(render(node, me, ev, refs, unlinked, anchor, anchor_kind, a.full, a.limit,
                 collect_caps(node), with_map=with_map))
    if with_map:
        print()
        print(render_map(node, owner, name))
    elif a.map == "yes":
        print()
        print("（issue には変更の地図は無い）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — 想定外は 2 で落とす（1 は「見つからない」に使う）
        sys.exit(f"catchup.py が想定外の例外で停止: {type(e).__name__}: {e}")
