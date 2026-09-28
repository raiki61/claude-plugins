"""単位ごとの閉鎖の表（blk-fix の受け付けの前段。写しの受け付け recount.accept_fix の前に回す）。

閉鎖は機械の数え直しで決め、修正役の申告では決めない（CodeQL の variant analysis: 1 本の問いで同じ形を全部引き、その結果を数える）。
判定者の class_query（裁定 replace_query を受けた単位は置き換えた問い）を、写しの RL の _run_query が修正前の版と修正後の作業ツリーで
数え、defects なら修正後 0、population なら申告の site が母数に届くかで closed を決める。修正役の申告（closure.sites の件数・
remaining・作り直した how）が数え直しと合わない形は、写しの fix_covers_open_units なら返答全体を拒む 4 つの形と同じで、ここでは
拒まずに表の discrepancies に記録する。写しに渡す返答は、その 4 つの拒否が発火しないように揃える（sites を母数に切る・空の
remaining に機械の記録を書く）。写しは変えない（板の POST_CHECKS は差し替えられない。ADR 0009・TA25 の置き場）。

- build(changes, judged, *, count, blank, zero_keys, replaced): 本体（盤面を読まない）。返り (写しに渡す changes, 表の行)
- take(reply, b, repo): 盤面から材料を引いて build を当てる。返り (写しに渡す返答, 表の行)。数える問いが 1 つも無ければ返答をそのまま
"""
import copy
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import board as _board  # noqa: E402
import conflict  # noqa: E402

MIN_REMAINING = 10   # 写しの remaining の空同然の閾値（fix_covers_open_units の blank(…, 10)）
MACHINE_REMAINING = "機械の数え直しが申告と合わなかった（閉鎖は数え直しで決め、単位ごとの表に記録した）: "
RULING_REMAINING = "裁定 {id} が判定者の問いを置き換えた（判定者の問いは直した後の正しい形にも当たった）"


def _sites(c) -> list:
    return [s for s in ((c.get("closure") or {}).get("sites") or []) if isinstance(s, dict)]


def build(changes, judged: dict, *, count, blank, zero_keys=(), replaced=None):
    """changes の各行を数え直す。count(how, at_rev) -> (件数, 拒否文)（at_rev が真なら修正前の版）。数えられない行・問いの無い行は
    表に載せず写しに任せる（写しが自分の文で拒む）。返り (写しに渡す changes, 表の行)"""
    replaced = replaced or {}
    out, rows = [], []
    for c in changes:
        if not isinstance(c, dict):
            out.append(c)
            continue
        key = c.get("unit_key")
        jq = judged.get(key) or {}
        cov = dict(c.get("coverage") or {})
        rq = replaced.get(key)
        how, how_from = (rq["how"], f"裁定 {rq['id']}") if rq else \
            (cov.get("how"), "修正役") if cov.get("how") else (jq.get("how"), "判定者")
        counts = (rq or {}).get("counts") or jq.get("counts") or cov.get("counts")
        if not how or counts not in ("defects", "population"):
            out.append(c)
            continue
        total, why = count(how, True)
        after, why2 = count(how, False) if not why else (None, why)
        if why or why2:
            out.append(c)
            continue
        sites = _sites(c)
        claimed = len(sites)
        cap = total if total else after
        remaining = not blank(cov.get("remaining"), MIN_REMAINING)
        jt = 0 if key in zero_keys else jq.get("total")
        narrowed = isinstance(jt, int) and not isinstance(jt, bool) and total < jt
        bad = []
        if claimed > cap:
            bad.append(f"申告の closure.sites {claimed} 件が母数 {cap} を超える")
        if claimed < cap and not remaining:
            bad.append(f"母数 {cap} のうち申告の site は {claimed} 件で、remaining が無い")
        if narrowed and not remaining and not rq:
            bad.append(f"問いが判定者の母数 {jt} より狭い（修正前 {total}）のに remaining が無い")
        if counts == "defects" and after and min(claimed, cap) >= total and not remaining:
            bad.append(f"母数 {total} を全部塞いだと申告したが、修正後も {after} 件を数える")
        # closed を決めるのは判定者の問い（か裁定が置き換えた問い）。修正役が作り直した how は写しの数え合わせにだけ使う
        auth = rq["how"] if rq else jq.get("how") or how
        a_total, a_after = (total, after) if auth == how else (count(auth, True)[0], count(auth, False)[0])
        if a_total is None or a_after is None:
            a_total, a_after = total, after
        a_cap = a_total if a_total else a_after
        closed = a_after == 0 if counts == "defects" else min(claimed, a_cap) >= a_cap
        rows.append({"unit_key": key, "how_from": how_from, "counts": counts, "total": a_total, "after": a_after,
                     "claimed": claimed, "closed": closed, "discrepancies": bad})
        c2 = copy.deepcopy(c)
        cov2 = {**cov, "how": how}
        if claimed > cap:
            c2.setdefault("closure", {})["sites"] = sorted(sites, key=lambda s: not s.get("red_seen"))[:cap]
        if not remaining and (bad or (rq and narrowed)):
            cov2["remaining"] = MACHINE_REMAINING + " / ".join(bad) if bad else RULING_REMAINING.format(id=rq["id"])
        c2["coverage"] = cov2
        out.append(c2)
    return out, rows


def take(reply: dict, b, repo):
    """盤面の判定者の問い・置き換えた問い・engine_zero と写しの RL の _run_query で build を当てる"""
    changes = reply.get("changes") or []
    judged = {u.get("key"): u.get("class_query") or {}
              for u in ((b.record.get("process") or {}).get("diagnosis") or {}).get("units", []) if isinstance(u, dict)}
    if not any(isinstance(c, dict) and ((judged.get(c.get("unit_key")) or {}).get("how") or (c.get("coverage") or {}).get("how"))
               for c in changes):
        return reply, []
    R = _board.rules_module(pathlib.Path(b.state["graph"]))
    rev = (b.state.get("inputs") or {}).get("review_rev")
    zero = b.loop_state.get("engine_zero") or {}
    zero_keys = set(zero.get("keys") or []) if zero.get("round") == b.round else set()

    def count(how, at_rev):
        if at_rev:
            return R._run_query(b, "閉鎖の数え直し（修正前）", how, str(repo), rev=rev)
        return R._run_query(b, "閉鎖の数え直し（修正後）", {**how, "untracked": True}, str(repo), probe=False)
    out, rows = build(changes, judged, count=count, blank=R.blank, zero_keys=zero_keys, replaced=conflict.replaced_queries(b))
    return {**reply, "changes": out}, rows
