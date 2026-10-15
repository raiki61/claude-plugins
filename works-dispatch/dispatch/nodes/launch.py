#!/usr/bin/env python3
"""launch ノード: 割り振りの案の 1 行と作業場のペインを受け、そのペインでアカウントの Claude Code を起こす（設計書 2 節の 6）。外に書く。

ペインのシェルに、アカウントの起動のコマンド（設定の accounts の command）を打ち込む。最初のプロンプトは付けない。
`CLAUDE_CONFIG_DIR=… claude` の形は使わない。持ち主の claude はシェル関数で、既定のアカウントのトークンを入れてから起こすので、
設定のフォルダを替えても既定のアカウントで動いてしまう。herdr の agent start も使わない（素の claude を起こし、アカウントを選べない）。
起こした後に、そのペインに会話が見えることを herdr から読み戻してから返す（送ったつもりで起きていない、を返さない）。
打ち込む前に、ペインの前にシェルだけが居ることを確かめる。vim・dev server・別の会話が残っていれば打ち込まない（pane_busy）。
起こした後に確認の画面（フォルダの信頼・ログインなど）で止まったら、blocked で返し、/catchup は送らない。
POSIX のシェルでは、コマンドの前に `ATTENTION_CATCHUP_OPEN=0` を置く。attention の /catchup は書いたページを VS Code の窓に
開くが、dispatch は何件も一度に起こすので、窓にタブが一気に開かないようにする（ページは書かれ、一覧のページに載る）。
シェル関数のアカウントのコマンドにも、この前置きは関数の間だけ環境変数として渡る（bash・zsh で確かめた）。

使い方: python3 nodes/launch.py --plan <plan の JSON> --number <PR 番号> --pane <ペイン ID> [--out <パス>]
"""

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import herdr  # noqa: E402
import jsonio  # noqa: E402


QUIET_CATCHUP = "ATTENTION_CATCHUP_OPEN=0"


def start(row, pane, h=herdr, posix=None):
    command = row["account"]["command"]
    if os.name != "nt" if posix is None else posix:
        command = f"{QUIET_CATCHUP} {command}"
    result = {"number": row["number"], "pane": pane, "status": "launch_failed", "detail": None}
    try:
        if not h.shell_in_front(pane):
            result.update(status="pane_busy", detail="作業場のペインの前で、シェルではない物が動いている（打ち込まない。そのペインを空けてから打ち直す）")
            return result
        h.run(pane, command)
        state = h.wait_ready(pane)
        seen = h.agent(pane)
    except h.HerdrError as e:
        result["detail"] = str(e)
        return result
    if state == "blocked":
        result.update(status="blocked", detail="起こした後に確認の画面で止まっている（フォルダの信頼・ログインなど）。"
                                               "そのペインで答えてから /catchup を送る")
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
    ap.add_argument("--pane", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"launch": start(row, a.pane)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
