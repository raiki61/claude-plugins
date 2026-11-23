#!/usr/bin/env python3
"""report ノード: 報告の行を作る純粋な関数（設計書のセクション 2 の 8）。外には書かない。

頭に注記（使用率の控えが無いアカウントなど）、続けて 1 件 1 行: `#<番号> <タイトル>  <ブランチ>  <アカウント>  <結末>`。
issue から始めたもの（kind が issue）は `issue #<番号> …` で始める。まだブランチが無ければブランチのフィールドは `-`。
結末の語は sent・refreshed・blocked・stalled・already_open・no_news・busy・dirty・unpushed・many_open・department・unread_news・
close_failed・no_account・provision_failed・branch_busy・pane_busy・launch_failed・send_failed・issue_closed と、--dry-run の
create（作業場を作る）・reuse（使い直す）・refresh（送り直す）。
終わりに、/catchup が届かなかった（--dry-run では届かない見込みの）PR を、1 本 1 行で訳と一緒に出す（skipped。黙って飛ばさない。
持ち主 2026-11-23「開いてっていったときに絶対にcatchupうつの修正させて」。頼み 2d6839）。
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
SKIPPED = "/catchup が届いていない PR と訳:"
DELIVERED = ("sent", "refreshed", "create", "reuse", "refresh")   # 届いた（--dry-run の 3 語は届く見込み）
AT_TOP = "訳は上の注記"
WHY = {
    "already_open": "同じブランチの会話がもう開いている。PR の作業場の外（代表の clone や別の場所）の会話と、--issue で開いた作業場の会話は終えない",
    "no_news": "前に /catchup を送った後に、相手の新しい返事（コメント・レビュー・commit）も head の変化も無い。打ち直すなら --pr <番号> で名指す",
    "busy": "作業場の会話が作業中か、確認の画面で答えを待っている。終えない",
    "dirty": "作業場に未コミットの変更か、git に足していないファイルが在る。会話を終えない",
    "unpushed": "作業場に、手元にしか無い commit か、そのブランチの stash が在る。会話を終えない",
    "many_open": "作業場で会話が 2 つ以上開いている。どれを終えてよいか決められないので、どれにも触らない",
    "department": "部署の作業場の会話なので終えない。レビューの返しは --ask <部署> --text <頼み> で部署へ回す",
    "unread_news": f"前に送った後の相手の動きを GitHub から読めず、会話を立て直すかを決められなかった（{AT_TOP}）",
    "close_failed": f"立て直す前に、前の会話を終えられなかったか、作業場を閉じられなかった（{AT_TOP}）",
    "no_account": "使用率が上限に届かず、使える時間帯の中のアカウントが無い",
    "provision_failed": f"作業場を用意できなかった（{AT_TOP}）",
    "branch_busy": "代表の clone 自身がそのブランチを開いているので、作業場を作らない",
    "pane_busy": "ペインの前に、シェルでない物（エディタ・dev server・別の会話）が居る",
    "launch_failed": f"Claude Code を起動できなかった（{AT_TOP}）",
    "blocked": "会話が確認の画面（フォルダの信頼・ログイン・許可など）で止まっている。画面で答えれば進む",
    "stalled": "/catchup を打ったが、会話が動き出さなかった",
    "send_failed": "/catchup か 2 ターン目の文を送れなかった（途中で窓が閉じた・herdr が落ちたなど）",
    "issue_closed": "issue が閉じているので、ブランチを作らない",
}


def lines(plan, results, notes):
    out = list(notes)
    if not plan:
        return out + [NONE]
    for r in plan:
        head = "issue " if r.get("kind") == "issue" else ""
        who = (r.get("account") or {}).get("name") or "-"
        out.append(f"{head}#{r['number']} {r['title']}  {r.get('head') or '-'}  {who}  {results.get(r['number'], r['outcome'])}")
    return out + skipped(plan, results)


def skipped(plan, results):
    """/catchup が届かなかった PR の 1 本 1 行（見出しの後に `- #<番号>: <訳>（<結末>）`）。全部届いたなら空。"""
    rows = []
    for r in plan:
        word = results.get(r["number"], r["outcome"])
        if word in DELIVERED or word == "assigned":
            continue
        head = "issue " if r.get("kind") == "issue" else ""
        rows.append(f"- {head}#{r['number']}: {WHY.get(word, AT_TOP)}（{word}）")
    return [SKIPPED] + rows if rows else []


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
