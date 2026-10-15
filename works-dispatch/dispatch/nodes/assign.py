#!/usr/bin/env python3
"""assign ノード: PR ごとに結末を 1 つ決める純粋な関数（設計書 2 節の 4）。外には書かない。

決める順:
1. 会話が開いていれば already_open。(対象のリポジトリ, PR の head の枝) の組の会話か、その枝の場所（元の clone の worktree。
   設計書 3 節）かその下を作業フォルダにする会話があるとき。作業場もアカウントも取らない（会話を閉じるのは持ち主だけ）。
2. 開く PR を、選べるアカウントに順の頭から割り振る。全部の PR は同時に走るので、始める前に件数を決める。
   - 1 件あたりの使用率（cost ノードが測って覚えた見積もり）があれば、各アカウントに、上限（limit_percent）に届かずに
     入る件数まで入れ、あふれた分を次のアカウントへ回す（持ち主の決め「切り替わりの近い枠から使い切る」）。
     件数は、週と 5 時間の枠ごとに「使用率 + 件数 × 1 件あたり < 上限」を満たす最大の数の、小さい方。
     使用率の分からないアカウント（控えが無い・使用率の枠が無い）は、件数で縛らない。
   - まだ測っていなければ、1 つのアカウントに寄せず、選べるアカウントに 1 件ずつ順に配る（入れすぎない側に倒す）。
   - どのアカウントにも入らない PR は no_account。
3. どれにも当たらなければ assigned で、アカウントを付ける。
各行には、その枝の場所（まだ無ければ None）と、PR か issue か（kind）を付ける。並びは prs の順のまま。

使い方: python3 nodes/assign.py --prs <JSON> --sessions <JSON> --accounts <JSON> [--places <JSON>] [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import math
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import jsonio  # noqa: E402


def _inside(cwd, path):
    c, p = pathlib.PurePath(cwd), pathlib.PurePath(path)
    return c == p or p in c.parents


WINDOWS = ("seven_day", "five_hour")


def _capacity(account, limit_percent, cost):
    """そのアカウントに、上限に届かずに入る件数。縛れないなら math.inf。"""
    if not account.get("known", True):
        return math.inf
    caps = []
    for w in WINDOWS:
        used, each = (account.get(w) or {}).get("used"), (cost or {}).get(w)
        if isinstance(used, (int, float)) and isinstance(each, (int, float)) and each > 0:
            caps.append(max(math.ceil((limit_percent - used) / each) - 1, 0))
    return min(caps) if caps else math.inf


def _spread(accounts, n, limit_percent, cost):
    """開く n 件に、順にアカウントを 1 つずつ（入らなければ None）。"""
    eligible = [a for a in accounts if a.get("eligible")]
    if not eligible:
        return [None] * n
    if cost is None:
        return [eligible[i % len(eligible)] for i in range(n)]
    out = []
    for a in eligible:
        cap = _capacity(a, limit_percent, cost)
        while len(out) < n and cap > 0:
            out.append(a)
            cap -= 1
    return out + [None] * (n - len(out))


def plan(repo, prs, open_keys, open_cwds, accounts, limit_percent=95, cost=None, places=None):
    """cost は {枠: 1 件あたりの使用率}（cost ノードの estimate）。None はまだ測っていない。
    places は {枝: その枝の場所のパス}。prs の 1 件の kind（pr・issue。無ければ pr）と fork（fork の PR か）は、そのまま行に写す。"""
    places = places or {}
    rows = []
    for p in prs:
        path = places.get(p["head"]) if p.get("head") else None
        row = {"number": p["number"], "kind": p.get("kind", "pr"), "title": p["title"], "head": p.get("head"),
               "url": p.get("url"), "fork": bool(p.get("fork")), "outcome": "assigned", "account": None, "path": path}
        if (repo.repo, p.get("head")) in open_keys or (path and any(_inside(c, path) for c in open_cwds if c)):
            row["outcome"] = "already_open"
        rows.append(row)
    to_open = [r for r in rows if r["outcome"] == "assigned"]
    for row, account in zip(to_open, _spread(accounts, len(to_open), limit_percent, cost)):
        if account is None:
            row["outcome"] = "no_account"
        else:
            row["account"] = account
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--prs", "--sessions", "--accounts"):
        ap.add_argument(k, required=True)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--places", help="枝 → 場所のパスの JSON（{\"places\": {...}}）")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    repo = config.pick_repo(config.load(a.config, os.environ), a.repo)
    sessions = jsonio.load(a.sessions)["sessions"]
    keys = {(s["repo"], s["branch"]) for s in sessions if s.get("repo") and s.get("branch")}
    cwds = {s["cwd"] for s in sessions if s.get("cwd")}
    places = jsonio.load(a.places)["places"] if a.places else {}
    rows = plan(repo, jsonio.load(a.prs)["prs"], keys, cwds, jsonio.load(a.accounts)["accounts"], places=places)
    jsonio.dump({"plan": rows}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
