#!/usr/bin/env python3
"""1 つのリポジトリの open のマイルストーン全部を、GitHub の今の状態のまま 1 枚の HTML の地図にする。

〈目的〉/whose-turn（自分の番の PR の全件）と /catchup（1 件）に並ぶ、マイルストーン全体を見る口。正本は GitHub の
マイルストーン・issue・blocked by で、ここはそれを読むだけで書き換えない。機械は母集団を固定して事実を全部出し、
判定（どれが受け皿か・律速の読み・間に合うかの一言）は AI が材料を読んで書く。

〈母集団〉open のマイルストーン全部と、その open の issue（本文・blocked by・親子）と open の PR、直近 --weeks 週に
閉じた issue の日付、マイルストーンの付いていない open の issue の件数。

〈依存の線〉open の issue の blocked by のうち、相手が open で、このリポジトリの別の open のマイルストーンに居る物を
マイルストーンの組ごとに集めて線にする（向きは「止めている側 → 待つ側」、本数は issue の組の数）。0 件なら線は出ない。
止めている側の期日が待つ側の期日より後ろの線は「期日の逆転」として印を付ける。

〈依存の候補〉open の issue の本文が、別のマイルストーンの open の issue に触れている（`#番号` か、このリポジトリの
issue の URL）物を、マイルストーンの組ごとに集めて薄い点線にする。blocked by ではない（触れているだけで、前提かは
読んでいない）。人が見て blocked by を付けたくなる入口。本文が --max-refs 件より多くの issue に触れる issue は、
一覧（棚卸し・週次の器など）とみなして候補から外し、上限の行に出す。

〈見込み〉throughput に基づくモンテカルロ。マイルストーンごとに、直近の週ごとの閉じた件数（マイルストーンを作る前の
週は入れない）を標本にし、残りの件数が 0 になるまで週の件数を復元抽出で引く試しを --trials 回回して、50% と 85% の
週の数を今日に足した日付を出す。平均で割らない。標本が 8 週未満か閉じた件数が 10 件未満なら「幅が広い」と書く
（この 2 つの数は、このツールが置いた目安）。乱数は --seed とマイルストーンの番号から決めるので、同じ材料なら同じ日付が
出る。

〈律速〉線が 1 本以上あるときだけ出す。マイルストーンの終わりを「自分の 85% の日付と、止めている側の終わりの遅い方」
として線をたどり、終わりがいちばん遅いマイルストーンから、いちばん遅い止めている側を先頭までたどった鎖を律速とする。
見込めないマイルストーン（閉じた実績が無い）を含む鎖と、輪になった線は律速の計算から外して別に出す。
"""

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import math
import os
import pathlib
import random
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import catchup_html  # noqa: E402 — ページの書き方と VS Code で開く口を /catchup と共用
import outfile  # noqa: E402 — 報告をファイルへ逃がす共通部。/whose-turn・/catchup と共用
from ghcli import gh  # noqa: E402 — gh を呼ぶ共通部。/whose-turn・/catchup と共用
from ghpage import fetch_all, stop_on_errors, truncated  # noqa: E402 — 全ページの取得と上限の行。/whose-turn と共用
from ghtext import repo_refs  # noqa: E402 — 本文が指す自リポジトリの番号の読み方。/whose-turn と共用

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = 1
HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates" / "milestone-map.html"
BODY_SLOT = "<!--__BODY__-->"
TITLE_SLOT = "<title>milestone-map</title>"

WEEKS = 16          # 閉じた件数を数える週の数（直近）
TRIALS = 10000      # モンテカルロの試しの回数
SEED = 1            # 乱数の種の既定。同じ材料なら同じ日付を出すため固定する
CAP_WEEKS = 260     # 1 回の試しで引く週の上限（5 年）。閉じる件数が少なく残りが多いと終わらないので打ち切る
WIDE_WEEKS = 8      # 標本の週がこれ未満なら幅が広い
WIDE_CLOSED = 10    # 閉じた件数がこれ未満なら幅が広い
MAX_REFS = 15       # 本文がこれより多くの issue に触れる issue は一覧とみなして候補から外す
BLOCKED_FIRST = 50  # 1 件の issue の blocked by を取る数。GitHub の上限（種類ごとに 50 件）と同じ
PR_FIRST = 50       # マイルストーンごとの open の PR を取る数
FIELD_CAPS = {"headline": 80, "point": 120, "points": 6, "note": 60}

NOT_SEEN = """\
見ていないもの:
  - issue の本文やコメントにだけ書かれた依存（blocked by になっていない物）。本文が別のマイルストーンの issue に
    触れている物は「依存の候補」に出すが、前提と書いてあるかは読んでいない。コメント・コードブロック・引用・
    リンクの飛び先の URL は読んでいない{enumerations}
  - 別のリポジトリとの依存。blocked by の相手が別のリポジトリなら件数だけ出す（{other_repo} 件）。
    別のリポジトリから止められている向き（blocking）は相手のリポジトリを読まないので見ていない
  - GitHub の外（口頭・チャット・文書）で決めた順番。マイルストーンの説明文に書かれた順番は AI が読むだけで、線にはしない
  - Projects のフィールドの中身（Start Date・Target Date・見積もりなど）。トークンに read:project が無くても走るよう、取りに行かない
  - 閉じたマイルストーンと、マイルストーンの付いていない open の issue（{no_milestone} 件）の中身。それらが
    blocked by の相手なら「外から止めている」に出す
  - 見込みに入れていない物: 途中で足される issue（範囲の増え）・人の増減・休み。閉じた件数は今そのマイルストーンに
    居る issue だけで数え、閉じた後に別のマイルストーンへ移された issue は入らない。PR は残りに数えない"""

