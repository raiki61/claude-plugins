#!/usr/bin/env python3
"""my_notes の会話の記録から、dispatch.py の打ち方を数える（台帳の頼み 0903d3）。

使い方: python3 docs/reform/dispatch-calls.py [--split YYYY-MM-DDTHH:MM] [--since 日] [--until 日]
--split の前と後に分けて、次を出す（時刻は手元の時刻）。
- dispatch.py を打った会話の数と、そのうちスキルを呼ばず、スキルのファイル（skills/dispatch/ の下）も開かずに打った会話の数
- dispatch.py を打った回数・--help（-h）を打った回数・引数の誤り（argparse の「dispatch.py: error:」）の回数・
  形の誤り（dispatch.py が終わりの値 2 で「送らなかった」「止めた」などと断った回数。引数の誤りは除く。
  フックのゲート〔外部投稿ゲートなど〕に止められた回は、dispatch.py が走っていないので数えない）
会話は、最初に dispatch.py を打った時刻で前か後に分ける。回数は打った時刻で分ける。
読むのは ~/.claude-*/projects/ の、my_notes の本社と作業場（名前に my-notes を含み、/private/tmp でない物）の
会話のログ（*.jsonl。サブエージェントのログは数えない）。
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

CALL = re.compile(r"python[0-9.]*\s+\S*dispatch\.py(\s|$)|\$\{?D\}?\s+--|dispatch\.py\s+--")
HELP = re.compile(r"\s(--help|-h)(\s|$)")
ERROR = "dispatch.py: error:"


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()


def opens_skill(name, inp):
    if name == "Skill":
        return "dispatch" in str(inp.get("skill", ""))
    text = json.dumps(inp, ensure_ascii=False)
    if name in ("Read", "Grep", "Glob"):
        return "skills/dispatch" in text
    if name == "Bash":
        cmd = inp.get("command", "")
        return "skills/dispatch" in cmd and not CALL.search(cmd)
    return False


def scan(path):
    calls = {}  # tool_use id -> (time, is_help)
    errors = []
    refused = []
    first = None
    opened = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list) or "timestamp" not in rec:
                continue
            at = parse_time(rec["timestamp"])
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    if opens_skill(c.get("name"), inp):
                        opened = True
                    cmd = inp.get("command", "") if c.get("name") == "Bash" else ""
                    if cmd and "dispatch.py" in cmd and CALL.search(cmd):
                        calls[c.get("id")] = (at, bool(HELP.search(cmd)))
                        first = first or at
                elif c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                    body = json.dumps(c.get("content"), ensure_ascii=False)
                    if ERROR in body:
                        errors.append(calls[c["tool_use_id"]][0])
                    elif c.get("is_error") and "Exit code 2" in body:
                        refused.append(calls[c["tool_use_id"]][0])
    return first, opened, list(calls.values()), errors, refused


def main():
    for s in (sys.stdout, sys.stderr):   # Windows の既定のコーデックでも日本語を出せるように
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2026-10-20T19:44")
    ap.add_argument("--since")
    ap.add_argument("--until")
    a = ap.parse_args()
    split = dt.datetime.fromisoformat(a.split).astimezone()
    since = dt.datetime.fromisoformat(a.since).astimezone() if a.since else None
    until = dt.datetime.fromisoformat(a.until).astimezone() if a.until else None

    def side(t):
        if (since and t < since) or (until and t >= until):
            return None
        return "後" if t >= split else "前"

    keys = ("会話", "スキルを開かずに打った会話", "打った回数", "--help", "引数の誤り", "形の誤り")
    out = {s: dict.fromkeys(keys, 0) for s in ("前", "後")}
    paths = [
        p
        for d in glob.glob(os.path.expanduser("~/.claude-*/projects/*my-notes*"))
        if "private-tmp" not in d
        for p in glob.glob(os.path.join(d, "*.jsonl"))
    ]
    for p in paths:
        first, opened, calls, errors, refused = scan(p)
        if first and side(first):
            out[side(first)]["会話"] += 1
            out[side(first)]["スキルを開かずに打った会話"] += not opened
        for t, is_help in calls:
            if side(t):
                out[side(t)]["打った回数"] += 1
                out[side(t)]["--help"] += is_help
        for t in errors:
            if side(t):
                out[side(t)]["引数の誤り"] += 1
        for t in refused:
            if side(t):
                out[side(t)]["形の誤り"] += 1
    for s in ("前", "後"):
        print(s, " ".join(f"{k}={v}" for k, v in out[s].items()))


if __name__ == "__main__":
    main()
