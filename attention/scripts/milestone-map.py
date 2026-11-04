#!/usr/bin/env python3
"""1 つのリポジトリの open のマイルストーン全部を、GitHub の今の状態のまま 1 枚の HTML の地図にする。

〈目的〉/whose-turn（自分の番の PR の全件）と /catchup（1 件）に並ぶ、マイルストーン全体を見る口。正本は GitHub の
マイルストーン・issue・blocked by で、ここはそれを読むだけで書き換えない。GitHub から取った事実だけを描き、推定・見込み
（AI の推論やモンテカルロの日付）は載せない（持ち主 2026-11-04「推論とか予想はあとでできるよね」）。

〈母集団〉open のマイルストーン全部と、その open の issue（blocked by と、閉じる予定の open の PR）と、マイルストーンの
付いていない open の issue（右の端の「No milestone」の枠に、マイルストーン 1 本と同じ形で置く）。

〈渡す日付〉GitHub の issue には期日のフィールドが無い。--dates に「issue の番号 → 日付」の JSON を渡すと、マイルストーンの付いて
いない issue のうち日付の在る物を、日付ごとの「No milestone」の枠にしてその日の列に置く（マイルストーンの在る issue は
マイルストーンの期日で置き、渡した日付は使わない）。日付をどこから取るか（Projects の日付のフィールドなど）はこのスクリプトの外の
固有の部品が決める。Projects の日付のフィールドから取る部品は scripts/project-dates.py。

〈図〉左から右へ期日の列が並ぶ（期日なしは右の端）。issue 1 件を番号と題名のカード 1 枚にし、マイルストーン 1 本を、
その issue を包む薄い枠 1 つにする。枠は期日の列に置き、空いた所へ詰める（クリティカルパスの在る枠を先に上へ置く）。
枠は開け閉めできる。列の中は依存の順番で、線の在るカードは止めている側ほど左の段に置き、鎖を横 1 本に並べる。線の
無いカードはその下に格子で並べ、地図に線が 1 本でも在れば、そのうち灰のカードを枠ごとに畳む（押すと開く）。カードの色を GitHub の
事実で分ける:
  - 赤: Blocked（open の blocked by を 1 件以上持つ。相手がどこに居ても）
  - 緑: Linked PR（この issue を閉じる予定の open の PR が在る。GitHub の closedByPullRequestsReferences）
  - 灰: それ以外
  赤と緑の両方に当たる issue は赤にする（止まっている方を先に見せる）。

〈線〉open の issue の blocked by のうち、相手もこの地図に載っている（このリポジトリの open のマイルストーンの open の
issue）物を、カードからカードへの矢印にする（向きは「止めている側 → 待つ側」）。待つ側の issue より左の列へ止めている側を
寄せ、同じ期日の列の中では止めている側を左の段に置くので、矢印は右へ向かう（輪の中の線だけは向きを揃えられない）。
同じマイルストーンの中の線も引く。閉じた枠の issue の線は、枠の帯のうちその issue の列の端から引く（帯が列をまたいでも、線を右向きに保つため）。相手が
地図に載っていない blocked by（別のリポジトリ・閉じた issue・閉じたマイルストーン）は線にせず、カードを赤くして、
カードの説明（マウスを載せると出る）に相手の番号を書く。

〈誰が〉実質の担当を、issue の担当者（GitHub の assignee）と、その issue を閉じる PR を出した人とする（担当者のフィールドに
入っていなくても、PR の本文に closes を書いて進めている人は担当と同じ。持ち主 2026-11-04）。open の issue は閉じる予定の
open の PR、閉じた issue は閉じた PR（GitHub の最後の ClosedEvent の closer）の作者を見る。PR でなく手で閉じた issue は、
担当者が居なければ閉じる操作をした人を担当とする。カードに頭文字の丸で出し、担当者のフィールドに居ない人は点線の丸にする。上の
人の一覧で人を押すと、その人のカードだけを光らせる。

〈期間〉ページの上で期間（既定は今日までの 14 日）を選ぶと、その間に閉じた issue（closedAt）と作られた issue
（createdAt）を数え、日ごとの棒と、残りの数の線で描く。残りの数は「今そのマイルストーンに在る issue のうち、その日に
作られていて、まだ閉じていなかった物」の数（マイルストーンを移した・外した日は GitHub の timeline を読まないと分からない
ので数えない）。期間の中で閉じた issue は、枠の中に薄いカードで残し、期間の中で作られた open の issue には「New」を付ける。
日付は手元の時刻の日付で切る。

〈クリティカルパス〉線をつないだ鎖のうち、issue の件数がいちばん多い鎖。issue ごとの所要日数は GitHub に無いので、
日数でなく件数で測る。線が 1 本も無ければ無い（ページには何も出さない）。輪の中の線は鎖から外し、ページに輪を 1 行出す。
"""

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import catchup_html  # noqa: E402 — ページの書き方と VS Code で開く口を /catchup と共用
from ghcli import gh  # noqa: E402 — gh を呼ぶ共通部。/whose-turn・/catchup と共用
from ghpage import fetch_all, stop_on_errors, truncated  # noqa: E402 — 全ページの取得と上限の行。/whose-turn と共用

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates" / "milestone-map.html"
BODY_SLOT = "<!--__BODY__-->"
TITLE_SLOT = "<title>milestone-map</title>"
DATA_SLOT = "/*__DATA__*/null"

