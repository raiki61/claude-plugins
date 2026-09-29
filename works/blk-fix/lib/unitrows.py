"""単位ごとの閉鎖の表（blk-fix の受け付けの前段。写しの受け付け recount.accept_fix の前に回す）。

閉鎖は機械の数え直しで決め、修正役の申告では決めない（CodeQL の variant analysis: 1 本の問いで同じ形を全部引き、その結果を数える）。
判定者の class_query（裁定 replace_query を受けた単位は置き換えた問い）を、写しの RL の _run_query が修正前の版と修正後の作業ツリーで
数え、defects なら修正後 0、population なら申告の site が母数に届くかで closed を決める。修正役の申告（closure.sites が覆う当たりの
件数・remaining・作り直した how）が数え直しと合わない形は、写しの fix_covers_open_units なら返答全体を拒む 4 つの形と同じで、ここでは
拒まずに表の discrepancies に記録する。写しに渡す返答は、その 4 つの拒否が発火しないように揃える（sites を母数に切る・空の
remaining に機械の記録を書く）。写しは変えない（板の POST_CHECKS は差し替えられない。ADR 0009・TA25 の置き場）。
申告の site は works だけの欄 path（recount.SITE_PATH）で問いの当たりのファイルに結び、site の件数でなく、site が在る当たりの
ファイルの件数（covered）を母数と比べる（site の件数と行数・ファイル数は単位が違う）。当たりの外の site（試験・文書など）は
不一致に数えず、表の out_of_query にパスを並べる。結べない時は len(sites) で比べ、理由を discrepancies の頭に書く。
写しの sites は additionalProperties: false なので、写しに渡す返答からは path を外す。

- build(changes, judged, *, count, blank, zero_keys, replaced, per_file): 本体（盤面を読まない）。返り (写しに渡す changes, 表の行)
- file_counts(how, root, rev): 問いの当たりをファイルごとに数える（argv は写しの count_argv、走らせ方は写しの _grep）
- take(reply, b, repo): 盤面から材料を引いて build を当てる。返り (写しに渡す返答, 表の行)。数える問いが 1 つも無ければ返答をそのまま
"""
import copy
import pathlib
import posixpath
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import board as _board  # noqa: E402
import conflict  # noqa: E402
import engine.util as _util  # noqa: E402  （board が写しの engine を sys.path に足す）
import recount  # noqa: E402

MIN_REMAINING = 10   # 写しの remaining の空同然の閾値（fix_covers_open_units の blank(…, 10)）
MACHINE_REMAINING = "機械の数え直しが申告と合わなかった（閉鎖は数え直しで決め、単位ごとの表に記録した）: "
COVERED_REMAINING = ("申告の site は {claimed} 件だが、path が指す問いの当たりのファイルが母数 {cap} のうち {covered} 件を覆う"
                     "（写しは site の件数で数えるので、機械が書いた）")
RULING_REMAINING = "裁定 {id} が判定者の問いを置き換えた（判定者の問いは直した後の正しい形にも当たった）"


def _sites(c) -> list:
    return [s for s in ((c.get("closure") or {}).get("sites") or []) if isinstance(s, dict)]


def _unpathed(c):
    """写しに渡す形: closure.sites から works だけの欄 path を外した写し"""
    if not isinstance(c, dict) or not any(recount.SITE_PATH in s for s in _sites(c)):
        return c
    c2 = copy.deepcopy(c)
    c2["closure"]["sites"] = [{k: v for k, v in s.items() if k != recount.SITE_PATH} if isinstance(s, dict) else s
                              for s in c2["closure"]["sites"]]
    return c2


def _norm(p):
    """対象の根からの相対パスに揃えた形。空・根の外（絶対パス・..）は None"""
    if not isinstance(p, str) or not p.strip():
        return None
    q = posixpath.normpath(p.strip().replace("\\", "/"))
    return None if q.startswith("/") or q == ".." or q.startswith("../") or q == "." else q


def _bind(sites, cap, files):
    """site を問いの当たりのファイルに結ぶ ——（covered, 当たりの外のパス, 結べない理由）。files は ({パス: 件数}, 拒否文) か None。
    結べなければ covered は len(sites)（今の数え方）"""
    if files is None:
        return len(sites), [], ""
    paths = [_norm(s.get(recount.SITE_PATH)) for s in sites]
    unpathed = sum(p is None for p in paths)
    if unpathed:
        return len(sites), [], f"path が無い site {unpathed} 件（今の数え方で比べた）"
    got, why = files
    if why or not isinstance(got, dict):
        return len(sites), [], f"ファイルごとに数えられない（{why}）（今の数え方で比べた）"
    got = {_norm(k): v for k, v in got.items()}
    if sum(got.values()) != cap:
        return len(sites), [], f"ファイルごとの数が合計と合わない（ファイルごと {sum(got.values())}・合計 {cap}）（今の数え方で比べた）"
    hit = set(paths)
    return sum(n for p, n in got.items() if p in hit), sorted(hit - set(got)), ""


def file_counts(how, root, rev=None, timeout=60):
    """問いの当たりのファイルごとの数 ——（{パス: 件数}, ""）か（None, 理由）。count: files はファイル 1 本を 1 と数える。
    写しの _run_query の予算（count-budget.json）と控え（count-cache.json）は通らない（写しは rules-copy の下で works から載せられない）。
    1 単位 1 回だけ走る"""
    argv, why = _util.count_argv(how, rev)
    if why:
        return None, why
    # 引用符と 8 進に崩したパス（core.quotePath の既定）は site の path と一致しないので、生のパスで出させる
    out, why = _util._grep([argv[0], "-c", "core.quotePath=false", *argv[1:]], str(root), timeout)
    if why:
        return None, why
    got = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        if rev and line.startswith(f"{rev}:"):
            line = line[len(rev) + 1:]
        if how["count"] == "files":
            got[line] = 1
            continue
        path, _, n = line.rpartition(":")
        if not n.strip().isdigit():
            return None, f"-c の出力が `…:数` の形でない（{line[:60]!r}）"
        got[path] = int(n)
    return got, ""


