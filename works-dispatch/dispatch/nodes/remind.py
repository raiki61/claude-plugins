#!/usr/bin/env python3
"""リマインダー（部署か窓口が「この日に見る」「この頼みが閉じたら見る」と台帳に残す件）の射影と、見る時が来たかの判じ。
流れは reminds.py（--remind・--remind-done と、--due が知らせる notify）。形と決めた事は docs/ledger.md の「リマインダー」。"""

import time

REMIND = "remind"             # 立てた（id はリマインダーの受付。text・holder・on・after）
REMINDED = "reminded"         # 見る時が来て、担当者に知らせた（1 度だけ。why に来た訳）
REMIND_DONE = "remind-done"   # 閉じた
# after の頼みが閉じたと見る状態（ledger.STATES の、開いていない物。回して閉じた頼みも done で、forwarded の印が付く）
CLOSED = ("done", "dropped", "failed")
FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")


def parse_on(text):
    """--on の日時（手元の時刻の YYYY-MM-DD か YYYY-MM-DDTHH:MM。日付だけならその日の 0 時）の UNIX 時刻か、読めなければ None。"""
    for f in FORMATS:
        try:
            return time.mktime(time.strptime(text.strip(), f))
        except ValueError:
            continue   # 次の形で読む。どの形でも読めなければ None を返し、呼ぶ側（--remind）が止める
    return None


def stamp(at):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))


def project(rows):
    """行の並びから {受付: リマインダー}。知らせの行（to が字）は、リマインダーの受付を指していれば知らせた印に数える（reminded の
    行を書く前に落ちても、2 度は知らせない）。"""
    out = {}
    for r in rows:
        kind, i = r.get("kind"), r.get("id")
        if not i:
            continue
        if isinstance(r.get("to"), str):
            if i in out and not out[i]["reminded"]:
                out[i]["reminded"] = r.get("at")
            continue
        if kind == REMIND:
            out[i] = {"id": i, "text": r.get("text") or "", "holder": r.get("holder"), "on": r.get("on"),
                      "after": list(r.get("after") or []), "created": r.get("at"), "reminded": None, "closed": None}
        elif kind == REMINDED and i in out:
            out[i]["reminded"] = out[i]["reminded"] or r.get("at")
        elif kind == REMIND_DONE and i in out:
            out[i]["closed"] = r.get("at")
    return out


def came(rem, tasks, now):
    """見る時が来た訳か None。見る日が過ぎたか、待つ頼みのどれかが閉じたら来た（どちらか先に来た方）。tasks は ledger.build の頼み。"""
    if rem["closed"]:
        return None
    if rem["on"] is not None and rem["on"] <= now:
        return f"見る日 {stamp(rem['on'])} が来た"
    shut = [(i, tasks[i]) for i in rem["after"] if (tasks.get(i) or {}).get("state") in CLOSED]
    if shut:
        return "、".join(f"受付 {i} が閉じた（{'回した' if t.get('forwarded') else t['label']}）" for i, t in shut)
    return None


def waits_for(rem):
    """何を待つかの短い字（--todo と --remind の出力）。"""
    got = ([f"見る日 {stamp(rem['on'])}"] if rem["on"] is not None else []) + [f"受付 {i} が閉じたら" for i in rem["after"]]
    return "・".join(got) + ("（先に来た方）" if len(got) > 1 else "")