ISSUE_FIELDS = f"""
  number title url createdAt body
  parent {{ number milestone {{ number }} }}
  subIssuesSummary {{ total completed }}
  blocking(first: 1) {{ totalCount }}
  blockedBy(first: {BLOCKED_FIRST}) {{ totalCount nodes {{
    number title url state repository {{ nameWithOwner }} milestone {{ number }} }} }}
"""

MILESTONES_QUERY = f"""
query($owner: String!, $name: String!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    milestones(states: OPEN, first: 50, after: $cursor, orderBy: {{field: DUE_DATE, direction: ASC}}) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number title url description dueOn createdAt
        closedIssues: issues(states: CLOSED) {{ totalCount }}
        pullRequests(states: OPEN, first: {PR_FIRST}) {{ totalCount nodes {{ number title url isDraft }} }}
      }}
    }}
  }}
}}"""

OPEN_ISSUES_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {{
  repository(owner: $owner, name: $name) {{
    milestone(number: $number) {{
      issues(states: OPEN, first: 50, after: $cursor) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {ISSUE_FIELDS} }}
      }}
    }}
  }}
}}"""

# since は更新の日時で絞る（閉じたのが直近なら更新も直近）。閉じた日時は受け取ってから見る
CLOSED_ISSUES_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $since: DateTime!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    milestone(number: $number) {
      issues(states: CLOSED, first: 100, after: $cursor, filterBy: {since: $since}) {
        pageInfo { hasNextPage endCursor }
        nodes { number closedAt }
      }
    }
  }
}"""

