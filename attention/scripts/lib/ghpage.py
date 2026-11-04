"""GitHub の GraphQL の一覧を全部のページまで取る共通部。/whose-turn と /milestone-map で共用。

fetch_all() はカーソルで最後のページまで取り、GraphQL のエラーなら止める。ただし、呼ぶ側が optional に挙げた
フィールドをその GitHub が持たないとき（GHES の古い版など）だけは MissingField を投げ、呼ぶ側が別の問い合わせで
取り直せるようにする。truncated() は、ページを取らない入れ子の一覧（first: N）が上限に当たったかを 1 行で言う。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/ghpage.py、写しは works-dispatch/dispatch/vendor/lib/ghpage.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/ghpage.py。

import json
import sys

from ghcli import gh
from turn import missing_only


class MissingField(Exception):
    """問い合わせたフィールドをその GitHub が持たない（graphql-ruby の静的検証の undefinedField）"""


def stop_on_errors(data):
    """GraphQL の答えにエラーがあれば止める。無ければそのまま返す"""
    if data.get("errors"):
        sys.exit("GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False))
    return data


def dig(data, path):
    """data["data"]["repository"] から、点で区切った path（"milestone.issues" など）をたどる。"""
    node = data["data"]["repository"]
    for key in path.split("."):
        node = node[key]
    return node


def fetch_all(query, owner, name, field, optional=(), variables=()):
    """field（"pullRequests" や "milestone.issues"）の全ページ。variables は gh の -F に渡す "key=value" の並び
    （数は -F で Int になる）。optional に挙げたフィールドが無いと返ったときだけ MissingField を投げ、ほかのエラーは止める"""
    nodes, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", "query=" + query, "-f", "owner=" + owner, "-f", "name=" + name]
        for v in variables:
            args += ["-F", v]
        if cursor:
            args += ["-f", "cursor=" + cursor]
        data = json.loads(gh(*args, graphql_errors=bool(optional)))
        if missing_only(data.get("errors"), optional):
            raise MissingField()
        conn = dig(stop_on_errors(data), field)
        nodes += conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return nodes
        cursor = conn["pageInfo"]["endCursor"]


def truncated(conn, what, where):
    """取得上限に当たったら、その旨の 1 行。全件取れていれば None。"""
    if conn["totalCount"] > len(conn["nodes"]):
        return f"{where}: {what} {conn['totalCount']} 件のうち {len(conn['nodes'])} 件しか見ていない"
    return None
