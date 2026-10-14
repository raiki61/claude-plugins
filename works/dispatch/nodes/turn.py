#!/usr/bin/env python3
"""turn ノード: 会話にターンを送る（設計書 2 節の 7）。外に書く。

1 ターン目の `/catchup <番号>` は待ち付きで送る。herdr の agent prompt --wait は、送った後に動き出したのを見てから止まるまで待つ。
`herdr agent wait` だけで待たないのは、それがターンの区切りを追わず、始まる前の idle に当たりうるため。
2 ターン目は、1 ターン目が idle か done で終えた時だけ、待たずに送る。2 ターン目の文が無ければ（--no-second）、
`/catchup <番号>` だけを待たずに送って終える。blocked（許可の確認などで止まっている）と
stalled（送って動き出さなかった。herdr の組み込みの見張りの結末）なら送らない。こちらからは期限を足さない。

使い方: python3 nodes/turn.py --pane <ペイン ID> --text <文> [--wait] [--out <パス>]
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import herdr  # noqa: E402
import jsonio  # noqa: E402

FINISHED = ("idle", "done")


def send(pane, text, wait, h=herdr):
    try:
        return {"pane": pane, "status": h.prompt(pane, text, wait), "detail": None}
    except h.HerdrError as e:
        return {"pane": pane, "status": "failed", "detail": str(e)}


def catchup_then_second(number, pane, second, h=herdr):
    """結末の語 sent・blocked・stalled・send_failed のどれかを返す。second が None なら 1 ターン目だけ送る。"""
    if second is None:
        only = send(pane, f"/catchup {number}", False, h)
        return "sent" if only["status"] == "sent" else "send_failed"
    first = send(pane, f"/catchup {number}", True, h)
    if first["status"] == "failed":
        return "send_failed"
    if first["status"] not in FINISHED:
        return first["status"]  # blocked か stalled
    second_result = send(pane, second, False, h)
    return "sent" if second_result["status"] == "sent" else "send_failed"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pane", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    jsonio.dump({"turn": send(a.pane, a.text, a.wait)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
