#!/usr/bin/env python3
"""部署の会話が役の本文の決まりを読み違えた回を、期間で数える（業務改革の測り。頼み d32ad0）。

頼み 79eacf（役の本文と Stop のフックの差し戻しの文を英語にした。claude-plugins の main の f8997e2e、works-dispatch 0.138.0）の
入る前と後を比べるために置いた。会話の選び方（受付箱の台帳に出た会話）は docs/reform/dispatch-overhead.py と同じ。
会話は始まりの時刻で期間に入れる（役の本文は会話の始まりに足されるので、会話の途中で版が替わっても、始まりの版の本文で動く）。

数える物（会話ごとに、1 回でも在ったか。後ろに回数の計）:
- undelivered: 納品せずに止まろうとして、Stop のフックに差し戻された（「まだ納品していない」/「You have not delivered ask」）
- undelivered_again: その差し戻しの 2 回目より後（差し戻しの後も納品せずに止まった）
- unlanded: 納品した後、main に入れずに止まろうとして差し戻された（「納品済みだが」/「is delivered, but the branch」）
- undone: 納品して main に入れた後、--done を打たずに止まろうとして差し戻された（「納品済みで、ブランチも」/「is delivered and the branch」）
- holder_reject: 納品の検査が担当者（holder）の値で止めた（「担当者「…」は … のどれでもない」）。うち司令塔（前の名前の社長室・段取りも）か自分の受け持ちの名前を書いた物は holder_relay_or_self
- commit_after: 通った納品（出力に「納品 <受付> →」）の後、次の頼み（「頼みです（受付」）が届く前に git commit を打った（--again の納品の前の commit も数える）

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
KINDS = ("undelivered", "undelivered_again", "unlanded", "undone", "holder_reject", "holder_relay_or_self", "commit_after")
# 持ち主への中継の会話の名前（司令塔は 2026-10-24 に社長室・段取りから名前が替わった）
RELAYS = ("司令塔", "社長室", "段取り")
AGAIN = re.compile(r"(\d+) 回目）|this is #(\d+)")


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


def walk(path):
    """会話の始まりの時刻・役・数えた物の Counter。"""
    start, role, name, n = None, None, None, collections.Counter()
    delivered = False
    deliver_ids = set()
    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if start is None and d.get("timestamp"):
            start = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
        m = d.get("message") or {}
        c = m.get("content")
        blocks = c if isinstance(c, list) else [{"type": "text", "text": c}] if isinstance(c, str) else []
        if d.get("type") == "attachment" or d.get("attachment"):
            blocks = blocks + [{"type": "text", "text": json.dumps(d.get("attachment"), ensure_ascii=False)}]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("text") if b.get("type") == "text" else oh.result_text(b) if b.get("type") == "tool_result" else ""
            t = t or ""
            if d.get("type") == "user" and b.get("type") == "text" and "頼みです（受付" in t:
                delivered = False   # 常駐の部署は次の頼みを同じ会話で受ける。commit を数えるのは納品から次の頼みまで
            if role is None:
                r = re.search(r"の部署で、役は「([^」]+)」", t)
                if r:
                    role = r.group(1)
            if name is None:
                r = re.search(r"受け持ちは「([^」]+)」", t)
                if r:
                    name = r.group(1)
            if b.get("type") == "tool_use":
                cmd = str((b.get("input") or {}).get("command") or "")
                if oh.is_dispatch(cmd) and "--deliver" in cmd:
                    deliver_ids.add(b.get("id"))
                if delivered and re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
                    n["commit_after"] += 1
            if b.get("type") == "tool_result" and b.get("tool_use_id") in deliver_ids:
                if re.search(r"納品 \d{8}-\d{6}-[0-9a-f]{6} →", t):
                    delivered = True
                for h in re.findall(r"担当者「([^」]*)」は [^\n]*のどれでもない", t):
                    n["holder_reject"] += 1
                    if any(r in h for r in RELAYS) or (name and name in h):
                        n["holder_relay_or_self"] += 1
            if any(s in t for s in STOP) or (b.get("type") == "text" and d.get("type") == "user" and t.startswith(("頼み（受付", "Ask ", "You have not"))):
                for k in stop_kinds(t):
                    n[k] += 1
    return start, role, n


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
        start, role, n = walk(path)
        if not start or not (since <= start < until) or not role:
            continue
        key = (company, role)
        sessions[key] += 1
        for k in KINDS:
            if n[k]:
                hit[key + (k,)] += 1
                total[key + (k,)] += n[k]
    print(f"期間 {since:%Y-%m-%d %H:%M} 〜 {until:%Y-%m-%d %H:%M}（会話の始まりの時刻）")
    for key in sorted(sessions):
        cells = "  ".join(f"{k} {hit[key + (k,)]}/{total[key + (k,)]}" for k in KINDS)
        print(f"{key[0]} {key[1]}: 会話 {sessions[key]}  {cells}")
    print("（値は「1 回でも在った会話の数/回数の計」）")


if __name__ == "__main__":
    main(sys.argv)