COUNT_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    all: issues(states: OPEN) { totalCount }
    withMilestone: issues(states: OPEN, filterBy: {milestoneNumber: "*"}) { totalCount }
  }
}"""


# ---- 取得 ------------------------------------------------------------------


def fetch(owner, name, today, weeks):
    """母集団の生の材料。戻り値は (マイルストーンの並び, マイルストーンの付いていない open の issue の件数)。"""
    milestones = fetch_all(MILESTONES_QUERY, owner, name, "milestones")
    since = (dt.datetime.combine(today - dt.timedelta(days=7 * weeks), dt.time()).astimezone()
             .astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def one(m):
        num = f"number={m['number']}"
        m["openIssues"] = fetch_all(OPEN_ISSUES_QUERY, owner, name, "milestone.issues", variables=(num,))
        m["closedRecent"] = fetch_all(CLOSED_ISSUES_QUERY, owner, name, "milestone.issues",
                                      variables=(num, "since=" + since))
        return m

    # 4 本まで並べる（マイルストーンが 30 本で 1 本ずつだと 1 分を越える。GitHub の二次の上限に当たらない数）
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        milestones = list(pool.map(one, milestones))
    counts = stop_on_errors(json.loads(gh("api", "graphql", "-f", "query=" + COUNT_QUERY,
                                          "-f", "owner=" + owner, "-f", "name=" + name)))["data"]["repository"]
    return milestones, counts["all"]["totalCount"] - counts["withMilestone"]["totalCount"]


# ---- 事実を組む（純粋関数。tests/milestone-map-suite.py が規則を pin する） ----------------


def local_date(ts):
    """ISO 8601（UTC）の時刻を、この機械のローカルの日付にする。"""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()


def due_date(m):
    """期日。GitHub の dueOn は日付だけを持つフィールドで、時刻の部分は見ない。"""
    return dt.date.fromisoformat(m["dueOn"][:10]) if m.get("dueOn") else None


def weekly_closed(closed_dates, created, today, weeks=WEEKS):
    """週ごとの閉じた件数（古い週から新しい週の順）。週 0 は今日までの 7 日。マイルストーンを作る前の週と、作った日を
    含む端数の週は入れない（途中から数えた週が 0 寄りになり、見込みが遅く偏るため）。作って 7 日に満たなければ週 0 だけ。"""
    age = (today - created).days if created else 7 * weeks
    n = max(1, min(weeks, age // 7))
    counts = [0] * n
    for d in closed_dates:
        k = (today - d).days // 7
        if 0 <= k < n:
            counts[n - 1 - k] += 1
    return counts


def pct(sorted_values, q):
    """並べた値の q 分位（その値以下に q の割合が入る、いちばん小さい値）。"""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def forecast(remaining, weekly, today, seed=SEED, key=0, trials=TRIALS, due=None):
    """残りの件数が 0 になる日の見込み。state は done（残り 0）・none（閉じた実績が無い）・ok の 3 つ。"""
    closed = sum(weekly)
    out = {"remaining": remaining, "samples": len(weekly), "closed": closed}
    if remaining <= 0:
        return {**out, "state": "done"}
    if closed == 0:
        return {**out, "state": "none"}
    rng = random.Random(f"{seed}:{key}")
    runs = []
    for _ in range(trials):
        left, w = remaining, 0
        while left > 0 and w < CAP_WEEKS:
            left -= rng.choice(weekly)
            w += 1
        runs.append(w)
    runs.sort()
    w50, w85 = pct(runs, 0.5), pct(runs, 0.85)
    p50, p85 = today + dt.timedelta(weeks=w50), today + dt.timedelta(weeks=w85)
    wide = []
    if len(weekly) < WIDE_WEEKS:
        wide.append(f"標本が {len(weekly)} 週しか無い")
    if closed < WIDE_CLOSED:
        wide.append(f"閉じた件数が {closed} 件しか無い")
    return {**out, "state": "ok", "weeks50": w50, "weeks85": w85, "p50": p50.isoformat(), "p85": p85.isoformat(),
            "capped": w85 >= CAP_WEEKS, "wide": wide, "late": bool(due and p85 > due)}


HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t#]*$")
FENCE = re.compile(r"^ {0,3}(```|~~~)")


def headings(text):
    """説明文の Markdown の見出し（コードブロックの中は見ない）。"""
    out, fenced = [], False
    for line in (text or "").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def issue_row(i, repo):
    blockers = []
    for b in i["blockedBy"]["nodes"]:
        if b["state"] != "OPEN":
            continue
        other = (b.get("repository") or {}).get("nameWithOwner")
        blockers.append({"number": b["number"], "title": b["title"], "url": b["url"],
                         "repo": other if (other or "").casefold() != repo.casefold() else None,
                         "milestone": (b.get("milestone") or {}).get("number")})
    parent = i.get("parent") or {}
    sub = i.get("subIssuesSummary") or {}
    return {"number": i["number"], "title": i["title"], "url": i["url"], "blocked_by": blockers,
            "blocking": (i.get("blocking") or {}).get("totalCount", 0),
            "parent": parent.get("number"), "parent_milestone": (parent.get("milestone") or {}).get("number"),
            "sub_total": sub.get("total", 0), "sub_done": sub.get("completed", 0)}


def cross_edges(ms, open_numbers):
    """blocked by のうち、マイルストーンをまたぐ物の線と、マイルストーンの外から止めている物。"""
    pairs, outside = {}, []
    for m in ms:
        for i in m["issues"]:
            for b in i["blocked_by"]:
                if b["repo"]:
                    outside.append({"number": i["number"], "milestone": m["number"], "blocker": b["number"],
                                    "where": "other_repo", "repo": b["repo"], "url": b["url"]})
                elif b["milestone"] is None:
                    outside.append({"number": i["number"], "milestone": m["number"], "blocker": b["number"],
                                    "where": "no_milestone", "url": b["url"]})
                elif b["milestone"] not in open_numbers:
                    outside.append({"number": i["number"], "milestone": m["number"], "blocker": b["number"],
                                    "where": "closed_milestone", "url": b["url"]})
                elif b["milestone"] != m["number"]:
                    pairs.setdefault((b["milestone"], m["number"]), []).append([i["number"], b["number"]])
    due = {m["number"]: m["due"] for m in ms}
    edges = []
    for (frm, to), ps in sorted(pairs.items()):
        rev = bool(due[frm] and due[to] and due[frm] > due[to])
        edges.append({"from": frm, "to": to, "count": len(ps), "pairs": sorted(ps), "reversed": rev})
    return edges, outside


def candidate_edges(ms, bodies, repo, max_refs=MAX_REFS):
    """本文が別のマイルストーンの open の issue に触れている物。向きは持たない（組は番号の小さい順）。"""
    where = {i["number"]: m["number"] for m in ms for i in m["issues"]}
    linked = {(i["number"], b["number"]) for m in ms for i in m["issues"] for b in i["blocked_by"] if not b["repo"]}
    pairs, lists = {}, []
    for m in ms:
        for i in m["issues"]:
            refs = repo_refs(bodies.get(i["number"], ""), repo) - {i["number"]}
            if len(refs) > max_refs:
                lists.append({"number": i["number"], "refs": len(refs)})
                continue
            for r in sorted(refs):
                other = where.get(r)
                if other is None or other == m["number"]:
                    continue
                if (i["number"], r) in linked or (r, i["number"]) in linked:
                    continue
                key = tuple(sorted((m["number"], other)))
                pairs.setdefault(key, set()).add((i["number"], r))
    cands = [{"a": a, "b": b, "count": len(ps), "pairs": sorted([list(p) for p in ps])}
             for (a, b), ps in sorted(pairs.items())]
    return cands, lists


def critical_chain(ms, edges):
    """律速の鎖。線が無ければ None。終わりは「自分の 85% の日付と、止めている側の終わりの遅い方」。"""
    if not edges:
        return None
    by = {m["number"]: m for m in ms}
    preds = {}
    for e in edges:
        preds.setdefault(e["to"], []).append(e["from"])
    nodes = sorted({e["from"] for e in edges} | {e["to"] for e in edges})

    def own(n):
        f = by[n]["forecast"]
        if f["state"] == "done":
            return by[n]["today"]
        return f.get("p85") if f["state"] == "ok" else None

    finish, state, cycles = {}, {}, []

    def visit(n, stack):
        if state.get(n) == "done":
            return finish[n]
        if state.get(n) == "open":
            cycles.append(stack[stack.index(n):] + [n])
            return None
        state[n] = "open"
        ends = [own(n)]
        for p in preds.get(n, []):
            ends.append(visit(p, stack + [n]))
        state[n] = "done"
        finish[n] = None if any(x is None for x in ends) else max(ends)
        return finish[n]

    for n in nodes:
        visit(n, [])
    in_cycle = {n for c in cycles for n in c}
    known = [n for n in nodes if finish.get(n) and n not in in_cycle]
    unknown = [n for n in nodes if n not in known]
    if not known:
        return {"chain": [], "end": None, "tail_due": None, "unknown": unknown, "cycles": cycles}
    tail = max(known, key=lambda n: (finish[n], -n))
    chain = [tail]
    while True:
        ps = [p for p in preds.get(chain[0], []) if p in known and p not in chain]
        if not ps:
            break
        chain.insert(0, max(ps, key=lambda n: (finish[n], -n)))
    return {"chain": chain, "end": finish[tail], "tail_due": by[tail]["due"], "unknown": unknown, "cycles": cycles}


def build(raw, no_milestone, repo, today, seed=SEED, trials=TRIALS, weeks=WEEKS, max_refs=MAX_REFS, now=None):
    """取得した生の材料から、ページと AI の材料の両方に使う事実を組む。"""
    limits, ms, bodies = [], [], {}
    for m in raw:
        due = due_date(m)
        created = local_date(m["createdAt"]) if m.get("createdAt") else None
        issues = []
        for i in m["openIssues"]:
            bodies[i["number"]] = i.get("body") or ""
            limits.append(truncated(i["blockedBy"], "blocked by", f"#{i['number']}"))
            issues.append(issue_row(i, repo))
        prs = m["pullRequests"]
        limits.append(truncated(prs, "open の PR", f"マイルストーン {m['title']}"))
        closed_dates = [local_date(c["closedAt"]) for c in m["closedRecent"] if c.get("closedAt")]
        weekly = weekly_closed(closed_dates, created, today, weeks)
        ms.append({
            "number": m["number"], "title": m["title"], "url": m["url"],
            "due": due.isoformat() if due else None,
            "overdue_days": (today - due).days if due and due < today else 0,
            "description": m.get("description") or "", "headings": headings(m.get("description")),
            "open": len(issues), "closed_total": m["closedIssues"]["totalCount"],
            "prs": prs["nodes"], "prs_total": prs["totalCount"],
            "weekly": weekly, "issues": issues, "today": today.isoformat(),
            "forecast": forecast(len(issues), weekly, today, seed, m["number"], trials, due),
        })
    open_numbers = {m["number"] for m in ms}
    edges, outside = cross_edges(ms, open_numbers)
    cands, lists = candidate_edges(ms, bodies, repo, max_refs)
    if lists:
        limits.append(f"本文が {max_refs} 件より多くの issue に触れる issue {len(lists)} 件は、一覧とみなして依存の候補から外した: "
                      + "・".join(f"#{x['number']}（{x['refs']} 件）" for x in lists))
    other_repo = sum(1 for o in outside if o["where"] == "other_repo")
    enum = f"。一覧とみなして外した issue が {len(lists)} 件ある（上限の行）" if lists else ""
    return {
        "schema": SCHEMA, "repo": repo, "url": f"https://github.com/{repo}/milestones",
        "taken_at": (now or dt.datetime.now().astimezone()).isoformat(timespec="seconds"),
        "today": today.isoformat(), "seed": seed, "trials": trials, "weeks": weeks,
        "scope": {"milestones": len(ms), "open_issues": sum(m["open"] for m in ms),
                  "open_prs": sum(m["prs_total"] for m in ms),
                  "closed_recent": sum(sum(m["weekly"]) for m in ms),
                  "blocked_by": sum(len(i["blocked_by"]) for m in ms for i in m["issues"]),
                  "cross_edges": sum(e["count"] for e in edges), "candidates": sum(c["count"] for c in cands),
                  "no_milestone_issues": no_milestone},
        "milestones": ms, "edges": edges, "outside": outside, "candidates": cands,
        "critical": critical_chain(ms, edges),
        "limits": [x for x in limits if x],
        "not_seen": NOT_SEEN.format(enumerations=enum, other_repo=other_repo, no_milestone=no_milestone),
    }


def materials(data, data_path):
    """AI が読む材料。issue の並びは止まっている物だけにし、本文は持たない（ページは data の全部から描く）。"""
    ms = []
    for m in data["milestones"]:
        ms.append({k: m[k] for k in ("number", "title", "url", "due", "overdue_days", "description", "headings",
                                     "open", "closed_total", "prs_total", "weekly", "forecast")}
                  | {"blocked_issues": [{"number": i["number"], "title": i["title"],
                                         "blocked_by": [b["number"] for b in i["blocked_by"]]}
                                        for i in m["issues"] if i["blocked_by"]]})
    keep = ("repo", "taken_at", "today", "seed", "trials", "weeks", "scope", "edges", "outside", "candidates",
            "critical", "limits", "not_seen")
    return {"data_path": str(data_path), "fields_path": str(fields_path(data_path)),
            **{k: data[k] for k in keep}, "milestones": ms}


# ---- AI のフィールド -----------------------------------------------------------------


def fields_path(data_path):
    p = pathlib.Path(data_path)
    return p.with_name(p.stem + "-fields.json")


def validate_fields(obj, data):
    """フィールドの JSON の誤り（1 件 1 行）。無ければ空。"""
    if not isinstance(obj, dict):
        return ["フィールドは JSON のオブジェクトにする"]
    errs = [f"知らないキー {k}（使えるのは headline・points・notes・trays）"
            for k in obj if k not in ("headline", "points", "notes", "trays")]
    numbers = {m["number"] for m in data["milestones"]}
    h = obj.get("headline")
    if not isinstance(h, str) or not h.strip():
        errs.append("headline（全体の一言）が無い")
    elif len(h) > FIELD_CAPS["headline"]:
        errs.append(f"headline が {len(h)} 字（{FIELD_CAPS['headline']} 字まで）")
    pts = obj.get("points", [])
    if not isinstance(pts, list) or not all(isinstance(p, str) and p.strip() for p in pts):
        errs.append("points は空でない文字列の並びにする")
    else:
        if len(pts) > FIELD_CAPS["points"]:
            errs.append(f"points が {len(pts)} 件（{FIELD_CAPS['points']} 件まで）")
        errs += [f"points[{n}] が {len(p)} 字（{FIELD_CAPS['point']} 字まで）"
                 for n, p in enumerate(pts) if len(p) > FIELD_CAPS["point"]]
    notes = obj.get("notes", {})
    if not isinstance(notes, dict):
        errs.append("notes はマイルストーンの番号（文字列）から一言へのオブジェクトにする")
    else:
        for k, v in notes.items():
            if not (re.fullmatch(r"[0-9]+", str(k)) and int(k) in numbers):
                errs.append(f"notes の {k} は母集団のマイルストーンの番号でない")
            elif not isinstance(v, str) or not v.strip():
                errs.append(f"notes の {k} が空")
            elif len(v) > FIELD_CAPS["note"]:
                errs.append(f"notes の {k} が {len(v)} 字（{FIELD_CAPS['note']} 字まで）")
    trays = obj.get("trays", [])
    if not isinstance(trays, list) or not all(isinstance(t, int) and not isinstance(t, bool) for t in trays):
        errs.append("trays はマイルストーンの番号（数）の並びにする")
    else:
        errs += [f"trays の {t} は母集団のマイルストーンの番号でない" for t in trays if t not in numbers]
    return errs


# ---- 図（SVG） -----------------------------------------------------------------------

BOX_W, BOX_H, GAP, PX_DAY, LEFT, TOP, NODUE_GAP = 250, 92, 14, 14, 16, 44, 70
BOX_CHARS = 35  # 箱の 1 行に入る表示の幅（半角を 1。12px の英数字はおよそ 6.6px なので、BOX_W から左右の余白を引いた 234px に収まる数）


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cut(s, w):
    """表示の幅 w（半角を 1）に収める。収まらなければ末尾を … にする。"""
    if width(s) <= w:
        return s
    out = ""
    for c in s:
        if width(out + c) > w - 1:
            return out + "…"
        out += c
    return out


def md(iso, year=None):
    """図の日付。今年なら月-日だけ、別の年なら年から書く。"""
    if not iso:
        return ""
    return iso[5:] if year is None or iso[:4] == str(year) else iso


def layout(ms, today):
    """箱の位置。期日の有る箱は右の端を期日に合わせ、重ならない段に詰める。期日なしは右端の列に縦に並べる。"""
    dated = sorted((m for m in ms if m["due"]), key=lambda m: (m["due"], m["number"]))
    nodue = sorted((m for m in ms if not m["due"]), key=lambda m: m["number"])
    days = [dt.date.fromisoformat(m["due"]) for m in dated] + [today]
    d0 = min(days) - dt.timedelta(days=2)
    d1 = max(days) + dt.timedelta(days=2)

    def x(d):
        return LEFT + BOX_W + (d - d0).days * PX_DAY

    pos, lanes = {}, []
    for m in dated:
        right = x(dt.date.fromisoformat(m["due"]))
        left = right - BOX_W
        lane = next((k for k, r in enumerate(lanes) if r + GAP <= left), None)
        if lane is None:
            lane = len(lanes)
            lanes.append(0)
        lanes[lane] = right
        pos[m["number"]] = (left, TOP + lane * (BOX_H + GAP))
    col = x(d1) + NODUE_GAP
    for k, m in enumerate(nodue):
        pos[m["number"]] = (col, TOP + k * (BOX_H + GAP))
    rows = max(len(lanes), len(nodue), 1)
    return {"pos": pos, "d0": d0, "d1": d1, "x": x, "col": col if nodue else None,
            "w": (col + BOX_W if nodue else x(d1)) + LEFT, "h": TOP + rows * (BOX_H + GAP) + 10}


def _t(x, y, s, cls="", size=12, weight=None):
    w = f' font-weight="{weight}"' if weight else ""
    fill = {"bad": "#c62828", "warn": "#b26a00", "sub": "#59636e"}.get(cls, "#1f2328")
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"{w}>{html.escape(s)}</text>'


def box_lines(m, year):
    """箱の中の 4 行まで（字, 色, 太さ）。どの行も箱の幅に切る。"""
    f = m["forecast"]
    lines = [(f"#{m['number']} {m['title']}", "", "600")]
    due = f"期日 {md(m['due'], year)}" if m["due"] else "期日なし"
    lines.append((f"{due}・残り {m['open']} 件", "", None))
    if f["state"] == "done":
        lines.append(("残りの issue は 0 件", "sub", None))
    elif f["state"] == "none":
        lines.append((f"閉じた実績 0 件（{f['samples']} 週）で見込めない", "warn", None))
    else:
        tail = "以降" if f["capped"] else ""
        lines.append((f"50% {md(f['p50'], year)}・85% {md(f['p85'], year)}{tail}", "warn" if f["late"] else "", None))
    flags = []
    if m["overdue_days"]:
        flags.append((f"期日切れ {m['overdue_days']} 日", "bad"))
    if f.get("late") and not m["overdue_days"]:
        flags.append(("85% が期日を越える", "warn"))
    if f.get("wide"):
        flags.append(("標本が少なく幅が広い", "sub"))
    if flags:
        lines.append(("・".join(s for s, _ in flags), flags[0][1], None))
    return [(cut(s, BOX_CHARS), cls, weight) for s, cls, weight in lines]


def _curve(p, q):
    (x1, y1), (x2, y2) = p, q
    dx = max(40, abs(x2 - x1) / 3)
    return f"M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}", ((x1 + x2) / 2, (y1 + y2) / 2)


def svg(data, trays):
    ms = [m for m in data["milestones"] if m["number"] not in trays]
    today = dt.date.fromisoformat(data["today"])
    lay = layout(ms, today)
    pos, x = lay["pos"], lay["x"]
    crit = data.get("critical") or {}
    chain = crit.get("chain") or []
    on_chain = {(a, b) for a, b in zip(chain, chain[1:])}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{lay["w"]}" height="{lay["h"]}" '
           f'viewBox="0 0 {lay["w"]} {lay["h"]}" role="img" aria-label="マイルストーンの時間軸">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
           'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#57606a"/></marker></defs>']
    # 週の目盛り（月曜）と今日の線
    d = lay["d0"] + dt.timedelta(days=(7 - lay["d0"].weekday()) % 7)
    while d <= lay["d1"]:
        out.append(f'<line x1="{x(d)}" y1="{TOP - 14}" x2="{x(d)}" y2="{lay["h"]}" stroke="#eaeef2"/>')
        out.append(_t(x(d) - 14, 16, md(d.isoformat(), today.year), "sub", 11))
        d += dt.timedelta(days=7)
    out.append(f'<line x1="{x(today)}" y1="{TOP - 20}" x2="{x(today)}" y2="{lay["h"]}" stroke="#c62828" '
               'stroke-dasharray="4 3"/>')
    out.append(_t(x(today) + 4, TOP - 8, "今日", "bad", 11))
    if lay["col"] is not None:
        out.append(f'<line x1="{lay["col"] - NODUE_GAP / 2}" y1="0" x2="{lay["col"] - NODUE_GAP / 2}" '
                   f'y2="{lay["h"]}" stroke="#d1d9e0"/>')
        out.append(_t(lay["col"], 16, "期日なし", "sub", 11))

    def port(n, side):
        bx, by = pos[n]
        return (bx + BOX_W if side == "right" else bx, by + BOX_H / 2)

    # 依存の候補は既定で隠す（多いと線で箱が読めない）。ページの上のチェックボックスで CSS だけで出す
    out.append('<g class="cand">')
    for c in data["candidates"]:
        if c["a"] in pos and c["b"] in pos:
            a, b = sorted((c["a"], c["b"]), key=lambda n: pos[n][0])
            path, (mx, my) = _curve(port(a, "right"), port(b, "left"))
            out.append(f'<path d="{path}" fill="none" stroke="#9aa4ae" stroke-width="1" stroke-dasharray="2 4">'
                       f'<title>依存の候補 {c["count"]} 組（blocked by ではない）</title></path>')
            out.append(_t(mx, my - 3, f"候補 {c['count']}", "sub", 10))
    out.append("</g>")
    for e in data["edges"]:
        if e["from"] in pos and e["to"] in pos:
            path, (mx, my) = _curve(port(e["from"], "right"), port(e["to"], "left"))
            heavy = (e["from"], e["to"]) in on_chain
            color = "#c62828" if e["reversed"] else "#57606a"
            out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{4 if heavy else 1.6}" '
                       f'marker-end="url(#arrow)"><title>blocked by {e["count"]} 組</title></path>')
            out.append(_t(mx, my - 4, f"{e['count']} 本", "bad" if e["reversed"] else "", 11, "600"))
    for m in ms:
        bx, by = pos[m["number"]]
        f = m["forecast"]
        stroke, sw = ("#c62828", 2.5) if m["overdue_days"] else ("#8c959f", 1)
        if m["number"] in chain:
            stroke, sw = "#1f2328", 4
        fill = "#fff4e5" if f.get("late") or f["state"] == "none" else "#ffffff"
        out.append(f'<g><rect x="{bx}" y="{by}" width="{BOX_W}" height="{BOX_H}" rx="6" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"><title>{html.escape(m["title"])}</title></rect>')
        for k, (s, cls, weight) in enumerate(box_lines(m, today.year)):
            out.append(_t(bx + 8, by + 20 + k * 19, s, cls, 12, weight))
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


# ---- ページ ---------------------------------------------------------------------------


def esc(s):
    return html.escape(str(s))


def link(url, text):
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def name_of(data, n):
    m = next((m for m in data["milestones"] if m["number"] == n), None)
    return f"#{n} {m['title']}" if m else f"#{n}"


def issue_link(data, n):
    return link(f"https://github.com/{data['repo']}/issues/{n}", f"#{n}")


def forecast_text(f, due):
    if f["state"] == "done":
        return "残りの issue は 0 件"
    if f["state"] == "none":
        return f"直近 {f['samples']} 週に閉じた実績が無いので見込めない"
    tail = "（5 年で打ち切った。それより後）" if f["capped"] else ""
    s = f"50% {f['p50']}・85% {f['p85']}{tail}（標本 {f['samples']} 週・閉じた {f['closed']} 件）"
    if f["wide"]:
        s += "。" + "・".join(f["wide"]) + "ので、幅が広い"
    if f["late"] and due:
        s += f"。85% の日付が期日 {due} を越える"
    return s


def details(data, m, note):
    f = m["forecast"]
    blocked = [i for i in m["issues"] if i["blocked_by"]]
    rows = [f'<details id="m{m["number"]}"><summary>{esc(name_of(data, m["number"]))}'
            f'<span class="meta">期日 {esc(m["due"] or "なし")}・残り {m["open"]} 件'
            f'{"・期日切れ " + str(m["overdue_days"]) + " 日" if m["overdue_days"] else ""}</span></summary>']
    if note:
        rows.append(f'<p class="ai"><span class="tag">AI の読み</span> {esc(note)}</p>')
    rows.append(f'<p>{link(m["url"], "GitHub のマイルストーン")}。閉じた issue は全部で {m["closed_total"]} 件。</p>')
    rows.append(f"<p><b>見込み</b>: {esc(forecast_text(f, m['due']))}</p>")
    rows.append(f'<p class="weeks">週ごとの閉じた件数（古い週から）: {esc(" ".join(str(n) for n in m["weekly"]))}</p>')
    hs = m["headings"]
    rows.append("<p><b>説明文の見出し</b>: " + (esc("・".join(hs)) if hs else "見出しは無い") + "</p>")
    if blocked:
        rows.append("<p><b>止まっている issue</b></p><ul>" + "".join(
            f"<li>{issue_link(data, i['number'])} {esc(i['title'])} ← "
            + "・".join(link(b["url"], (b["repo"] + "#" if b["repo"] else "#") + str(b["number"])) for b in i["blocked_by"])
            + "</li>" for i in blocked) + "</ul>")
    else:
        rows.append("<p><b>止まっている issue</b>: 無い（open の blocked by を持つ issue は 0 件）</p>")
    cross_parent = [i for i in m["issues"] if i["parent"] and i["parent_milestone"] != m["number"]]
    if cross_parent:
        rows.append("<p><b>親が別のマイルストーンに居る issue</b>: " + "・".join(
            f"{issue_link(data, i['number'])}（親 {issue_link(data, i['parent'])}・"
            f"{esc(name_of(data, i['parent_milestone']) if i['parent_milestone'] else 'マイルストーンなし')}）"
            for i in cross_parent) + "</p>")
    rows.append(f"<p><b>残りの issue</b>（{m['open']} 件）</p><ul>" + "".join(
        f"<li>{issue_link(data, i['number'])} {esc(i['title'])}"
        + (f'<span class="note">（子 {i["sub_done"]}/{i["sub_total"]}）</span>' if i["sub_total"] else "")
        + "</li>" for i in m["issues"]) + "</ul>")
    if m["prs_total"]:
        rows.append(f"<p><b>open の PR</b>（{m['prs_total']} 件。残りには数えない）</p><ul>" + "".join(
            f"<li>{link(p['url'], '#' + str(p['number']))} {esc(p['title'])}{'（draft）' if p.get('isDraft') else ''}</li>"
            for p in m["prs"]) + "</ul>")
    rows.append("</details>")
    return "\n".join(rows)


OUTSIDE_WORDS = {"other_repo": "別のリポジトリ", "no_milestone": "マイルストーンなし", "closed_milestone": "閉じたマイルストーン"}


def body_html(data, fields):
    trays = set(fields.get("trays") or [])
    notes = {int(k): v for k, v in (fields.get("notes") or {}).items()}
    s = data["scope"]
    out = [f"<h1>マイルストーンの地図 — {esc(data['repo'])}</h1>",
           f'<p class="sub">{esc(data["taken_at"])} に GitHub から取った。open のマイルストーン {s["milestones"]} 本・'
           f'open の issue {s["open_issues"]} 件・open の PR {s["open_prs"]} 件・直近 {data["weeks"]} 週（作る前の週を除く）に閉じた issue '
           f'{s["closed_recent"]} 件。マイルストーンの付いていない open の issue は {s["no_milestone_issues"]} 件。'
           f'正本は {link(data["url"], "GitHub のマイルストーン")}で、このページは読むだけ。</p>',
           '<div class="ai"><span class="tag">AI の読み（下の機械の事実から書いた判定）</span>'
           f'<p class="headline">{esc(fields["headline"])}</p>']
    if fields.get("points"):
        out.append("<ul>" + "".join(f"<li>{esc(p)}</li>" for p in fields["points"]) + "</ul>")
    out.append("</div>")
    out.append("<h2>時間軸</h2>")
    shown = [c for c in data["candidates"] if c["a"] not in trays and c["b"] not in trays]
    if shown:
        out.append('<input type="checkbox" id="showcand"><label class="toggle" for="showcand"> 依存の候補の点線を図に出す'
                   f'（マイルストーンの組 {len(shown)} 本。blocked by ではない）</label>')
    out.append(f'<div class="fig">{svg(data, trays)}</div>')
    out.append('<p class="legend"><span>箱の右の端＝期日</span><span>50%・85%＝残りを閉じ終える見込みの日</span>'
               '<span>赤い枠＝期日切れ</span><span>橙の地＝85% の見込みが期日を越える・見込めない</span><span>実線の矢印＝blocked by（止めている側 → 待つ側。'
               '数は issue の組の数。赤は期日の逆転）</span><span>太線＝律速</span><span>点線＝依存の候補（blocked by ではない）</span>'
               '<span>箱の中身の続きは下の「マイルストーンごとの詳細」</span></p>')
    out.append("<h2>依存</h2>")
    edges = data["edges"]
    if edges:
        out.append(f"<p>issue の blocked by のうち、マイルストーンをまたぐ物 {s['cross_edges']} 組を {len(edges)} 本の線にした。</p><ul>")
        for e in edges:
            rev = '<span class="bad">（期日の逆転: 止めている側の期日が後ろ）</span>' if e["reversed"] else ""
            out.append(f"<li>{esc(name_of(data, e['from']))} → {esc(name_of(data, e['to']))}: {e['count']} 本{rev}（"
                       + "・".join(f"{issue_link(data, a)} ← {issue_link(data, b)}" for a, b in e["pairs"]) + "）</li>")
        out.append("</ul>")
    else:
        out.append(f"<p>issue の blocked by でマイルストーンをまたぐ物は 0 件なので、依存の線は出ない（open の issue が持つ "
                   f"open の blocked by は全部で {s['blocked_by']} 件）。</p>")
    crit = data.get("critical")
    if crit and crit["chain"]:
        out.append("<p><b>律速</b>（85% 側の終わりがいちばん遅い鎖。終わり "
                   f"{esc(crit['end'])}）: " + " → ".join(esc(name_of(data, n)) for n in crit["chain"]) + "</p>")
    if crit and crit["unknown"]:
        out.append("<p>見込めない・輪になったため律速の計算から外したマイルストーン: "
                   + "・".join(esc(name_of(data, n)) for n in crit["unknown"]) + "</p>")
    if data["outside"]:
        out.append("<p><b>外から止めている issue</b></p><ul>" + "".join(
            f"<li>{issue_link(data, o['number'])}（{esc(name_of(data, o['milestone']))}）← "
            f"{link(o['url'], (o.get('repo') + '#' if o.get('repo') else '#') + str(o['blocker']))}"
            f"（{OUTSIDE_WORDS[o['where']]}）</li>" for o in data["outside"]) + "</ul>")
    cands = data["candidates"]
    if cands:
        out.append(f"<p><b>依存の候補</b>（blocked by ではない。issue の本文が別のマイルストーンの issue に触れている物 "
                   f"{s['candidates']} 組。前提かは読んでいない。前提なら GitHub で blocked by を付けると、次から実線になる）</p><ul>")
        for c in cands:
            out.append(f"<li>{esc(name_of(data, c['a']))} ⇔ {esc(name_of(data, c['b']))}: {c['count']} 組（"
                       + "・".join(f"{issue_link(data, a)} → {issue_link(data, b)}" for a, b in c["pairs"]) + "）</li>")
        out.append("</ul>")
    tray_ms = [m for m in data["milestones"] if m["number"] in trays]
    if tray_ms:
        out.append("<h2>受け皿</h2><p class=\"note\">完了条件を置かないマイルストーン（AI が説明文から選んだ）。時間軸には置かない。</p>"
                   '<div class="trays">')
        for m in tray_ms:
            out.append(f'<div class="tray"><b>{esc(name_of(data, m["number"]))}</b><br>'
                       f'残り {m["open"]} 件・期日 {esc(m["due"] or "なし")}</div>')
        out.append("</div>")
    out.append("<h2>マイルストーンごとの詳細</h2>")
    order = sorted((m for m in data["milestones"] if m["number"] not in trays),
                   key=lambda m: (m["due"] is None, m["due"] or "", m["number"])) + tray_ms
    out += [details(data, m, notes.get(m["number"])) for m in order]
    out.append("<h2>見込みの出し方</h2>")
    out.append(f"<p>throughput に基づくモンテカルロ。マイルストーンごとに直近 {data['weeks']} 週（作る前の週は入れない）の週ごとの"
               f"閉じた件数を標本にし、残りの件数が 0 になるまで週を復元抽出で引く試しを {data['trials']} 回回して、50% と 85% の"
               f"週の数を今日（{esc(data['today'])}）に足した。平均の割り算はしない（"
               + link("https://www.hanssamios.com/dokuwiki/why_a_plan_based_on_average_velocity_will_fail",
                      "a plan based on averages will fail, on average")
               + f"）。標本が {WIDE_WEEKS} 週未満か閉じた件数が {WIDE_CLOSED} 件未満なら幅が広いと書く（このツールの目安）。"
               f"乱数の種は {data['seed']}。同じ材料なら同じ日付が出る。</p>")
    out.append("<h2>上限と見ていないもの</h2>")
    if data["limits"]:
        out.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in data["limits"]) + "</ul>")
    else:
        out.append("<p>取得の上限に当たった所は無い。</p>")
    out.append("<pre style=\"white-space:pre-wrap\">" + esc(data["not_seen"]) + "</pre>")
    return "\n".join(out)


def build_html(template, data, fields):
    for slot in (BODY_SLOT, TITLE_SLOT):
        if slot not in template:
            raise ValueError(f"雛形に差し込み口 {slot} が無い")
    head, tail = template.split(BODY_SLOT, 1)
    title = f"<title>{esc('マイルストーンの地図 ' + data['repo'])}</title>"
    return head.replace(TITLE_SLOT, title, 1) + body_html(data, fields) + tail


def cache_root(home=None):
    return pathlib.Path(home or pathlib.Path.home()) / ".cache" / "attention" / "milestone-map"


def repo_dir(repo, root=None):
    return (pathlib.Path(root) if root else cache_root()) / catchup_html._safe(repo.replace("/", "-"))


def render(data_path, fields_file, template=None, env=None):
    """ページを描く。戻り値は (終了コード, 人に見せる行)。"""
    try:
        data = json.loads(pathlib.Path(data_path).read_text(encoding="utf-8"))
        fields = json.loads(pathlib.Path(fields_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 2, [f"材料かフィールドの JSON が読めない（{e}）"]
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return 2, [f"材料の形が違う（schema {SCHEMA} の milestone-map.py --out で集め直す）"]
    errs = validate_fields(fields, data)
    if errs:
        return 2, ["フィールドの JSON を直す:"] + [f"- {e}" for e in errs]
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    path = pathlib.Path(data_path).with_name("map.html")
    catchup_html._write_atomic(path, build_html(template, data, fields))
    return 0, [str(path), fields["headline"], catchup_html.open_in_vscode(path, env)]


# ---- 入口 ------------------------------------------------------------------------


def parser():
    ap = argparse.ArgumentParser(
        description=__doc__ + "\n" + NOT_SEEN.format(enumerations="", other_repo="N", no_milestone="N"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="OWNER/NAME（省略時はカレントリポジトリ）")
    ap.add_argument("--weeks", type=int, default=WEEKS, help=f"閉じた件数を数える直近の週の数（既定 {WEEKS}）")
    ap.add_argument("--trials", type=int, default=TRIALS, help=f"モンテカルロの試しの回数（既定 {TRIALS}）")
    ap.add_argument("--seed", type=int, default=SEED, help=f"乱数の種（既定 {SEED}。同じ材料なら同じ日付が出る）")
    ap.add_argument("--max-refs", type=int, default=MAX_REFS,
                    help=f"本文がこれより多くの issue に触れる issue は一覧とみなして依存の候補から外す（既定 {MAX_REFS}）")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="今日の日付 YYYY-MM-DD（試験と見直しの再現のため。既定は今日）")
    ap.add_argument("--render", nargs=2, metavar=("材料", "フィールド"), help="材料とフィールドの JSON からページを描く")
    outfile.add_flag(ap)
    return ap


def collect(a):
    # 正式の名前（大文字小文字）に揃える。blocked by の相手のリポジトリと、本文の URL を自リポジトリと照合するため
    repo = gh("repo", "view", *([a.repo] if a.repo else []), "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    owner, name = repo.split("/", 1)
    today = a.today or dt.date.today()
    raw, no_ms = fetch(owner, name, today, a.weeks)
    data = build(raw, no_ms, repo, today, a.seed, a.trials, a.weeks, a.max_refs)
    path = repo_dir(repo) / "data.json"
    catchup_html._write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(materials(data, path), ensure_ascii=False, indent=1))
    return 0


def main(argv=None):
    a = parser().parse_args(argv)
    if a.render:
        code, lines = render(*a.render)
        print("\n".join(lines))
        return code
    if a.weeks < 1 or a.trials < 1:
        print("--weeks と --trials は 1 以上にする", file=sys.stderr)
        return 2
    if not a.out:
        return collect(a)
    return outfile.run_to_file(lambda: collect(a), "milestone-map")


if __name__ == "__main__":
    sys.exit(main())
