#!/usr/bin/env python3
"""1 件の PR / issue について「前回自分が触ってから何が起きたか」を機械で取り切り、短く出す。

〈目的〉並行作業から戻ったときに「この作業のどこで止まっていたか」を思い出す。判定（次に何を
するか）はしない——それは読む人か /catchup の AI の仕事。

〈基準点〉この道具の中心は diff ではなく**自分の最後の発言**である。本文コメント・レビュー・
レビュースレッド・push を全部見て最も新しい自分の痕跡を基準点に置き、その後に起きたことだけを
並べる。自分がまだ一度も触っていないときは、自分に渡された時点（レビュー依頼・assign・
メンションのうち最も新しいもの）に落とし、それも無ければ作成時に落とす。

diff の要約を出さないのは、それが思い出す助けにならないため。戻ったときに失われているのは
「何を変える PR か」（本文に書いてある）ではなく、会話のどこで自分が止まったかの方である。

〈短さ〉既定の出力は画面 1 つに収める。全文が要るときだけ --full を付ける。長い抜粋を既定に
すると、思い出すための道具が読み直しの作業になり、目的と衝突する。
"""

import argparse
import datetime as dt
import json
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

QUERY = """
query($owner:String!,$name:String!,$num:Int!){
  repository(owner:$owner,name:$name){
    issueOrPullRequest(number:$num){
      __typename
      ... on PullRequest {
        number title url state isDraft createdAt body
        additions deletions changedFiles mergeable reviewDecision
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
          author{user{login} name}}}}
        head: commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){
          totalCount nodes{__typename
            ... on CheckRun{name conclusion status}
            ... on StatusContext{context state}}}}}}}
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
        r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はこのファイル内のリテラルと番号だけ
            [exe, *args], capture_output=True, text=True
        )
        if r.returncode == 0:
            return r.stdout
        if "504" not in r.stderr or attempt == 2:
            sys.exit(f"gh {' '.join(args[:2])} が失敗: {r.stderr.strip()}")
    return None


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


def collect_events(node, me):
    """全部の発言・push・受け渡しを 1 本の時系列にする。基準点探しも表示もこれを使う。"""
    ev = []

    def add(t, who, kind, text, bot=False, mine_kind=True):
        ev.append({"t": ts(t), "who": who, "kind": kind, "text": text,
                   "bot": bot, "utterance": mine_kind})

    for c in node["comments"]["nodes"]:
        add(c["createdAt"], login_of(c["author"]), "コメント", c["body"],
            is_bot(c["author"]))

    for r in node.get("reviews", {}).get("nodes", []):
        # 未送信（PENDING）は submittedAt が null で、相手にも届いていない。時系列には入れず
        # 「止めているもの」側で自分の宿題として扱う
        if r["state"] == "PENDING" or not r["submittedAt"]:
            continue
        label = {"APPROVED": "レビュー（承認）",
                 "CHANGES_REQUESTED": "レビュー（要修正）"}.get(r["state"], "レビュー")
        add(r["submittedAt"], login_of(r["author"]), label, r["body"], is_bot(r["author"]))

    for th in node.get("reviewThreads", {}).get("nodes", []):
        where = th["path"] + (f":{th['line']}" if th["line"] else "")
        state = "解決済" if th["isResolved"] else "未解決"
        for c in th["comments"]["nodes"]:
            add(c["createdAt"], login_of(c["author"]), f"スレッド {where}（{state}）",
                c["body"], is_bot(c["author"]))

    for n in node.get("allCommits", {}).get("nodes", []):
        c = n["commit"]
        who = ((c.get("author") or {}).get("user") or {}).get("login") \
            or (c.get("author") or {}).get("name") or "（不明）"
        add(c["committedDate"], who, "push",
            f"{c['oid'][:9]} {c['messageHeadline']} (+{c['additions']}/-{c['deletions']})")

    for it in node.get("timelineItems", {}).get("nodes", []):
        k = it["__typename"]
        if k == "ReviewRequestedEvent":
            r = it.get("requestedReviewer") or {}
            add(it["createdAt"], login_of(it.get("actor")), "レビュー依頼",
                "→ " + (r.get("login") or r.get("name") or "（不明）"), mine_kind=False)
        elif k == "AssignedEvent":
            add(it["createdAt"], login_of(it.get("actor")), "担当",
                "→ " + login_of(it.get("assignee")), mine_kind=False)
        elif k == "ReadyForReviewEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書き解除", "", mine_kind=False)
        elif k == "ConvertToDraftEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書きへ戻す", "", mine_kind=False)
        elif k == "CrossReferencedEvent":
            s = it.get("source") or {}
            if s.get("number"):
                add(it["createdAt"], "", "参照",
                    f"#{s['number']} {s.get('title', '')}", mine_kind=False)

    ev.sort(key=lambda e: e["t"])
    return ev


def find_anchor(ev, node, me):
    """基準点を決める。戻り値は (出来事 or None, 種別)。

    自分の痕跡 → 自分に渡された時点 → 作成時、の順に落とす。渡された時点まで落とすのは、
    まだ一度も触っていない件（依頼が来たきり）でも「何がいつ自分に来たか」は思い出す助けに
    なるため。ここを作成時に直行させると、依頼の存在が出力から消える。"""
    mine = [e for e in ev if e["who"] == me and e["utterance"]]
    if mine:
        return mine[-1], "私の最後の発言"

    handover = []
    for e in ev:
        if e["kind"] in ("レビュー依頼", "担当") and e["text"].endswith(me):
            handover.append(e)
        elif e["utterance"] and re.search(r"@" + re.escape(me) + r"\b", e["text"] or ""):
            handover.append(e)
    if handover:
        return handover[-1], "私に渡された時点"
    return None, "作成時（私はまだ触っていない）"


# ---- 状態 --------------------------------------------------------------------


def check_state(node):
    """head commit のチェックを (赤の名前, 実行中の数, 緑の数) に畳む。"""
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
                red.append(c["name"])
        else:
            if c["state"] in ("PENDING", "EXPECTED"):
                running += 1
            elif c["state"] == "SUCCESS":
                green += 1
            else:
                red.append(c["context"])
    return red, running, green


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
    if any(a["login"] == me for a in node["assignees"]["nodes"]):
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


def find_ask(ev, node, me, cutoff):
    """最後に私へ向けられた依頼を 1 つ返す。cutoff より後だけを見る（None なら全期間）。

    自分の最後の発言だけでは戻れない——「相手が今その件で私に何を求めているか」が要る。
    メンション・レビュー依頼・私が返す番の未解決スレッドを同じ土俵で見て、最も新しいものを取る。

    cutoff を None にできるのが要点。自分がまだ発言していない件では、依頼は「渡された時点」より
    前に来ていることがある（本文で頼まれた後にレビュー依頼ボタンが押される順序）。基準点より後に
    限ると、その依頼が丸ごと消えて「依頼は来ていない」と出る（実測: レビュー依頼の 27 分前に
    本文で 3 点を名指しで委ねられていた PR で発生）。"""
    at_me = re.compile(r"@" + re.escape(me) + r"\b")
    hits = [e for e in ev if (cutoff is None or e["t"] > cutoff) and (
        (e["utterance"] and at_me.search(e["text"] or ""))
        or (e["kind"] == "レビュー依頼" and e["text"].endswith(me)))]
    if hits:
        # 本文を持つ発言を、レビュー依頼ボタンより優先する。ボタンは中身が無く、押された順序も
        # 本文の依頼と前後する（本文で頼んでからボタンを押す運用が普通）。新しい方を機械的に
        # 取ると、実際の用件が書いてある方が消える
        spoken = [h for h in hits if h["utterance"]]
        chosen = spoken[-1] if spoken else hits[-1]
        later = [h for h in hits if not h["utterance"] and h["t"] > chosen["t"]]
        if later:
            chosen = dict(chosen, followup=later[-1])
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
                    "bot": is_bot(cs[-1]["author"]), "utterance": True}
    return None


def render(node, me, ev, anchor, anchor_kind, full, limit, caps):
    is_pr = node["__typename"] == "PullRequest"
    out = []
    w = out.append
    red, running, green = check_state(node) if is_pr else ([], 0, 0)
    reasons = my_turn(node, me, ev, red)

    anchor_t = anchor["t"] if anchor else ts(node["createdAt"])
    # 自分が発言している件だけ基準点で切る。未発言の件は全期間から拾う（find_ask の説明を参照）
    spoke = bool(anchor and anchor["who"] == me and anchor["utterance"])
    ask = find_ask(ev, node, me, anchor_t if spoke else None)
    # 名指しで頼まれて返していない状態は、依頼ボタンも未解決スレッドも無いまま成立する。
    # 形式の信号が 1 つも立たないときの取りこぼしを、これで塞ぐ
    if ask and not reasons:
        reasons.append("私宛の依頼が来ていて、その後に私は発言していない")

    kind = "PR" if is_pr else "issue"
    w(f"# #{node['number']} {node['title']}")
    w("  " + ("● 私の番" if reasons else "○ 待ち") + " — "
      + ("／".join(reasons) if reasons else waiting_on(node, me)))
    head = [f"{kind} {node['state'].lower()}", f"作者 {login_of(node['author'])}"]
    if is_pr:
        if node["isDraft"]:
            head.append("下書き")
        head.append(f"{node['changedFiles']} ファイル "
                    f"+{node['additions']}/-{node['deletions']}")
    w("  " + " · ".join(head))
    w("  " + node["url"])
    w("")

    w("## 求められていること")
    if ask:
        w(f"  {hhmm(ask['t'])}  {ask['who']} の {ask['kind']}")
        w("  " + excerpt(ask["text"], 0 if full else 220))
        f = ask.get("followup")
        if f:
            w(f"  （その後 {hhmm(f['t'])} に {f['who']} が {f['kind']} を出している）")
    else:
        w("  私宛の依頼は、基準点より後には来ていない")
    w("")

    w("## 私が最後に置いた場所")
    if spoke:
        w(f"  {hhmm(anchor['t'])}  {anchor['kind']}")
        w("  " + excerpt(anchor["text"], 0 if full else 220))
    else:
        w("  この件で私はまだ一度も発言していない")
        if anchor:
            w(f"  {hhmm(anchor['t'])}  {anchor['who']} の {anchor['kind']} で私に渡された")
        else:
            w(f"  {hhmm(anchor_t)}  {anchor_kind}")
    w("")

    after = [e for e in ev if e["t"] > anchor_t]
    shown = after if full else after[-limit:]
    w(f"## その後に起きたこと — {len(after)} 件"
      + ("" if len(shown) == len(after) else f"（新しい方から {len(shown)} 件だけ表示）"))
    if not after:
        w("  なし。私が置いた場所から動いていない")
    for e in shown:
        who = f"{e['who']} が " if e["who"] else ""
        tag = "[bot] " if e["bot"] else ""
        w(f"  {hhmm(e['t'])}  {tag}{who}{e['kind']}")
        body = excerpt(e["text"], 0 if full else 110)
        if body != "（本文なし）":
            w(f"      {body}")
    w("")

    w("## いまの状態")
    if is_pr:
        w("  承認: " + APPROVAL.get(node["reviewDecision"], str(node["reviewDecision"]))
          + " ／ 取り込み: " + MERGEABLE.get(node["mergeable"], str(node["mergeable"])))
        # チェックが 1 本も無い状態を「全 pass」と言うと、検査が無いことが緑に化ける
        ci = ("全 pass" if red or running or green else "報告なし") if not red else ""
        if red:
            ci = f"赤 {len(red)} 件（{', '.join(red[:3])}"
            ci += "…）" if len(red) > 3 else "）"
        if running:
            ci += ("／" if ci else "") + f"実行中 {running} 件"
        w(f"  CI: {ci}（緑 {green}）" if green or red or running else "  CI: 報告なし")
        unresolved = [t for t in node["reviewThreads"]["nodes"] if not t["isResolved"]]
        human = [t for t in unresolved
                 if any(not is_bot(c["author"]) for c in t["comments"]["nodes"])]
        w(f"  未解決スレッド: {len(unresolved)} 件"
          f"（うち人が入っているもの {len(human)} 件）")
    assignees = [a["login"] for a in node["assignees"]["nodes"]]
    if assignees:
        w("  担当: " + ", ".join(assignees))
    w("")

    linked = node.get("closingIssuesReferences", {}).get("nodes", []) if is_pr else []
    refs = [e for e in ev if e["kind"] == "参照"]
    if linked or refs:
        w("## つながっている先")
        for i in linked:
            w(f"  閉じる  #{i['number']} {i['state'].lower()}  {i['title']}")
        for e in refs[-5:]:
            w(f"  参照    {e['text']}")
        w("")

    if caps:
        w("上限に当たったもの: " + "、".join(caps))
    w("見ていないもの:")
    w("  - GitHub の外（チャット・口頭・メール）でのやり取り")
    w("  - 本文と diff の中身。この道具は会話の位置だけを出す（差分は gh pr diff で見る）")
    if not full:
        w("  - 発言の全文。--full で出る")
    return "\n".join(out)


def collect_caps(node):
    caps = []
    for field, label in (("comments", "コメント"), ("reviews", "レビュー"),
                         ("reviewThreads", "スレッド"), ("allCommits", "コミット")):
        conn = node.get(field)
        if conn and conn.get("totalCount", 0) > len(conn["nodes"]):
            caps.append(f"{label}（{conn['totalCount']} 件中 {len(conn['nodes'])} 件）")
    return caps


def main(argv=None):
    p = argparse.ArgumentParser(
        description="1 件の PR / issue について、前回自分が触ってから何が起きたかを出す")
    p.add_argument("target", help="番号、または PR / issue の URL")
    p.add_argument("-R", "--repo", help="owner/repo（URL を渡すときは不要）")
    p.add_argument("--me", help="基準にする login（既定は gh の認証ユーザ）")
    p.add_argument("--full", action="store_true", help="発言を全文で出す")
    p.add_argument("--limit", type=int, default=12,
                   help="その後に起きたことの表示件数（既定 12）")
    a = p.parse_args(argv)

    owner, name, num = resolve_target(a.target, a.repo)
    me = a.me or gh("api", "user", "--jq", ".login").strip()
    node = fetch(owner, name, num)
    ev = collect_events(node, me)
    anchor, anchor_kind = find_anchor(ev, node, me)
    print(render(node, me, ev, anchor, anchor_kind, a.full, a.limit, collect_caps(node)))
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
