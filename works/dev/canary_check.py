"""works/dev/canary_check.py — canary の run（dev/canary.sh）が、狙った道を本当に通ったかを、終わった run の記録から出す（開発の殻。
読むだけで何も書かない）。

  python3 canary_check.py <canary の置き場> [<run-id>] [--request tdd|fix|units|large|lanes2|change] [--json]
  python3 canary_check.py --db <archon.db> --run <run-id> [--board <盤面>] [--diff <差分>] [--launches <置き場>] [--request tdd|fix|units|large|lanes2|change] [--json]

置き場の形は canary.sh が作る物（home/archon-home/archon.db・home/runs/<run-id>.json・home/diffs/run-<id>.diff）。run-id を省けば
home/runs の一番新しい控えの run。盤面は Archon の run の行の output_root の下の artifacts/runs/<id>/board（--board で替える）。
db は読むだけで開く（?mode=ro）。盤面と run ごとの置き場（盤面の隣の run-place）はファイルを読むだけ。
包みの起動の記録（adapter.py の launches。置き場の形では home/adapter/launches/、--db の形では --launches で名指す）も
読むだけで、盤面の state.json の run の worktree（inputs.cwd）のファイルの、盤面を作った後の行だけをその run の物と見る。
--request は canary.sh の --request と同じ語（tdd は既定の canary-request.json、fix は canary-request-fix.json、units は固定材料
canary-fixture-units/ から始める run、large は測りの canary-request-large.json、lanes2 は canary-request-lanes2.json、change は
canary-request-fix.json に commit しない 1 行の変更を足して変更から入る run）で、終了コードだけを変える（fix なら (e) も yes でないと 1、
units は (f) だけ・large は (g) だけ・lanes2 は (k) だけ・change は (h)(j) だけで決める）。出す物は同じ。

依頼から始めた run（start の控え r1/start.json の entry が request。--request change のほかの語の run）は、局所レビューの役を回さない
（P1 の役の条件 not_request_entry。1 周の run は修正が入る前の周しか回らない）。そういう run で局所レビューの跡（受け付けの控え・
局所レビューの役の起動）が無ければ、(h)(j) は no でなく not_exercised（回す形の run でなかった）と出す。本当の赤の no と見分ける
ため。跡が在れば（修正が入った後の周で回った）いつもの判じに戻す。控えが無い・entry が change・both の run も、いつもの判じ。

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
- (e) fix_lanes（修正役の並べを本物で通したか。canary-request-fix.json の狙い。docs/plans/2026-10-07-fix-lane-nodes.md の 9 節）:
  植えた枝（trace の fix_lanes_planted の lanes と項目）・枝の輪の同時の最大（(a) と同じ fix-lane-loop-<n> と中の節の区間）・
  締めの行（fix_lanes_settled の merged・back・parked・shared・union）・枝の中の相談（trace の plan_scope_asked のうち pass が
  lane-<n> の行）・答えの節 plan-answer-lane-<n> の包みの起動（session の mode・fork・of・from・id）を出す。
  通ったと言う決まり: 植えた枝が 2 本以上・枝の輪が同時に 2 本以上・締めの行が在る・枝の中の相談に answered が在る・
  plan-answer-lane-<n> の起動が 1 つ以上在り、どれも旗 fork の形（mode continued・fork true・of が fix-planner・元 from が
  修正案の役（節 plan・plan-revise の起動）の会話の id で、新しい id が元と違う。adapter.py の頭の 1）。植えなければ no（fix-fork の理由を添える）、植えて足りない物が在れば attempted（足りない物を名指す）
- (f) item_units（1 つの修正案の項目に 2 つ以上の単位。canary-fixture-units の狙い。0.2.38 の tddloop._close_covered）: 2 つ以上の単位を
  持つ項目（plan-fields.json）・TDD の輪の単位ごとの道・赤・緑・covered_by（tdd-<k>/state.json）・食い違いの申し出（同じ状態の calls の
  phase conflict。並べの周の枝の中の呼びは同じ状態の lanes.calls）・trace の conflict_parked・conflict_ruled の数・裁定役の節（名の
  最後が ruling.ROLE）の node_started の数を出す。
  通ったと言う決まり: covered_by で閉じた単位（赤・緑とも ok）が在り、covered_by の単位は同じ輪で自分の段で緑に届いた tdd の単位で、
  申し出・conflict_parked・conflict_ruled・裁定役の起動が全部 0。2 つ以上の単位を持つ項目か TDD の輪の状態が無ければ no、ほかは attempted
- (g) measure（測り。canary-request-large.json を全部 on と全部 off で回して並べる）: include ごとの段（節の名の頭の <include>__。
  include の外の線の節は line）の分（段の節の node_started の最初から終わりの最後まで。line は節の区間の和）と AI の節の費用の和、
  修正の include の中の TDD の輪の段（外の輪の節が tdd-start・tdd-loop・tdd-fork・tdd-lane-loop-<n>・tdd-join・tdd-rest-loop）と
  修正役の段（fix-fork・fix-loop・fix-lane-loop-<n>・fix-join・conflict-check・rule-loop・fix-ruled-loop）の分と費用、TDD の輪の枝の数
  （並べの周の目録）と修正役の枝の数（fix_lanes_planted）と枝の輪の同時の最大、切った機能（start の控えの features_off）と機能ごとの実効の値（features。既定と全部 on を見分ける）、全体の分と
  費用（spend と同じ）。通ったと言う決まり: 結末が fixed で、切っていない枝の機能（tdd_lanes・fix_lanes）はどれも枝 2 本以上が
  同時に 2 本以上走った。報告の結末が無ければ no、ほかは attempted
- (h) lens_seen（fork のレンズの所見が届いたか。--request change の時だけ終了コードに数える）: 局所レビューの受け付けが周ごとに
  残す控え（diverted.LENS_FILE）が fork のレンズ（/code-review）を見ていない（unseen）と書いた周が在れば attempted（所見の本文が
  局所レビューに届かなかった）、無ければ yes。控えが無ければ no（依頼から始めた run なら not_exercised。上）
- (i) cold_new（報告の初見の読み手の会話。読むだけで終了コードには数えない）: 包みの起動の記録のうち report-write-cold の起動が
  どれも新しい会話（session.mode が new）なら yes。書き手の会話を継いだ起動が在る・起動が無い・記録が読めないなら no
- (j) text_reply（返答の契約。--request change の時だけ終了コードに数える）: 包みの起動の記録のうち局所レビューの役（local-review）の起動が
  どれも旗 text-reply（fence.text_reply。包みが schema を子に渡さず、本文で受けて確かめ、合わなければ同じ会話で出し直させる。
  .shared/core/adapter.py の頭の 21）で、包みの家の replies/<cwd の hash>.jsonl（adapter.replies_path）が起動ごと（pid）に
  決めを持ち、返答の道具が残った跡（kind native）が無ければ yes。出し直しを使い切った
  （gave_up）・誤りの result（error）・決めの無い起動・包みが拒んだ起動（mode refused。旗の有無を数えない）が在れば attempted。
  旗の無い起動・返答の道具の跡が在る・子を起こした起動が無い・記録が読めないなら no（起動が無いのが依頼から始めた run なら
  not_exercised。上）
- (k) lane_chain（修正役の並べの 1 本の枝が 2 つ以上の項目を順に直したか。canary-request-lanes2.json の狙い。run 97fd532f）: 植えた枝
  （trace の fix_lanes_planted の items）のうち項目が 2 つ以上の枝と、締めの行（fix_lanes_settled の outcomes）の項目ごとの結末を出す。
  通ったと言う決まり: 2 項目以上の枝が在り、その枝の 2 つ目からの項目が全部 merged（項目の頭から照らして当たった）。2 項目以上の枝が
  無ければ no（植えた枝の項目か fix-fork の理由を添える）、在って 2 つ目からの項目が戻った・締めの行が無いなら attempted（戻った項目と
  理由を名指す）
ほか: 報告の冒頭の結末の語（fixed・round_limit など）、修正案の項目（盤面の plan-fields.json。番号は 1 始まりの並び）ごとの
allowed_paths・テストのファイル・その項目の単位を持つ TDD の輪の枝が実際に変えたファイル（当てる時に控えた枝の差分
tdd-<k>/lanes/item-<n>.patch）、節の同時の最大（node_started から node_completed・node_failed まで）、AI の節の費用の和
（node_completed の data.node.kind が agent の物。輪の節 loop_group は中の和なので足さない。読み方は report._event_cost）と費用の
取れない節の名と理由（Archon が costUsd を source unavailable で記録した節。和に入らないので、和は下限）、出来事の最初から
最後までの分、差分が変えたファイル。

終了コード: 0 = (a)(b)(c)（--request fix なら (e) も。--request units は (f) だけ・--request large は (g) だけ・--request lanes2 は (k) だけ・
--request change は (h)(j) だけ）が全部 yes（attempted・not_exercised は yes でない）・1 = どれかが yes でない・2 = 引数の誤り・db が開けない・
run が無い（標準エラーに 1 行）。
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
import types

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

PACK = pathlib.Path(__file__).resolve().parents[1]
for _p in (PACK / "blk-report" / "lib", PACK / "blk-fix" / "lib", PACK / ".shared" / "core"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import conflict  # noqa: E402  trace の行の語（ASKED_OP・PARK_OP・RULE_OP・REPLAN_OP）
import diverted  # noqa: E402  局所レビューの控え（LENS_FILE）
import fixlanes  # noqa: E402  修正役の並べの締めの trace の行の語（SETTLED_OP）・合わせの結末の語（MERGED）
import gatemarks  # noqa: E402  報告の冒頭の起きたことの行の頭（HAPPENED）
import consult  # noqa: E402    範囲の相談の行の status の語（ANSWERED）
import adapter  # noqa: E402    包みの起動の記録の置き場（cwd_key）と旗の語（FORK）
import fixture  # noqa: E402    包みの起動の記録を数え始める時刻（since）
import planmarks  # noqa: E402  修正案の欄の控え（FIELDS_FILE・AMEND_OP）
import entry  # noqa: E402      機能ごとの実効の値（feature_words・features_on_of・features_part）
import report  # noqa: E402    節の名の最後の語（_step_name）と費用の読み（_event_cost）
import report_roles  # noqa: E402  報告の初見の読み手の節の名（WRITE_COLD）
import ruling  # noqa: E402    裁定役の節の名（ROLE）
import scopes  # noqa: E402    周の作業ファイルを全部の周と scope の根から集める（all_rounds）
import tddlanes  # noqa: E402  合わせの結末の語（UNION・CLASH・SEMANTIC）

YES, ATTEMPTED, NO = "yes", "attempted", "no"
NOT_EXERCISED = "not_exercised"   # (h)(j): 依頼から始めた run で、局所レビューを回す形でなかった（no と見分ける）
REQUEST_ENTRY = entry.ENTRIES[0]   # start の控えの entry のうち、依頼だけから始めた run（request）
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
LANE_PASS = re.compile(r"lane-(\d+)")   # 枝の中の相談の段の名（consult の pass。fix-lane-consult-check-<n> の with の pass）
ANSWER_LANE = re.compile(r"plan-answer-lane-(\d+)")   # 枝の答えの節（印 continue=fix-planner fork）
PLANNER_NODES = ("plan", "plan-revise")   # 修正案の役の会話を起こす・継ぐ節（印の名）
LAUNCHES = ("adapter", "launches")   # 利用の家の下の包みの起動の記録の置き場（adapter.launches_path）
CONFLICT_PHASE = "conflict"   # TDD の輪の呼びの段の語のうち、食い違いの申し出（tddloop の step が積む calls の phase）
# canary.sh の --request の語と、終了コードを決める道（tdd は (a)〜(c)・fix は (e) も・units は (f) だけ・change は (h)(j) だけ）
REQUESTS = {"tdd": ("a_parallel", "b_overlap", "c_consult"), "fix": ("a_parallel", "b_overlap", "c_consult", "e_fix_lanes"),
            "units": ("f_item_units",), "large": ("g_measure",), "lanes2": ("k_lane_chain",),
            "change": ("h_lens_seen", "j_text_reply")}
# 測り（(g)）の段: include（節の名の頭の <include>__）ごとの段。include の外の線の節（start・h-*・report など）は段 LINE_STAGE で、
# run の全体に散るので分は区間の和。修正の include（FIX_SCOPES）の中は、さらに TDD の輪の段（TDD_TOP）と修正役の段（FIX_TOP）を
# 外の輪の節の名で分けて出す
FIX_SCOPES = ("fixing", "refitting")
TDD_TOP = re.compile(r"tdd-(?:start|loop|fork|join|rest-loop|lane-loop-\d+)")
FIX_TOP = re.compile(r"fix-(?:fork|join|loop|ruled-loop|lane-loop-\d+)|conflict-check|rule-loop")
LINE_STAGE = "line"
FIXED = "fixed"   # 報告の結末の語のうち直した物（report.OUTCOMES）。fixed_needs_check（測れなかった確かめが残る）は満たさない: canary の種は網も資格も要らない対象で、素材が測れないのはラインのどこかの不具合
LANE_FEATURES = {"tdd": "tdd_lanes", "fix": "fix_lanes"}   # 枝を切る機能の語（entry.FEATURES。切れば枝を求めない）
WORDS = "|".join(REQUESTS)
USAGE = (f"usage: canary_check.py <canary の置き場> [<run-id>] [--request {WORDS}] [--json] | "
         "canary_check.py --db <archon.db> --run <run-id> [--board <盤面>] [--diff <差分>] [--launches <置き場>] "
         f"[--request {WORDS}] [--json]")


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


def _tdd_states(board: pathlib.Path) -> list:
    """盤面の TDD の輪の状態 [(状態のファイル, 状態)]（盤面の根と scope の下の tdd-<k>/state.json。読めない物は除く）"""
    out = []
    for st_path in sorted(board.glob("tdd-*/state.json")) + sorted(board.glob("*/tdd-*/state.json")):
        st = _json(st_path)
        if isinstance(st, dict):
            out.append((st_path, st))
    return out


def item_units(board: pathlib.Path, items: list, trace: list, events: list) -> tuple[dict, dict]:
    """((f) の判じ {status, why}, 出す証拠 {items, units, conflict_calls, conflict_parked, conflict_ruled, rule_runs})。
    items は 2 つ以上の単位を持つ修正案の項目 [{item, units}]、units は TDD の輪の単位 [{loop, unit, route, red, green, covered_by}]"""
    multi = [{"item": it["item"], "units": len(it["unit_keys"])} for it in items if len(it["unit_keys"]) >= 2]
    units, calls = [], 0
    for st_path, st in _tdd_states(board):
        loop = str(st_path.parent.relative_to(board))
        for k, u in (st.get("units") or {}).items():
            u = u if isinstance(u, dict) else {}
            units.append({"loop": loop, "unit": k, **{f: u.get(f) or "" for f in ("route", "red", "green")},
                          "covered_by": list(u.get("covered_by") or [])})
        lanes = st.get("lanes") if isinstance(st.get("lanes"), dict) else {}
        calls += sum(1 for c in [*(st.get("calls") or []), *(lanes.get("calls") or [])]   # 枝の中の呼びは締めが lanes に集める
                     if isinstance(c, dict) and c.get("phase") == CONFLICT_PHASE)
    got = {"items": multi, "units": units, "conflict_calls": calls,
           "conflict_parked": sum(1 for r in trace if r.get("op") == conflict.PARK_OP),
           "conflict_ruled": sum(1 for r in trace if r.get("op") == conflict.RULE_OP),
           "rule_runs": sum(1 for e in events if e["event_type"] == "node_started"
                            and report._step_name(e["step_name"]) == ruling.ROLE)}
    if not multi:
        return {"status": NO, "why": "修正案に 2 つ以上の単位を持つ項目が無い（狙いの形でない）"}, got
    if not units:
        return {"status": NO, "why": "TDD の輪の状態が無い（輪が回らなかった）"}, got
    green = {(u["loop"], u["unit"]) for u in units if u["route"] == "tdd" and u["green"] == "ok" and not u["covered_by"]}
    closed = [u for u in units if u["covered_by"] and u["red"] == "ok" and u["green"] == "ok"
              and all((u["loop"], g) in green for g in u["covered_by"])]
    facts = ["・".join(f"閉じた単位 {u['unit']}（covered_by {'、'.join(u['covered_by'])}）" for u in closed)
             or "covered_by で閉じた単位が無い",
             f"申し出 {got['conflict_calls']}・conflict_parked {got['conflict_parked']}・conflict_ruled {got['conflict_ruled']}"
             f"・裁定役の起動 {got['rule_runs']}"]
    quiet = not (got["conflict_calls"] or got["conflict_parked"] or got["conflict_ruled"] or got["rule_runs"])
    return {"status": YES if closed and quiet else ATTEMPTED, "why": "・".join(facts)}, got


def tdd_lanes(board: pathlib.Path, items: list = ()) -> list:
    """TDD の輪の並べの周ごと（盤面の tdd-<k>/state.json の lanes。並べた輪だけ）[{loop, lanes, rows, units, shared, expect}]。
    rows は枝ごと {lane, items（枝の単位を持つ修正案の項目）, files（当てる時に控えた枝の差分 tdd-<k>/lanes/item-<n>.patch の
    ファイル。控えが無ければ None）}"""
    out = []
    for st_path, st in _tdd_states(board):
        lanes = st.get("lanes")
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
    """範囲の相談の行（trace の ASKED_OP と、前の形の run-place のまだ写していない記録）[{scope, id, item, pass, node, status,
    decision, paths, granted_paths, why_refused, settled}]（pass は相談の段: 修正の輪は first・ruled、修正役の並べの枝は lane-<n>）。同じ scope と id は trace の行だけ"""
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
    return [{"scope": s, "id": r.get("id"), "item": r.get("item"), "pass": r.get("pass") or "", "node": r.get("node") or "",
             "status": r.get("status", ""),
             "decision": r.get("decision", ""), "paths": r.get("paths") or [], "granted_paths": r.get("granted_paths") or [],
             "why_refused": r.get("why_refused") or "", "settled": settled} for s, r, settled in rows]


def run_launches(launches_dir, board: pathlib.Path) -> list | None:
    """包みの起動の記録のうち、この run の行。記録は run の worktree ごとの 1 ファイル（adapter.launches_path。盤面の state.json の
    inputs.cwd）で、同じ worktree の前の run の行も載りうるので、盤面を作った時刻（fixture.since）より後の行だけ（報告と同じ絞り方。
    report._since_created）。置き場が無い・名指しが無い（None）・盤面の cwd か時刻が読めない・ファイルが無いなら None（読めない）"""
    if launches_dir is None:
        return None
    state = _json(board / "state.json")
    cwd = ((state.get("inputs") or {}).get("cwd") if isinstance(state, dict) else None)
    if not isinstance(cwd, str) or not cwd:
        return None
    path = pathlib.Path(launches_dir) / f"{adapter.cwd_key(cwd)}.jsonl"
    if not path.is_file() or report._time(fixture.since(board, state.get("created"))) is None:
        return None
    return report._since_created(types.SimpleNamespace(dir=board, state=state), _jsonl(path))


def answer_launches(rows: list | None) -> list:
    """枝の答えの節（plan-answer-lane-<n>）の起動 [{node, mode, fork, of, from, id}]（起動の順）"""
    out = []
    for r in rows or []:
        node = r.get("node")
        if not isinstance(node, str) or not ANSWER_LANE.fullmatch(node):
            continue
        s = r.get("session") if isinstance(r.get("session"), dict) else {}
        out.append({"node": node, "mode": s.get("mode") or "", "fork": s.get(adapter.FORK) is True, "of": s.get("of") or "",
                    "from": s.get("from") or "", "id": s.get("id") or ""})
    return out


def planner_ids(rows: list | None) -> set:
    """修正案の役の会話の id（節 plan・plan-revise の起動の session の id。枝の答えの節が写す元。consult.PEER の会話）"""
    return {r["session"]["id"] for r in rows or [] if r.get("node") in PLANNER_NODES and isinstance(r.get("session"), dict)
            and isinstance(r["session"].get("id"), str) and r["session"]["id"]}


def forked(launch: dict, planners: set) -> bool:
    """旗 fork の起動の形か（adapter.py の頭の 1: continue=X を X の会話の写しで起こし、新しい id をこの節の名で記録する）。
    X は consult.PEER（修正案の役）で、写しの元 from は修正案の役の会話の id のどれか"""
    return (launch["mode"] == "continued" and launch["fork"] and launch["of"] == consult.PEER and launch["from"] in planners
            and bool(launch["id"]) and launch["id"] != launch["from"])


def lens_seen(board: pathlib.Path) -> tuple[dict, dict]:
    """((h) の判じ {status, why}, 出す証拠 {rounds, unseen})。局所レビューの受け付けが周ごとに残す控え（diverted.LENS_FILE）の
    見ていない fork のレンズ（unseen）を数える"""
    docs = [d for d in (_json(p) for p in scopes.all_rounds(board, diverted.LENS_FILE)) if isinstance(d, dict)]
    unseen = sorted({str(x) for d in docs for x in d.get("unseen") or []})
    got = {"rounds": len(docs), "unseen": unseen}
    if not docs:
        return {"status": NO, "why": f"局所レビューの控え（{diverted.LENS_FILE}）が無い（局所レビューを受け付けなかった）"}, got
    if unseen:
        return {"status": ATTEMPTED, "why": f"fork のレンズ {unseen} の本文が局所レビューに届かなかった（見ていない）"}, got
    return {"status": YES, "why": f"見ていない fork のレンズは無い（控えの周 {len(docs)}）"}, got


LOCAL_REVIEW = "local-review"   # 旗 text-reply の局所レビューの役の印の名（blk-material の material.ROLES の鍵）


def run_replies(launches_dir, board: pathlib.Path) -> list | None:
    """包みの家の replies/<cwd の hash>.jsonl（返答の契約の記録。adapter.replies_path）のうち、盤面を作った後の行（盤面の
    state.json の inputs.cwd と created で絞る）。読めなければ None、ファイルが無ければ []"""
    if launches_dir is None:
        return None
    state = _json(board / "state.json")
    cwd = ((state.get("inputs") or {}).get("cwd") if isinstance(state, dict) else None)
    if not isinstance(cwd, str) or not cwd or report._time(fixture.since(board, state.get("created"))) is None:
        return None
    rows = adapter.read_replies(cwd, pathlib.Path(launches_dir).parent)   # 無ければ []
    return report._since_created(types.SimpleNamespace(dir=board, state=state), rows)


def local_review_launches(rows: list | None, refused: bool = False) -> list:
    """局所レビューの役の起動。既定は子を起こした起動（mode が refused でない）、refused なら包みが拒んだ起動（fence が無い）"""
    return [r for r in rows or [] if r.get("node") == LOCAL_REVIEW and (r.get("mode") == "refused") == refused]


def text_reply(rows: list | None, replies: list | None) -> tuple[dict, dict]:
    """((j) の判じ {status, why}, 証拠 {launches, kinds, undecided})。rows は起動の記録（run_launches）、replies は返答の契約の
    記録（run_replies）。None は読めない"""
    got = local_review_launches(rows)
    kinds: dict = {}
    for r in replies or []:
        k = str(r.get("kind"))
        kinds[k] = kinds.get(k, 0) + 1
    decided = {r.get("pid") for r in replies or [] if r.get("kind") != "reasked"}
    undecided = sorted({r.get("pid") for r in got if r.get("pid") not in decided}, key=str)
    ev = {"launches": len(got), "kinds": kinds, "undecided": undecided}
    if rows is None or replies is None:
        return {"status": NO, "why": "包みの起動の記録か返答の契約の記録が読めない"}, ev
    if not got:
        return {"status": NO, "why": f"{LOCAL_REVIEW} の起動が無い（局所レビューを回さなかった）"}, ev
    plain = [r for r in got if not (isinstance(r.get("fence"), dict) and r["fence"].get("text_reply"))]
    if plain:
        return {"status": NO, "why": f"旗 text-reply の無い {LOCAL_REVIEW} の起動 {len(plain)}/{len(got)}（返答の道具で返す形）"}, ev
    if kinds.get("native"):
        return {"status": NO, "why": f"返答の道具が残った跡（kind native {kinds['native']}）——schema を外し損ねた"}, ev
    refused = local_review_launches(rows, refused=True)
    ev["refused"] = len(refused)
    if kinds.get("gave_up") or kinds.get("error") or undecided or refused:
        return {"status": ATTEMPTED, "why": f"決め {kinds}・決めの無い起動 {undecided or '無し'}"
                                            + (f"・包みが拒んだ起動 {len(refused)}（" + "・".join(sorted({str(r.get('why') or '?')
                                                                                         for r in refused})) + "）"
                                               if refused else "")}, ev
    return {"status": YES, "why": f"{LOCAL_REVIEW} の起動 {len(got)} 本はどれも旗 text-reply で、決め {kinds}"}, ev


def cold_launches(rows: list | None) -> tuple[dict, list]:
    """((i) の判じ {status, why}, 報告の初見の読み手（report_roles.WRITE_COLD）の起動 [{mode, id, of, from}]（起動の順））"""
    got = [{"mode": s.get("mode") or "", "id": s.get("id") or "", "of": s.get("of") or "", "from": s.get("from") or ""}
           for s in (r.get("session") if isinstance(r.get("session"), dict) else {}
                     for r in rows or [] if r.get("node") == report_roles.WRITE_COLD)]
    if rows is None:
        return {"status": NO, "why": "包みの起動の記録が無い（読めない）"}, got
    if not got:
        return {"status": NO, "why": f"{report_roles.WRITE_COLD} の起動が無い（報告の書き手の輪を回さなかった）"}, got
    old = [r for r in got if r["mode"] != "new"]
    if old:
        return {"status": NO, "why": f"新しい会話でない起動 {len(old)}/{len(got)}（"
                                     + "・".join(f"{r['mode'] or '?'} 元 {r['of'] or '?'}" for r in old) + "）"}, got
    return {"status": YES, "why": f"{report_roles.WRITE_COLD} の起動 {len(got)} 本はどれも新しい会話"}, got


def fix_lane_run(trace: list, asks: list, fix_lane_nodes: dict, launches: list | None) -> tuple[dict, dict]:
    """((e) の判じ {status, why}, 出す証拠 {planted, items, parallel, settled, consults, answer_launches, launches_read})"""
    planted = [r for r in trace if r.get("op") == fixlanes.PLANTED_OP]
    best = max(planted, key=lambda r: r.get("lanes") or 0, default={})
    n = best.get("lanes") or 0
    settled = [r for r in trace if r.get("op") == fixlanes.SETTLED_OP]
    last = settled[-1] if settled else None
    in_lane = [{"lane": r["pass"], "id": r["id"], "item": r["item"], "status": r["status"], "decision": r["decision"],
                "granted_paths": r["granted_paths"]} for r in asks if LANE_PASS.fullmatch(str(r.get("pass") or ""))]
    runs = answer_launches(launches)
    got = {"planted": n, "items": best.get("items") or {}, "parallel": fix_lane_nodes["parallel"],
           "settled": ({"lanes": last.get("lanes") or 0, **{k: last.get(k) or [] for k in ("merged", "back", "parked", "shared",
                                                                                          "union")}} if last else None),
           "consults": in_lane, "answer_launches": runs, "launches_read": launches is not None}
    if n < 2:
        whys = [r.get("why") or "" for r in planted if not r.get("lanes")]
        return {"status": NO, "why": "修正役の並べを植えなかった（" + ("・".join(w for w in whys if w) or "fix-fork の行が無い")
                + "）"}, got
    answered = [r for r in in_lane if r["status"] == consult.ANSWERED]
    planners = planner_ids(launches)
    ok_fork = [r for r in runs if forked(r, planners)]
    facts = [f"植えた枝 {n} 本（項目 {got['items']}）", f"枝の輪の同時の最大 {got['parallel']}",
             (f"締め merged {last.get('merged') or []}・back {last.get('back') or []}・shared {last.get('shared') or []}"
              if last else "締めの行が無い"),
             f"枝の中の相談 {len(in_lane)}（答えた {len(answered)}）"]
    if launches is None:
        facts.append("包みの起動の記録が無い（旗 fork を確かめられない）")
    else:
        bad = [r["node"] for r in runs if not forked(r, planners)]
        facts.append(f"旗 fork の起動 {len(ok_fork)}/{len(runs)}" + (f"（fork でない: {'・'.join(bad)}）" if bad else ""))
    yes = (got["parallel"] >= 2 and last is not None and answered and launches is not None and runs
           and len(ok_fork) == len(runs))
    return {"status": YES if yes else ATTEMPTED, "why": "・".join(facts)}, got


def lane_chain(trace: list) -> tuple[dict, dict]:
    """((k) の判じ {status, why}, 出す証拠 {chains: {枝: [項目]}, outcomes: [{item, lane, outcome, why}]})。植えた行が 2 度以上
    在れば（修正の輪の後の周など）、2 項目以上の枝を持つ一番後の行と、その後の締めの行を見る"""
    planted = [(k, r) for k, r in enumerate(trace) if r.get("op") == fixlanes.PLANTED_OP]
    chained = [(k, r) for k, r in planted
               if any(isinstance(v, list) and len(v) >= 2 for v in (r.get("items") or {}).values())]
    if not chained:
        seen = [f"{r.get('items')}" if r.get("lanes") else f"植えなかった（{r.get('why') or '理由の記録が無い'}）"
                for _, r in planted]
        return {"status": NO, "why": "項目が 2 つ以上の枝が無い（" + ("・".join(seen) or "fix-fork の行が無い") + "）"}, \
            {"chains": {}, "outcomes": []}
    at, row = chained[-1]
    chains = {str(n): list(v) for n, v in (row.get("items") or {}).items() if isinstance(v, list) and len(v) >= 2}
    settled = next((r for r in trace[at + 1:] if r.get("op") == fixlanes.SETTLED_OP), None)
    outs = [{k: o.get(k) for k in ("item", "lane", "outcome", "why")} for o in (settled or {}).get("outcomes") or []
            if isinstance(o, dict)]
    got = {"chains": chains, "outcomes": outs}
    if settled is None:
        return {"status": ATTEMPTED, "why": f"2 項目以上の枝 {chains} を植えたが締めの行が無い"}, got
    by = {(str(o.get("lane")), o.get("item")): o for o in outs}
    later = [(n, i) for n, items in chains.items() for i in items[1:]]
    bad = [(n, i, by.get((n, i)) or {}) for n, i in later if (by.get((n, i)) or {}).get("outcome") != fixlanes.MERGED]
    facts = f"2 項目以上の枝 {chains}・締め merged {settled.get('merged') or []}・back {settled.get('back') or []}"
    if bad:
        return {"status": ATTEMPTED, "why": facts + "・2 つ目からの項目で当たらなかった物: " + "・".join(
            f"枝 {n} の項目 {i}（{(o.get('outcome') or '結末の記録が無い')}: {(o.get('why') or '')[:200]}）" for n, i, o in bad)}, got
    return {"status": YES, "why": facts + "・2 つ目からの項目は全部当たった"}, got


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
def stage_of(step) -> str:
    """出来事の節の名の段（include の名か LINE_STAGE）。入れ子の節（<輪>.<節>）は外の輪の段"""
    scope, sep, _ = str(step or "").split(".", 1)[0].partition("__")
    return scope if sep else LINE_STAGE


def part_of(step) -> str | None:
    """修正の include の中の段（<include>/tdd か <include>/fix）。ほかは None"""
    scope, sep, name = str(step or "").split(".", 1)[0].partition("__")
    if not sep or scope not in FIX_SCOPES:
        return None
    return f"{scope}/tdd" if TDD_TOP.fullmatch(name) else f"{scope}/fix" if FIX_TOP.fullmatch(name) else None


def _union(spans: list) -> float:
    """区間 [(始め, 終わり)] の和の長さ（重なりは 1 度だけ数える）"""
    total, end = 0.0, None
    for a, b in sorted(spans):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return total


def stages(events: list, key=stage_of) -> list:
    """段ごと [{stage, minutes, cost_usd, ai_nodes}]（段は key(節の名)。None の節は数えない。段の最初の節の始めの順）。分は段の節の
    node_started の最初から終わりの最後まで（線の段だけは節の区間の和）。費用は段の AI の節（spend と同じ数え方）の和で、取れない節は
    ai_nodes に数えて和に入れない"""
    rows, open_ = {}, {}
    for e in events:
        name = key(e["step_name"])
        if name is None or e["at"] is None or e["event_type"] not in ("node_started", *NODE_ENDS):
            continue
        r = rows.setdefault(name, {"first": e["at"], "last": e["at"], "cost": 0.0, "ai": 0, "spans": []})
        r["first"], r["last"] = min(r["first"], e["at"]), max(r["last"], e["at"])
        if e["event_type"] == "node_started":
            open_.setdefault(e["step_name"], []).append(e["at"])
        elif open_.get(e["step_name"]):
            r["spans"].append((open_[e["step_name"]].pop(0), e["at"]))
        if e["event_type"] == "node_completed" and (e["data"].get("node") or {}).get("kind") == AI_KIND:
            r["ai"] += 1
            r["cost"] += report._event_cost(e)[0] or 0.0
    out = []
    for name, r in sorted(rows.items(), key=lambda kv: kv[1]["first"]):
        secs = _union(r["spans"]) if name == LINE_STAGE else r["last"] - r["first"]
        out.append({"stage": name, "minutes": round(secs / 60, 1), "cost_usd": round(r["cost"], 4), "ai_nodes": r["ai"]})
    return out


def start_entry(board: pathlib.Path) -> str:
    """start の控え（r1/start.json）の入口の形（entry.ENTRIES の語。無い・読めなければ ""）"""
    doc = _json(board / "r1" / "start.json")
    got = doc.get("entry") if isinstance(doc, dict) else None
    return got if isinstance(got, str) else ""


def unexercised(board: pathlib.Path, seen: dict, launch_rows: list | None) -> dict | None:
    """依頼から始めた run で局所レビューの跡（受け付けの控え・局所レビューの役の起動。拒んだ起動も）が無ければ、(h)(j) に置く
    not_exercised の判じ。ほかは None（いつもの判じ）"""
    if start_entry(board) != REQUEST_ENTRY or seen["rounds"] or any(r.get("node") == LOCAL_REVIEW for r in launch_rows or []):
        return None
    return {"status": NOT_EXERCISED, "why": f"依頼から始めた run（start の控えの entry が {REQUEST_ENTRY}）で、局所レビューは回らない"
                                            "（P1 の役の条件 not_request_entry。変更から入る run は canary.sh --request change）"}


def features_off(board: pathlib.Path) -> list:
    """start の控え（r1/start.json）の切った機能の語（無い・読めなければ []）"""
    doc = _json(board / "r1" / "start.json")
    got = doc.get("features_off") if isinstance(doc, dict) else None
    return [w for w in got if isinstance(w, str)] if isinstance(got, list) else []


def features_on(board: pathlib.Path) -> list:
    """start の控えの入れた機能の語（entry.features_on_of。features_on の欄の無い前の版の控えは前の版の既定の全部 on）"""
    doc = _json(board / "r1" / "start.json")
    got = entry.features_on_of(doc) if isinstance(doc, dict) else []
    return [w for w in got if isinstance(w, str)] if isinstance(got, list) else []


def measure(board: pathlib.Path, events: list, *, tdd_lanes: int, tdd_par: int, fix_lanes: int, fix_par: int, spent: dict,
            done: str) -> tuple[dict, dict]:
    """((g) の判じ {status, why}, 出す証拠 {features_off, features, stages, tdd, fix, total})。features は機能ごとの実効の値
    （on・off・auto。既定の run と全部 on の run を見分ける）。stages は include ごとの段、tdd・fix は修正の
    include の中の TDD の輪の段・修正役の段の分と費用の和（refitting の同じ段も足す）と枝の数・枝の輪の同時の最大。total は spend の
    分と費用。全部 on と全部 off の run を並べて比べるための物"""
    off, on = features_off(board), features_on(board)
    rows, parts = stages(events), stages(events, part_of)

    def part(kind, lanes, par):
        sel = [r for r in parts if r["stage"].endswith("/" + kind)]
        return {"minutes": round(sum(r["minutes"] for r in sel), 1), "cost_usd": round(sum(r["cost_usd"] for r in sel), 4),
                "lanes": lanes, "parallel": par}

    got = {"features_off": off, "features": entry.feature_words(off, on), "stages": rows, "tdd": part("tdd", tdd_lanes, tdd_par), "fix": part("fix", fix_lanes, fix_par),
           "total": {"minutes": spent["minutes"], "cost_usd": spent["cost_usd"]}}
    facts = [f"結末 {done or '無い'}", f"切った機能 {'・'.join(off) or '無い'}", entry.features_part(off, on),
             f"TDD の輪の枝 {tdd_lanes} 本・同時 {tdd_par}", f"修正役の枝 {fix_lanes} 本・同時 {fix_par}"]
    if not done:
        return {"status": NO, "why": "報告の結末が無い・" + "・".join(facts[1:])}, got
    short = done != FIXED or any(LANE_FEATURES[k] not in off and not (got[k]["lanes"] >= 2 and got[k]["parallel"] >= 2)
                                 for k in LANE_FEATURES)
    return {"status": ATTEMPTED if short else YES, "why": "・".join(facts)}, got


def check(run_id: str, row: dict, events: list, board: pathlib.Path, diff=None, launches=None) -> dict:
    """launches は包みの起動の記録の置き場（run_launches。None なら読まない）"""
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
    launch_rows = run_launches(launches, board)
    e, fix_run = fix_lane_run(trace, asks, fix_lane_nodes, launch_rows)
    h, seen = lens_seen(board)
    i, cold = cold_launches(launch_rows)
    j, replied = text_reply(launch_rows, run_replies(launches, board))
    idle = unexercised(board, seen, launch_rows)
    if idle:
        h, j = idle, dict(idle)
    k, chain = lane_chain(trace)
    f, units_run = item_units(board, items, trace, events)
    spent, done = spend(events), outcome(board)
    g, measured = measure(board, events, tdd_lanes=tdd_lanes_n, tdd_par=tdd_par, fix_lanes=fix_run["planted"], fix_par=fixl_par,
                          spent=spent, done=done)
    changed = diff_files(diff) if diff else None
    return {
        "run_id": run_id,
        "status": row.get("status", ""),
        "outcome": done,
        "board": str(board),
        "report": str(board / report.REPORT_FILE) if (board / report.REPORT_FILE).is_file() else "",
        "features": {"a_parallel": a, "b_overlap": b, "c_consult": c,
                     "d_replan": {"status": YES if d[conflict.REPLAN_OP] or d[planmarks.AMEND_OP] else NO, "counts": d},
                     "e_fix_lanes": e, "f_item_units": f, "g_measure": g, "h_lens_seen": h, "i_cold_new": i,
                     "j_text_reply": j, "k_lane_chain": k},
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
        "fix_lane_run": fix_run,
        "lane_chain": chain,
        "item_units": units_run,
        "measure": measured,
        "lens_seen": seen,
        "cold_launches": cold,
        "text_reply": replied,
        "nodes": node_peak(events),
        "spend": spent,
        "diff_files": changed,
    }


def summary_lines(got: dict) -> list:
    f = got["features"]
    out = [f"run {got['run_id']}（Archon の状態 {got['status']}・結末 {got['outcome'] or '報告が無い'}）"]
    for key, name in (("a_parallel", "(a) 別のファイルの項目の並べ"), ("b_overlap", "(b) 同じファイルの枝の合わせ"),
                      ("c_consult", "(c) 範囲の相談")):
        out.append(f"{name}: {f[key]['status']} — {f[key]['why']}")
    out.append(f"(d) run の中の案の直し（起きなくてよい）: {f['d_replan']['status']} — {f['d_replan']['counts']}")
    out.append(f"(e) 修正役の並べ: {f['e_fix_lanes']['status']} — {f['e_fix_lanes']['why']}")
    for r in got["fix_lane_run"]["answer_launches"]:
        out.append(f"  {r['node']} {r['mode'] or '?'}{' fork' if r['fork'] else ''} 元 {r['of'] or '?'}（{r['from'] or '?'} → "
                   f"{r['id'] or '?'}）")
    out.append(f"(k) 枝の中の 2 つ目からの項目: {f['k_lane_chain']['status']} — {f['k_lane_chain']['why']}")
    out.append(f"(f) 1 つの項目の 2 つの単位: {f['f_item_units']['status']} — {f['f_item_units']['why']}")
    out.append(f"(h) fork のレンズの所見: {f['h_lens_seen']['status']} — {f['h_lens_seen']['why']}")
    out.append(f"(i) 報告の初見の読み手の会話: {f['i_cold_new']['status']} — {f['i_cold_new']['why']}")
    out.append(f"(j) 返答の契約: {f['j_text_reply']['status']} — {f['j_text_reply']['why']}")
    m = got["measure"]
    out.append(f"(g) 測り: {f['g_measure']['status']} — {f['g_measure']['why']}")
    out.append("  段ごと: " + ("・".join(f"{r['stage']} {r['minutes']} 分 {r['cost_usd']} USD" for r in m["stages"]) or "出来事が無い"))
    out.append(f"  TDD の輪の段 {m['tdd']['minutes']} 分 {m['tdd']['cost_usd']} USD（枝 {m['tdd']['lanes']} 本・同時 {m['tdd']['parallel']}）"
               f"・修正役の段 {m['fix']['minutes']} 分 {m['fix']['cost_usd']} USD（枝 {m['fix']['lanes']} 本・同時 {m['fix']['parallel']}）"
               f"・全体 {m['total']['minutes']} 分 {m['total']['cost_usd']} USD")
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
    return home / "archon-home" / "archon.db", run_id, home / "diffs" / f"run-{run_id}.diff", home.joinpath(*LAUNCHES)


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
    p.add_argument("--launches")
    p.add_argument("--request", default="tdd")
    p.add_argument("--json", action="store_true")
    try:
        a, rest = p.parse_known_args(argv)
        if rest or a.request not in REQUESTS:
            raise Refused(USAGE)
        if a.db:
            if a.root or a.run_id or not a.run:
                raise Refused(USAGE)
            db, run_id, diff, launches = pathlib.Path(a.db), a.run, a.diff, a.launches
        else:
            if not a.root or a.run or a.launches:
                raise Refused(USAGE)
            db, run_id, diff, launches = _from_root(pathlib.Path(a.root), a.run_id)
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
    got = check(run_id, row, events, board, diff, launches)
    if a.json:
        print(json.dumps(got, ensure_ascii=False))
    else:
        print("\n".join(summary_lines(got)))
    return 0 if all(got["features"][k]["status"] == YES for k in REQUESTS[a.request]) else 1


if __name__ == "__main__":
    sys.exit(main())
