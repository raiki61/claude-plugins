"""報告をファイルへ逃がす共通部。/whose-turn・/catchup・/what-am-i-doing で共用。

Claude Code の Bash は 1 回あたりの出力に上限（約 30,000 バイト）を持ち、門はバイトで測る。
日本語は 1 文字 3 バイトなので、およそ 1 万文字で当たる（実測 2026-09-16: /whose-turn の
材料付きが 21,870 文字＝39,375 バイト、/catchup の 1 件が 62,379〜104,782 文字＝91,701〜
158,078 バイト、/what-am-i-doing が 16,891 文字＝29,918 バイト）。

越えても中身は欠けない——ツール側がファイルへ退避してパスを返す。ただし走らせてから気づく形に
なるので、gh の呼び出しごともう 1 回走る。--out は最初からファイルへ書いてパスだけ返すので、
実行が 1 回で確定する。読み戻しは Read で行う——cat で読むと同じ量が再び Bash の出力に乗って、
また退避される。
"""

import contextlib
import datetime as dt
import os
import tempfile

HELP = (
    "報告を標準出力ではなく一時ファイルへ書き、パスと大きさだけ返す。"
    "出力は Claude Code の Bash の 1 回あたりの上限（約 30,000 バイト）を越えることがあり、"
    "越えるとツール側で退避されて走らせ直しになる。先に書いて Read で読むと実行が 1 回で済む"
)


def add_flag(ap):
    """--out を足す。値は取らせない——取らせると `<位置引数> --out` の並びで位置引数を吸う。"""
    ap.add_argument("--out", action="store_true", help=HELP)


def label(line, width=20):
    """見出しから飛び先の目印になる分だけ。（ の前・ — の前で切り、長ければ畳む。"""
    s = line[3:].split("（")[0].split(" — ")[0].strip()
    return s if len(s) <= width else s[:width] + "…"


def index(text, stop=None):
    """節（行頭の `## `）と、その行番号。Read の offset に直接使える形で返す。

    材料の本文は人が書いたもので、行頭に `## ` を持つことがある（実測 2026-09-16: /whose-turn の
    材料に、`## 評価方法` で始まる issue の本文が入っていた）。材料の始まりに印を持つ script は
    stop=(印, 呼び名) を渡す——印から下は見ない。印を持たない script は、材料を自分の記号
    （catchup は `  | `、what-am-i-doing は字下げ）で囲っているので行頭では当たらない。
    """
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        if stop and line.startswith(stop[0]):
            out.append(f"{n} {stop[1]}")
            break
        if line.startswith("## "):
            out.append(f"{n} {label(line)}")
    return out


def run_to_file(run, stem, stop=None):
    """run() の標準出力を一時ファイルへ落とし、パスと大きさと節の行番号だけを返す。

    戻り値は run の戻り値。節の行番号を添えるのは、取得と読み込みを切り離すため——全部
    取っておいて、context に載せるのは要る節だけにできる（Read は offset と limit を取る）。
    """
    path = os.path.join(
        tempfile.gettempdir(), f"{stem}-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    )
    with open(path, "w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
        code = run()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    print(
        f"報告は {path} に書いた（{len(text)} 文字 / {len(text.encode())} バイト）。"
        "Read で読む——cat で読むと Bash の上限に当たって退避され、二度手間になる"
    )
    lines = index(text, stop)
    if lines:
        print("節（Read の offset）: " + " / ".join(lines))
    return code
