#!/usr/bin/env python3
"""世界の解の DW（attention/workflows/dig-world.js）の抜き書きを、同じ URL から取り直した本文で照合する入口。

DW の取り直しの段（haiku のエージェント 1 体が、このコマンドを字のまま 1 回打つ）が、類ごとに 1 回打つ。
設計は attention/docs/small-workflows-design.md の 3.6。照合そのものは工場から字のまま写した copied/excerpts.py の verify で、
取る口は copied/webget.py の http_get。定数 MAX_EXCERPTS・MAX_BODY・HEADERS は工場の workflows/world/src/steps.py の 51〜54 行と
同じ値（台帳 COPIED_FROM の「書き替えた」）。

入力の行（--b64 の後の引数 1 つが 1 行の UTF-8 の base64。--b64 が無ければ標準入力の 1 行ずつ）:
  1 行目: {"class": <類の id>, "count": <この後の行の数>}
  2 行目から: [id, url, excerpt, sum] の JSON の配列。sum は f"{id}\\n{url}\\n{excerpt}" の FNV-1a 32 bit（UTF-16 の単位。
  dig-world.js の fnv と同じ）。sum の合わない行と、base64 として読めない引数（写し違えた行）は照合せずに garbled に数える。
  DW のコマンドは 1 行の bash <run-python.sh> <この台本> --b64 <行> <行> ...。ヘッドレスの許しの規則
  Bash(bash <run-python.sh> <この台本> --b64 *) に当てるため（here-document の形は規則に当たらず拒まれた。PR 2555 の 1 回目）。

標準出力（JSON 1 つ）:
  {"ran": true, "class", "checked", "kept": [id], "dropped": [{id, why}], "garbled": [id], "over": n, "offline": bool, "error": ""}
  over は MAX_EXCERPTS を超えて取らなかった行の数（DW が先に切るので、ふつうは 0）。

  --pages <file>: ネットワークに出ず、ファイルの {url: [状態の番号, 本文]} を取り直しの答えにする（試験の口）。
"""
import base64
import binascii
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "copied"))
import excerpts  # noqa: E402 — 工場の workflows/world/src/excerpts.py の写し
import webget  # noqa: E402 — 工場の lib/webget.py の写し

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MAX_EXCERPTS = 6   # 類ごとの抜き書きの上限（工場の steps.py の MAX_EXCERPTS）
MAX_BODY = 2 * 1024 * 1024   # 取り直す本文の上限（工場の steps.py の MAX_BODY）
HEADERS = {"User-Agent": "works-world/1", "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"}   # 工場の steps.py の HEADERS


def fnv32(s):
    """FNV-1a の 32 bit を UTF-16 の単位で（dig-world.js の fnv・my-turn-prep.py の fnv32 と同じ）"""
    h = 0x811c9dc5
    b = s.encode("utf-16-le", "surrogatepass")
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 0x01000193) & 0xffffffff
    return "%08x" % h


def fake_get(pages):
    def get(url):
        if url not in pages:
            raise webget.FetchError("試験の pages に無い URL")
        status, body = pages[url]
        return status, body.encode("utf-8")
    return get


def fetch(url):
    return webget.http_get(url, HEADERS, MAX_BODY)


def run(lines, get):
    head = json.loads(lines[0]) if lines else None
    if not isinstance(head, dict) or not isinstance(head.get("count"), int):
        raise ValueError('1 行目は {"class": <類の id>, "count": <行の数>}')
    rows, garbled = [], []
    for raw in lines[1:]:
        try:
            item = json.loads(raw)
        except ValueError:
            garbled.append("?")
            continue
        if not (isinstance(item, list) and len(item) == 4 and all(isinstance(x, str) for x in item)):
            garbled.append(str(item[0]) if isinstance(item, list) and item else "?")
            continue
        rid, url, text, got = item
        if fnv32("%s\n%s\n%s" % (rid, url, text)) != got:
            garbled.append(rid)
            continue
        rows.append({"id": rid, "url": url, "excerpt": text})
    taken = rows[:MAX_EXCERPTS]
    res = excerpts.verify(taken, get)
    return {"ran": True, "class": head.get("class", ""), "checked": len(rows) + len(garbled),
            "kept": [r["id"] for r in res["kept"]],
            "dropped": [{"id": r["id"], "why": r["why"]} for r in res["dropped"]],
            "garbled": garbled, "over": len(rows) - len(taken), "offline": bool(res["offline"]), "error": ""}


def unb64(word):
    """base64 の 1 語を 1 行に戻す。読めない語は JSON にならない行にして、run で garbled に数えさせる"""
    try:
        return base64.b64decode(word, validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return "\x00 not base64"


def main(argv):
    get = fetch
    if argv[:1] == ["--pages"] and len(argv) >= 2:
        with open(argv[1], encoding="utf-8") as f:
            get = fake_get(json.load(f))
        argv = argv[2:]
    if argv[:1] == ["--b64"]:
        lines = [unb64(w) for w in argv[1:]]
    elif argv:
        print(json.dumps({"ran": False, "error": "引数は [--pages <file>] [--b64 <行> ...] だけ"}, ensure_ascii=False))
        return 2
    else:
        lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
    try:
        out = run(lines, get)
    except ValueError as e:
        print(json.dumps({"ran": False, "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