BLOCKED_FIRST = 50  # 1 件の issue の blocked by を取る数。GitHub の上限（種類ごとに 50 件）と同じ
PR_FIRST = 10       # 1 件の issue を閉じる予定の PR を取る数。色は open の物が 1 件在るかだけで決まる
WHO_FIRST = 10      # 1 件の issue の担当者を取る数（GitHub の assignee の上限と同じ）

SINCE_DAYS = 400  # マイルストーンの付いていない閉じた issue を取る日数。ページで選べる期間の上限と同じ

NOT_SEEN = f"""\
見ていないもの:
  - issue の本文やコメントにだけ書かれた依存（blocked by になっていない物）。線は blocked by だけから引く
  - 別のリポジトリとの依存の線。blocked by の相手が別のリポジトリならカードを赤くするだけで線は引かない。
    別のリポジトリから止められている向き（blocking）は相手のリポジトリを読まないので見ていない
  - GitHub の外（口頭・チャット・文書）で決めた順番と、マイルストーンの説明文に書かれた順番
  - Projects のフィールドの中身（Start Date・Target Date・見積もりなど）。トークンに read:project が無くても走るよう、
    このスクリプトは取りに行かない（日付は --dates で外から渡せる）
  - 閉じたマイルストーンと、その issue
  - 見込み（いつ終わりそうか）と、AI の推定した依存。まだ載せない
  - issue がマイルストーンへ足された日・移された日（timeline を読まない）。期間の数は作られた日と閉じた日だけで数える
  - マイルストーンの付いていない閉じた issue のうち、閉じた日が {SINCE_DAYS} 日より前の物（期間の数には効かない。
    選べる期間は {SINCE_DAYS} 日まで）
  - 本文で issue を閉じると書いていない PR（GitHub が issue に結び付けていない PR は、緑に数えない）"""

MILESTONES_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    milestones(states: OPEN, first: 50, after: $cursor, orderBy: {field: DUE_DATE, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url dueOn closedIssues: issues(states: CLOSED) { totalCount } }
    }
  }
}"""

OPEN_FIELDS = f"""
          number title url createdAt
          assignees(first: {WHO_FIRST}) {{ totalCount nodes {{ login }} }}
          blockedBy(first: {BLOCKED_FIRST}) {{ totalCount nodes {{
            number url state repository {{ nameWithOwner }} }} }}
          closedByPullRequestsReferences(first: {PR_FIRST}, includeClosedPrs: false) {{
            totalCount nodes {{ number url state author {{ login }} }} }}"""
CLOSED_FIELDS = (f"number title url createdAt closedAt stateReason assignees(first: {WHO_FIRST}) {{ totalCount nodes {{ login }} }} "
                 "timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) { nodes { ... on ClosedEvent { "
                 "actor { __typename login } closer { ... on PullRequest { author { login } } } } } }")

OPEN_ISSUES_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    milestone(number: $number) {{
      issues(states: OPEN, first: 50, after: $cursor) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{{OPEN_FIELDS}
        }}
      }}
    }}
  }}
}}"""

CLOSED_ISSUES_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    milestone(number: $number) {{
      issues(states: CLOSED, first: 100, after: $cursor) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {CLOSED_FIELDS} }}
      }}
    }}
  }}
}}"""

# マイルストーンの付いていない issue は検索（no:milestone）で取る。GraphQL の issues の filterBy の milestoneNumber に
# "none" を渡しても 0 件が返るため（2026-11-04 に guided-resolver で、検索では 19 件・filterBy では 0 件だった）。
# 検索は 1 つの問いに 1000 件までしか返さないので、それを超えたら上限の行に出す。
SEARCH_FIRST = 50
def search_query(fields):
    """検索（search）で issue を 1 ページずつ取る問い合わせ。open と閉じた物で、取る中身（fields）だけが違う。"""
    return f"""
