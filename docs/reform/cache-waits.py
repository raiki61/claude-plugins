#!/usr/bin/env python3
"""claude-plugins と my_notes の部署の会話の、待ちの後のキャッシュの書き直しと keepalive の費用を日ごとに数える（業務改革の測り。頼み 3ca5fe）。

rent-or-buy（keepalive を続けるか・compact するかを費用の式で決める部品。docs/specs/2026-10-24-rent-or-buy-design.md）が
入る前と後を比べるために置いた。会話の選び方とドルの単価は docs/reform/dispatch-overhead.py と同じ。

日ごとに出す物（要求は requestId で 1 回。時刻は手元の時刻）:
- 要求の数、1 回あたりの重み（入力 1・1 時間の書き込み 2・5 分の書き込み 1.25・読み 0.05。頼み 3ca5fe の決めた重み）と、
  1 回あたりの文脈の長さ（入力・書き込み・読みの和）、重み ÷ 文脈（文脈の長さによらない、書き込みの多さの目安）
- 5 分か 1 時間の書き込みの割合（どちらの寿命で書いたか）
- 書き直し: 前の要求から 5 分を超えて間が空き、書き込みが 2 万トークン以上で読みより多かった要求の数と、その書き込みの
  ドル（読みで済んだ場合との差）。間の長さで 5 分〜1 時間と 1 時間超に分ける。compact と /clear の直後の要求は数えない
- keepalive のターンの要求の数とドル（Stop のフックが keepalive の文か compact の問いを渡したターンの要求）
- compact の数（compact_boundary の行）

使い方: python3 docs/reform/cache-waits.py [--since 2026-10-20] [--until 2026-10-29]
"""
import argparse
import collections
import datetime
import importlib.util
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

_spec = importlib.util.spec_from_file_location(
    "dispatch_overhead", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch-overhead.py"))
oh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oh)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-20")
    ap.add_argument("--until", default="2026-10-29")
    a = ap.parse_args(argv[1:])
    tz = datetime.datetime.now().astimezone().tzinfo
    since = datetime.datetime.fromisoformat(a.since).replace(tzinfo=tz)
    until = datetime.datetime.fromisoformat(a.until).replace(tzinfo=tz)
    price = oh.prices()
    out = collections.defaultdict(collections.Counter)
    for sid, (company, path) in oh.sessions().items():
        seen = set()
        prev = None
        ka = False
        fresh = False   # compact の直後の要求（要約から文脈を書き直すのは切れではないので、書き直しに数えない）
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            t = d.get("type")
            if t == "system" and d.get("subtype") == "compact_boundary":
                at = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
                if since <= at < until:
                    out[at.strftime("%m-%d")]["compacts"] += 1
                fresh = True
                continue
            if t == "user":
                m = (d.get("message") or {}).get("content")
                if isinstance(m, str) and m.startswith("<command-name>/clear"):
                    fresh = True    # /clear の後の書き込みも、待ちの切れではない
                elif isinstance(m, str):
                    ka = oh.STOP in m and oh.stop_kind(m)[0] in ("keepalive", "compact_q")
                elif isinstance(m, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in m):
                    ka = False
                continue
            if t != "assistant":
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            rid = d.get("requestId") or msg.get("id")
            if not u or rid in seen:
                continue
            seen.add(rid)
            at = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
            gap = (at - prev).total_seconds() if prev else 0
            prev = at
            after_compact, fresh = fresh, False
            if not (since <= at < until):
                continue
            p_in, p_w5, p_w1, p_r, p_out = price(msg.get("model"))
            c = u.get("cache_creation") or {}
            w1 = c.get("ephemeral_1h_input_tokens", 0)
            w5 = c.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1)
            read = u.get("cache_read_input_tokens", 0)
            inp = u.get("input_tokens", 0)
            o = out[at.strftime("%m-%d")]
            o["requests"] += 1
            o["weighted"] += inp + 1.25 * w5 + 2 * w1 + 0.05 * read
            o["ctx"] += inp + w5 + w1 + read
            o["w5"] += w5
            o["w1"] += w1
            o["cost"] += inp * p_in + w5 * p_w5 + w1 * p_w1 + read * p_r + u.get("output_tokens", 0) * p_out
            if ka:
                o["ka_n"] += 1
                o["ka_cost"] += inp * p_in + w5 * p_w5 + w1 * p_w1 + read * p_r + u.get("output_tokens", 0) * p_out
            if gap > 300 and w5 + w1 >= 20000 and w5 + w1 > read and not after_compact:
                band = "cold_1h" if gap > 3600 else "cold_5m"
                o[band] += 1
                o[band + "_cost"] += w5 * (p_w5 - p_r) + w1 * (p_w1 - p_r)
    print("日 要求 重み/回 文脈/回 重み÷文脈 1時間の書き込みの割合 書き直し(5分〜1時間・1時間超) 書き直しの$ keepaliveの要求 keepaliveの$ compact 費用$")
    for day in sorted(out):
        o = out[day]
        n = o["requests"] or 1
        w = o["w5"] + o["w1"] or 1
        print(f"{day} {o['requests']} {o['weighted'] / n:.0f} {o['ctx'] / n:.0f} {o['weighted'] / (o['ctx'] or 1):.3f}"
              f" {100 * o['w1'] / w:.0f}% {o['cold_5m']}・{o['cold_1h']} ${o['cold_5m_cost'] + o['cold_1h_cost']:.1f}"
              f" {o['ka_n']} ${o['ka_cost']:.1f} {o['compacts']} ${o['cost']:.0f}")


if __name__ == "__main__":
    main(sys.argv)
