"""works/dev/canary_check.py — canary の run（dev/canary.sh）が、狙った道を本当に通ったかを、終わった run の記録から出す（開発の殻。
読むだけで何も書かない）。

  python3 canary_check.py <canary の置き場> [<run-id>] [--json]
  python3 canary_check.py --db <archon.db> --run <run-id> [--board <盤面>] [--diff <差分>] [--json]

置き場の形は canary.sh が作る物（home/archon-home/archon.db・home/runs/<run-id>.json・home/diffs/run-<id>.diff）。run-id を省けば
home/runs の一番新しい控えの run。盤面は Archon の run の行の output_root の下の artifacts/runs/<id>/board（--board で替える）。
db は読むだけで開く（?mode=ro）。盤面と run ごとの置き場（盤面の隣の run-place）はファイルを読むだけ。

見る道（canary.sh の頭の (a)〜(d)）と、通ったと言う決まり:
- (a) parallel（別のファイルの 2 項目以上の並べ）: no の時は、TDD の輪が振り分けの後に並べなかった理由（盤面の trace の
  lanes_skipped。節 tdd-step が積む {reason, why, loop}。tddlanes.SKIP_OP）と、修正役の並べを切らなかった理由（trace の
  fix_lanes_planted の lanes 0 の行の why。節 fix-fork が積む。fixlanes.PLANTED_OP）を why に足し、出力の lanes_skipped・
  fix_lanes_skipped に並べる。
  通ったと言う決まり: TDD の輪の並べの周の目録が枝 2 本以上で、枝の輪（節の名の最後が
  tdd-lane-loop-<n>・tdd-lane-prep-<n>・tdd-lane-<n>・tdd-lane-step-<n>。docs/plans/2026-10-07-lane-nodes.md）が同時に 2 本以上
  走った。枝ごとの区間は枝 n の節の node_started の最初から終わり（node_completed・node_failed）の最後まで。または修正役の並べの
  締めの trace の行（fix_lanes_settled。docs/plans/2026-10-07-fix-lane-nodes.md）の枝が 2 本以上で、修正役の並べの枝の輪（節の名の
  最後が fix-lane-loop-<n>・fix-lane-prep-<n>・fix-lane-<n>・fix-lane-consult-<n>・plan-answer-lane-<n>・fix-lane-consult-check-<n>・
  fix-lane-step-<n>）が同時に 2 本以上走った。前の形の run（修正役が Agent で項目の下請けを並べた版）は、修正役の締めの
  trace の行（units_settled）が 2 項目以上を当てて、修正役の節（最後が fix）の下請けが同時に 2 本以上走った、でも数える。下請けの
  同時は Archon の出来事 task_activity（task_type local_agent の started と、同じ task_id の completed・failed・stopped）の
  created_at の区間の重なり（秒の粒。端が触れるだけは重ならない。枝の区間も同じ）
- (b) overlap（同じファイルの枝の合わせ）: TDD の輪の締めの重なりのファイル（lanes.shared）か、枝の合わせの結末に union が在る、
  または修正役の並べの締めの行（fix_lanes_settled。前の形の run は units_settled）の shared・union が空でない。同じファイルを見込んだ組（lanes.expect）か、修正案の 2 項目以上が触ってよい
  同じファイル（案の重なり。allowed_paths と tests・rewrite_tests の id のファイルの和を字のまま比べる）が在るのに、合わせが字・意味の
  食い違いで戻った・合わせの記録が無いなら attempted。案の項目どうしが同じファイルを共にしなければ no（計画役が同じファイルの単位を
  1 項目にまとめたか、テストを別のファイルに置いた）
- (c) consult（範囲の相談）: 相談の記録（盤面の trace の plan_scope_asked。修正の輪の確かめの節 fix-consult-check が書く。
  前の形 askplan.py（0.2.32〜0.2.35）の run は、まだ写していない run-place/<scope>/ask-plan/exchanges.jsonl も読む）に
  answered の行が在る。refused・invalid・unavailable だけなら attempted（断った行の訳 why_refused を添える。0.2.35 までの
  版は修正案が out_of_scope に名指したパスも断った。0.2.36 からは断らずに答えの節へ回す）
- (d) replan（run の中の案の直し。起きなくてよい）: trace の replan_state・plan_amended・conflict_parked・conflict_ruled の数を出すだけ
ほか: 報告の冒頭の結末の語（fixed・round_limit など）、修正案の項目（盤面の plan-fields.json。番号は 1 始まりの並び）ごとの
allowed_paths・テストのファイル・その項目の単位を持つ TDD の輪の枝が実際に変えたファイル（当てる時に控えた枝の差分
tdd-<k>/lanes/item-<n>.patch）、節の同時の最大（node_started から node_completed・node_failed まで）、AI の節の費用の和
（node_completed の data.node.kind が agent の物。輪の節 loop_group は中の和なので足さない。読み方は report._event_cost）と費用の
取れない節の名と理由（Archon が costUsd を source unavailable で記録した節。和に入らないので、和は下限）、出来事の最初から
最後までの分、差分が変えたファイル。

終了コード: 0 = (a)(b)(c) が全部 yes・1 = どれかが yes でない・2 = 引数の誤り・db が開けない・run が無い（標準エラーに 1 行）。
出力は辞書を書いた順（同じ入力なら同じ出力）。時刻は記録の物だけを使う。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sqlite3
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

PACK = pathlib.Path(__file__).resolve().parents[1]
for _p in (PACK / "blk-fix" / "lib", PACK / ".shared" / "core"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import conflict  # noqa: E402  trace の行の語（ASKED_OP・PARK_OP・RULE_OP・REPLAN_OP）
import fixlanes  # noqa: E402  修正役の並べの締めの trace の行の語（SETTLED_OP）・合わせの結末の語（MERGED）
import gatemarks  # noqa: E402  報告の冒頭の起きたことの行の頭（HAPPENED）
import consult  # noqa: E402    範囲の相談の行の status の語（ANSWERED）
import planmarks  # noqa: E402  修正案の欄の控え（FIELDS_FILE・AMEND_OP）
import report  # noqa: E402    節の名の最後の語（_step_name）と費用の読み（_event_cost）
import tddlanes  # noqa: E402  合わせの結末の語（UNION・CLASH・SEMANTIC）

YES, ATTEMPTED, NO = "yes", "attempted", "no"
LOCAL_AGENT = "local_agent"
TASK_ENDS = ("completed", "failed", "stopped")
NODE_ENDS = ("node_completed", "node_failed")
AI_KIND = "agent"
FIX_NODE = "fix"
LANE_NODE = re.compile(r"tdd-lane-(?:loop-|prep-|step-)?(\d+)")   # 枝の輪とその中の節の名（最後の 1 語）。番号は枝
# 修正役の並べの枝の輪とその中の節の名（最後の 1 語。docs/plans/2026-10-07-fix-lane-nodes.md）。番号は枝
FIX_LANE_NODE = re.compile(r"(?:fix-lane-(?:loop-|prep-|step-|consult-check-|consult-)?|plan-answer-lane-)(\d+)")
OLD_UNITS_OP = "units_settled"   # 前の形の修正役の締めの trace の行（0.2.36 まで。修正役が Agent で項目の下請けを並べた run）
OLD_ASK_PLACE, OLD_ASK_LOG = "ask-plan", "exchanges.jsonl"   # 前の形 askplan.py の run ごとの置き場の相談の記録（受け付けが trace へ写す前）
REPLAN_OPS = (conflict.REPLAN_OP, planmarks.AMEND_OP, conflict.PARK_OP, conflict.RULE_OP)
USAGE = ("usage: canary_check.py <canary の置き場> [<run-id>] [--json] | "
         "canary_check.py --db <archon.db> --run <run-id> [--board <盤面>] [--diff <差分>] [--json]")


class Refused(Exception):
    """引数・db・run の誤り（終了コード 2）"""


# ---------------------------------------------------------------- 読む口
def _secs(at) -> float | None:
    try:
        return datetime.datetime.fromisoformat(str(at).replace(" ", "T").rstrip("Z")).timestamp()
    except (TypeError, ValueError):
        return None


def read_run(db, run_id: str) -> tuple[dict, list]:
    """(run の行 {status, started_at, completed_at, output_root}, 出来事 [{event_type, step_name, data, at}]（event_order の順）)"""
    db = pathlib.Path(db)
    if not db.is_file():
        raise Refused(f"archon.db が無い（{db}）")
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise Refused(f"archon.db {db} を開けない（{e}）") from None
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(remote_agent_workflow_runs)")]
        want = [c for c in ("status", "started_at", "completed_at", "output_root") if c in cols]
        got = con.execute(f"SELECT {', '.join(want)} FROM remote_agent_workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if got is None:
            raise Refused(f"archon.db {db} に run {run_id} が無い")
        row = {c: got[n] for n, c in enumerate(want)}
        rows = con.execute("SELECT event_type, step_name, data, created_at FROM remote_agent_workflow_events "
                           "WHERE workflow_run_id = ? ORDER BY event_order, rowid", (run_id,)).fetchall()
    except sqlite3.Error as e:
        raise Refused(f"archon.db {db} を読めない（{e}）") from None
    finally:
        con.close()
    out = []
    for kind, step, data, at in rows:
        try:
            doc = json.loads(data or "{}")
        except ValueError:
            doc = {}
        out.append({"event_type": kind or "", "step_name": step or "", "data": doc if isinstance(doc, dict) else {},
                    "at": _secs(at)})
    return row, out


def _json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _jsonl(path) -> list:
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


# ---------------------------------------------------------------- 盤面
def plan_items(board: pathlib.Path) -> list:
    """承認済みの修正案の欄の控え（plan-fields.json）の項目 [{item, route, unit_keys, allowed_paths, test_files, files}]。
    test_files は tests・rewrite_tests の id のファイル（planmarks.test_paths。書いてよい範囲に入る）、files は allowed_paths と
    test_files の和（項目が触ってよいファイル。glob は字のまま）。無ければ []"""
    doc = _json(board / planmarks.FIELDS_FILE)
    fields = doc.get("fields") if isinstance(doc, dict) else None
    out = []
    for n, f in enumerate(fields if isinstance(fields, list) else [], 1):
        f = f if isinstance(f, dict) else {}
        paths = f.get("allowed_paths")
        paths = [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
        keys = f.get("unit_keys")
        tests = planmarks.test_paths(f)
        out.append({"item": n, "route": f.get("route", ""),
                    "unit_keys": [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else [],
                    "allowed_paths": paths, "test_files": tests, "files": sorted(set(paths) | set(tests))})
    return out


def planned_overlap(items: list) -> dict:
    """修正案の 2 項目以上が触ってよいファイル（files。字のまま比べる）{ファイル: [項目の番号]}。(b) の前提が案に在るか"""
    seen = {}
    for it in items:
        for f in it["files"]:
            seen.setdefault(f, []).append(it["item"])
    return {f: ns for f, ns in sorted(seen.items()) if len(ns) > 1}


def _lane_items(keys, items: list) -> list:
    """枝の単位の鍵を持つ修正案の項目の番号"""
    return [it["item"] for it in items if set(it["unit_keys"]) & set(keys or [])]


def tdd_lanes(board: pathlib.Path, items: list = ()) -> list:
    """TDD の輪の並べの周ごと（盤面の tdd-<k>/state.json の lanes。並べた輪だけ）[{loop, lanes, rows, units, shared, expect}]。
    rows は枝ごと {lane, items（枝の単位を持つ修正案の項目）, files（当てる時に控えた枝の差分 tdd-<k>/lanes/item-<n>.patch の
    ファイル。控えが無ければ None）}"""
    out = []
    for st_path in sorted(board.glob("tdd-*/state.json")) + sorted(board.glob("*/tdd-*/state.json")):
        st = _json(st_path)
        lanes = st.get("lanes") if isinstance(st, dict) else None
        if not isinstance(lanes, dict) or not lanes.get("rows"):
            continue
        rows = []
        for r in lanes["rows"]:
            r = r if isinstance(r, dict) else {}
            n = r.get("n")
            rows.append({"lane": n, "items": _lane_items(r.get("unit_keys"), list(items)),
                         "files": diff_files(st_path.parent / tddlanes.KEPT / f"item-{n}.patch")})
        out.append({"loop": str(st_path.parent.relative_to(board)), "lanes": len(lanes["rows"]), "rows": rows,
                    "units": [{k: u.get(k) for k in ("lane", "outcome", "merge")} for u in lanes.get("out") or []
                              if isinstance(u, dict)],
                    "shared": list(lanes.get("shared") or []), "expect": list(lanes.get("expect") or [])})
    return out


def consults(board: pathlib.Path, trace: list) -> list:
    """範囲の相談の行（trace の ASKED_OP と、前の形の run-place のまだ写していない記録）[{scope, id, item, status, decision, paths,
    granted_paths, why_refused, settled}]。同じ scope と id は trace の行だけ"""
    rows, seen = [], set()
    for r in trace:
        if r.get("op") == conflict.ASKED_OP:
            seen.add((r.get("scope", ""), r.get("id")))
            rows.append((r.get("scope", ""), r, True))
    place = board.parent / "run-place"
    for log in sorted(place.glob(f"**/{OLD_ASK_PLACE}/{OLD_ASK_LOG}")):
        scope = "/".join(log.parent.parent.relative_to(place).parts)
        for r in _jsonl(log):
            if (scope, r.get("id")) not in seen:
                seen.add((scope, r.get("id")))
                rows.append((scope, r, False))
    return [{"scope": s, "id": r.get("id"), "item": r.get("item"), "status": r.get("status", ""),
             "decision": r.get("decision", ""), "paths": r.get("paths") or [], "granted_paths": r.get("granted_paths") or [],
             "why_refused": r.get("why_refused") or "", "settled": settled} for s, r, settled in rows]


def outcome(board: pathlib.Path) -> str:
    """報告（report.md）の冒頭の起きたことの行（gatemarks.HAPPENED）の括弧の結末の語（report.OUTCOMES）。報告が無い・読めなければ空"""
    try:
        lines = (board / report.REPORT_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    for line in lines[:10]:
        if line.startswith(gatemarks.HAPPENED):
            return next((w for w in report.OUTCOMES if f"（{w}）" in line), "")
    return ""


# ---------------------------------------------------------------- 出来事
def _peak(spans: list) -> tuple[int, list]:
    """区間 [(名, 始め, 終わり)] の同時の最大と、その時に重なっていた名の並び（端が触れるだけは重ならない）"""
    best, names = 0, []
    for _, s, _ in spans:
        live = [n for n, a, b in spans if a <= s < b]
        if len(live) > best:
            best, names = len(live), live
    return best, names


def agent_spans(events: list) -> dict:
    """節（step_name）ごとの下請けの同時の最大 {step_name: {tasks, parallel}}（終わりの行の無い下請けは数えない）"""
    starts, spans = {}, {}
    for e in events:
        if e["event_type"] != "task_activity" or e["at"] is None:
            continue
        d = e["data"]
        tid, act = d.get("task_id"), d.get("activity")
        key = (e["step_name"], tid)
        if act == "started" and d.get("task_type") == LOCAL_AGENT and key not in starts:
            starts[key] = e["at"]
        elif act in TASK_ENDS and key in starts:
            spans.setdefault(e["step_name"], {}).setdefault(tid, (tid, starts[key], e["at"]))
    out = {}
    for step in sorted(spans):
        got = list(spans[step].values())
        out[step] = {"tasks": len(got), "parallel": _peak(got)[0]}
    return out


def lane_peak(events: list, pattern=LANE_NODE) -> dict:
    """枝の輪の同時の最大 {lanes, parallel}（既定は TDD の輪の枝。修正役の並べの枝は FIX_LANE_NODE）。枝 n の区間は枝 n の節
    （pattern）の started の最初から終わりの最後まで（輪の節と中の節の区間が重なっても 1 本に数える）。終わりの行の無い枝は数えない"""
    first, last = {}, {}
    for e in events:
        m = pattern.fullmatch(report._step_name(e["step_name"]))
        if not m or e["at"] is None:
            continue
        n = int(m.group(1))
        if e["event_type"] == "node_started":
            first[n] = min(first.get(n, e["at"]), e["at"])
        elif e["event_type"] in NODE_ENDS:
            last[n] = max(last.get(n, e["at"]), e["at"])
    spans = [(n, first[n], last[n]) for n in sorted(first) if n in last]
    return {"lanes": len(spans), "parallel": _peak(spans)[0]}


def node_peak(events: list) -> dict:
    """節の同時の最大 {parallel, nodes}（同じ節の名の started と終わりを順に組む）"""
    open_, spans = {}, []
    for e in events:
        if e["at"] is None:
            continue
        if e["event_type"] == "node_started":
            open_.setdefault(e["step_name"], []).append(e["at"])
        elif e["event_type"] in NODE_ENDS and open_.get(e["step_name"]):
            spans.append((e["step_name"], open_[e["step_name"]].pop(0), e["at"]))
    best, names = _peak(spans)
    return {"parallel": best, "nodes": sorted(names)}


def spend(events: list) -> dict:
    """AI の節の費用の和と取れない節の数とその節（節の名の最後の語と取れない理由）・出来事の最初から最後までの分"""
    total, missing = 0.0, []
    for e in events:
        if e["event_type"] == "node_completed" and (e["data"].get("node") or {}).get("kind") == AI_KIND:
            v, why = report._event_cost(e)
            if v is None:
                missing.append({"node": report._step_name(e["step_name"]), "why": why})
            else:
                total += v
    ats = [e["at"] for e in events if e["at"] is not None]
    return {"cost_usd": round(total, 4), "cost_missing_nodes": len(missing), "cost_missing": missing,
            "minutes": round((max(ats) - min(ats)) / 60, 1) if ats else None}


def _max_parallel(spans: dict, node: str) -> int:
    return max([v["parallel"] for k, v in spans.items() if report._step_name(k) == node] or [0])


def diff_files(path) -> list | None:
    """差分（git diff の形）が変えたファイルの並び。読めなければ None"""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out = []
    for line in text.splitlines():
        if line.startswith("diff --git a/"):
            name = line[len("diff --git a/"):].split(" b/", 1)[0]
            if name not in out:
                out.append(name)
    return out


# ---------------------------------------------------------------- 判じる
def check(run_id: str, row: dict, events: list, board: pathlib.Path, diff=None) -> dict:
    trace = _jsonl(board / "trace.jsonl")
    items = plan_items(board)
    planned = planned_overlap(items)
    loops = tdd_lanes(board, items)
    units = [{k: r.get(k) or [] for k in ("applied", "conflict", "unmerged", "shared", "union")}
             for r in trace if r.get("op") == OLD_UNITS_OP]
    fixl = [{"lanes": r.get("lanes") or 0, **{k: r.get(k) or [] for k in ("merged", "back", "parked", "shared", "union")}}
            for r in trace if r.get("op") == fixlanes.SETTLED_OP]
    asks = consults(board, trace)
    spans = agent_spans(events)
    lane_nodes = lane_peak(events)
    fix_lane_nodes = lane_peak(events, FIX_LANE_NODE)
    tdd_par, fix_par = lane_nodes["parallel"], _max_parallel(spans, FIX_NODE)
    fixl_par = fix_lane_nodes["parallel"]

    tdd_lanes_n = max([lp["lanes"] for lp in loops] or [0])
    fix_items_n = max([len(u["applied"]) for u in units] or [0])
    fixl_n = max([r["lanes"] for r in fixl] or [0])
    why = []
    if tdd_lanes_n >= 2 and tdd_par >= 2:
        ends = {}
        for lp in loops:
            for u in lp["units"]:
                ends[u.get("outcome") or "?"] = ends.get(u.get("outcome") or "?", 0) + 1
        why.append(f"TDD の輪の枝 {tdd_lanes_n} 本・枝の輪の同時の最大 {tdd_par}・単位の結末 {ends}")
    if fixl_n >= 2 and fixl_par >= 2:
        merged = sorted({i for r in fixl for i in r["merged"]})
        back = sorted({i for r in fixl for i in r["back"]})
        why.append(f"修正役の並べの枝 {fixl_n} 本・枝の輪の同時の最大 {fixl_par}・当てた項目 {merged}・戻した項目 {back}")
    if fix_items_n >= 2 and fix_par >= 2:
        why.append(f"修正役が当てた項目 {fix_items_n}・修正役の下請けの同時の最大 {fix_par}（前の形の run）")
    skipped = [{"scope": r.get("scope") or "", "loop": r.get("loop") or "", "reason": r.get("reason") or "", "why": r.get("why") or ""}
               for r in trace if r.get("op") == tddlanes.SKIP_OP]
    a = {"status": YES if why else NO,
         "why": "・".join(why) or (f"並べの証拠が足りない（TDD の輪の枝 {tdd_lanes_n}・枝の輪の同時 {tdd_par}・"
                                   f"修正役の並べの枝 {fixl_n}・枝の輪の同時 {fixl_par}・"
                                   f"前の形の修正役が当てた項目 {fix_items_n}・修正役の下請けの同時 {fix_par}）")}
    fix_skipped = [{"scope": r.get("scope") or "", "why": r.get("why") or ""}
                   for r in trace if r.get("op") == fixlanes.PLANTED_OP and not r.get("lanes")]
    if not why and skipped:
        a["why"] += "・TDD の輪が並べなかった理由: " + "・".join(
            f"{x['scope'] or '—'} {x['loop'] or '—'} {x['reason']}（{x['why']}）" for x in skipped)
    if not why and fix_skipped:
        a["why"] += "・修正役の並べを切らなかった理由: " + "・".join(f"{x['scope'] or '—'}（{x['why']}）" for x in fix_skipped)

    shared = sorted({f for lp in loops for f in lp["shared"]} | {f for u in units for f in u["shared"]}
                    | {f for r in fixl for f in r["shared"]})
    unions = sorted({f for u in units for f in u["union"]} | {f for r in fixl for f in r["union"]})
    merges = sorted({u["merge"] for lp in loops for u in lp["units"] if u.get("merge")})
    expected = any(lp["expect"] for lp in loops) or any(r.get("expect") for r in trace if r.get("op") == fixlanes.PLANTED_OP)
    plan_said = "・".join(f"{f} 項目 {ns}" for f, ns in planned.items()) or "無い"
    if shared or unions or tddlanes.UNION in merges:
        b = {"status": YES, "why": f"重なりのファイル {shared}・試験のファイルの union {unions}・枝の合わせ {merges}"
                                   f"・案の重なり {plan_said}"}
    elif expected or planned or tddlanes.CLASH in merges or tddlanes.SEMANTIC in merges:
        b = {"status": ATTEMPTED, "why": f"同じファイルを触る項目を見込んだが合わせなかった（案の重なり {plan_said}・"
                                         f"枝の合わせ {merges}）"}
    elif items:
        b = {"status": NO, "why": "修正案の項目どうしが触ってよいファイルを共にしない（計画役が同じファイルの単位を 1 項目に"
                                  "まとめたか、テストを別のファイルに置いた。下の修正案の項目を見る）"}
    else:
        b = {"status": NO, "why": "同じファイルを触る枝が無かった（修正案の欄の控えも重なりの見込みも合わせの記録も無い）"}

    answered = [r for r in asks if r["status"] == consult.ANSWERED]
    if answered:
        c = {"status": YES, "why": "答えた相談 {}（{}）".format(
            len(answered), "・".join(f"項目 {r['item']} {r['decision']} {r['granted_paths']}" for r in answered))}
    elif asks:
        c = {"status": ATTEMPTED, "why": "答えの無い相談だけ（{}）".format("・".join(sorted({r["status"] for r in asks})))
             + "".join(sorted({f"・断った訳: {r['why_refused']}" for r in asks if r["why_refused"]}))}
    else:
        c = {"status": NO, "why": "相談の記録が無い"}

    d = {op: sum(1 for r in trace if r.get("op") == op) for op in REPLAN_OPS}
    changed = diff_files(diff) if diff else None
    return {
        "run_id": run_id,
        "status": row.get("status", ""),
        "outcome": outcome(board),
        "board": str(board),
        "report": str(board / report.REPORT_FILE) if (board / report.REPORT_FILE).is_file() else "",
        "features": {"a_parallel": a, "b_overlap": b, "c_consult": c,
                     "d_replan": {"status": YES if d[conflict.REPLAN_OP] or d[planmarks.AMEND_OP] else NO, "counts": d}},
        "plan_items": items,
        "planned_overlap": planned,
        "tdd_lanes": loops,
        "lanes_skipped": skipped,
        "fix_lanes_skipped": fix_skipped,
        "fix_units": units,
        "fix_lanes": fixl,
        "consults": asks,
        "agents": spans,
        "lane_nodes": lane_nodes,
        "fix_lane_nodes": fix_lane_nodes,
        "nodes": node_peak(events),
        "spend": spend(events),
        "diff_files": changed,
    }


def summary_lines(got: dict) -> list:
    f = got["features"]
    out = [f"run {got['run_id']}（Archon の状態 {got['status']}・結末 {got['outcome'] or '報告が無い'}）"]
    for key, name in (("a_parallel", "(a) 別のファイルの項目の並べ"), ("b_overlap", "(b) 同じファイルの枝の合わせ"),
                      ("c_consult", "(c) 範囲の相談")):
        out.append(f"{name}: {f[key]['status']} — {f[key]['why']}")
    out.append(f"(d) run の中の案の直し（起きなくてよい）: {f['d_replan']['status']} — {f['d_replan']['counts']}")
    lanes = {}
    for lp in got["tdd_lanes"]:
        for r in lp["rows"]:
            for n in r["items"]:
                lanes.setdefault(n, []).append(f"{lp['loop']} 枝 {r['lane']} {r['files'] if r['files'] is not None else '控え無し'}")
    out.append("修正案の項目:" if got["plan_items"] else "修正案の項目: 無い（plan-fields.json が無い）")
    for i in got["plan_items"]:
        out.append(f"  {i['item']} {i['route']} 範囲 {i['allowed_paths']}・テスト {i['test_files']}"
                   f"・枝の差分 {'・'.join(lanes.get(i['item']) or ['並べなかった'])}")
    s = got["spend"]
    gone = "・".join(m["node"] for m in s["cost_missing"])
    out.append(f"費用: AI の節の和 {s['cost_usd']} USD（取れない節 {s['cost_missing_nodes']}{': ' + gone if gone else ''}）"
               f"・時間 {s['minutes']} 分・節の同時の最大 {got['nodes']['parallel']}")
    if got["diff_files"] is not None:
        out.append("差分のファイル: " + ("・".join(got["diff_files"]) or "無い"))
    if got["report"]:
        out.append(f"報告: {got['report']}")
    return out


# ---------------------------------------------------------------- 入口
def _from_root(root: pathlib.Path, run_id: str | None) -> tuple:
    home = root / "home"
    if run_id is None:
        ledgers = sorted((home / "runs").glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))
        if not ledgers:
            raise Refused(f"run の控えが無い（{home / 'runs'}）。run-id を名指す")
        run_id = ledgers[-1].stem
    return home / "archon-home" / "archon.db", run_id, home / "diffs" / f"run-{run_id}.diff"


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):   # 日本語の行を Windows の既定 cp1252 で落とさない
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="canary_check.py", add_help=False)
    p.add_argument("root", nargs="?")
    p.add_argument("run_id", nargs="?")
    p.add_argument("--db")
    p.add_argument("--run")
    p.add_argument("--board")
    p.add_argument("--diff")
    p.add_argument("--json", action="store_true")
    try:
        a, rest = p.parse_known_args(argv)
        if rest:
            raise Refused(USAGE)
        if a.db:
            if a.root or a.run_id or not a.run:
                raise Refused(USAGE)
            db, run_id, diff = pathlib.Path(a.db), a.run, a.diff
        else:
            if not a.root or a.run:
                raise Refused(USAGE)
            db, run_id, diff = _from_root(pathlib.Path(a.root), a.run_id)
            diff = a.diff or (diff if diff.is_file() else None)
        row, events = read_run(db, run_id)
        board = pathlib.Path(a.board) if a.board else \
            pathlib.Path(row.get("output_root") or "") / "artifacts" / "runs" / run_id / "board"
        if not board.is_dir():
            raise Refused(f"盤面が無い（{board}）。--board で名指す")
    except Refused as e:
        print(f"canary_check.py: {e}", file=sys.stderr)
        return 2
    except SystemExit:
        print(f"canary_check.py: {USAGE}", file=sys.stderr)
        return 2
    got = check(run_id, row, events, board, diff)
    if a.json:
        print(json.dumps(got, ensure_ascii=False))
    else:
        print("\n".join(summary_lines(got)))
    return 0 if all(got["features"][k]["status"] == YES for k in ("a_parallel", "b_overlap", "c_consult")) else 1


if __name__ == "__main__":
    sys.exit(main())
