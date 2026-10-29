#!/usr/bin/env python3
"""部署の会話が役の本文の決まりを読み違えた回を、期間で数える（業務改革の測り。頼み d32ad0）。

頼み 79eacf（役の本文と Stop のフックの差し戻しの文を英語にした。claude-plugins の main の f8997e2e、works-dispatch 0.138.0）の
入る前と後を比べるために置いた。会話の選び方（受付箱の台帳に出た会話）と、役の本文・Stop のフックの文の拾い方は
docs/reform/dispatch-overhead.py と同じ。

出来事は、出来事の時刻で期間に入れる（常駐の部署の会話は日をまたいで生きるので、会話の始まりで分けると外れる）。
役は、その出来事の前に最後に足された役の本文（会話の始まり・compact と /clear の後に SessionStart のフックが足す）から取り、
その本文が英語か日本語か（lang の en・ja）で分ける。差し戻しの文の言語は出来事の時の works-dispatch の版で決まるので、
lang の en・ja は役の本文の言語だけを指す。

数える物（会話ごとに、1 回でも在ったか。後ろに回数の計）:
- undelivered: 納品せずに止まろうとして、Stop のフックに差し戻された（「まだ納品していない」/「You have not delivered ask」）
- undelivered_again: その差し戻しの 2 回目以降（差し戻しの後も納品せずに止まった）
- unlanded: 納品した後、main に入れずに止まろうとして差し戻された（「納品済みだが」/「is delivered, but the branch」）
- undone: 納品して main に入れた後、--done を打たずに止まろうとして差し戻された（「納品済みで、ブランチも」/「is delivered and the branch」）
- holder_reject: 納品の検査が担当者（holder）の値で止めた（「担当者「…」は … のどれでもない」）。うち司令塔（前の名前の社長室・段取りも）か自分の受け持ちの名前を書いた物は holder_relay_or_self
- commit_after: 通った納品（出力に「納品 <受付> →」）の後、次の頼み（「頼みです（受付」）が届く前に git commit を打った（--again の納品の前の commit も数える）

会話の数は、期間の中に出来事（記録の行）が 1 つでも在った会話。割合は「1 回でも在った会話 ÷ 会話の数」。

使い方: python3 docs/reform/misread-count.py --since 2026-10-22T12:01 --until 2026-10-29T12:01
"""
import argparse
import collections
import datetime
import importlib.util
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

_spec = importlib.util.spec_from_file_location(
    "dispatch_overhead", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch-overhead.py"))
oh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oh)

STOP = ("Stop hook blocking error from command", "Stop hook feedback:")
# 待ち受けが遅れて送る差し戻しは、利用者の文として頭に LATE_NOTE（wake_hook.py）を付けて届く
LATE = ("（ターンの終わりに", "(A notice left")
KINDS = ("undelivered", "undelivered_again", "unlanded", "undone", "holder_reject", "holder_relay_or_self", "commit_after")
# 持ち主への中継の会話の名前（司令塔は 2026-10-24 に社長室・段取りから名前が替わった）
RELAYS = ("司令塔", "社長室", "段取り")
AGAIN = re.compile(r"(\d+) 回目）|this is #(\d+)")
COMMIT = re.compile(r"\bgit(\s+-\S+(\s+\S+)?)*\s+commit(?![\w-])")
# 英語にした役の本文にだけ在る文（担当・作業・窓口のどれにも在る Language の行の頭）
EN_ROLE = "Language: everything the owner reads"


def stop_kinds(text):
    out = []
    if "まだ納品していない" in text or "You have not delivered ask" in text:
        out.append("undelivered")
        m = AGAIN.search(text)
        if m and int(m.group(1) or m.group(2)) >= 2:
            out.append("undelivered_again")
    if "は納品済みだが、ブランチが" in text or "is delivered, but the branch" in text:
        out.append("unlanded")
    if "は納品済みで、ブランチも" in text or "is delivered and the branch is in" in text:
        out.append("undone")
    return out


def when(d):
    ts = d.get("timestamp")
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone() if ts else None


