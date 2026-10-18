#!/usr/bin/env python3
"""cost ノード: 1 件の PR を開くとアカウントの使用率がどれだけ増えるかを、実行の前後の控えから測って覚える。外に書く（覚えるファイル 1 つ）。

- 測り方: dispatch が、/catchup を送る前と、全部の /catchup が終わった後に使用率を取り直す。アカウントごとに
  「見えた差 + 1」を、そのアカウントで開いた PR の数で割る。使用率は 1% 刻みで届くので、本当の増えは見えた差 + 1 より小さい。
  少なく見積もると 1 つのアカウントに入れすぎるので、上の端を採る。
- 枠（週・5 時間）ごとに測る。実行の途中で切り替わった枠は、差が意味を持たないので測らない。
- 覚えるのは枠ごとに新しい KEEP 回ぶん。見積もりはその中央値（同じ時にほかの会話が使った分が混ざった回に引きずられない）。
- 1 件あたりの値は /catchup と、2 ターン目を送ったところまで。2 ターン目の続きの使用は入らない。

使い方: python3 nodes/cost.py <覚えるファイル>   … 今の見積もりを JSON で出す
"""

import json
import os
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import filex  # noqa: E402

# Windows の既定の標準出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

WINDOWS = ("seven_day", "five_hour")
KEEP = 10  # 枠ごとに覚える回数。PR の大きさで値が揺れるので、古い回は捨てて今の使い方に寄せる


def _empty():
    return {w: [] for w in WINDOWS}


def samples(before, after, counts):
    """before・after は {アカウント名: 控え}、counts は {アカウント名: 開いた PR の数}。枠ごとの 1 件あたりの値の並びを返す。"""
    out = _empty()
    for name, n in counts.items():
        b, a = before.get(name), after.get(name)
        if not n or not isinstance(b, dict) or not isinstance(a, dict):
            continue
        for w in WINDOWS:
            bw, aw = b.get(w), a.get(w)
            if not isinstance(bw, dict) or not isinstance(aw, dict):
                continue
            bu, au = bw.get("used_percentage"), aw.get("used_percentage")
            if not isinstance(bu, (int, float)) or not isinstance(au, (int, float)) or bw.get("resets_at") != aw.get("resets_at"):
                continue
            out[w].append(round(max(au - bu, 0) / n + 1 / n, 6))
    return out


def estimate(history):
    """{枠: 1 件あたりの見積もり, "runs": 測った回の数}。まだ 1 回も測っていなければ None。"""
    got = {w: statistics.median(history[w]) for w in WINDOWS if history.get(w)}
    if not got:
        return None
    return {**got, "runs": max(len(history.get(w) or []) for w in WINDOWS)}


class CostError(ValueError):
    """覚えるファイルが読めない（壊れている）。空として読んで上書きすると、覚えた回が消える。"""


def load(path):
    """覚えた値。ファイルが無ければ空。読めない・形が違えば CostError（前は空として読み、次の save が上書きした）。"""
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as e:
        raise CostError(f"PR 1 件あたりの使用率の控え {path} が読めない（{e}）。直すか、消して測り直す") from e
    if not (isinstance(raw, dict) and all(isinstance(raw.get(w, []), list) and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in raw.get(w, [])) for w in WINDOWS)):
        raise CostError(f"PR 1 件あたりの使用率の控え {path} の形が違う（枠ごとの数の並びでない）。直すか、消して測り直す")
    return {w: [float(x) for x in raw.get(w, [])] for w in WINDOWS}


def save(path, new):
    """new の値を足し、枠ごとに新しい KEEP 回ぶんだけ残して書く。今のファイルが読めなければ書かずに CostError。"""
    path = pathlib.Path(path)
    old = load(path)
    data = {"schema": 1, **{w: (old[w] + list(new.get(w) or []))[-KEEP:] for w in WINDOWS}}
    filex.replace(path, json.dumps(data, ensure_ascii=False))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        got = load(argv[0])
    except CostError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps({"schema": 1, "estimate": estimate(got)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
