"""承認済みの修正案の項目の範囲で、変わったパスを照らす決まりの 1 か所（修正案の範囲の照らし。依頼 218）。修正の受け付け
（blk-fix の planscope。単位に結べる行の照らしと欠けの照らしはそちら）と、手直しの受け付け（refix.accept_fix）が同じ決まりで使う。

語:
- 項目の範囲: allowed_paths の glob と、tests・rewrite_tests の id のファイル（planmarks.test_paths）
- out_of_scope: 範囲の中でも触らない物で、範囲より強い。ただし範囲の相談の合意でその項目の out_of_scope から外したパス（LIFTED。
  字のまま同じパスだけ）は、その項目では当たらない
- 合意（with_agreed）: 範囲の相談で修正案を書いた役が許したパス（conflict.agreed）を、その項目の allowed_paths に足す
- 許し（permit_paths）: テストの変更の許し（conflict.test_permits の範囲の行）のパスと、裁定の後なら直す裁定のパス
  （conflict.ruled_paths）。run の全部の項目の範囲の和に入る。out_of_scope には勝たない

- with_agreed(items, agreed)・inside(path, it)・oos_hit(path, items)・oos_hit_for(path, mine, items): 範囲の読み
- permit_paths(b, *, ruled, agreed): 許しのパスの並び
- outside(items, paths, permits, *, hint): 単位に結べない変わったパスの外れの行（全項目の範囲の和か許しに入らない・どれかの項目の
  out_of_scope に当たる）。hint なら、ほかの項目の out_of_scope に当たるがある項目の範囲には入るパスに OWNER_HINT を足す
- answer_tables(board_dir): 修正案の欄 structure の答えの要る行の表の並び（構造の目の汚れる行と世界の解の答えの要る行。修正案の
  受け付けと同じ run の中の案の直しが planmarks.structure_gaps に渡す。世界の解の行は項目に場所で結ばない）
- check_paths(b, paths, *, ruled, by): 盤面の承認済みの修正案の項目で paths を outside で照らす (行, 記録)。照らさない盤面（修正案の
  無い・範囲の欄の無い控え）は ([], {"checked": False, "why": 理由})。控えが凍結の印と食い違えば conflict.fields_broken の道
"""
from __future__ import annotations

import posixpath

import conflict
import planmarks
import stopby   # L1。止めの理由の住処
import structmark   # 構造の目の汚れる行（修正案の欄 structure の答えの要る行の表の 1 つ）
import worldmark    # 世界の解の答えの要る行（同じ表のもう 1 つ）

# 単位に結べない変わったパスがほかの項目の out_of_scope に当たり、ある項目の範囲には入る時に足す文（申告すればその項目で照らす）
OWNER_HINT = "（項目 {nums} の範囲には入る。その項目の単位の changes[].files に申告すれば、その項目の out_of_scope だけで照らす）"
LIFTED = "out_of_scope_lifted"   # with_agreed が項目の写しに足す欄: 合意でその項目の out_of_scope から外したパス（字のまま）
NO_PLAN = "承認済みの修正案か works の欄の控えが無い"
NO_SCOPE = "範囲の欄の無い控え（217 番の形の盤面）"


def globs(it: dict) -> list[str]:
    return [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g]


def _oos(it: dict) -> list[str]:
    return [r["glob"] for r in it.get("out_of_scope") or [] if isinstance(r, dict) and isinstance(r.get("glob"), str)
            and r["glob"]]


def inside(path: str, it: dict) -> bool:
    """path が項目の範囲（allowed_paths の glob・tests と rewrite_tests の id のファイル）に入るか"""
    return path in planmarks.test_paths(it) or any(planmarks.glob_match(path, g) for g in globs(it))


def answer_tables(board_dir) -> list:
    return [planmarks.design_need(structmark.dirty(board_dir)), worldmark.need(worldmark.stage_rows(board_dir) or [])]


def oos_hit(path: str, items: list[dict]):
    """path に当たる out_of_scope の最初の (項目, glob)。無ければ None。合意でその項目の out_of_scope から外したパス（LIFTED）は
    その項目では当たらない"""
    return next(((it, g) for it in items if path not in (it.get(LIFTED) or ()) for g in _oos(it)
                 if planmarks.glob_match(path, g)), None)


def oos_hit_for(path: str, mine: list[dict], items: list[dict]):
    """行の単位の項目（mine）から見た path の out_of_scope の当たり。mine のどれかが path を明示に許す（inside。allowed_paths・
    tests と rewrite_tests の id のファイル・with_agreed が足した合意）なら mine の out_of_scope だけで照らす（ほかの項目の
    out_of_scope は「その項目は触らない」で、許した項目の単位まで禁じない。run 249b）。許していなければ全部の項目で照らす。
    permits（run の全部に効く許し）は明示の許しに数えない"""
    return oos_hit(path, mine if any(inside(path, it) for it in mine) else items)