def walk(path, since, until, active, hit, total):
    """1 つの会話の記録を読み、期間の中の出来事を (役, lang, 種類) ごとに足す。active は期間の中で動いた (役, lang) の会話。"""
    role, name, lang = None, None, None
    delivered = False
    deliver_ids = set()
    last_texts = collections.deque(maxlen=4)
    seen = collections.Counter()

    def count(kind, at, k=1):
        if role and since <= at < until:
            seen[(role, lang, kind)] += k

    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        at = when(d)
        if at is None:
            continue
        texts = []   # 仕組みが会話に渡した文（Stop のフックの差し戻しと、届いた頼み）: (Stop のフックの attachment か, 文)
        if d.get("type") == "attachment":
            a = d.get("attachment") or {}
            if a.get("type") == "hook_additional_context" and a.get("hookEvent") == "SessionStart":
                text = "\n".join(a.get("content") or [])
                saved = re.match(r"<persisted-output>\s*Output too large[^\n]*Full output saved to: (\S+)", text)
                if saved and os.path.isfile(saved.group(1)):
                    # 1 万字を超えた文は、Claude Code がファイルに置き、会話には頭の 2,000 字だけを入れる（頼み d32ad0）
                    text = open(saved.group(1), encoding="utf-8").read()
                r = re.search(r"^この会話は会社「[^」]+」の部署で、役は「([^」]+)」", text)
                if r:
                    role = r.group(1)
                    n = re.search(r"受け持ちは「([^」]+)」", text)
                    name = n.group(1) if n else None
                    # 置き場のファイルが読めず頭の 2,000 字しか無いときは、最後の行に在る EN_ROLE を見られないので言語を決めない
                    lang = "en" if EN_ROLE in text else "unknown" if text.startswith("<persisted-output>") else "ja"
            elif a.get("type") == "hook_blocking_error" and a.get("hookEvent") == "Stop":
                be = a.get("blockingError")
                texts.append((True, be.get("blockingError") if isinstance(be, dict) else str(be or "")))
        elif d.get("type") == "user":
            c = (d.get("message") or {}).get("content")
            for b in ([{"type": "text", "text": c}] if isinstance(c, str) else c if isinstance(c, list) else []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    texts.append((False, b.get("text") or ""))
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in deliver_ids:
                    t = oh.result_text(b)
                    if re.search(r"納品 \d{8}-\d{6}-[0-9a-f]{6} →", t):
                        delivered = True
                    for h in re.findall(r"担当者「([^」]*)」は [^\n]*のどれでもない", t):
                        count("holder_reject", at)
                        if any(r in h for r in RELAYS) or (name and name in h):
                            count("holder_relay_or_self", at)
        elif d.get("type") == "assistant":
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    cmd = str((b.get("input") or {}).get("command") or "")
                    if oh.is_dispatch(cmd) and "--deliver" in cmd:
                        deliver_ids.add(b.get("id"))
                    if delivered and COMMIT.search(cmd):
                        count("commit_after", at)
        for stop, t in texts:
            if "頼みです（受付" in t:
                delivered = False   # 常駐の部署は次の頼みを同じ会話で受ける。commit を数えるのは納品から次の頼みまで
            if not (stop or any(s in t for s in STOP) or t.startswith(LATE)):
                continue
            body = t.split("\n", 1)[1] if t.startswith(STOP) and "\n" in t else t
            if any(body == x and abs((at - t0).total_seconds()) < 10 for x, t0 in last_texts):
                continue   # 同じ差し戻しが attachment と利用者の文の両方に残る（同じ時のものだけを 1 つにする）
            last_texts.append((body, at))
            for k in stop_kinds(body):
                count(k, at)
        if role and since <= at < until:
            active.add((role, lang))
    for (r, l, k), v in seen.items():
        hit[(r, l, k)] += 1
        total[(r, l, k)] += v


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    a = ap.parse_args(argv[1:])
    since = datetime.datetime.fromisoformat(a.since).astimezone()
    until = datetime.datetime.fromisoformat(a.until).astimezone()
    sessions = collections.Counter()
    hit = collections.Counter()
    total = collections.Counter()
    for sid, (company, path) in sorted(oh.sessions().items()):
        active = set()
        h, t = collections.Counter(), collections.Counter()
        walk(path, since, until, active, h, t)
        for r, l in active:
            sessions[(company, r, l)] += 1
        for (r, l, k), v in h.items():
            hit[(company, r, l, k)] += v
        for (r, l, k), v in t.items():
            total[(company, r, l, k)] += v
    print(f"期間 {since:%Y-%m-%d %H:%M} 〜 {until:%Y-%m-%d %H:%M}（出来事の時刻）")
    for key in sorted(sessions):
        n = sessions[key]
        cells = "  ".join(f"{k} {hit[key + (k,)]}/{total[key + (k,)]}（{hit[key + (k,)] / n:.0%}）" for k in KINDS)
        print(f"{key[0]} {key[1]} {key[2]}: 会話 {n}  {cells}")
    print("（値は「1 回でも在った会話の数/回数の計（1 回でも在った会話 ÷ 会話の数）」。en・ja は役の本文の言語）")


if __name__ == "__main__":
    main(sys.argv)
