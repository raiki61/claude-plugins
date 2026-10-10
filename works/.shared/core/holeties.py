"""差分の審査の穴に枝の名札を付ける（線の木の段 4a。設計 docs/plans/2026-10-07-hole-to-branch.md の 2.2・2.3）。層 L3。

枝は修正案の項目（"item:<番号>"）か、どの項目にも無い単位（"unit:<単位の key>"）。穴 1 件ごとに、それが属する枝の組と、
どの規則で結んだかを機械が付ける。答え方も直す義務も変えない（手直しの役の材料・最後の関所の文・報告・次の run の依頼の下書きに
添えるだけ）。盤面の節の名は知らない（集める口は refix.hole_ties）。

規則（全部当てて枝の和を取る。VIA の語）:
- compliance: 準拠の落ちた行（deltamarks の行 {item, face_key}）の face_key が穴の key → その項目
- check:      塞がっていない検算の key が事前審査の穴の key → その穴の unit_keys を持つ項目（項目に無い単位はその単位の枝）
- path:       穴の where が項目の allowed_paths の glob（planmarks.glob_match）か受け入れ・書き換えのテストのファイル
              （planmarks.test_paths）に当たる → その項目
- change:     修正の changes の行で files に where を持つ行の unit_key → その単位の項目（無ければ単位の枝）
- unit:       単位の key の頭のパス（unit_path）が where と同じ → その単位の項目（無ければ単位の枝）
- earlier:    2 回目の手直しの穴: 検算の key は 1 回目にその key に結んだ枝、where は 1 回目の手直しがそのファイルを変えた
              穴の枝（earlier が組む）

- tie(holes, items, *, compliance, plan_faces, changes, earlier): 穴の順の [{key, from, where, branches, via, held}]。
  held は、結んだ枝が全部裁定で外れた項目（項目の held）の時の理由（「・」でつなぐ）。ほかは空
- earlier(ties, handled): 1 回目の名札と 1 回目の手直しの handled から 2 回目の earlier を組む
- groups(ties): 枝の組 {lanes: {枝: [key]}（名札が枝 1 つで held でない穴）, synergy: [key]（枝 2 つ以上・0・held）}
- spread(ties): 測りの数 {holes, single, multi, none, held, groups（空でない組の数）, branches: {枝: 穴の数}}
- label(枝)・note(名札)・lines(ties)・count_line(ties): 人が読む字（「項目 1」「単位 <key>」）
- unit_path(単位の key): 頭のパス
"""
from __future__ import annotations

import pathlib
import sys

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import planmarks  # noqa: E402  （glob の当て方とテストのファイルの正本）

VIA = ("compliance", "check", "path", "change", "unit", "earlier")
NOWHERE = "どの枝にも結べない"
MULTI = "2 つ以上の枝にまたがる"
HELD = "裁定で外れた項目だけ"


def item_branch(n) -> str:
    return f"item:{n}"


def unit_branch(key: str) -> str:
    return f"unit:{key}"


def unit_path(key: str) -> str:
    """単位の key の頭のパス（`<パス>+<名>: <一言>` か `<パス>: <一言>` の <パス>）。取れなければ空"""
    head = str(key or "").split(":", 1)[0].split("+", 1)[0].strip()
    return head if "/" in head or "." in head else ""


def label(bid: str) -> str:
    kind, _, rest = str(bid).partition(":")
    return f"項目 {rest}" if kind == "item" else f"単位 {rest}"


def _order(bid: str):
    kind, _, rest = bid.partition(":")
    return (0, int(rest), "") if kind == "item" and rest.isdigit() else (1, 0, rest)


def _units_to_branches(keys, items) -> set:
    out = set()
    for k in keys or []:
        if not isinstance(k, str):
            continue
        hit = {item_branch(it["item"]) for it in items if k in (it.get("unit_keys") or [])}
        out |= hit or {unit_branch(k)}
    return out


def _path_hit(where: str, it: dict) -> bool:
    globs = [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g]
    return any(planmarks.glob_match(where, g) for g in globs) or where in planmarks.test_paths(it)


def earlier(ties: list, handled: list) -> dict:
    """1 回目の名札 ties と 1 回目の手直しの handled から、2 回目の名札の earlier {keys: {key: [枝]}, files: {パス: [枝]}}"""
    keys = {t["key"]: list(t["branches"]) for t in ties}
    files: dict = {}
    for h in handled or []:
        if not isinstance(h, dict) or h.get("key") not in keys:
            continue
        for f in h.get("files") or []:
            if isinstance(f, str):
                files[f] = sorted(set(files.get(f, [])) | set(keys[h["key"]]), key=_order)
    return {"keys": keys, "files": files}


