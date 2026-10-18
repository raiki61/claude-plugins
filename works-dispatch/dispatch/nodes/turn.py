#!/usr/bin/env python3
"""turn ノード: 会話にターンを送る（設計書のセクション 2 の 7）。外に書く。

1 ターン目の `/catchup <番号>` は待ち付きで送る。herdr の agent prompt --wait は、送った後に動き出したのを見てから止まるまで待つ。
`herdr agent wait` だけで待たないのは、それがターンの区切りを追わず、始まる前の idle に当たりうるため。
2 ターン目は、1 ターン目が idle か done で終えた時だけ、待たずに送る。2 ターン目の文が無ければ（--no-second）、
`/catchup <番号>` だけを待たずに送って終える。blocked（許可の確認などで止まっている）と
stalled（送って動き出さなかった。herdr の組み込みの見張りの結末）なら送らない。
1 ターン目の終わりは、入口が state を渡せば、Claude Code 自身が返す会話の状態（claude agents --json の status。idle・busy）で見る。
herdr は画面の下の行で作業中かを決めるので、会話が裏に待ちのコマンドを残すと、ターンが終わっても作業中と見続ける（2026-10-15 に
#2003 で 54 分止まり、2 ターン目も報告も出なかった）。動き出したことだけは herdr の --wait --until working で見る（herdr の
組み込みの見張りが、動き出さなければ stalled で返す）。その後、Claude Code が idle を返すまで間をおいて見る。herdr が blocked
（許可の確認など）を返せば blocked。期限は足さない（D5）。

close_session は、会話を終えてペインの前をシェルに戻す（送り直す前と、閉じた PR の片付けの前に使う）。会話に /exit を送り、
シェルが前に戻るのを読み戻してから closed を返す。戻らなければ close_failed。

送るのはプラグイン名つきの `/<プラグイン名>:catchup <番号>`（名前の組み立ては claudex.catchup_commands）。人が画面で `/catchup` と
打つと補完がプラグイン名を足すが、herdr は打った文字をそのまま送るので、`/catchup` のままだと Claude Code が「Unknown command」と
返す（2026-10-14 に 2.1.299 で見た）。

使い方: python3 nodes/turn.py --pane <ペイン ID> --text <文> [--wait] [--out <パス>]
"""

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import herdr  # noqa: E402
import jsonio  # noqa: E402

FINISHED = ("idle", "done")


POLL_S = 5                         # 1 ターン目の終わりを Claude Code に問う間
CLOSE_TRIES, CLOSE_PAUSE_S = 30, 1  # /exit の後にシェルが前に戻るのを見る回数と間


def send(pane, text, wait, h=herdr, until=()):
    try:
        status = h.prompt(pane, text, wait, until=until) if until else h.prompt(pane, text, wait)
        return {"pane": pane, "status": status, "detail": None}
    except h.HerdrError as e:
        return {"pane": pane, "status": "failed", "detail": str(e)}


def _until(check, tries, pause):
    for i in range(tries):
        if check():
            return True
        if i + 1 < tries:
            pause()
    return False


def _turn_end(pane, h, state, pause):
    """動き出した後、Claude Code が idle を返すまで待つ。idle・blocked のどちらか。state() が None（会話が見えない）の回は
    herdr の見立てを使う。"""
    while True:
        got = state()
        if got == "idle":
            return "idle"
        if got is None:
            seen = (h.agent(pane) or {}).get("agent_status")
            if seen in FINISHED:
                return "idle"
            if seen == "blocked":
                return "blocked"
        elif (h.agent(pane) or {}).get("agent_status") == "blocked":
            return "blocked"
        pause()


def catchup_then_second(number, pane, second, h=herdr, *, catchup, state=None, pause=lambda: time.sleep(POLL_S)):
    """結末の語 sent・blocked・stalled・send_failed のどれかを返す。second が None なら 1 ターン目だけ送る。
    catchup は送るコマンドの名前（例 /attention:catchup）。入口がアカウントのプラグインから組み立てて渡す。
    state() は、その会話の状態を Claude Code 自身に問う口（idle・busy・None）。None を渡すと、終わりも herdr の見立てで待つ。"""
    if second is None:
        only = send(pane, f"{catchup} {number}", False, h)
        return "sent" if only["status"] == "sent" else "send_failed"
    first = send(pane, f"{catchup} {number}", True, h, until=("working", "blocked") if state else ())
    if first["status"] == "failed":
        return "send_failed"
    if state is not None and first["status"] == "working":
        first["status"] = _turn_end(pane, h, state, pause)
    if first["status"] not in FINISHED:
        return first["status"]  # blocked か stalled
    second_result = send(pane, second, False, h)
    return "sent" if second_result["status"] == "sent" else "send_failed"


def close_session(pane, h=herdr, tries=CLOSE_TRIES, pause=lambda: time.sleep(CLOSE_PAUSE_S)):
    """会話を終えて、ペインの前をシェルに戻す。closed・close_failed のどちらか。前がもうシェルなら何も送らない。"""
    try:
        if h.shell_in_front(pane):
            return "closed"
        h.prompt(pane, "/exit", False)
        return "closed" if _until(lambda: h.shell_in_front(pane), tries, pause) else "close_failed"
    except h.HerdrError:
        return "close_failed"


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
