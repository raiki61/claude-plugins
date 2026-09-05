#!/usr/bin/env python3
"""絵（系の前後の図）が端末で崩れずに出るかを、幅と縦線と箱の対で検査する。

〈何を見るか〉AI が /catchup の説明の後ろに描く図（```text の中身）を受けて、
(1) 各行の幅が 60 桁以内か、(2) 行数が 14 行以内か（空行を含む。変更前と変更後の 2 つで 1 図）、
(3) `│` が縦線の列に揃っているか、(4) 罫線の箱 ┌┐ と └┘ の幅が合っているか、を出す。
図の意味（ラベルが説明の語か・線が本文の関係か）は見ない——それは描いた AI が確かめる。

〈桁の数え方〉東アジア幅 W / F を 2、それ以外を 1 で数える。罫線と矢印（│ ─ → ←）は
「曖昧幅」で 1 に数える。等幅の端末で図を使う前提なので、幅は端末の 60 桁の規則と同じ物差し。
桁は 0 始まり（行頭の文字が桁 0）。

〈縦線の列〉2 行以上に現れる `│` の桁を「縦線の列」と呼び、それ以外の桁にある `│` を「ずれ」
とする。列が 1 行にしか無ければ、隣の行の線と繋がらないので崩れて見える。全角のラベルの後ろで
桁が 1 つずれるのが典型で、目視では気付きにくい。

〈箱〉同じ行の ┌ と ┐ を左から順に対にし、└ と ┘ も同じく対にして、i 番目どうしの幅を比べる。
入れ子や複数行にまたがる箱は厳密には追わない（簡易。無理に厳密にしない）。

〈使い方〉`python3 figure-check.py [file]`。file が無ければ標準入力から読む。通れば
`通った（N 行、最大 M 桁）` で 0、落ちたら 1 件 1 行で出して 1。
"""

import collections
import itertools
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402 — 東アジア幅の物差し。枠の 60 桁と絵の 60 桁を同じ関数で数える

WIDTH_CAP = 60   # 1 行の幅の上限（命令書の 60 桁の規則と同じ）
LINES_CAP = 14   # 図の行数の上限（変更前・変更後の 2 つで 1 図）
BAR = "│"

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


width = changemap.width


def columns_of(line, chars):
    """line の中で chars のどれかが立つ (桁, 文字) を左から。桁は表示幅で数える（0 始まり）。"""
    found, col = [], 0
    for c in line:
        if c in chars:
            found.append((col, c))
        col += width(c)
    return found


def vertical_columns(lines):
    """2 行以上に `│` が立つ桁。図の縦線はここに揃っているはず。"""
    seen = collections.Counter(col for line in lines for col, _ in columns_of(line, BAR))
    return sorted(c for c, n in seen.items() if n >= 2)


def check_width(lines):
    return [f"行 {i}: 幅 {width(line)} 桁（{WIDTH_CAP} まで）"
            for i, line in enumerate(lines, 1) if width(line) > WIDTH_CAP]


def check_lines(lines):
    if len(lines) > LINES_CAP:
        return [f"行数 {len(lines)} 行（{LINES_CAP} まで）"]
    return []


def check_bars(lines):
    cols = vertical_columns(lines)
    where = ", ".join(str(c) for c in cols) if cols else "無い"
    return [f"行 {i} 桁 {col}: {BAR} がずれ（縦線の列は {where}）"
            for i, line in enumerate(lines, 1)
            for col, _ in columns_of(line, BAR) if col not in cols]


def box_edges(lines, open_ch, close_ch):
    """各行の open_ch と close_ch を左から順に対にした (行, 桁, 幅)。対が揃わない分は幅 None。"""
    edges = []
    for i, line in enumerate(lines, 1):
        cols = columns_of(line, open_ch + close_ch)
        opens = [c for c, ch in cols if ch == open_ch]
        closes = [c for c, ch in cols if ch == close_ch]
        for o, c in itertools.zip_longest(opens, closes):
            edges.append((i, c if o is None else o, None if o is None or c is None else c - o))
    return edges


def check_boxes(lines):
    tops = box_edges(lines, "┌", "┐")
    bottoms = box_edges(lines, "└", "┘")
    out = [f"行 {i} 桁 {c}: 箱がずれ（同じ行に対の罫線が無い）"
           for i, c, w in tops + bottoms if w is None]
    for (ti, tc, tw), (bi, bc, bw) in zip(tops, bottoms):
        if tw is not None and bw is not None and tw != bw:
            out.append(f"行 {bi} 桁 {bc}: 箱がずれ（上辺は行 {ti} で {tw} 桁、下辺は {bw} 桁）")
    if len(tops) != len(bottoms):
        out.append(f"箱がずれ（上辺 ┌┐ が {len(tops)} 組、下辺 └┘ が {len(bottoms)} 組）")
    return out


def report(text):
    """戻り値は (終了コード, 出力の行)。gh にも git にも触らない純関数。"""
    lines = text.splitlines()
    if not lines:
        return 1, ["図が空（何も渡されていない）"]
    problems = check_width(lines) + check_lines(lines) + check_bars(lines) + check_boxes(lines)
    if problems:
        return 1, problems
    return 0, [f"通った（{len(lines)} 行、最大 {max(width(l) for l in lines)} 桁）"]


def read_input(argv):
    if len(argv) > 1:
        sys.exit("使い方: figure-check.py [file]（無ければ標準入力）")
    if argv:
        with open(argv[0], encoding="utf-8", errors="replace") as f:
            return f.read()
    return sys.stdin.read()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    code, lines = report(read_input(argv))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
