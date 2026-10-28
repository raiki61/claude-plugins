#!/usr/bin/env python3
"""claude-plugins の部署の会話の、キャッシュの書き込みと読みの量を、期間を区切って数える（業務改革の測り。頼み b5b5c1）。

会社の形の keepalive と promptCacheTtl を替えた前後の費用を比べるために置いた。数えるのは、代表の clone の受付箱の台帳
（.git/company/inbox/log.jsonl）で、部署の作業場（place が ~/.herdr/worktrees/claude-plugins/ の下）に付いた会話（行の
session）の記録のうち、期間の中の要求だけ。1 つの要求は記録に何行も出て同じ usage を繰り返すので、requestId で 1 回に数える。

出す物:
- 要求の数、5 分の書き込み・1 時間の書き込み・読みのトークンの合計
- 費用の目安: 入力の単価を 1 とした重み（5 分の書き込み 1.25・1 時間の書き込み 2・読み 0.05。Opus 5.5・Sonnet 5.5 の倍率。
  https://platform.claude.com/docs/en/about-claude/pricing ）を掛けた合計と、要求 1 回あたりの値
- 5 分を超えて 1 時間以内の要求どうしの間の数と、そのうち台帳に keepalive の行が無い間の数と、その間の後の要求のキャッシュの
  長さ（読み＋書き）の合計 Q。寿命が 5 分なら Q が書き直しになる。1 時間が得なのは Q > 0.625 × 1 時間の書き込み のとき
  （5 分にすると書き込みが 0.75 下がり、Q が 1.2 上がる）
- 待ちの後の最初の要求のうち、書き込みが読みより多かった（キャッシュが切れて書き直した）回数。compact の問いと compact の
  keepalive の行（COMPACT_ROWS）の後は数えない
- 台帳の keepalive の行の数（送った sent〔status の無い行〕と、送らなかった skipped と、そのほか）

使い方: python3 docs/reform/cache-cost.py <始まり> <終わり>（どちらも 2026-10-24T20:00 の形の手元の時刻）
"""
import datetime
import glob
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

LOG = os.path.expanduser("~/src/claude-plugins/.git/company/inbox/log.jsonl")
PLACE = os.path.expanduser("~/.herdr/worktrees/claude-plugins/")
# compact の問いと compact の行。その後の要求は要約から文脈を書き直すので、切れの書き直しに数えない（頼み 3ca5fe で外した）
COMPACT_ROWS = ("asked", "answered", "compacted", "compact-failed")
WEIGHT = {"w5": 1.25, "w1": 2.0, "r": 0.05}


def stamp(text):
    return datetime.datetime.fromisoformat(text).timestamp()


def requests(paths, start, end):
    """会話の記録（アカウントごとに写しが在りうる）から、期間の中の要求を requestId ごとに 1 回、時刻の順で返す。"""
    seen = {}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            u = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
            if not u:
                continue
            at = stamp(d["timestamp"].replace("Z", "+00:00"))
            key = d.get("requestId") or (d.get("message") or {}).get("id") or (path, at)
            if start <= at < end:
                seen.setdefault(key, (at, u))
    return sorted(seen.values(), key=lambda x: x[0])


def main(argv):
    start, end = stamp(argv[1]), stamp(argv[2])
    rows = [json.loads(line) for line in open(LOG, encoding="utf-8") if line.strip()]
    sessions = {r["session"] for r in rows
                if isinstance(r.get("session"), str) and str(r.get("place", "")).startswith(PLACE)}
    paths = {}
    for p in glob.glob(os.path.expanduser("~/.claude*/projects/*/*.jsonl")):
        paths.setdefault(os.path.basename(p)[:-6], []).append(p)
    waits = {}
    cold_waits = {}
    keep = {"sent": 0, "skipped": 0, "other": 0}
    for r in rows:
        if r.get("kind") == "keepalive" and start <= r["at"] < end:
            status = r.get("status")
            keep["sent" if status is None else "skipped" if status == "skipped" else "other"] += 1
            waits.setdefault(r.get("session"), []).append(r["at"])
            if status not in COMPACT_ROWS:
                cold_waits.setdefault(r.get("session"), []).append(r["at"])
    n = 0
    tot = {"w5": 0, "w1": 0, "r": 0}
    cold = gaps = bare = q = 0
    for sid in sessions:
        reqs = requests(paths.get(sid, []), start, end)
        for i, (at, u) in enumerate(reqs):
            c = u.get("cache_creation") or {}
            w1 = c.get("ephemeral_1h_input_tokens", 0)
            w5 = c.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1)
            tot["w5"] += w5
            tot["w1"] += w1
            tot["r"] += u.get("cache_read_input_tokens", 0)
            n += 1
            if i and 300 < at - reqs[i - 1][0] <= 3600:
                gaps += 1
                if not any(reqs[i - 1][0] < w < at for w in waits.get(sid, [])):
                    bare += 1
                    q += u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        for w in cold_waits.get(sid, []):
            after = [u for at, u in reqs if at > w]
            if after and after[0].get("cache_creation_input_tokens", 0) > after[0].get("cache_read_input_tokens", 0):
                cold += 1
    cost = sum(tot[k] * WEIGHT[k] for k in tot)
    print(f"会話 {len(sessions)}・要求 {n} 回・5 分の書き込み {tot['w5']}・1 時間の書き込み {tot['w1']}・読み {tot['r']}（トークン）")
    print(f"費用の目安（入力のトークンに直した量） {cost:.0f}・要求 1 回あたり {cost / n if n else 0:.0f}")
    print(f"5 分を超えて 1 時間以内の間 {gaps}・そのうち keepalive の行の無い間 {bare}・その後のキャッシュの長さ Q {q}"
          f"（0.625 × 1 時間の書き込み = {0.625 * tot['w1']:.0f}）")
    print(f"待ちの後に書き直した {cold} 回・keepalive の行 送った {keep['sent']}・送らなかった {keep['skipped']}・そのほか {keep['other']}")


if __name__ == "__main__":
    main(sys.argv)
