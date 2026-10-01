"""修正の後の局所レビュー（レンズ）の控え lens.json（盤面の今の周の作業ファイル）。読み書きはこの口だけ。

レンズのブロックの振り分けが行を書き、集め役が埋め、差分の審査の支度（refix.cut）と機械の報告が読む（後で数える口も同じ
ファイルを読む。2 つ目の置き場を作らない）。行の形:
{lens, agent, go, reason, state: pending|ran|failed|not_routed, findings: [{lens, where, cite, why}]}
findings の lens は指摘の出どころ（レンズの名）。

- write_routes(b, rows): 振り分けの行（{lens, agent, go, reason}）を書く。go が偽の行は not_routed、真の行は pending
- collect(b, outputs):   {レンズの名: レンズの節の出口 | None} で pending の行を埋める（出口が無い・形が違えば failed と理由、
                         在れば ran と出どころつきの findings）。控えが無い・読めなければ ValueError
- read(b):               行の一覧。控えが無い run は None、読めない・形が違えば ValueError
- brief_rows(b):         差分の審査役の brief の lens の欄（控えが無い run は []。読めなければ ValueError）
- report_lines(b):       報告の「未確認のレンズ」の節の行（控えが無い run は []。読めなければ理由の行）
"""
import json
import os

LENS_FILE = "lens.json"
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


def _findings(name: str, out) -> list | None:
    items = out.get("findings") if isinstance(out, dict) else None
    if not isinstance(items, list) or not all(isinstance(f, dict) and all(isinstance(f.get(k), str) and f[k] for k in FINDING_KEYS)
                                              for f in items):
        return None
    return [{"lens": name, **{k: f[k] for k in FINDING_KEYS}} for f in items]


def collect(b, outputs: dict) -> list:
    rows = read(b)
    if rows is None:
        raise ValueError("レンズの控えが無い（振り分けが書いていない）")
    for r in rows:
        if r["state"] != "pending":
            continue
        out = outputs.get(r["lens"])
        found = None if out is None else _findings(r["lens"], out)
        if out is None:
            r.update(state="failed", reason="レンズの節の出口が無い（落ちたか走らなかった）")
        elif found is None:
            r.update(state="failed", reason=f"レンズの節の出口の findings の形が違う: {str(out)[:200]}")
        else:
            r.update(state="ran", findings=found)
    _write(b, rows)
    return rows


def brief_rows(b) -> list:
    return [{k: r.get(k) for k in ("lens", "state", "reason", "findings")} for r in read(b) or []]


def report_lines(b) -> list:
    try:
        rows = read(b)
    except ValueError as e:
        return [f"レンズの控えが読めない（{e}）。どのレンズが見たかを確かめられない", REFIX_NOTE]
    if rows is None:
        return []
    left = [f"{r['lens']}: {UNSEEN[r['state']]}（{r.get('reason') or '理由の記録が無い'}）" for r in rows if r["state"] in UNSEEN]
    return [*(left or ["なし（振り分けたレンズは全部走った）"]), REFIX_NOTE]
