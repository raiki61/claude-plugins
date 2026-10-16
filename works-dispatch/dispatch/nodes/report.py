#!/usr/bin/env python3
"""report ノード: 報告の行を作る純粋な関数（設計書 2 節の 8）。外には書かない。

頭に注記（使用率の控えが無いアカウントなど）、続けて 1 件 1 行: `#<番号> <タイトル>  <枝>  <アカウント>  <結末>`。
issue から始めたもの（kind が issue）は `issue #<番号> …` で始める。まだ枝が無ければ枝の欄は `-`。
結末の語は sent・refreshed・blocked・stalled・already_open・no_news・busy・dirty・unpushed・close_failed・
no_account・provision_failed・branch_busy・pane_busy・launch_failed・send_failed・issue_closed と、--dry-run の create（作業場を作る）・
reuse（使い直す）・refresh（送り直す）。
PR が 0 件なら「自分の番の PR は無い」の 1 行。

使い方: python3 nodes/report.py --plan <plan の JSON> [--results <番号→結末の JSON>]
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jsonio  # noqa: E402

# Windows の既定の標準出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

NONE = "自分の番の PR は無い"


def lines(plan, results, notes):
    out = list(notes)
    if not plan:
        return out + [NONE]
    for r in plan:
        head = "issue " if r.get("kind") == "issue" else ""
        who = (r.get("account") or {}).get("name") or "-"
        out.append(f"{head}#{r['number']} {r['title']}  {r.get('head') or '-'}  {who}  {results.get(r['number'], r['outcome'])}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    results = {int(k): v for k, v in json.loads(pathlib.Path(a.results).read_text()).items()} if a.results else {}
    print("\n".join(lines(jsonio.load(a.plan)["plan"], results, [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
