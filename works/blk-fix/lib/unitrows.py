"""単位ごとの閉鎖の表（blk-fix の受け付けの前段。写しの受け付け recount.accept_fix の前に回す）。

閉鎖は機械の数え直しで決め、修正役の申告では決めない（CodeQL の variant analysis: 1 本の問いで同じ形を全部引き、その結果を数える）。
判定者の class_query（裁定 replace_query を受けた単位は置き換えた問い）を、写しの RL の _run_query が修正前の版と修正後の作業ツリーで
数え、defects なら修正後 0、population なら申告の site か単位の変更が覆う当たりの件数（covered）が母数に届くかで closed を決める。修正役の申告（closure.sites が覆う当たりの
件数・remaining・作り直した how）が数え直しと合わない形は、写しの fix_covers_open_units なら返答全体を拒む 4 つの形と同じで、ここでは
拒まずに表の discrepancies に記録する。写しに渡す返答は、その 4 つの拒否が発火しないように揃える（sites を母数に切る・空の
remaining に機械の記録を書く）。写しは変えない（板の POST_CHECKS は差し替えられない。ADR 0009・TA25 の置き場）。
申告の site は works だけの欄 path（recount.SITE_PATH）で問いの当たりのファイルに結び、site の件数でなく、site が在る当たりの
ファイルの件数（covered）を母数と比べる（site の件数と行数・ファイル数は単位が違う）。当たりの外の site（試験・文書など）は
不一致に数えず、表の out_of_query にパスを並べる。path の無い site は覆いに数えず、ファイルごとの数が引ければ path の在る site で
同じ規則で数える。ファイルごとの数が引けない・合計と合わない時は、修正で変わったファイルを path が指す site を数える（count が
files なら同じファイルは 1 件）。どちらも理由を discrepancies の頭に書く。
site が名指さない当たりのファイルも、その単位の files に在り、修正前の版から実際に変わったファイル（touched。writes.changed）なら
覆ったと数え、表の changed_cover にパスを並べる（覆いは機械が見た変更で決め、site の書き漏れで閉じていないとしない。
canary の run a2097fd6: 母数の問いの 3 ファイルを全部直して files に並べたのに site をコードの 1 か所だけ書き、閉じていないと数えた）。
site が名指す当たりのファイルも、修正前の版から実際に変わっていなければ覆ったと数えず、表の unchanged_sites にパスを並べる（問いの
種類に依らない。名指すだけで数えると、population の当たりの 5 ファイルを site に並べて 2 ファイルだけ変えた直しが閉じた）。変更が
読めなければ何も覆わず、理由 UNKNOWN_CHANGES を discrepancies の頭に書く。
写しの sites は additionalProperties: false なので、写しに渡す返答からは path を外す。

- build(changes, judged, *, count, blank, zero_keys, replaced, per_file, touched): 本体（盤面を読まない）。返り (写しに渡す changes, 表の行)
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
import writes  # noqa: E402
from leftovers import Unreadable  # noqa: E402

MIN_REMAINING = 10   # 写しの remaining の空同然の閾値（fix_covers_open_units の blank(…, 10)）
MACHINE_REMAINING = "機械の数え直しが申告と合わなかった（閉鎖は数え直しで決め、単位ごとの表に記録した）: "
COVERED_REMAINING = ("申告の site は {claimed} 件だが、修正で変わり、path が指すか単位の files に在る問いの当たりのファイルが"
                     "母数 {cap} のうち {covered} 件を覆う（写しは site の件数で数えるので、機械が書いた）")
UNKNOWN_CHANGES = "修正前の版からの変更が読めない（site の path が指すファイルも変わったと確かめられず、覆いに数えなかった）"
# 結べない時の数え方（_bind の理由の尾）。当たりのファイルが分からないので、覆いは修正で変わったファイルを path が指す site
UNBOUND_HOW = "（当たりのファイルが分からず、修正で変わったファイルを path が指す site を覆いに数えた。count が files なら同じファイルは 1 件）"
# path の無い site が在るがファイルごとの数は引けた時の理由の尾
PATHLESS_HOW = "（path の無い site は覆いに数えず、path の在る site と単位の files で数えた）"
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


def _bind(sites, cap, files, moved=None, declared=frozenset(), by_file=False):
    """site を問いの当たりのファイルに結ぶ ——（covered, 当たりの外のパス, 結べない理由, 変更で覆った当たりのファイル,
    site が名指したが変わっていない当たりのファイル, site を当たりのファイルに結べたか（path の在る site が在るか site が無く、
    ファイルごとの数が引けた））。files は ({パス: 件数}, 拒否文) か None。moved は修正前の版から変わった
    ファイル（_norm 済み。None は読めなかった）、declared はこの単位の files（_norm 済み）。当たりのファイルは、変わっていて、
    site が名指すか declared に在れば覆ったと数える（site が名指すだけでは数えない。名指さず declared で覆った物を 4 つ目、
    名指したが変わっていない物を 5 つ目に並べる）。moved が None なら何も覆わない。path の無い site はどれも覆いに数えず、
    ファイルごとの数が引ければ path の在る site で同じ規則で数え、理由（path が無い）を返す。ファイルごとの数が引けない・合計と
    合わない時は当たりのファイルが分からないので、修正で変わったファイルを path が指す site を数える（by_file（count が files）
    なら同じファイルは 1 件）。files が None（結ぶ口を渡さない呼び元。take は渡す）なら len(sites)"""
    if files is None:
        return len(sites), [], "", [], [], False
    paths = [_norm(s.get(recount.SITE_PATH)) for s in sites]
    named = [p for p in paths if p is not None]
    unpathed = f"path が無い site {len(paths) - len(named)} 件" if len(named) < len(paths) else ""
    got, why = files
    if why or not isinstance(got, dict):
        loose = f"ファイルごとに数えられない（{why}）"
    else:
        got = {_norm(k): v for k, v in got.items()}
        loose = "" if sum(got.values()) == cap else \
            f"ファイルごとの数が合計と合わない（ファイルごと {sum(got.values())}・合計 {cap}）"
    moved_ = moved or set()
    if loose:
        on = [p for p in named if p in moved_]
        covered = len(set(on)) if by_file else len(on)
        return covered, [], "・".join(filter(None, (unpathed, loose))) + UNBOUND_HOW, [], [], False
    hit = set(named)
    cover = {p for p in got if p in moved_ and (p in hit or p in declared)}
    unchanged = sorted(p for p in got if p in hit and p not in moved_) if moved is not None else []
    return (sum(got[p] for p in cover), sorted(hit - set(got)), unpathed + PATHLESS_HOW if unpathed else "",
            sorted(cover - hit), unchanged, bool(named) or not paths)


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


def build(changes, judged: dict, *, count, blank, zero_keys=(), replaced=None, per_file=None, touched=None):
    """changes の各行を数え直す。count(how, at_rev) -> (件数, 拒否文)（at_rev が真なら修正前の版）。per_file(how, at_rev) ->
    ({パス: 件数}, 拒否文) は site を当たりのファイルに結ぶ口（無ければ len(sites) で比べる）。touched は修正前の版から変わった
    ファイル（対象の根から。None は読めなかった）で、site の path が指すか行の files に在る当たりのファイルを、ここに在る物だけ
    覆ったと数える（None なら何も覆わない）。数えられない行・
    問いの無い行は表に載せず写しに任せる（写しが自分の文で拒む）。返り (写しに渡す changes, 表の行)"""
    replaced = replaced or {}
    moved = None if touched is None else {q for q in map(_norm, touched) if q}
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
        declared = {q for q in map(_norm, c.get("files") or []) if q}
        covered, out_of_query, unbound, changed_cover, unchanged_sites, by_hits = _bind(
            sites, cap, per_file(how, bool(total)) if per_file else None, moved, declared, how.get("count") == "files")
        bound = per_file is not None and by_hits   # path の無い site が在っても、ほかの site を結べた
        unknown = per_file is not None and moved is None   # 変更が読めず、覆いを数えていない（結べても結べなくても）
        remaining = not blank(cov.get("remaining"), MIN_REMAINING)
        jt = 0 if key in zero_keys else jq.get("total")
        narrowed = isinstance(jt, int) and not isinstance(jt, bool) and total < jt
        bad = ([unbound] if unbound else []) + ([UNKNOWN_CHANGES] if unknown else [])
        if not bound and claimed > cap:   # 結べた時は当たりの外の site を out_of_query に分ける。結べない時は申告の件数で比べる
            bad.append(f"申告の closure.sites {claimed} 件が母数 {cap} を超える")
        if covered < cap and not remaining and not unknown:   # 変更が読めない時は覆いを数えていない（理由は頭に在る）
            bad.append(f"母数 {cap} のうち修正で覆った当たりは {covered} 件で、remaining が無い")
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
        a_covered, a_changed_cover, a_unchanged = covered, changed_cover, unchanged_sites
        if auth != how:
            a_covered, _, a_unbound, a_changed_cover, a_unchanged, _ = _bind(
                sites, a_cap, per_file(auth, bool(a_total)) if per_file else None, moved, declared,
                isinstance(auth, dict) and auth.get("count") == "files")
            if a_unbound:   # closed を決める数が site の件数になった理由を黙って捨てない
                bad.append(f"判定者の問いで {a_unbound}")
        closed = a_after == 0 if counts == "defects" else min(a_covered, a_cap) >= a_cap
        rows.append({"unit_key": key, "how_from": how_from, "counts": counts, "total": a_total, "after": a_after,
                     "claimed": claimed, "covered": covered, "out_of_query": out_of_query, "bound": bound, "closed": closed,
                     "changed_cover": a_changed_cover, "unchanged_sites": a_unchanged, "discrepancies": bad})
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
    try:   # 受け付けの書き込みの照らし（check_writes）と同じ変更の集合。読めなければ何も覆わない（site の path も変わったと確かめられない）
        touched = writes.changed(repo, writes.base_rev(b))
    except Unreadable:
        touched = None
    out, rows = build(changes, judged, count=count, blank=R.blank, zero_keys=zero_keys, replaced=conflict.replaced_queries(b),
                      per_file=per_file, touched=touched)
    return {**reply, "changes": out}, rows
