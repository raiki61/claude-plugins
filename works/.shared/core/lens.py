"""修正の後の局所レビュー（レンズ）の控え lens.json（盤面の今の周の作業ファイル）。読み書きはこの口だけ。

レンズのブロックの振り分けが行を書き、集め役が埋め、差分の審査の支度（refix.cut）と機械の報告が読む（後で数える口も同じ
ファイルを読む。2 つ目の置き場を作らない）。行の形:
{lens, agent, go, reason, state: pending|ran|failed|not_routed, findings: [{lens, where, cite, why}], dropped}
findings の lens は指摘の出どころ（レンズの名）。dropped は形の誤りで捨てた発見の件数（ran の行だけ）。

- write_routes(b, rows): 振り分けの行（{lens, agent, go, reason}）を書く。go が偽の行は not_routed、真の行は pending
- collect(b, outputs):   {レンズの名: レンズの節の出口 | None} で pending の行を埋める（出口が無い・形が違えば failed と理由、
                         在れば ran と出どころつきの findings。1 件の形の誤りは捨てて dropped に数える）。控えが無い・読めなければ ValueError
- read(b):               行の一覧。控えが無い run は None、読めない・形が違えば ValueError
- brief_rows(b):         差分の審査役の brief の lens の欄（控えが無い run は []。読めなければ ValueError）
- summary(b):            レンズの集計（採った・採らなかった・捨てた件数・落ちたレンズ。投げない）。報告・関所・次の依頼はこれだけを読む
- report_lines(b):       報告の「未確認のレンズ」の節の行（控えが無い run は「走らせていない」の行。読めなければ理由の行）
"""
import json
import os

LENS_FILE = "lens.json"
REVIEW_NODE = "p3.delta_review"   # 採った・採らなかったを数える差分の審査の節（1 回目）
STOP_BY = "works:lens"   # 集め役が終わらなかった盤面の state.stop.by
STATES = ("pending", "ran", "failed", "not_routed")
FINDING_KEYS = ("where", "cite", "why")
UNSEEN = {"pending": "集め役が埋めていない", "failed": "落ちた", "not_routed": "起こさなかった"}
REFIX_NOTE = "手直しの差分にはレンズが当たらない（最後のテストで守る）"


def _write(b, rows: list):
    path = b.work(LENS_FILE)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_routes(b, rows: list):
    return _write(b, [{"lens": r["lens"], "agent": r["agent"], "go": bool(r["go"]), "reason": r.get("reason") or "",
                       "state": "pending" if r["go"] else "not_routed", "findings": []} for r in rows])


def read(b) -> list | None:
    path = b.work(LENS_FILE)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"レンズの控え {path} が読めない: {e}") from None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("lens"), str)
                                             and r.get("state") in STATES for r in rows):
        raise ValueError(f"レンズの控え {path} の形が違う（rows の行に lens と state が要る）")
    return rows


def _findings(name: str, out) -> tuple | None:
    """レンズの出口の findings を 1 件ずつ FINDING_KEYS で検め、形の合った発見（出どころ name つき）と捨てた件数を返す。
    出口全体の形が違えば（findings が配列でない）None"""
    items = out.get("findings") if isinstance(out, dict) else None
    if not isinstance(items, list):
        return None
    kept = [f for f in items if isinstance(f, dict) and all(isinstance(f.get(k), str) and f[k] for k in FINDING_KEYS)]
    return [{"lens": name, **{k: f[k] for k in FINDING_KEYS}} for f in kept], len(items) - len(kept)


def collect(b, outputs: dict) -> list:
    rows = read(b)
    if rows is None:
        raise ValueError("レンズの控えが無い（振り分けが書いていない）")
    for r in rows:
        if r["state"] != "pending":
            continue
        out = outputs.get(r["lens"])
        got = None if out is None else _findings(r["lens"], out)
        if out is None:
            r.update(state="failed", reason="レンズの節の出口が無い（落ちたか走らなかった）")
        elif got is None:
            r.update(state="failed", reason=f"レンズの節の出口の findings の形が違う: {str(out)[:200]}")
        else:
            r.update(state="ran", findings=got[0], dropped=got[1])
    _write(b, rows)
    return rows


