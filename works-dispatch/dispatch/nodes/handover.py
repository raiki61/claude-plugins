#!/usr/bin/env python3
"""handover ノード: 部署か窓口の受け持ちを、同じ会社のほかの部署（後継）へ移す（dispatch.py --handover）の中身。流れ（どの順に呼ぶか）は
handover.py が持つ。

移すのは宛先（名前）で、受付番号は替えない。台帳（log.jsonl）は追記だけなので、前の行は書き換えず、移したことを kind handover の行で
足す（started と done の 2 行。途中で落ちたら、started で done の無い行から同じ手順を続ける）。後で読む側は、この行で読み替える:

- 宛先: 後継の属性 company.former-names に前の名前を足す（--ask・--land・会社の形の desk は前の名前でも後継を引く。gitx.former_names）。
- 待ち受け: 後継の属性 company.inherited（JSON の並び。読み方は gitx.inherited）の since（台帳のバイトの位置）より後の、前の名前宛ての知らせだけを後継の物と
  見る（since より前は前の部署が読んだか、移すときに後継の宛先へ写し直した物。wake.watch の since）。
- 納品の返し先: 頼み元が前の部署で、移すより前に頼んだ物なら、頼み元の受付箱の台帳の handover の行で後継に読み替える（successor）。前の会話のペインに打ち込まない。
"""

import os

KIND = "handover"
STARTED, DONE = "started", "done"


def rows_of(records, hid=None):
    """台帳の行のうち handover の行（hid を渡せばその id の物）。"""
    return [r for r in records if r.get("kind") == KIND and (hid is None or r.get("id") == hid)]


def unfinished(records, from_name, to_place):
    """前の名前と後継の場所（worktree の git_dir）が同じで、started のまま done の無い handover の行（最後の 1 件）。無ければ None。"""
    done = {r.get("id") for r in rows_of(records) if r.get("status") == DONE}
    hits = [r for r in rows_of(records) if r.get("status") == STARTED and r.get("id") not in done
            and (r.get("from") or {}).get("name") == from_name
            and os.path.realpath((r.get("to") or {}).get("place") or "") == os.path.realpath(to_place)]
    return hits[-1] if hits else None


STAMP = 15   # 受付番号の頭の時刻（UTC の YYYYMMDD-HHMMSS。deliver.new_id）の字数


def _matches(row, boss):
    """頼み元が、その handover の行の前の部署か。名前（前の名前を含む）で見る（会話の id だけでは見ない。前の会話が引き継ぎの後に
    --desk でほかの名前を名乗っても、その名前の頼みを後継へ横取りしない）。"""
    src = row.get("from") or {}
    return bool(boss.get("name")) and boss["name"] in ([src.get("name")] + list(src.get("former") or []))


def _before(ask, row):
    """受付 ask が、その handover より前に頼まれたか（どちらも受付番号の頭の時刻で比べる。比べられなければ偽）。"""
    a, h = (ask or "")[:STAMP], (row.get("id") or "")[:STAMP]
    return len(a) == STAMP == len(h) and a[8:9] == "-" == h[8:9] and a.replace("-", "").isdigit() and h.replace("-", "").isdigit() \
        and a <= h


def successor(records, boss, ask):
    """受付 ask の頼み元（{name, session, account, pane, inbox}）が、移した前の部署なら、後継に読み替えた頼み元。読み替える物が無ければ
    None。records は頼み元の受付箱の台帳の行。移すより前に頼んだ物だけ読み替える（移した後に同じ名前で頼んだ物は、その頼み元へ返す）。
    後継がさらに移していれば先までたどる（同じ行を 2 度は使わない）。"""
    used, out = set(), None
    current = dict(boss)
    while True:
        hit = next((r for r in reversed(rows_of(records)) if r.get("status") == STARTED and r.get("id") not in used
                    and _matches(r, current) and _before(ask, r)), None)
        if hit is None:
            return out
        used.add(hit["id"])
        to = hit.get("to") or {}
        current = {**current, "name": to.get("name"), "session": to.get("session"), "account": to.get("account"),
                   "pane": to.get("pane")}
        out = {**current, "via": hit["id"]}


def copy_key(r):
    """写し直した知らせと元の知らせを結ぶ鍵（打ち直しで同じ知らせを 2 度写さない）。"""
    return (r.get("id"), r.get("kind"), r.get("file"), r.get("at"), r.get("to"))


def copies(records, hid):
    """その handover で写し直した知らせの元の鍵の集まり。"""
    return {tuple(r["copied"]) for r in records if r.get(KIND) == hid and isinstance(r.get("copied"), list)}


def copied(r, to, hid):
    """前の宛先宛ての知らせ r を、後継の宛先 to 宛てに写し直した行。"""
    return {**r, "to": to, KIND: hid, "copied": list(copy_key(r))}