def oos_line(head: str, path: str, hit) -> str:
    return f"{head}{path} は項目 {hit[0].get('item')} の out_of_scope（{hit[1]}）に当たる"


def with_agreed(items: list[dict], agreed) -> list[dict]:
    """範囲の相談の合意（conflict.agreed の行 {item, granted_paths, granted_tests}）のパスを、その番号の項目の allowed_paths の
    後ろに足した写し。許したパスと許したテストの範囲のパスは、その項目の写しの LIFTED にも並べ、字のまま同じパスに限ってその項目の
    out_of_scope から外す（oos_hit。案を書いた役が自分の外した物を考え直して許した。持ち主 2026-10-07）。元の項目は変えない。
    ほかの項目は変えない。テストの書き換えの許しは conflict.test_permits が持つ"""
    more: dict = {}
    lift: dict = {}
    for r in agreed or []:
        n = str(r.get("item"))
        for p in r.get("granted_paths") or []:
            if isinstance(p, str) and p and p not in more.setdefault(n, []):
                more[n].append(p)
        tests = [got[0] for got in (conflict.parse_limit(t) for t in r.get("granted_tests") or [] if isinstance(t, str))
                 if got]
        for p in [*more.get(n, []), *tests]:
            p = posixpath.normpath(p)
            if p not in lift.setdefault(n, []):
                lift[n].append(p)
    out = []
    for it in items:
        n = str(it.get("item"))
        add = [p for p in more.get(n, []) if p not in globs(it)]
        if not add and not lift.get(n):
            out.append(it)
            continue
        out.append({**it, "allowed_paths": [*(it.get("allowed_paths") or []), *add],
                    LIFTED: [*(it.get(LIFTED) or []), *lift.get(n, [])]})
    return out


def permit_paths(b, *, ruled: bool, agreed=None) -> list[str]:
    """許しのパス: テストの変更の許し（conflict.test_permits の範囲の行。裁定の範囲は含めない）のパスと、ruled なら直す裁定の
    パス（conflict.ruled_paths）。欄の控えが凍結の印と食い違えば test_permits が盤面を止めて BoardGap"""
    out = []
    for p in conflict.test_permits(b, rulings=False, agreed_rows=agreed):
        got = conflict.parse_limit(p["limit"]) if "limit" in p else None   # 単位で許す行（案の直し）はパスを足さない
        if got and got[0] not in out:
            out.append(got[0])
    if ruled:
        out += [p for p in conflict.ruled_paths(b) if p not in out]
    return out


def outside(items: list[dict], paths, permits=(), *, hint: bool = True) -> list[str]:
    """単位に結べない変わったパス paths の外れの行（並びの順）: どれかの項目の out_of_scope に当たる（hint なら、当たらずに範囲に
    入れる項目を OWNER_HINT で名指す）か、全項目の範囲の和にも permits にも入らない。純粋な関数"""
    permits = set(permits)
    out = []
    for p in paths:
        hit = oos_hit(p, items)
        if hit:
            owners = [it for it in items if inside(p, it) and not oos_hit(p, [it])] if hint else []
            out.append(oos_line("", p, hit) + (OWNER_HINT.format(nums="・".join(str(it.get("item")) for it in owners))
                                               if owners else ""))
        elif not (p in permits or any(inside(p, it) for it in items)):
            out.append(f"{p} はどの項目の allowed_paths にも無い")
    return out


def approved(b, *, by: str = stopby.FIX):
    """(承認済みの修正案の項目, 照らさない理由)。項目が無い・範囲の欄の無い控えなら (None, 理由)。控えが凍結の印と食い違えば
    conflict.fields_broken の道（by の印で盤面を止めて BoardGap）"""
    try:
        items = planmarks.approved_items(b)
    except planmarks.FieldsBroken as e:   # 控えが壊れた時の 1 本の道（盤面を止めて BoardGap）
        raise conflict.fields_broken(b, e, by=by) from None
    if items is None:
        return None, NO_PLAN
    if not planmarks.scoped(items):
        return None, NO_SCOPE
    return items, ""


def check_paths(b, paths, *, ruled: bool = True, by: str = stopby.FIX) -> tuple[list[str], dict]:
    """盤面 b の承認済みの修正案の項目（範囲の相談の合意を足した物）で、単位に結べない変わったパス paths を outside で照らす
    （hint なし: 結ぶ単位を申告する欄の無い役）。返り (外れの行, 記録 {checked, items | why})"""
    items, why = approved(b, by=by)
    if items is None:
        return [], {"checked": False, "why": why}
    agreed = conflict.agreed(b)
    items = with_agreed(items, agreed)
    lines = outside(items, sorted(paths), permit_paths(b, ruled=ruled, agreed=agreed), hint=False)
    return lines, {"checked": True, "items": [it.get("item") for it in items]}
