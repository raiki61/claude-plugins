#!/usr/bin/env python3
"""マイルストーンの付いていない issue の、Projects の日付のフィールド（Target Date など）を、/milestone-map の --dates の JSON にする。

〈目的〉GitHub の issue には期日のフィールドが無い。日付を Projects の日付のフィールドに書いているリポジトリ向けの、固有の部品。
/milestone-map の本体（milestone-map.py）は日付をどこから取るかを知らず、--dates の JSON だけを読む。ほかの所（別の
Projects のフィールド・表計算の書き出しなど）から日付を取るときは、同じ形の JSON を出す部品を別に書けばよい。

〈出力〉標準出力に {"issue の番号": "YYYY-MM-DD"}。マイルストーンの付いていない open の issue 全部と、閉じた issue の
うち閉じた日が 400 日の中の物（milestone-map.py の SINCE_DAYS と同じ）を見て、フィールドに日付が在る物だけを書く。issue が
Projects の 2 つ以上に載り、どれにも同じ名前のフィールドが在るときは、--project で 1 つに絞らない限り、いちばん早い日付を取る。

〈要るもの〉トークンに read:project（または project）。無ければ GitHub のエラーを出して止まる。

使い方: milestone-map.py --dates <(project-dates.py --field 'Target Date' [--project 9] [--repo OWNER/NAME])
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from ghcli import gh  # noqa: E402 — gh を呼ぶ共通部。/whose-turn・/catchup と共用
from ghpage import stop_on_errors  # noqa: E402 — GraphQL のエラーで止める。/whose-turn と共用

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SINCE_DAYS = 400  # milestone-map.py の SINCE_DAYS と同じ
ITEMS_FIRST = 20  # 1 件の issue が載っている Projects を取る数

# マイルストーンの付いていない issue は検索（no:milestone）で取る（issues の filterBy の milestoneNumber に "none" を
# 渡しても 0 件が返るため。milestone-map.py と同じ）
QUERY = f"""
query($q: String!, $field: String!, $cursor: String) {{
  search(type: ISSUE, query: $q, first: 50, after: $cursor) {{
    issueCount
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ ... on Issue {{
      number
      projectItems(first: {ITEMS_FIRST}) {{ nodes {{
        project {{ number }}
        fieldValueByName(name: $field) {{ ... on ProjectV2ItemFieldDateValue {{ date }} }} }} }} }} }}
  }}
}}"""


def search_all(q, field):
    """検索の全ページの issue。検索は 1 つの問いに 1000 件までしか返さないので、取り切れなければ標準エラーに知らせる
    （標準出力の JSON は変えない）。"""
    nodes, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", "query=" + QUERY, "-f", "q=" + q, "-f", "field=" + field]
        conn = stop_on_errors(json.loads(gh(*args + (["-f", "cursor=" + cursor] if cursor else []))))["data"]["search"]
        nodes += [n for n in conn["nodes"] if n]
        if not conn["pageInfo"]["hasNextPage"]:
            if conn.get("issueCount", 0) > len(nodes):
                print(f"project-dates: 「{q}」は {conn['issueCount']} 件のうち {len(nodes)} 件しか見ていない（検索の上限）",
                      file=sys.stderr)
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


def dates_of(issues, project=None):
    """issue の並びから {番号の字: 日付の字} を組む。project を渡せばその番号の Projects のフィールドだけを見る。"""
    out = {}
    for i in issues:
        got = [n["fieldValueByName"]["date"] for n in i["projectItems"]["nodes"]
               if (n.get("fieldValueByName") or {}).get("date") and (project is None or (n.get("project") or {}).get("number") == project)]
        if got:
            out[str(i["number"])] = min(got)[:10]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--field", required=True, help="Projects の日付のフィールドの名前（例: 'Target Date'）")
    ap.add_argument("--project", type=int, help="見る Projects の番号（省略時は、issue が載っている Projects 全部）")
    ap.add_argument("--repo", help="OWNER/NAME（省略時はカレントリポジトリ）")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="今日の日付 YYYY-MM-DD（試験のため。既定は今日）")
    a = ap.parse_args(argv)
    repo = gh("repo", "view", *([a.repo] if a.repo else []), "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    base = f"repo:{repo} is:issue no:milestone"
    since = (a.today or dt.date.today()) - dt.timedelta(days=SINCE_DAYS)
    issues = search_all(base + " is:open", a.field) + search_all(f"{base} is:closed closed:>={since}", a.field)
    json.dump(dates_of(issues, a.project), sys.stdout, ensure_ascii=False, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