def brief_rows(b) -> list:
    return [{k: r.get(k) for k in ("lens", "state", "reason", "findings")} for r in read(b) or []]


def summary(b) -> dict:
    """レンズの集計の正本。報告・最後の関所・次の依頼はこの戻り値だけを読む（lens 欄の読みもここだけ）。投げない。
    {ran, readable, reason, rows, failed, dropped, adopted, not_adopted, unmatched}。
    - ran: 控えが在る（レンズを走らせた）。無ければ False で、ほかの数は 0 か None
    - readable: 控えが読めた。読めなければ False と reason（0 件に見せない）
    - rows: ran のレンズごとの {lens, findings, adopted, not_adopted, dropped}。adopted は今の周の p3.delta_review の faces のうち
      lens 欄がその名の穴の数、not_adopted は findings から adopted を引いた残り（負にしない）
    - failed: 落ちたレンズの [{lens, reason}]。dropped: 形の誤りで捨てた発見の総数
    - adopted・not_adopted: 今の周の差分の審査の出力が無ければ None（審査が走っていない＝調べていない。0 ではない）
    - unmatched: lens 欄が ran のレンズの名に当たらない穴の数（数えに混ざらないよう別に出す。審査が無ければ None）"""
    out = {"ran": False, "readable": True, "reason": "", "rows": [], "failed": [], "dropped": 0,
           "adopted": None, "not_adopted": None, "unmatched": None}
    try:
        rows = read(b)
    except ValueError as e:
        return {**out, "ran": True, "readable": False, "reason": str(e)}
    if rows is None:
        return {**out, "adopted": 0, "not_adopted": 0, "unmatched": 0}
    try:
        review = b.output_of_round(REVIEW_NODE, b.round)
    except (OSError, ValueError, KeyError) as e:
        return {**out, "ran": True, "readable": False, "reason": f"差分の審査の出力が読めない: {e}"}
    faces = [f for f in (review.get("faces") or []) if isinstance(f, dict)] if isinstance(review, dict) else None
    ran = [r for r in rows if r["state"] == "ran"]
    counted = []
    for r in ran:
        found = r.get("findings") if isinstance(r.get("findings"), list) else []
        adopted = None if faces is None else sum(1 for f in faces if f.get("lens") == r["lens"])
        counted.append({"lens": r["lens"], "findings": len(found), "adopted": adopted,
                        "not_adopted": None if adopted is None else max(0, len(found) - adopted),
                        "dropped": r["dropped"] if isinstance(r.get("dropped"), int) else 0})
    names = {r["lens"] for r in ran}
    return {**out, "ran": True, "rows": counted,
            "failed": [{"lens": r["lens"], "reason": r.get("reason") or "理由の記録が無い"} for r in rows if r["state"] == "failed"],
            "dropped": sum(c["dropped"] for c in counted),
            "adopted": None if faces is None else sum(c["adopted"] for c in counted),
            "not_adopted": None if faces is None else sum(c["not_adopted"] for c in counted),
            "unmatched": None if faces is None else sum(1 for f in faces if isinstance(f.get("lens"), str) and f["lens"] not in names)}


def count_line(s: dict) -> str:
    """summary の採った・採らなかった・捨てた件数を 1 行にする（審査が走っていなければ「調べていない」）"""
    if s["adopted"] is None:
        taken = "差分の審査が走っていないので採った・採らなかったは調べていない"
    else:
        taken = f"採った {s['adopted']} 件・採らなかった {s['not_adopted']} 件"
        if s["unmatched"]:
            taken += f"（レンズの名に当たらない lens 欄 {s['unmatched']} 件は数えに入れない）"
    return f"レンズの発見: {taken}・形の誤りで捨てた {s['dropped']} 件"


def report_lines(b) -> list:
    s = summary(b)
    if not s["readable"]:
        return [f"レンズの控えが読めない（{s['reason']}）。どのレンズが見たかを確かめられない", REFIX_NOTE]
    if not s["ran"]:
        return ["レンズを走らせていない（控えが無い）"]
    left = [f"{r['lens']}: {UNSEEN[r['state']]}（{r.get('reason') or '理由の記録が無い'}）" for r in read(b) if r["state"] in UNSEEN]
    return [*(left or ["なし（振り分けたレンズは全部走った）"]), REFIX_NOTE, count_line(s)]
