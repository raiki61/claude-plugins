#!/usr/bin/env python3
"""launch ノード: 割り振りの案の 1 行を受け、作業場のペインでアカウントの Claude Code を起こす（設計書 2 節の 6）。外に書く。

ペインのシェルに、アカウントの起動のコマンド（設定の accounts の command）を打ち込む。最初のプロンプトは付けない。
`CLAUDE_CONFIG_DIR=… claude` の形は使わない。持ち主の claude はシェル関数で、既定のアカウントのトークンを入れてから起こすので、
設定のフォルダを替えても既定のアカウントで動いてしまう。herdr の agent start も使わない（素の claude を起こし、アカウントを選べない）。
起こした後に、そのペインに会話が見えることを herdr から読み戻してから返す（送ったつもりで起きていない、を返さない）。

使い方: python3 nodes/launch.py --plan <plan の JSON> --number <PR 番号> [--out <パス>]
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import herdr  # noqa: E402
import jsonio  # noqa: E402


def start(row, h=herdr):
    pane, command = row["slot"]["pane"], row["account"]["command"]
    result = {"number": row["number"], "pane": pane, "status": "launch_failed", "detail": None}
    try:
        h.run(pane, command)
        h.wait_ready(pane)
        seen = h.agent(pane)
    except h.HerdrError as e:
        result["detail"] = str(e)
        return result
    if seen.get("agent") != "claude":
        result["detail"] = f"起こした後のペインに会話が見えない（agent={seen.get('agent')}, status={seen.get('agent_status')}）"
        return result
    result["status"] = "ready"
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"launch": start(row)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