def tie(holes: list, items: list, *, compliance=(), plan_faces=(), changes=(), earlier: dict | None = None) -> list:
    """穴の名札（頭の注記）。holes は [{key, from, where?, check?}]、items は承認済みの項目（item・unit_keys・allowed_paths・
    tests・rewrite_tests・held?）"""
    items = [it for it in items or [] if isinstance(it, dict) and "item" in it]
    faces = {f.get("key"): f.get("unit_keys") for f in plan_faces or [] if isinstance(f, dict)}
    rows = [c for c in changes or [] if isinstance(c, dict) and isinstance(c.get("unit_key"), str)]
    known = [k for it in items for k in it.get("unit_keys") or [] if isinstance(k, str)] + [c["unit_key"] for c in rows]
    held = {item_branch(it["item"]): it["held"] for it in items if it.get("held")}
    prev = earlier or {}
    out = []
    for h in holes or []:
        key, where = h.get("key"), str(h.get("where") or "")
        found: dict = {}

        def add(via, got):
            if got:
                found.setdefault(via, set()).update(got)
        add("compliance", {item_branch(r["item"]) for r in compliance or []
                           if isinstance(r, dict) and r.get("face_key") == key and isinstance(r.get("item"), int)})
        if h.get("check"):
            if key in faces:
                add("check", _units_to_branches(faces[key], items))
            add("earlier", set((prev.get("keys") or {}).get(key) or []))
        if where:
            add("path", {item_branch(it["item"]) for it in items if _path_hit(where, it)})
            add("change", _units_to_branches([c["unit_key"] for c in rows if where in (c.get("files") or [])], items))
            add("unit", _units_to_branches([k for k in dict.fromkeys(known) if unit_path(k) == where], items))
            add("earlier", set((prev.get("files") or {}).get(where) or []))
        branches = sorted(set().union(*found.values()) if found else set(), key=_order)
        whys = [held[x] for x in branches if x in held]
        out.append({"key": key, "from": h.get("from") or "", "where": where, "branches": branches,
                    "via": [v for v in VIA if v in found],
                    "held": "・".join(dict.fromkeys(whys)) if branches and len(whys) == len(branches) else ""})
    return out


def groups(ties: list) -> dict:
    """枝の組と相乗りの組（頭の注記）"""
    lanes: dict = {}
    synergy = []
    for t in ties or []:
        if len(t["branches"]) == 1 and not t["held"]:
            lanes.setdefault(t["branches"][0], []).append(t["key"])
        else:
            synergy.append(t["key"])
    return {"lanes": dict(sorted(lanes.items(), key=lambda kv: _order(kv[0]))), "synergy": synergy}


def spread(ties: list) -> dict:
    """測りの数（頭の注記）"""
    g = groups(ties)
    return {"holes": len(ties or []),
            "single": sum(1 for t in ties or [] if len(t["branches"]) == 1 and not t["held"]),
            "multi": sum(1 for t in ties or [] if len(t["branches"]) >= 2 and not t["held"]),
            "none": sum(1 for t in ties or [] if not t["branches"]),
            "held": sum(1 for t in ties or [] if t["held"]),
            "groups": len(g["lanes"]) + (1 if g["synergy"] else 0),
            "branches": {k: len(v) for k, v in g["lanes"].items()}}


def note(t: dict) -> str:
    """1 件の名札の字（「項目 1」・「項目 1・項目 2（2 つ以上の枝にまたがる）」・「どの枝にも結べない」・held の理由つき）"""
    if not t["branches"]:
        return NOWHERE
    text = "・".join(label(x) for x in t["branches"])
    if t["held"]:
        return f"{text}（{HELD}: {t['held']}）"
    return f"{text}（{MULTI}）" if len(t["branches"]) >= 2 else text


def lines(ties: list) -> list:
    """穴ごとの 1 行（`<key>: <名札>`）"""
    return [f"{t['key']}: {note(t)}" for t in ties or []]


def count_line(ties: list) -> str:
    """件数の 1 行（枝 1 つ・2 つ以上・結べない・裁定で外れた項目だけ・空でない組の数）"""
    s = spread(ties)
    return (f"{s['holes']} 件（枝 1 つ {s['single']}・{MULTI} {s['multi']}・{NOWHERE} {s['none']}・{HELD} {s['held']}。"
            f"穴の在る組 {s['groups']}）")
