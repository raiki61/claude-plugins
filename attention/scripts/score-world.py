#!/usr/bin/env python3
"""世界の解の DW（attention/workflows/dig-world.js）の 1 回の返りを、走らせる前に書いた正解の札で照合し、数を出す。

使い方:
  score-world.py --key <札の JSON> --world <world.json> [--args <world-args.json>] [--record <重い版の記録>]
                 [--headless <world-headless.json>] [--transcripts <会話の記録のフォルダ>] [--name <対象の名前> ...]

数えること（attention/docs/small-workflows-design.md の 8.3）:
  - keys: 札ごとに拾えたか（hit）と、当たった比べ（hits）・名前の種類と相手が合うのに外れた比べ（near）と外れた訳
  - lines: 依頼の行のうち、行を返した数と missing の数
  - restate: 言い直しの回数・手段と名前の機械の当たり・漏れの照合で差し戻した数
  - excerpts: 抜き書きの残った・落ちた・照合できなかった数と、比べの根拠が web の割合
  - queries: 探す役が打った検索語（会話の記録の WebSearch）に、対象の名前が出た数
  - cost: 費用・時間・エージェントの数（--headless の出力と返りの counts から）
  - heavy: 重い版の記録の、世界の解の問い（origin が world のノード）の答えた数と、引用の照合の数
  - gate: 返りの head が札の head と同じで（別の head の返りを合にしない）、札のうち gate が true の物が全部拾えたか（8.4 の合否）
出力は JSON 1 つ。読めない入力は止める（docs/standards/machine-readable-values.md の決まり 4）。
"""
import argparse
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TEXT_FIELDS = ("practice", "challenge", "why", "applies")

# dig-world.js の WORD・shaped・tokensOf と同じ（対象の名前を検索語から探すため）
WORD = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*")


def shaped(t):
    return len(t) >= 3 and re.search(r"[A-Za-z]", t) and (re.search(r"[_./\-0-9]", t) or re.search(r"[a-z][A-Z]", t))


def tokens_of(text):
    out = set()
    for raw in WORD.findall(str(text)):
        tok = re.sub(r"[.\-/]+$", "", raw).split(":")[0]
        if shaped(tok):
            out.add(tok)
        if "/" in tok:
            parts = [p for p in tok.split("/") if p]
            out.update(p for p in parts if shaped(p))
            if parts and len(parts[-1]) >= 3:
                out.add(parts[-1])
    return out


class Stop(Exception):
    pass


def load(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise Stop("%s（%s）を読めません: %s" % (what, path, e))


def comparisons(world):
    for r in world.get("rows") or []:
        for c in r.get("comparisons") or []:
            yield r, c


def text_of(c):
    return "\n".join(str(c.get(k) or "") for k in TEXT_FIELDS)


def brief(r, c, why=None):
    a = c.get("against") or {}
    out = {"n": r.get("n"), "class_id": r.get("class_id"), "kind": a.get("kind"), "name": a.get("name"),
           "layer": c.get("layer"), "verdict": c.get("verdict"), "basis": c.get("basis"),
           "practice": str(c.get("practice") or "")[:400], "challenge": str(c.get("challenge") or "")[:400]}
    if why:
        out["missed"] = why
    return out


def score_key(key, world):
    name_re = re.compile(key["name"], re.I)
    text_re = re.compile(key["text"], re.I)
    hits, near = [], []
    for r, c in comparisons(world):
        a = c.get("against") or {}
        if a.get("kind") not in key["kinds"] or not name_re.search(str(a.get("name") or "")):
            continue
        why = []
        if c.get("layer") not in key["layers"]:
            why.append("layer")
        if c.get("verdict") not in key["verdicts"]:
            why.append("verdict")
        if not text_re.search(text_of(c)):
            why.append("text")
        (near if why else hits).append(brief(r, c, why or None))
    return {"id": key["id"], "gate": bool(key.get("gate")), "hit": bool(hits), "hits": hits, "near": near}


def lines_part(world, args):
    total = len(args.get("lines") or []) if args else None
    answered = sorted({r.get("n") for r in world.get("rows") or []})
    missing = world.get("missing") or []
    return {"total": total, "answered": len(answered), "answeredLines": answered, "missing": len(missing),
            "missingWhy": missing}


def excerpts_part(world):
    ex = world.get("excerpts") or {}
    checked = (ex.get("kept") or 0) + (ex.get("dropped") or 0)
    comps = [c for _, c in comparisons(world)]
    web = sum(1 for c in comps if c.get("basis") == "web")
    return {**ex, "keptOfChecked": round(ex.get("kept", 0) / checked, 3) if checked else None,
            "comparisons": len(comps), "webBasis": web,
            "webShare": round(web / len(comps), 3) if comps else None}


def leak_names(args, extra):
    """対象の名前: 依頼の行から機械が取った名前（dig-world.js の bannedTokens と同じ取り方）から、依存の名と版を除いた物と、--name"""
    names = set()
    for ln in (args or {}).get("lines") or []:
        for v in ln.values():
            if isinstance(v, str):
                names |= tokens_of(v)
                names |= {m.strip() for m in re.findall(r"`([^`\n]{2,})`", v) if m.strip()}
    third = set()
    for d in (args or {}).get("deps") or []:
        for x in [d.get("name"), d.get("version")] + sorted(tokens_of(d.get("name") or "")):
            if x:
                third.add(str(x).lower())
    names = {n for n in names if n.lower() not in third}
    names |= set(extra or [])
    return names


def tool_calls(folder):
    """会話の記録（jsonl）の中の WebSearch の検索語と WebFetch の URL。読めない行は数えて返す"""
    queries, fetches, files, bad = [], [], 0, 0
    for root, _dirs, names in os.walk(folder):
        for nm in sorted(names):
            if not nm.endswith(".jsonl"):
                continue
            files += 1
            with open(os.path.join(root, nm), encoding="utf-8", errors="replace") as f:
                for raw in f:
                    try:
                        d = json.loads(raw)
                    except ValueError:
                        bad += 1   # 書きかけの行。数を出力の unreadableLines に出す
                        continue
                    content = ((d.get("message") or {}).get("content")) if isinstance(d, dict) else None
                    for it in content if isinstance(content, list) else []:
                        if not isinstance(it, dict) or it.get("type") != "tool_use":
                            continue
                        inp = it.get("input") or {}
                        if it.get("name") == "WebSearch":
                            queries.append({"file": nm, "query": str(inp.get("query") or "")})
                        elif it.get("name") == "WebFetch":
                            fetches.append(str(inp.get("url") or ""))
    return queries, fetches, files, bad


def queries_part(folder, names):
    if not folder:
        return None
    if not os.path.isdir(folder):
        raise Stop("会話の記録のフォルダ（%s）が在りません" % folder)
    queries, fetches, files, bad = tool_calls(folder)
    leaks = []
    for q in queries:
        found = sorted(n for n in names
                       if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n), q["query"], re.I))
        if found:
            leaks.append({**q, "names": found})
    return {"files": files, "unreadableLines": bad, "searches": len(queries), "fetches": len(fetches),
            "leaks": len(leaks), "leakQueries": leaks, "names": len(names)}


