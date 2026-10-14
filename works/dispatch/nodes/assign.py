#!/usr/bin/env python3
"""assign ノード: PR ごとに結末を 1 つ決める純粋な関数（設計書 2 節の 5）。外には書かない。

決める順:
1. (対象のリポジトリ, PR の head の枝) の組の会話が開いていれば already_open。作業場もアカウントも取らない。
2. 選べるアカウントが無ければ no_account。選べるなら、全部の PR を順の先頭のアカウントに入れる
   （控えは実行の途中で更新されず、持ち主の決め「切り替わりの近い枠から使い切る」とも同じ向きなので、散らさない）。
3. 作業場: 空きの中に、すでにその PR の枝にいる作業場があれば、それを先に取り置く（枝を移さずに済む）。
   取り置きの無い PR は、設定の順で、取り置かれていない最初の空きを取る。無ければ no_slot。
並びは prs の順のまま。作業場は 1 つにつき 1 件。

使い方: python3 nodes/assign.py --repo OWNER/NAME --prs <JSON> --sessions <JSON> --accounts <JSON> --slots <JSON> [--out <パス>]
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jsonio  # noqa: E402


def plan(repo, prs, open_keys, accounts, slots):
    account = next((a for a in accounts if a.get("eligible")), None)
    todo = [p for p in prs if (repo, p["head"]) not in open_keys]
    free = [s for s in slots if s.get("free")]

    reserved = {}  # PR 番号 → 作業場
    taken = set()
    if account:
        for p in todo:
            s = next((s for s in free if s.get("branch") == p["head"] and s["workspace"] not in taken), None)
            if s:
                reserved[p["number"]] = s
                taken.add(s["workspace"])

    rows = []
    for p in prs:
        row = {"number": p["number"], "title": p["title"], "head": p["head"], "url": p.get("url"),
               "outcome": None, "account": None, "slot": None}
        if (repo, p["head"]) in open_keys:
            row["outcome"] = "already_open"
        elif account is None:
            row["outcome"] = "no_account"
        else:
            s = reserved.get(p["number"])
            if s is None:
                s = next((s for s in free if s["workspace"] not in taken), None)
                if s:
                    taken.add(s["workspace"])
            if s is None:
                row["outcome"] = "no_slot"
            else:
                row.update(outcome="assigned", account=account, slot=s)
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--repo", "--prs", "--sessions", "--accounts", "--slots"):
        ap.add_argument(k, required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sessions = jsonio.load(a.sessions)["sessions"]
    keys = {(s["repo"], s["branch"]) for s in sessions if s.get("repo") and s.get("branch")}
    rows = plan(a.repo, jsonio.load(a.prs)["prs"], keys, jsonio.load(a.accounts)["accounts"], jsonio.load(a.slots)["slots"])
    jsonio.dump({"plan": rows}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