query($q: String!, $cursor: String) {{
  search(type: ISSUE, query: $q, first: {SEARCH_FIRST}, after: $cursor) {{
    issueCount
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ ... on Issue {{ {fields} }} }}
  }}
}}"""


LOOSE_OPEN_QUERY, LOOSE_CLOSED_QUERY = search_query(OPEN_FIELDS), search_query(CLOSED_FIELDS)

COUNT_QUERY = """
query($q: String!) {
  search(type: ISSUE, query: $q, first: 0) { issueCount }
}"""


def search_all(query, q):
    """検索の全ページ。戻り値は {"totalCount": 検索に当たった数, "nodes": 取れた issue}（truncated に渡せる形）。"""
    nodes, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", "query=" + query, "-f", "q=" + q] + (["-f", "cursor=" + cursor] if cursor else [])
        conn = stop_on_errors(json.loads(gh(*args)))["data"]["search"]
        nodes += [n for n in conn["nodes"] if n]
        if not conn["pageInfo"]["hasNextPage"]:
            # 検索の途中で issue が直されると、同じ issue が 2 ページに出ることがある。番号で 1 件にする
            return {"totalCount": conn["issueCount"], "nodes": list({n["number"]: n for n in nodes}.values())}
        cursor = conn["pageInfo"]["endCursor"]


# ---- 取得 ------------------------------------------------------------------


def fetch(owner, name, today):
    """母集団の生の材料。戻り値は (マイルストーンの並び, マイルストーンの付いていない issue をマイルストーンと同じ形にした物)。"""
    milestones = fetch_all(MILESTONES_QUERY, owner, name, "milestones")

    def one(m):
        m["openIssues"] = fetch_all(OPEN_ISSUES_QUERY, owner, name, "milestone.issues",
                                    variables=(f"number={m['number']}",))
        m["closedIssueList"] = fetch_all(CLOSED_ISSUES_QUERY, owner, name, "milestone.issues",
                                         variables=(f"number={m['number']}",))
        return m

    # 4 本まで並べる（マイルストーンが 30 本で 1 本ずつだと遅い。GitHub の二次の上限に当たらない数）
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        milestones = list(pool.map(one, milestones))
    base = f"repo:{owner}/{name} is:issue no:milestone sort:created-asc"  # 並びを決めて、ページの間で順が揺れないように
    closed_all = stop_on_errors(json.loads(gh("api", "graphql", "-f", "query=" + COUNT_QUERY,
                                              "-f", "q=" + base + " is:closed")))["data"]["search"]["issueCount"]
    opened = search_all(LOOSE_OPEN_QUERY, base + " is:open")
    closed = search_all(LOOSE_CLOSED_QUERY, f"{base} is:closed closed:>={today - dt.timedelta(days=SINCE_DAYS)}")
    loose = {"openIssues": opened["nodes"], "closedIssueList": closed["nodes"], "closedIssues": {"totalCount": closed_all},
             "limits": [truncated(opened, "マイルストーンの付いていない open の issue（検索）", "No milestone"),
                        truncated(closed, f"マイルストーンの付いていない、{SINCE_DAYS} 日の中で閉じた issue（検索）", "No milestone")]}
    return milestones, loose


# ---- 事実を組む（純粋関数。tests/milestone-map-suite.py が規則を pin する） ----------------


def due_date(m):
    """期日。GitHub の dueOn の UTC の日付（時刻の部分は見ない）。"""
    return dt.date.fromisoformat(m["dueOn"][:10]) if m.get("dueOn") else None


def local_day(ts):
    """GitHub の時刻（UTC の ISO 8601）を、手元の時刻の日付 YYYY-MM-DD にする。期間を手元の日付で切るため。"""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat() if ts else None


def logins(i):
    """担当者の login の並び。"""
    return [a["login"] for a in i["assignees"]["nodes"]]


def closer_of(i):
    """閉じた人と閉じ方 (login, "pr" か "hand")。最後の ClosedEvent の、閉じたのが PR ならその PR を出した人（"pr"）。
    PR でなく閉じた物（手で閉じた・commit で閉じた・PR の作者のアカウントが消えた）は、担当者が居なければ閉じる操作を
    した人（"hand"）、居れば (None, None)（担当者を実質の担当とする）。ただし手で閉じた物は、完了（stateReason が COMPLETED）
    で閉じた物だけを数え、Bot が閉じた物と、not planned・duplicate で閉じた物は誰の仕事にもしない（stale の Bot や、重複を
    閉じて回った人が、仕事を終えた人に見えないように）。"""
    ev = ((i.get("timelineItems") or {}).get("nodes") or [None])[-1] or {}
    by = ((ev.get("closer") or {}).get("author") or {}).get("login")
    if by:
        return by, "pr"
    who = ev.get("actor") or {}
    done = i.get("stateReason") in (None, "COMPLETED") and who.get("__typename") != "Bot"
    actor = None if i["assignees"]["nodes"] or not done else who.get("login")
    return (actor, "hand") if actor else (None, None)


def done_row(i):
    """閉じた issue 1 件の、期間の数に使う事実。by と how は閉じた人と閉じ方（closer_of）。"""
    by, how = closer_of(i)
    return {"number": i["number"], "title": i["title"], "url": i["url"],
            "made": local_day(i["createdAt"]), "shut": local_day(i["closedAt"]), "who": logins(i), "by": by, "how": how}


def issue_row(i, repo):
    """カード 1 枚分の事実。state は blocked（赤）・pr（緑）・idle（灰）。"""
    blockers = []
    for b in i["blockedBy"]["nodes"]:
        if b["state"] != "OPEN":
            continue
        other = (b.get("repository") or {}).get("nameWithOwner")
        blockers.append({"number": b["number"], "url": b["url"],
                         "repo": other if (other or "").casefold() != repo.casefold() else None})
    open_prs = [p for p in (i.get("closedByPullRequestsReferences") or {}).get("nodes", []) if p.get("state") == "OPEN"]
    prs = [p["number"] for p in open_prs]
    pr_of = [[p["number"], (p.get("author") or {}).get("login")] for p in open_prs]   # 消えたアカウントは author が null
    pr_by = sorted({w for _, w in pr_of} - {None})
    state = "blocked" if blockers else "pr" if prs else "idle"
    return {"number": i["number"], "title": i["title"], "url": i["url"], "state": state,
            "blocked_by": blockers, "prs": prs, "pr_by": pr_by, "pr_of": pr_of, "who": logins(i), "made": local_day(i["createdAt"])}


def edges_of(ms):
    """カードからカードへの線 [止めている側, 待つ側]。相手も地図に載っている blocked by だけ。"""
    on_map = {i["number"] for m in ms for i in m["issues"]}
    out = set()
    for m in ms:
        for i in m["issues"]:
            for b in i["blocked_by"]:
                if not b["repo"] and b["number"] in on_map:
                    out.add((b["number"], i["number"]))
    return sorted([list(e) for e in out])


def cycles_of(edges):
    """輪（互いに行き来できる issue の組。強連結成分のうち 2 件以上か、自分を止める 1 件）を、小さい番号の順で返す。
    Tarjan の方法を、深い鎖でも再帰の上限に当たらないよう、手で積む形で書いた。"""
    succ = {}
    for a, b in edges:
        succ.setdefault(a, []).append(b)
    index, low, on, stack, out = {}, {}, set(), [], []
    for root in sorted({n for e in edges for n in e}):
        if root in index:
            continue
        work = [(root, iter(sorted(succ.get(root, []))))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on.add(root)
        while work:
            n, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(succ.get(nxt, [])))))
                elif nxt in on:
                    low[n] = min(low[n], index[nxt])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[n])
            if low[n] == index[n]:
                comp = []
                while True:
                    x = stack.pop()
                    on.discard(x)
                    comp.append(x)
                    if x == n:
                        break
                if len(comp) > 1 or n in succ.get(n, []):
                    out.append(sorted(comp))
    return sorted(out)


def critical_path(edges):
    """issue の件数がいちばん多い鎖（止めている側から順）と、外した輪。線が無ければ鎖は空。
    輪の中の線だけを外し、残りの線で鎖を測る（輪の手前や先の鎖は残す）。
    同じ長さの鎖が複数あるときは、番号の並びが小さい方を採る（毎回同じ答えにするため）。"""
    cycles = cycles_of(edges)
    comp = {n: k for k, c in enumerate(cycles) for n in c}
    dag = [(a, b) for a, b in edges if not (a in comp and comp[a] == comp.get(b))]
    succ, indeg = {}, {}
    for a, b in dag:
        succ.setdefault(a, []).append(b)
        indeg[b] = indeg.get(b, 0) + 1
    nodes = sorted({n for e in dag for n in e})
    # 待つ側から順に（後ろから）、その issue から始まるいちばん長い鎖を決める
    order, ready = [], [n for n in nodes if not indeg.get(n)]
    while ready:
        n = ready.pop()
        order.append(n)
        for m in succ.get(n, []):
            indeg[m] -= 1
            if not indeg[m]:
                ready.append(m)
    best = {}
    for n in reversed(order):
        tails = [best[m] for m in succ.get(n, [])]
        best[n] = [n] + (min(tails, key=lambda t: (-len(t), t)) if tails else [])
    path = min(best.values(), key=lambda p: (-len(p), p)) if best else []
    return {"path": path if len(path) > 1 else [], "cycles": [c + [c[0]] for c in cycles]}


def order_key(m):
    return (m["due"] is None, m["due"] or "", bool(m.get("none")), m["number"])


def loose_frames(loose, dates, repo):
    """マイルストーンの付いていない issue を、マイルストーンと同じ形の枠にする。dates（issue の番号 → 日付）に在る issue は
    日付ごとの枠（その日を期日として置く）に、無い issue は期日なしの枠 1 つに入れる。日付の枠は open の issue の在る日だけ作り、
    閉じた issue は、同じ日付の枠が在ればそこへ、無ければ期日なしの枠へ入れる（閉じた issue だけの枠を古い日付の列に並べないため）。
    番号は 0（期日なし）と負の数（日付の枠）。
    閉じた数は、日付の枠は取った閉じた issue の数、期日なしの枠は残り（全部の閉じた数から日付の枠の分を引いた数）。"""
    if not loose or not (loose["openIssues"] or loose["closedIssueList"]):
        return []
    dates = dates or {}
    url = f"https://github.com/{repo}/issues?q=is%3Aissue%20is%3Aopen%20no%3Amilestone"
    groups = {}
    group = lambda d: groups.setdefault(d, {"openIssues": [], "closedIssueList": []})  # noqa: E731
    for i in loose["openIssues"]:
        group(dates.get(i["number"]))["openIssues"].append(i)
    for i in loose["closedIssueList"]:
        d = dates.get(i["number"])
        group(d if d in groups else None)["closedIssueList"].append(i)
    out, dated = [], 0
    for k, d in enumerate(sorted(x for x in groups if x), 1):
        g = groups[d]
        dated += len(g["closedIssueList"])
        out.append({"number": -k, "title": "No milestone", "dueOn": d.isoformat(), "none": True, "url": url, **g,
                    "closedIssues": {"totalCount": len(g["closedIssueList"])}})
    if None in groups:
        out.append({"number": 0, "title": "No milestone", "dueOn": None, "none": True, "url": url, **groups[None],
                    "closedIssues": {"totalCount": max(0, loose["closedIssues"]["totalCount"] - dated)}})
    return out


def read_dates(text):
    """--dates の JSON（{"issue の番号": "YYYY-MM-DD"}）を {番号: date} にする。形が違えば ValueError。"""
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("--dates の JSON は {\"issue の番号\": \"YYYY-MM-DD\"} の形にする")
    if any(v is not None and not isinstance(v, str) for v in raw.values()):
        raise ValueError("--dates の日付は \"YYYY-MM-DD\" の字で書く")
    return {int(k): dt.date.fromisoformat(v) for k, v in raw.items() if v}


def build(raw, loose, repo, today, now=None, dates=None):
    """取得した生の材料から、ページに描く事実を組む。loose はマイルストーンの付いていない issue（fetch の 2 つ目。
    無ければ None）で、loose_frames が「No milestone」の枠にする。dates は --dates の日付（read_dates）。"""
    limits, ms = list((loose or {}).get("limits") or []), []
    raw = list(raw) + loose_frames(loose, dates, repo)
    for m in raw:
        due = due_date(m)
        issues = []
        for i in m["openIssues"]:
            limits.append(truncated(i["blockedBy"], "blocked by", f"#{i['number']}"))
            limits.append(truncated(i["assignees"], "担当者", f"#{i['number']}"))
            issues.append(issue_row(i, repo))
        rank = {"blocked": 0, "pr": 1, "idle": 2}
        issues.sort(key=lambda i: (rank[i["state"]], i["number"]))
        ms.append({"number": m["number"], "title": m["title"], "url": m["url"], "none": bool(m.get("none")),
                   "due": due.isoformat() if due else None,
                   "overdue_days": (today - due).days if due and due < today else 0,
                   "open": len(issues), "closed": m["closedIssues"]["totalCount"], "issues": issues,
                   "done": sorted((done_row(i) for i in m["closedIssueList"]), key=lambda i: (i["shut"], i["number"]))})
        limits.extend(truncated(i["assignees"], "担当者", f"#{i['number']}") for i in m["closedIssueList"])
    ms.sort(key=order_key)
    edges = edges_of(ms)
    crit = critical_path(edges)
    count = {s: sum(1 for m in ms for i in m["issues"] if i["state"] == s) for s in ("blocked", "pr", "idle")}
    return {
        "repo": repo, "url": f"https://github.com/{repo}/milestones",
        "taken_at": (now or dt.datetime.now().astimezone()).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "scope": {"milestones": sum(1 for m in ms if not m["none"]), "open_issues": sum(m["open"] for m in ms), **count,
                  "edges": len(edges), "no_milestone_issues": sum(m["open"] for m in ms if m["none"])},
        "milestones": ms, "edges": edges, "critical": crit, "limits": [x for x in limits if x],
    }


# ---- ページ ---------------------------------------------------------------------------


def esc(s):
    return html.escape(str(s))


def md(iso, year):
    """期日の書き方。今年なら月-日だけ、別の年なら年から書く。"""
    return iso[5:] if iso[:4] == str(year) else iso


def columns(data):
    """issue の横の位置。左から右へ時間が流れる。基本は期日で、同じ期日の列の中は依存の順番。
    列は期日の順（期日なしは右の端）。issue はまず自分のマイルストーンの期日の列に置き、待たせている issue が
    もっと左の列に在れば、その列まで寄せる（間に合わせるには先に終える必要があるので。クリティカルパスの遅い開始と
    同じ考え方）。同じ列の中では、同じ列に在る止めている側の段より 1 つ右の段に置く（段 = 列の中の依存の順番。0 から）。
    輪の中の線は数えない。戻り値は ({番号: 列}, {番号: 段}, {列: 見出しの期日（期日なしは None）}, 列の数)。"""
    dues = sorted({m["due"] for m in data["milestones"] if m["due"]})
    base_of = {d: k for k, d in enumerate(dues)}
    nodue = len(dues)
    base = {i["number"]: base_of.get(m["due"], nodue) for m in data["milestones"] for i in m["issues"]}
    comp = {n: k for k, c in enumerate(cycles_of(data["edges"])) for n in c}
    dag = [(a, b) for a, b in data["edges"] if not (a in comp and comp[a] == comp.get(b))]
    succ, pred, indeg = {}, {}, {n: 0 for n in base}
    for a, b in dag:
        succ.setdefault(a, []).append(b)
        pred.setdefault(b, []).append(a)
        indeg[b] += 1
    order, ready = [], sorted((n for n in base if not indeg[n]), reverse=True)
    while ready:
        n = ready.pop()
        order.append(n)
        for m in sorted(succ.get(n, []), reverse=True):
            indeg[m] -= 1
            if not indeg[m]:
                ready.append(m)
    col, rank = {}, {}
    for n in reversed(order):
        col[n] = min([base[n]] + [col[m] for m in succ.get(n, [])])
    for n in order:
        rank[n] = max([rank[p] + 1 for p in pred.get(n, []) if col[p] == col[n]] + [0])
    heads = {base_of[d]: d for d in dues}
    if any(m["due"] is None for m in data["milestones"]):
        heads[nodue] = None
    width = max(heads) + 1 if heads else 0
    return col, rank, heads, width


def card_title(i):
    """カードにマウスを載せると出る説明。"""
    lines = [f"#{i['number']} {i['title']}"]
    if i["blocked_by"]:
        lines.append("Blocked by: " + "・".join((b["repo"] + "#" if b["repo"] else "#") + str(b["number"])
                                               for b in i["blocked_by"]))
    if i["prs"]:
        lines.append("PR: " + "・".join(f"#{p}" for p in i["prs"]) + (f"（{'・'.join(i['pr_by'])}）" if i["pr_by"] else ""))
    if i["who"]:
        lines.append("Assignee: " + "・".join(i["who"]))
    lines.append("作られた日: " + i["made"])
    return "\n".join(lines)


def late_edges(data):
    """止めている側のマイルストーンの期日が、待つ側の期日より後ろの線（期日の逆転）。"""
    where = {i["number"]: m for m in data["milestones"] for i in m["issues"]}
    out = []
    for a, b in data["edges"]:
        da, db = where[a]["due"], where[b]["due"]
        if (da is None and db is not None) or (da and db and da > db):
            out.append([a, b])
    return out


def view(data):
    """ページのスクリプトへ渡す材料。どの列に置くかはここで決め、画面の上の座標はスクリプトが決める
    （枠の開け閉めで置き直すため）。字はスクリプトが textContent で入れるので、ここではエスケープしない。"""
    col, rank, heads, width = columns(data)
    year, today = int(data["today"][:4]), data["today"]
    path = data["critical"]["path"]
    on_path = set(path)
    due_col = {d: c for c, d in heads.items()}
    cols = [{"label": ("Due " + md(heads[c], year)) if heads.get(c) else "No due date" if c in heads else "",
             "late": bool(heads.get(c) and heads[c] < today)} for c in range(width)]
    past = [c for c, d in heads.items() if d and d < today]
    ms = [{"n": m["number"], "title": m["title"], "url": m["url"], "col": due_col[m["due"]], "none": m["none"],
           "due": (("渡した日付 " if m["none"] else "Due ") + md(m["due"], year)) if m["due"] else "No due date",
           "overdue": m["overdue_days"],
           "open": m["open"], "closed": m["closed"],
           "count": {s: sum(1 for i in m["issues"] if i["state"] == s) for s in ("blocked", "pr", "idle")},
           "issues": [{"n": i["number"], "title": i["title"], "url": i["url"], "state": i["state"],
                       "col": col[i["number"]], "rank": rank[i["number"]], "crit": i["number"] in on_path, "blockers": len(i["blocked_by"]),
                       "prs": i["prs"], "prBy": i["pr_by"], "prOf": i["pr_of"], "who": i["who"], "made": i["made"], "tip": card_title(i)}
                      for i in m["issues"]],
           "done": [{"n": i["number"], "title": i["title"], "url": i["url"], "made": i["made"], "shut": i["shut"],
                     "who": i["who"], "by": i["by"], "how": i["how"]} for i in m["done"]]}
          for m in data["milestones"]]
    return {"columns": cols, "today": {"at": max(past) + 1 if past else 0, "label": "今日 " + md(today, year), "day": today},
            "milestones": ms, "edges": data["edges"], "path": [list(e) for e in zip(path, path[1:])],
            "late": late_edges(data), "since_days": SINCE_DAYS}


def body_html(data):
    s = data["scope"]
    path = data["critical"]["path"]
    repo = esc(data["repo"])
    out = ['<header class="top"><div class="hrow">',
           f'<h1>マイルストーンの地図 <a class="repo" href="{esc(data["url"])}">{repo}</a></h1>',
           '<ul class="chips">'
           f'<li><b>{s["milestones"]}</b> マイルストーン</li><li><b>{s["open_issues"]}</b> issue</li>'
           f'<li class="blocked"><i></i>Blocked <b>{s["blocked"]}</b></li>'
           f'<li class="pr"><i></i>Linked PR <b>{s["pr"]}</b></li>'
           f'<li class="idle"><i></i>それ以外 <b>{s["idle"]}</b></li>'
           f'<li>blocked by の線 <b>{s["edges"]}</b></li></ul></div>',
           f'<p class="meta">{esc(data["taken_at"])} に GitHub から取った事実だけを描いている（推定・見込みは載せない）。'
           + (f'マイルストーンの付いていない open の issue {s["no_milestone_issues"]} 件は、右の端の「No milestone」の枠に置いた。'
              if s["no_milestone_issues"] else "") + "</p>"]
    if path:
        out.append(f'<p class="path"><span class="label crit">クリティカルパス {len(path)} 件</span> ' + '<span class="arrow">→</span>'.join(
            f'<a href="https://github.com/{repo}/issues/{n}" data-n="{n}">#{n}</a>' for n in path) + "</p>")
    if data["critical"]["cycles"]:
        out.append('<p class="path bad">輪になった blocked by（クリティカルパスから外した）: ' + "、".join(
            " → ".join(f"#{n}" for n in c) for c in data["critical"]["cycles"]) + "</p>")
    if data["limits"]:
        out.append('<p class="path bad">取得の上限に当たった: ' + esc("・".join(data["limits"])) + "</p>")
    out.append("</header>")
    out.append('<section id="pulse" aria-label="期間の動きと、誰が進めているか"></section>')
    out.append('<div class="bar">'
               '<input id="q" type="search" placeholder="番号か題名で探す" aria-label="番号か題名で探す">'
               '<span id="hits" class="muted"></span>'
               '<span class="keys"><span><i class="ln crit"></i>クリティカルパス</span>'
               '<span><i class="ln late"></i>Blocking の期日が Blocked より後ろ</span>'
               '<span><i class="ln"></i>Blocking → Blocked（矢印の向き）</span></span>'
               '<span class="tools"><button type="button" data-act="open">全部開く</button>'
               '<button type="button" data-act="close">全部閉じる</button>'
               '<button type="button" data-act="out" title="縮める">−</button>'
               '<button type="button" data-act="in" title="広げる">＋</button>'
               '<button type="button" data-act="fit">全体</button>'
               '<button type="button" data-act="one">等倍</button></span></div>')
    out.append('<div id="view" tabindex="0" aria-label="マイルストーンの地図。ホイールかドラッグか矢印のキーで動かし、Ctrl とホイールで拡大・縮小する">'
               '<div id="world"></div></div>')
    return "\n".join(out)


def build_html(template, data):
    for slot in (BODY_SLOT, TITLE_SLOT, DATA_SLOT):
        if slot not in template:
            raise ValueError(f"雛形に差し込み口 {slot} が無い")
    head, tail = template.split(BODY_SLOT, 1)
    title = f"<title>{esc('マイルストーンの地図 ' + data['repo'])}</title>"
    return (head.replace(TITLE_SLOT, title, 1) + body_html(data)
            + tail.replace(DATA_SLOT, catchup_html._script_json(view(data)), 1))


def repo_dir(repo, root=None):
    """保存先。/catchup の保存先（~/.cache/attention/catchup）と並べて ~/.cache/attention/milestone-map に置く。"""
    root = pathlib.Path(root) if root else catchup_html.cache_root().parent / "milestone-map"
    return root / catchup_html._safe(repo.replace("/", "-"))


def summary_line(data):
    s = data["scope"]
    path = data["critical"]["path"]
    crit = (f"クリティカルパス {len(path)} 件" if path else
            "クリティカルパスなし（blocked by の線が 0 本）" if not s["edges"] else "クリティカルパスなし（線は輪だけ）")
    return (f"マイルストーン {s['milestones']} 本・issue {s['open_issues']} 件（Blocked {s['blocked']}・"
            f"Linked PR {s['pr']}・それ以外 {s['idle']}）・{crit}")


# ---- 入口 ------------------------------------------------------------------------


def parser():
    ap = argparse.ArgumentParser(description=__doc__ + "\n" + NOT_SEEN,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="OWNER/NAME（省略時はカレントリポジトリ）")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="今日の日付 YYYY-MM-DD（試験と見直しの再現のため。既定は今日）")
    ap.add_argument("--dates", metavar="FILE", help="マイルストーンの付いていない issue の日付の JSON"
                    "（{\"issue の番号\": \"YYYY-MM-DD\"}。- なら標準入力）。例: --dates <(scripts/project-dates.py --field 'Target Date')")
    return ap


def main(argv=None, env=None, root=None):
    a = parser().parse_args(argv)
    dates = None
    if a.dates:   # GitHub に問う前に読む（形が違えば、取得を待たずに止める）
        try:
            dates = read_dates(sys.stdin.read() if a.dates == "-" else pathlib.Path(a.dates).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"milestone-map: --dates を読めなかった: {e}", file=sys.stderr)
            return 2
    # 正式の名前（大文字小文字）に揃える。blocked by の相手のリポジトリを自リポジトリと照合するため
    repo = gh("repo", "view", *([a.repo] if a.repo else []), "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    owner, name = repo.split("/", 1)
    today = a.today or dt.date.today()
    raw, loose = fetch(owner, name, today)
    data = build(raw, loose, repo, today, dates=dates)
    page = repo_dir(repo, root) / "map.html"
    catchup_html._write_atomic(page, build_html(TEMPLATE.read_text(encoding="utf-8"), data))
    print("\n".join([str(page), summary_line(data), catchup_html.open_in_vscode(page, env)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
