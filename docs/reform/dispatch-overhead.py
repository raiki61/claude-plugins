#!/usr/bin/env python3
"""works-dispatch の仕組みが部署の会話に足す分の費用を、日ごとに数える（業務改革の測り。頼み 3ca5fe）。

数えるのは、claude-plugins と my_notes の代表の clone の受付箱の台帳（.git/company/inbox/log.jsonl）に出る会話（行の
session と from.session）のうち、作業場が両社の本社か部署の作業場の物。会話の記録（~/.claude*/projects/*/<会話>.jsonl。
アカウントごとに写しが在れば一番大きい物）の本体の行（isSidechain でない行）を順に読み、要求（requestId で 1 回）ごとに
費用を出す。費用はドル（モデルごとの単価は rent-or-buy/prompt_cache/snapshot.json。無いモデルは claude-opus-5-5 の値）で、
入力の側（入力・5 分の書き込み・1 時間の書き込み・読み）と出力の側を分けて持つ。

仕組みが足す分の数え方は 2 つ。
- 文脈に居座る分（占有）: 仕組みが足した文を、その後の要求のたびに文脈の一部として読み書きする費用。足した文のトークンの
  見積もり ÷ その要求の文脈の長さ × その要求の入力の側の費用を、compact か /clear で文脈が替わるまで足す。
- 仕組みが起こしたターン（起動）: 仕組みの文で始まり、人の頼みの仕事でないターンの要求の費用の全部（入力と出力）。
  keepalive・compact の問い・未納品の差し戻し・納品の検査の差し戻しの後の打ち直し。
トークンの見積もりは、字数から 1.07 × ASCII でない字 + 0.42 × ASCII の字（部署の会話の 5,755 組の、短い文 1 つだけが足された
前後の要求の文脈の差に当てた最小二乗。包みの system-reminder などの約 180 トークンは数えない）。

使い方: python3 docs/reform/dispatch-overhead.py [--since 2026-10-20] [--until 2026-10-29] [--json <出力>]
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HOME = os.path.expanduser("~")
LOGS = {"claude-plugins": f"{HOME}/src/claude-plugins/.git/company/inbox/log.jsonl",
        "my_notes": f"{HOME}/src/my_notes/.git/company/inbox/log.jsonl"}
PLACES = {"claude-plugins": (f"{HOME}/.herdr/worktrees/claude-plugins/", f"{HOME}/src/claude-plugins"),
          "my_notes": (f"{HOME}/.herdr/worktrees/my-notes/", f"{HOME}/.herdr/worktrees/my_notes/", f"{HOME}/src/my_notes")}
SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../rent-or-buy/prompt_cache/snapshot.json")
STOP = "Stop hook blocking error from command"
# 仕組みが起こすターンの種類（そのターンの要求の費用を全部、その種類に付ける）
TRIGGERED = ("keepalive", "compact_q", "undelivered", "deliver_retry", "gates_retry")
LABEL = {
    "role": "役の本文（会話の始まり・compact と /clear の後）",
    "role_reread": "会社の形が替わった時の役の読み替え",
    "notice": "頼みに添える知らせ（ブランチを進めた・空にしないまま渡す など）",
    "undelivered": "未納品・main に未入の差し戻し（Stop のフック）",
    "keepalive": "keepalive の文とそのターン",
    "compact_q": "compact の問い（焦点を 1 行で）とそのターン",
    "deliver_reject": "納品の検査の差し戻しの文",
    "deliver_retry": "納品の検査の差し戻しの後の打ち直し",
    "dispatch_out": "dispatch.py の出力（--todo・--ask・--deliver などの結果）",
    "dispatch_skill": "dispatch のスキルと別ファイルの読み",
    "reload": "/reload-plugins の打ち込みとその後の一覧",
    "gates": "（仕組みの外）gates の初見読みの指摘（Stop のフック）",
    "gates_reject": "（仕組みの外）gates の外部投稿ゲートが --deliver を止めた文",
    "gates_retry": "（仕組みの外）gates の外部投稿ゲートに止められた後の打ち直し",
}


def tokens(text):
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return 1.07 * (len(text) - ascii_n) + 0.42 * ascii_n


def prices():
    models = json.load(open(SNAPSHOT, encoding="utf-8"))["models"]

    def get(model):
        m = models.get(model) or models["claude-opus-5-5"]
        return (m["input_cost_per_token"], m["cache_creation_input_token_cost"],
                m["cache_creation_input_token_cost_above_1hr"], m["cache_read_input_token_cost"],
                m["output_cost_per_token"])
    return get


def sessions():
    found = {}
    for company, path in LOGS.items():
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            pairs = [(r.get("session"), r.get("place"))]
            if isinstance(r.get("from"), dict):
                pairs.append((r["from"].get("session"), r["from"].get("place")))
            for sid, place in pairs:
                if isinstance(sid, str) and isinstance(place, str) and place.startswith(PLACES[company]):
                    found.setdefault(sid, company)
    paths = {}
    for p in glob.glob(f"{HOME}/.claude*/projects/*/*.jsonl"):
        paths.setdefault(os.path.basename(p)[:-6], []).append(p)
    return {sid: (company, max(paths[sid], key=os.path.getsize)) for sid, company in found.items() if sid in paths}


def stop_kind(text):
    """Stop のフックが渡した文の種類と、仕組みの文の部分（頼み・納品の本文は仕事なので除く）。"""
    body = text.split(STOP, 1)[1]
    body = re.sub(r'^[^:]*:\s*', "", body)
    if re.match(r"（?keepalive", body) and "compact" not in body[:60]:
        return "keepalive", body
    if "good time to compact" in body[:80]:
        return "compact_q", body
    if body.startswith("会社の形が替わったので"):
        return "role_reread", body
    if body.startswith(("coldread", "初見読み", "読み手を起こせず")):
        return "gates", body
    if body.startswith(("頼み（受付",)) and ("まだ納品していない" in body[:80] or "納品済みだが" in body[:80]):
        return "undelivered", body
    if body.startswith(("（", "知らせ（")):
        # 頭の知らせだけが仕組みの文で、後ろに続く頼みの本文は仕事
        head = re.split(r"(頼みです（受付|納品です（受付|頼みの足しです（受付)", body, maxsplit=1)[0]
        return "notice", head
    return None, body


def is_dispatch(cmd):
    # dispatch.py を打ったコマンドだけ（リポジトリの works-dispatch を直す会話の grep・pytest の出力は仕事なので数えない）
    return bool(re.search(
        r"plugins/cache/[^\s\"']*dispatch\.py"            # 配った版を打つ（run-python.sh 越しも）
        r"|\$\{?\w+\}?[^\s\"']*dispatch\.py|\)[^\s\"']*dispatch\.py"   # 版の場所を変数や $(ls …) で出して打つ
        r"|(?:^|&&|;|\|)\s*(?:\w+=\S*\s+)*(?:\S*python[\d.]*\s+)?\S*dispatch\.py\b", cmd or ""))


def result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or "")


def walk(path, company, price, since, until, out):
    items = []          # 文脈に居座る仕組みの文: [種類, トークン]
    turn = None         # 今のターンを起こした仕組みの種類（仕事のターンなら None）
    retry = None        # 納品を止められてから、次の --deliver を打つまで（そのターンの中だけ）。止めた物の種類
    reload_until_req = False
    seen = set()
    tools = {}
    last_texts = collections.deque(maxlen=4)
    first = True
    skill = None        # 最初に dispatch のスキルを読んだ後の最初の要求を待つ間 True、測ったら False
    mark = 0            # 最後の要求の時の items の長さ（/clear より前に足された役の本文は、/clear の後の文脈に入る）
    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        t = d.get("type")
        if t == "system" and d.get("subtype") == "compact_boundary":
            items = []
            continue
        if t == "attachment":
            a = d.get("attachment") or {}
            if a.get("type") == "hook_additional_context" and a.get("hookEvent") == "SessionStart":
                text = "\n".join(a.get("content") or [])
                if text.startswith(("この会話は会社", "works-dispatch:")):
                    items.append(["role", tokens(text)])
            elif a.get("type") == "hook_blocking_error" and a.get("hookEvent") == "Stop":
                be = a.get("blockingError")
                text = be.get("blockingError") if isinstance(be, dict) else str(be or "")
                if text and text.startswith("頼み（受付") and text not in last_texts:
                    last_texts.append(text)
                    items.append(["undelivered", tokens(text)])
                    turn = "undelivered"
            elif reload_until_req and a.get("type") in ("skill_listing", "agent_listing_delta", "deferred_tools_delta"):
                items.append(["reload", tokens(json.dumps(a, ensure_ascii=False)) / 2])
            continue
        if t == "user":
            m = (d.get("message") or {}).get("content")
            if isinstance(m, str):
                if m.startswith("<command-name>/clear"):
                    items = [x for x in items[mark:] if x[0] == "role"]
                    mark = 0
                    turn = None
                    continue
                if m.startswith(("<command-name>/reload-plugins", "<local-command-caveat>", "<local-command-stdout>")):
                    if "reload" in m[:400] or m.startswith("<local-command-caveat>"):
                        items.append(["reload", tokens(m)])
                        reload_until_req = True
                    continue
                if STOP in m:
                    kind, body = stop_kind(m)
                    if kind:
                        items.append([kind, tokens(body)])
                    turn = kind if kind in TRIGGERED else None
                    continue
                if m.startswith("Stop hook feedback:\n頼み（受付"):
                    body = m.split("\n", 1)[1]
                    if body not in last_texts:
                        last_texts.append(body)
                        items.append(["undelivered", tokens(body)])
                    turn = "undelivered"
                    continue
                turn = None
                retry = None
                continue
            if isinstance(m, list):
                for b in m:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text = b.get("text", "")
                        if text.startswith("Base directory for this skill:") and "works-dispatch" in text[:200]:
                            items.append(["dispatch_skill", tokens(text)])
                            if skill is None:
                                skill = True
                        elif not text.startswith("Base directory"):
                            turn = None
                            retry = None
                    elif b.get("type") == "tool_result":
                        name, inp = tools.get(b.get("tool_use_id"), (None, {}))
                        text = result_text(b)
                        cmd = inp.get("command", "") if name == "Bash" else ""
                        fp = str(inp.get("file_path", ""))
                        if name == "Read" and "plugins/cache/" in fp and "/works-dispatch/" in fp:
                            items.append(["dispatch_skill", tokens(text)])
                        elif is_dispatch(cmd):
                            if "--deliver" in cmd:
                                retry = None
                            if "--deliver" in cmd and "外部投稿ゲート" in text[:300]:
                                items.append(["gates_reject", tokens(text)])
                                retry = "gates_retry"
                            elif "--deliver" in cmd and "送らなかった" in text:
                                items.append(["deliver_reject", tokens(text)])
                                retry = "deliver_retry"
                            else:
                                items.append(["dispatch_out", tokens(text)])
            continue
        if t != "assistant":
            continue
        msg = d.get("message") or {}
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tools[b.get("id")] = (b.get("name"), b.get("input") or {})
        u = msg.get("usage")
        rid = d.get("requestId") or msg.get("id")
        if not u or rid in seen:
            continue
        seen.add(rid)
        reload_until_req = False
        mark = len(items)
        at = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
        if not (since <= at < until):
            continue
        p_in, p_w5, p_w1, p_r, p_out = price(msg.get("model"))
        c = u.get("cache_creation") or {}
        w1 = c.get("ephemeral_1h_input_tokens", 0)
        w5 = c.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1)
        read = u.get("cache_read_input_tokens", 0)
        inp = u.get("input_tokens", 0)
        cin = inp * p_in + w5 * p_w5 + w1 * p_w1 + read * p_r
        cout = u.get("output_tokens", 0) * p_out
        ctx = inp + w5 + w1 + read
        day = at.strftime("%m-%d")
        o = out[day]
        o["requests"] += 1
        o["cost"] += cin + cout
        o["ctx"] += ctx
        o["weighted"] += inp + 1.25 * w5 + 2 * w1 + 0.05 * read
        o["co:" + company] += cin + cout
        if first:
            o["first_ctx_n"] += 1
            o["first_ctx"] += ctx
            o["first_role"] += sum(tok for k, tok in items if k == "role")
            first = False
        if skill:
            o["skill_ctx_n"] += 1
            o["skill_ctx"] += ctx
            skill = False
        kind = turn if turn in TRIGGERED else retry
        if kind:
            o["trig:" + kind] += cin + cout
            o["n:" + kind] += 1
            continue
        if ctx:
            for k, tok in items:
                o["occ:" + k] += min(1.0, tok / ctx) * cin


def subagents(sid, path, price, since, until, out):
    """会話が立てたサブエージェント（<会話>/subagents/*.jsonl）の要求の費用を日ごとに足す。仕組みの文は入らないので、全体の分母にだけ使う。"""
    seen = set()
    for f in glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage") if d.get("type") == "assistant" else None
            rid = d.get("requestId") or msg.get("id")
            if not u or rid in seen:
                continue
            seen.add(rid)
            at = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
            if not (since <= at < until):
                continue
            p_in, p_w5, p_w1, p_r, p_out = price(msg.get("model"))
            c = u.get("cache_creation") or {}
            w1 = c.get("ephemeral_1h_input_tokens", 0)
            w5 = c.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1)
            out[at.strftime("%m-%d")]["sub"] += (u.get("input_tokens", 0) * p_in + w5 * p_w5 + w1 * p_w1
                                                 + u.get("cache_read_input_tokens", 0) * p_r + u.get("output_tokens", 0) * p_out)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-20")
    ap.add_argument("--until", default="2026-10-29")
    ap.add_argument("--json")
    a = ap.parse_args(argv[1:])
    tz = datetime.datetime.now().astimezone().tzinfo
    since = datetime.datetime.fromisoformat(a.since).replace(tzinfo=tz)
    until = datetime.datetime.fromisoformat(a.until).replace(tzinfo=tz)
    price = prices()
    out = collections.defaultdict(collections.Counter)
    found = sessions()
    for sid, (company, path) in found.items():
        walk(path, company, price, since, until, out)
        subagents(sid, path, price, since, until, out)
    days = sorted(out)
    tot = collections.Counter()
    for dd in days:
        tot.update(out[dd])
    kinds = sorted({k.split(":", 1)[1] for k in tot if k.startswith(("occ:", "trig:"))},
                   key=lambda k: -(tot["occ:" + k] + tot["trig:" + k]))
    print(f"会話 {len(found)} 本（記録の在る物）・要求 {tot['requests']} 回・費用 ${tot['cost']:.0f}"
          f"（claude-plugins ${tot['co:claude-plugins']:.0f}・my_notes ${tot['co:my_notes']:.0f}）")
    mech = sum(tot["occ:" + k] + tot["trig:" + k] for k in kinds if not k.startswith("gates"))
    print(f"サブエージェントの費用 ${tot['sub']:.0f}（本体と足して ${tot['cost'] + tot['sub']:.0f}）")
    print(f"仕組みが足した分 ${mech:.0f}（本体の {100 * mech / tot['cost']:.1f}%・サブエージェントと足した全体の"
          f" {100 * mech / (tot['cost'] + tot['sub']):.1f}%）。種類ごと（占有 + 起動、本体に対する割合、起動したターンの要求の数）:")
    for k in kinds:
        v = tot["occ:" + k] + tot["trig:" + k]
        print(f"  {LABEL.get(k, k)}: ${v:.1f}（{100 * v / tot['cost']:.2f}%。占有 ${tot['occ:' + k]:.1f}・起動 ${tot['trig:' + k]:.1f}"
              f"・{tot['n:' + k]} 回）")
    print("日ごと: 日 要求 費用 1 回あたりの費用 1 回あたりの文脈 仕組みの割合 1 回あたりの重み（入力 1・書き 2/1.25・読み 0.05）"
          " 最初の要求の文脈（中の役の本文）・dispatch のスキルを読んだ直後の文脈")
    for dd in days:
        o = out[dd]
        m = sum(o["occ:" + k] + o["trig:" + k] for k in kinds if not k.startswith("gates"))
        n = o["requests"]
        fc = f"{o['first_ctx'] / o['first_ctx_n']:.0f}（{o['first_role'] / o['first_ctx_n']:.0f}）" if o["first_ctx_n"] else "-"
        sc = f"{o['skill_ctx'] / o['skill_ctx_n']:.0f}" if o["skill_ctx_n"] else "-"
        print(f"  {dd} {n} ${o['cost']:.0f} ${o['cost'] / n:.3f} {o['ctx'] / n:.0f} {100 * m / o['cost']:.1f}%"
              f" {o['weighted'] / n:.0f} {fc} {sc}  " + "・".join(f"{k} {100 * (o['occ:' + k] + o['trig:' + k]) / o['cost']:.1f}%" for k in kinds[:5]))
    if a.json:
        json.dump({dd: dict(out[dd]) for dd in days}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv)
