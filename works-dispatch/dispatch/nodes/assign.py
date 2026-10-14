#!/usr/bin/env python3
"""assign ノード: PR ごとに結末を 1 つ決める純粋な関数（設計書 2 節の 4）。外には書かない。

決める順:
1. 会話が開いていれば already_open。(対象のリポジトリ, PR の head の枝) の組の会話か、その PR の clone のフォルダかその下を
   作業フォルダにする会話があるとき。作業場もアカウントも取らない（会話を閉じるのは持ち主だけ）。
2. 選べるアカウントが無ければ no_account。選べるなら、全部の PR を順の先頭のアカウントに入れる
   （控えは実行の途中で更新されず、持ち主の決め「切り替わりの近い枠から使い切る」とも同じ向きなので、散らさない）。
3. どれにも当たらなければ assigned で、アカウントと、その PR の clone のフォルダを付ける。
並びは prs の順のまま。

使い方: python3 nodes/assign.py --prs <JSON> --sessions <JSON> --accounts <JSON> [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import jsonio  # noqa: E402


def _inside(cwd, path):
    c, p = pathlib.PurePath(cwd), pathlib.PurePath(path)
    return c == p or p in c.parents


def plan(repo, prs, open_keys, open_cwds, accounts):
    account = next((a for a in accounts if a.get("eligible")), None)
    rows = []
    for p in prs:
        path = config.clone_path(repo, p["number"])
        row = {"number": p["number"], "title": p["title"], "head": p["head"], "url": p.get("url"),
               "outcome": "assigned", "account": None, "clone_path": path}
        if (repo.repo, p["head"]) in open_keys or any(_inside(c, path) for c in open_cwds if c):
            row["outcome"] = "already_open"
        elif account is None:
            row["outcome"] = "no_account"
        else:
            row["account"] = account
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--prs", "--sessions", "--accounts"):
        ap.add_argument(k, required=True)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    repo = config.pick_repo(config.load(a.config, os.environ), a.repo)
    sessions = jsonio.load(a.sessions)["sessions"]
    keys = {(s["repo"], s["branch"]) for s in sessions if s.get("repo") and s.get("branch")}
    cwds = {s["cwd"] for s in sessions if s.get("cwd")}
    rows = plan(repo, jsonio.load(a.prs)["prs"], keys, cwds, jsonio.load(a.accounts)["accounts"])
    jsonio.dump({"plan": rows}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