def build(changes, judged: dict, *, count, blank, zero_keys=(), replaced=None, per_file=None):
    """changes の各行を数え直す。count(how, at_rev) -> (件数, 拒否文)（at_rev が真なら修正前の版）。per_file(how, at_rev) ->
    ({パス: 件数}, 拒否文) は site を当たりのファイルに結ぶ口（無ければ len(sites) で比べる）。数えられない行・問いの無い行は
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
            out.append(_unpathed(c))
            continue
        total, why = count(how, True)
        after, why2 = count(how, False) if not why else (None, why)
        if why or why2:
            out.append(_unpathed(c))
            continue
        sites = _sites(c)
        claimed = len(sites)
        cap = total if total else after
        covered, out_of_query, unbound = _bind(sites, cap, per_file(how, bool(total)) if per_file else None)
        bound = per_file is not None and not unbound
        remaining = not blank(cov.get("remaining"), MIN_REMAINING)
        jt = 0 if key in zero_keys else jq.get("total")
        narrowed = isinstance(jt, int) and not isinstance(jt, bool) and total < jt
        bad = [unbound] if unbound else []
        if covered > cap:   # 結べた時は covered が母数を超えない。結べない時の今の数え方にだけ立つ
            bad.append(f"申告の closure.sites {covered} 件が母数 {cap} を超える")
        if covered < cap and not remaining:
            bad.append(f"母数 {cap} のうち申告の site が覆うのは {covered} 件で、remaining が無い")
        if narrowed and not remaining and not rq:
            bad.append(f"問いが判定者の母数 {jt} より狭い（修正前 {total}）のに remaining が無い")
        if counts == "defects" and after and min(covered, cap) >= total and not remaining:
            bad.append(f"母数 {total} を全部塞いだと申告したが、修正後も {after} 件を数える")
        # closed を決めるのは判定者の問い（か裁定が置き換えた問い）。修正役が作り直した how は写しの数え合わせにだけ使う
        auth = rq["how"] if rq else jq.get("how") or how
        a_total, a_after = (total, after) if auth == how else (count(auth, True)[0], count(auth, False)[0])
        if a_total is None or a_after is None:
            a_total, a_after = total, after
        a_cap = a_total if a_total else a_after
        closed = a_after == 0 if counts == "defects" else min(claimed, a_cap) >= a_cap
        rows.append({"unit_key": key, "how_from": how_from, "counts": counts, "total": a_total, "after": a_after,
                     "claimed": claimed, "covered": covered, "out_of_query": out_of_query, "bound": bound, "closed": closed,
                     "discrepancies": bad})
        c2 = copy.deepcopy(c)
        cov2 = {**cov, "how": how}
        if claimed > cap:   # 写しの拒否は len(sites) で数える。当たりに結べた site・赤を見た site を先に残す
            c2.setdefault("closure", {})["sites"] = sorted(
                sites, key=lambda s: (not bound or _norm(s.get(recount.SITE_PATH)) in out_of_query, not s.get("red_seen")))[:cap]
        # 表の discrepancies は covered で決めるが、写しは len(sites) で拒むので、写しの側の揃えは len(sites) の式で決める
        if not remaining and (bad or (rq and narrowed) or claimed < cap):
            cov2["remaining"] = (MACHINE_REMAINING + " / ".join(bad) if bad else RULING_REMAINING.format(id=rq["id"]) if rq and narrowed
                                 else COVERED_REMAINING.format(claimed=claimed, cap=cap, covered=covered))
        c2["coverage"] = cov2
        out.append(_unpathed(c2))
    return out, rows


def take(reply: dict, b, repo):
    """盤面の判定者の問い・置き換えた問い・engine_zero と写しの RL の _run_query で build を当てる"""
    changes = reply.get("changes") or []
    judged = {u.get("key"): u.get("class_query") or {}
              for u in ((b.record.get("process") or {}).get("diagnosis") or {}).get("units", []) if isinstance(u, dict)}
    if not any(isinstance(c, dict) and ((judged.get(c.get("unit_key")) or {}).get("how") or (c.get("coverage") or {}).get("how"))
               for c in changes):
        return {**reply, "changes": [_unpathed(c) for c in changes]} if changes else reply, []
    R = _board.rules_module(pathlib.Path(b.state["graph"]))
    rev = (b.state.get("inputs") or {}).get("review_rev")
    zero = b.loop_state.get("engine_zero") or {}
    zero_keys = set(zero.get("keys") or []) if zero.get("round") == b.round else set()

    def count(how, at_rev):
        if at_rev:
            return R._run_query(b, "閉鎖の数え直し（修正前）", how, str(repo), rev=rev)
        return R._run_query(b, "閉鎖の数え直し（修正後）", {**how, "untracked": True}, str(repo), probe=False)

    def per_file(how, at_rev):
        return file_counts(how, repo, rev) if at_rev else file_counts({**how, "untracked": True}, repo)
    out, rows = build(changes, judged, count=count, blank=R.blank, zero_keys=zero_keys, replaced=conflict.replaced_queries(b),
                      per_file=per_file)
    return {**reply, "changes": out}, rows