def cost_part(world, headless):
    counts = world.get("counts") or {}
    out = {"agents": counts.get("agents"), "classes": counts.get("classes"), "stages": counts.get("stages")}
    if headless:
        out.update(costUsd=headless.get("total_cost_usd"), durationMs=headless.get("duration_ms"),
                   turns=headless.get("num_turns"), subtype=headless.get("subtype"),
                   models={k: (v or {}).get("costUSD") for k, v in (headless.get("modelUsage") or {}).items()})
    return out


def heavy_part(record):
    if not record:
        return None
    nodes = [n for n in record.get("nodes") or [] if n.get("origin") == "world"]
    answered = [n["id"] for n in nodes if n.get("status") != "unverified"]
    q = (record.get("counts") or {}).get("quotes") or {}
    dropped = q.get("dropped") or []
    ids = {n["id"] for n in nodes}
    world_ev = sum(len(n.get("evidence") or []) for n in nodes)
    return {"head": record.get("head"), "worldQuestions": len(nodes), "answered": len(answered),
            "answeredIds": answered, "cut": len(nodes) - len(answered),
            "worldEvidence": world_ev, "worldDropped": sum(1 for d in dropped if d.get("where") in ids),
            "quotes": {"items": q.get("items"), "checked": q.get("checked"), "dropped": len(dropped),
                       "unchecked": q.get("unchecked"),
                       "keptOfChecked": round((q["checked"] - len(dropped)) / q["checked"], 3) if q.get("checked") else None}}


def main(argv):
    ap = argparse.ArgumentParser(prog="score-world.py")
    ap.add_argument("--key", required=True)
    ap.add_argument("--world", required=True)
    ap.add_argument("--args")
    ap.add_argument("--record")
    ap.add_argument("--headless")
    ap.add_argument("--transcripts")
    ap.add_argument("--name", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        key = load(a.key, "正解の札")
        world = load(a.world, "世界の解の DW の返り")
        args = load(a.args, "DW の args") if a.args else None
        record = load(a.record, "重い版の記録") if a.record else None
        headless = load(a.headless, "ヘッドレスの出力") if a.headless else None
        if not isinstance(world.get("rows"), list):
            raise Stop("返りに rows がありません（status %s・reason %s）" % (world.get("status"), world.get("reason")))
        keys = [score_key(k, world) for k in key["keys"]]
        same_head = bool(key.get("head")) and world.get("head") == key.get("head")
        out = {"pr": key.get("pr"), "head": world.get("head"), "keyHead": key.get("head"),
               "headMatches": same_head, "status": world.get("status"),
               "gate": same_head and all(k["hit"] for k in keys if k["gate"]),
               "keys": keys, "lines": lines_part(world, args), "restate": world.get("restate"),
               "excerpts": excerpts_part(world),
               "queries": queries_part(a.transcripts, leak_names(args, a.name)),
               "cost": cost_part(world, headless), "heavy": heavy_part(record)}
    except Stop as e:
        print(json.dumps({"ok": False, "message": str(e)}, ensure_ascii=False))
        return 1
    except (KeyError, re.error) as e:
        print(json.dumps({"ok": False, "message": "札の形が違います: %s" % e}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **out}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
