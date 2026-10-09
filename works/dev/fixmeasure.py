"""works/dev/fixmeasure.py — 修正の形の腕ごとの測りと採否の判定（計画 220 Task 8。開発の殻。読むだけで何も書かない）。

  python3 fixmeasure.py row [--adapter-home <包みの家>] <archon.db> <run_id> <盤面>   1 run の行（JSON の 1 行）
  python3 fixmeasure.py verdict <行の jsonl>             採否の判定（JSON）
  python3 fixmeasure.py maintenance                      腕ごとの保守量（JSON）
  python3 fixmeasure.py wait <archon.db> <run_id>         段ごとの待ちの損（JSON。下の「待ちの損」）

誤り（引数・db が開けない・run が無い・jsonl が読めない）は標準エラーに 1 行で 2、ほかは 0。網に出ない。時刻を入れず、辞書は
書いた順（同じ入力なら同じ出力）。--adapter-home は run の包みの家（書き込みの記録 writes.jsonl の置き場の根。試しの run は
殻の家の下の家を使い、測る側の env の WORKS_ADAPTER_HOME と違う）。盤面も Archon も家を書かないので、省けば測る側の env の家。

語:
- 腕: 修正の形（ARMS の current・af・g3・g1）ごとの run。2026-10-09 に形は g3 だけになった（入力 fix_shape を消した）ので、
  形は前の版の盤面の start の控えの鍵 SHAPE_KEY から読み、鍵の無い盤面は g3（_shape_at。ここだけが前の版の盤面を読む）。
  固定材料: 同じ依頼を同じ所から始める盤面の写し（行の fixture は元の run の id。固定材料の印は fixture.adopted が読む）。
- 修正の工程: Archon の出来事の step_name の頭が FIX_STAGE の節。費用と時間は AI の節（data.node.kind が agent）だけを足す
  （輪の節 loop_group の node_completed は中の AI の節の費用の和を持つので、足すと 2 重になる。実物の archon.db で見た）。
- 混ざり（contamination）: 修正の工程の節の tool_called のうち、その形でその節に拒む道具（_denied。前の版の包みの柵の表。節は
  step_name の最後の区切り）の呼び出しで、走った物。柵が拒んだ呼び出しも skills: の一覧に残るので tool_called に出る（Task 2 の
  審査 M5）。走ったかの見分けは道具ごと:
  - Skill: 同じ tool_call_id の tool_completed の tool_outcome が REFUSED（error）なら refused に数え、混ざりにしない。完了の行の
    無い呼び出しは走ったかを言えないので混ざりに数える。
  - Agent: tool_outcome は下請けが走っても error になりうるので見ない。同じ節の task_activity の started・task_type LOCAL_AGENT
    （下請けが起きた印）の数までを走った物、残りを refused に数える。
  permissions.deny の素の Skill・Agent が実地で拒むかはまだ確かめていない（Task 3 の審査）——af・current・g1 の行で走った Skill
  は混ざりに出る（最初の試しの run で refused に出るかを見る。下の FIELDS_CHECKED）。
- 記録の欠け（record_gaps）: 盤面を開けない・形の控えが読めない・
  tdd・tdd-rest の節の node_completed の数と輪の calls の行（並べを締めた節 tdd-join の行 lanes を除く）の数が違う・並べの枝の役
  tdd-lane-<n> の node_completed の数と枝の控えの calls の行（状態の lanes.calls）の数が違う・tdd の項目の単位（輪に渡した単位のうち）に輪の単位の行が無い（g1 は
  輪を回さないので見ない）・平の run でないのに修正案の欄が在って brief の控えが無い・修正の工程の AI の節の費用が取れない・g1 で
  Agent が走ったのに書き込みの記録に下請けの行（agent_id）が無く、申告（bash_writes。記録の declared の行）だけが在る（フックの
  欠けを自己申告が隠した疑い。Task 7 の審査 M1）・g1 で Agent が走ったのに書き込みの記録が無い（家の取り違えか包みの無い起動。
  黙って空にしない）。g1 の「Agent が走った」は修正役の節の LOCAL_AGENT の started の task_id の数。
- 作り直し（redo）: fix_rejects は修正の受け付け（fix-accept・fix-ruled-accept。どちらも accept_fix）の拒否の本文のファイル
  FIX_REJECTS の数（修正の受け付けは role-rejects.json を書かない）から battery_rejects を引いた物（束の拒否も同じ本文を書くので
  2 重に数えない）、tdd_rejects は輪の calls と並べの枝の calls の ok が偽の行、battery_rejects は
  束の行の在る受け付けの回（周・pass・attempt。preflight F23）、delta_faces は差分の審査（p3.delta_review・p3.delta_review2）が
  受け付けた穴、refix_rounds は手直し（report.REFIX_NODES）を受け付けた回（盤面の trace の done の行）、subagent_redos は g1 の
  下請けの作り直しの往復（数え方は下）。compliance_fails・quality_fails（VERDICT_FAILS）は 1 回目の差分の
  審査が受けた 2 判定（盤面の trace の deltamarks.SAVED_OP）の準拠と品質の fail の数。どちらも delta_faces と同じ穴を判定で数え
  直した物なので redo_total に足さない（報告だけ）。平の run（current）は準拠がいつも not_applicable なので compliance_fails は 0。
  subagent_redos の数え方（g1 の作り直しは修正役の中で回り、ほかの形の拒否の数に出ないので、比べを揃える。ほかの形は 0）:
  - 数えるのは最初の周の修正役の節（G1_FIRST。fix-ruled でない方）の最初の回の中の LOCAL_AGENT の started だけ。最初の回の
    終わりはその節の最初の node_completed か node_failed（無ければ全部が最初の回）。受け付けの拒否の後の出し直しで起こし直した
    下請けは、その拒否を fix_rejects に数えたので数えない（2 重にしない）。
  - 裁定の後の 2 回目（fix-ruled）の下請けは数えない。裁定の後の 2 回目はどの形でも作り直しに数えず（裁定は報告だけ）、2 回目の
    受け付けの拒否は fix_rejects でどの形も同じに数える。
  - 項目ごとの 2 本（実装役と審査役）を超えた分を 2 本で 1 回。項目は最初の周に下請けを起こした項目の数: 修正案の項目のうち単位が
    輪に渡した単位（輪の状態の open_units）と重なる物と、どの項目にも無い直す義務の単位（open_units から excused を除いた物。
    fixrules.g1_values の owed）が在れば残りの 1 項目
    （fixrules.G1_REST。その 2 本は作り直しにしない）。輪の状態が無ければ修正案の項目の数。行の items（項目あたりの比べの
    分母）はどの腕も修正案の項目の数のままで、この数に替えない。
  - 下請けの数は task_id の数で、起き直した下請けの 2 行目の started を数えない。
- 裁定（rulings）・申し出（divergences）: 各周の食い違いの控え（conflict.FILE）の行を、裁定は語ごと（conflict.DECISIONS の順。
  案の項目そのものを誤りと裁く fix_plan_item も 1 語）、申し出は 211 の種類ごと（conflict.kind_counts。DIV_KINDS の順）に数える。
  種類の無い前の形の行（conflict.UNSET）は UNKINDED に数える。0 の語は出さない。どちらも報告だけ（verdict の report_only）。
- red_green_checked: 受け付けが受けた回に確かめなかった理由を載せる盤面の trace（fixgates.SKIPPED_OP。fixgates.unchecked の
  決まりで、義務の外の項目の OUT_OF_DUTY は除く）に行が 1 つでも在るか、輪の状態が無い（実行器の無い run）なら偽。拒んだ回の
  帳面の skipped は数えない（受け付けが受けた回だけを見る）。平の run（current）は束が赤緑を当てないので None（当てない。確かめたとは数えない）。

待ちの損（wait。依頼 243 の並べの 3 段目と線の木の 6 節の残り。docs/plans/2026-10-07-overlap-lanes.md の 4 節）: 下請け（Agent）を同時に
起こした一束について「一番遅い下請けの時間 − 下請けの時間の平均」を、節（step_name の最後の区切り。plan-review・tdd・fix など）ごとに
足した物。出どころは Archon の出来事の task_activity（task_type LOCAL_AGENT の started と、同じ task_id の completed・failed・stopped。
時間は行の created_at の差。秒の粒）。束は同じ step_name の started の並びで、束の誰かが終わった後の started から次の束にする
（同じメッセージの同時の起こしは、どの下請けも終わる前に全部 started が出る）。終わりの行の無い下請けは数えない。採否の判定
（verdict）には使わない。欄の形を本物の run で確かめるまで出力の verified は偽（WAIT_VERIFIED。確かめる物: 並べの周の起こしで
started が下請けの数だけ並び、completed が同じ task_id で出ること）。
TDD の輪の並べは下請けでなく枝ごとの Archon の節（tdd-lane-loop-<n>。docs/plans/2026-10-07-lane-nodes.md）なので、同じ include の
枝の輪の node_completed（data.timing.durationMs）を 1 束として段 LANE_STAGE に足す（lane_wait。時間の欄の無い輪は数えない）。
修正役の並べも同じ形の Archon の節（fix-lane-loop-<n>。docs/plans/2026-10-07-fix-lane-nodes.md）で、前の形の修正役の Agent の下請けの
束（段 fix）は起きないので、枝の輪の束を別の段 FIX_LANE_STAGE に足す。

比べの条件（計画の採否の決まりの 6）: current の腕は修正の段に修正案の欄を渡さないので、束の test_edits も修正案の書き換えの
名指し（rewrite_tests）を許しにしない（fixgates。preflight F15）。要る既存テストの書き換えは current では抜けに数えられうる。
vs_current は報告だけで決定に使わない。

判定の前提（preflight F21）: 測る関数が頼る欄の形（FIELDS_CHECKED）を最初の試しの run（af と g1 を 1 本ずつ）の実物で確かめる
まで、verdict は incomplete を返し、確かめていない印を unverified に名指す。報告と読んだ証拠の印（report.COST_FIELD_VERIFIED・
reads.EVENTS_VERIFIED）とは別の表（あちらは別の物を見る）。各印を真にする前に見る物:
- node_kind_cost: af の run の archon.db で、修正の工程の AI の節（fixing__fix-loop.fix など）の node_completed の data.node.kind が
  agent で、data.spend.costUsd が {source: provider, value: 数} であること。輪の節（fixing__fix-loop など）は kind が loop_group
  で、その費用が中の AI の節の費用の和であること（足していないことの根拠）。同じ節を 2 回起こした run（受け付けの出し直し）で、
  2 回目の costUsd が 1 回分（累積でない）であること。
- tool_outcome_refusal: af の run の TDD の役（fixing__tdd-loop.tdd）が Skill を呼んだなら、その tool_called と同じ
  tool_call_id の tool_completed の tool_outcome が error であること（柵が拒んだ呼び出しの記録の形）。呼ばなかった run では
  真にしない（別の run で確かめる）。
- local_agent_start: g1 の run の修正役（fixing__fix-loop.fix）が Agent を呼んだ回ごとに、同じ step_name の task_activity に
  activity started・task_type local_agent の行が 1 行出ること。下請けの起動の数と started の行の数が合うこと。
  あわせて、各回の started の行が、同じ回の fix の node_completed より event_order で前に並ぶこと（g1 の作り直しは最初の回の
  起動だけを数えるので、後に書かれると 0 と数える）。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sqlite3
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

PACK = pathlib.Path(__file__).resolve().parents[1]
for _p in (PACK / "blk-fix" / "lib", PACK / ".shared" / "core"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import adapter  # noqa: E402
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import conflict  # noqa: E402
import deltamarks  # noqa: E402
import entry  # noqa: E402
import fixgates  # noqa: E402
import fixture  # noqa: E402
import planbrief  # noqa: E402
import planmarks  # noqa: E402
import report  # noqa: E402
import script_io  # noqa: E402
import scopes  # noqa: E402
import seat  # noqa: E402
import spseam  # noqa: E402

FIX_STAGE = ("fixing__", "reviewing__", "refixing__")
MIN_FIXTURES = 3
COST_MARGIN = 1.10
G1_MARGIN = 0.90
# 修正の形（腕）の語と前の版の包みの柵の表（2026-10-09 に消した .shared/core/fixshape.py の物。前の版の盤面を測るためだけ）
ARMS = ("current", "af", "g3", "g1")
PLAIN_ARM, G1_ARM, SEAT_ARM = "current", "g1", "g3"
SHAPE_KEY = "fix_shape"                # 前の版の start の控えの鍵
DENY = (("Skill", seat.SKILL_NODES, frozenset({SEAT_ARM})), ("Agent", seat.AGENT_NODES, frozenset({G1_ARM, SEAT_ARM})))
AI_KIND = "agent"                      # node_completed の data.node.kind のうち AI の節
REFUSED = "error"                      # tool_completed の tool_outcome のうち、呼び出しが走らなかった（拒まれた）印
TDD_NODES = ("tdd", "tdd-rest")        # TDD の輪の役の印の名（step_name の最後の区切り。並べの後の順の輪の役 tdd-rest も）
LANE_PREFIX = "tdd-lane-"              # 並べの枝の役の印の名の頭（tdd-lane-<n>。枝の控えの calls と数え合わせる）
JOIN_PHASE = "lanes"                   # 輪の calls のうち並べを締めた節 tdd-join の行（AI の節でない）
LANE_LOOP = "tdd-lane-loop-"           # 並べの枝の輪の節の名の頭（待ちの損の束。lane_wait）
LANE_STAGE = "tdd-lanes"               # 待ちの損の段の名（枝の輪の束）
FIX_LANE_LOOP = "fix-lane-loop-"       # 修正役の並べの枝の輪の節の名の頭（lane_wait の loop。docs/plans/2026-10-07-fix-lane-nodes.md）
FIX_LANE_STAGE = "fix-lanes"           # 修正役の並べの枝の輪の束の段の名
FIX_REJECTS = f"{script_io.REJECT_PREFIX}accept_fix-*.txt"   # 修正の受け付けの拒否の本文（scope の根。script_io._write_reason）
REVIEW_NODES = ("p3.delta_review", "p3.delta_review2")      # 差分の審査の節（出力の faces が受け付けた穴）
TOOLS = ("Skill", "Agent")
UNKINDED = "unkinded"                  # 種類の無い申し出（211 の前の形。conflict.UNSET の数）
DECISIONS = ("keep_g3", "switch_to_af", "fix_gates_first", "incomplete")
METRICS = ("redo_per_item", "cost_per_item")
LOCAL_AGENT = "local_agent"            # task_activity の task_type のうち下請け（Agent）の起動
G1_FIRST = "fix"                       # g1 の作り直しを数える最初の周の修正役の節（seat.AGENT_NODES のうち fix-ruled でない方）
NODE_ENDS = ("node_completed", "node_failed")   # 節の 1 回の終わり
VERDICT_FAILS = ("compliance_fails", "quality_fails")   # redo のうち差分の審査の 2 判定の fail の数（redo_total に足さない）
# 測る関数が頼る欄の形の印（最初の試しの run で確かめたら真にする。何を見るかはモジュールの頭）。偽が 1 つでも在れば verdict は incomplete
FIELDS_CHECKED = {"node_kind_cost": False, "tool_outcome_refusal": False, "local_agent_start": False}
WAIT_VERIFIED = False                  # 待ちの損の欄の形を本物の run で確かめたら真にする（モジュールの頭の「待ちの損」）
TASK_ENDS = ("completed", "failed", "stopped")   # task_activity の終わりの印


# ---------------------------------------------------------------- 前の版の盤面の修正の形
def _shape_at(board) -> str:
    """盤面の修正の形（腕）: start の控え（fixture.START_REL）の鍵 SHAPE_KEY。控えが無い・鍵が無いなら g3（形が g3 だけになった後の
    盤面）。読めない・JSON の object でない・語の外は ValueError（黙って既定にしない）"""
    path = pathlib.Path(board) / fixture.START_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SEAT_ARM
    except (OSError, ValueError) as e:
        raise ValueError(f"start の控え {path} が読めない（{e}）") from None
    if not isinstance(doc, dict):
        raise ValueError(f"start の控え {path} が JSON の object でない")
    shape = doc.get(SHAPE_KEY, SEAT_ARM)
    if shape not in ARMS:
        raise ValueError(f"start の控え {path} の {SHAPE_KEY}={shape!r} は知らない値（{' / '.join(ARMS)}）")
    return shape


def _denied(shape: str, node: str) -> tuple:
    """前の版の包みが形 shape の盤面で印 node の役に拒んだ道具（表 DENY の順。座の節は g3 の外で Skill、修正役は g1 と g3 の外で Agent）"""
    return tuple(dict.fromkeys(tool for tool, nodes, allowed in DENY if node in nodes and shape not in allowed))


# ---------------------------------------------------------------- Archon の出来事
def _events(db, run_id: str) -> tuple[str, list[dict]]:
    """(run の status, 出来事の行 [{event_type, step_name, data}]（event_order の順）)。db は読むだけで開く。run が無ければ ValueError"""
    uri = pathlib.Path(db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        got = con.execute("SELECT status FROM remote_agent_workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if got is None:
            raise ValueError(f"archon.db {db} に run {run_id} が無い")
        rows = con.execute("SELECT event_type, step_name, data FROM remote_agent_workflow_events WHERE workflow_run_id = ? "
                           "ORDER BY event_order, rowid", (run_id,)).fetchall()
    finally:
        con.close()
    out = []
    for kind, step, data in rows:
        try:
            doc = json.loads(data or "{}")
        except ValueError:
            doc = {}
        out.append({"event_type": kind, "step_name": step or "", "data": doc if isinstance(doc, dict) else {}})
    return str(got[0] or ""), out


def _task_rows(db, run_id: str) -> list[dict]:
    """task_activity の行 [{step_name, data, at（created_at の秒）}]（event_order の順）。db は読むだけで開く。run が無ければ ValueError"""
    uri = pathlib.Path(db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        if con.execute("SELECT 1 FROM remote_agent_workflow_runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise ValueError(f"archon.db {db} に run {run_id} が無い")
        rows = con.execute("SELECT step_name, data, created_at FROM remote_agent_workflow_events WHERE workflow_run_id = ? "
                           "AND event_type = 'task_activity' ORDER BY event_order, rowid", (run_id,)).fetchall()
    finally:
        con.close()
    out = []
    for step, data, at in rows:
        try:
            doc = json.loads(data or "{}")
            when = datetime.datetime.fromisoformat(str(at).replace(" ", "T").rstrip("Z")).timestamp()
        except (TypeError, ValueError):
            continue
        out.append({"step_name": step or "", "data": doc if isinstance(doc, dict) else {}, "at": when})
    return out


def wait_loss(rows: list) -> dict:
    """task_activity の行（_task_rows の形）から段ごとの待ちの損（モジュールの頭）。
    {verified, stages: {節の名: {batches: [{n, max, mean, loss}], loss}}, total}（秒。小数 1 桁）"""
    by_step = {}
    for r in rows:
        by_step.setdefault(r["step_name"], []).append(r)
    stages = {}
    for step, evs in by_step.items():
        starts, ends, batches, cur = {}, {}, [], []
        for e in evs:
            d = e["data"]
            tid, act = d.get("task_id"), d.get("activity")
            if act == "started" and d.get("task_type") == LOCAL_AGENT and tid not in starts:
                if any(t in ends for t in cur):
                    batches.append(cur)
                    cur = []
                cur.append(tid)
                starts[tid] = e["at"]
            elif act in TASK_ENDS and tid in starts and tid not in ends:
                ends[tid] = e["at"]
        if cur:
            batches.append(cur)
        got = []
        for b in batches:
            secs = [ends[t] - starts[t] for t in b if t in ends]
            if secs:
                top, mean = max(secs), sum(secs) / len(secs)
                got.append({"n": len(secs), "max": round(top, 1), "mean": round(mean, 1), "loss": round(top - mean, 1)})
        if got:
            row = stages.setdefault(report._step_name(step), {"batches": [], "loss": 0.0})
            row["batches"] += got
            row["loss"] = round(row["loss"] + sum(x["loss"] for x in got), 1)
    return {"verified": WAIT_VERIFIED, "stages": stages, "total": round(sum(x["loss"] for x in stages.values()), 1)}


def lane_wait(events: list, loop: str = LANE_LOOP) -> list:
    """枝の輪の束 [{n, max, mean, loss}]（include ごとに 1 束。同じ include の <loop><n>（既定は tdd-lane-loop-<n>。修正役の並べは
    FIX_LANE_LOOP）の node_completed の時間）。輪の中の節（step_name が <include>__<loop><n>.<節>）は輪でないので数えない"""
    by = {}
    for e in events:
        name = e["step_name"].rsplit("__", 1)[-1]
        ms = ((e["data"].get("timing") or {}).get("durationMs")) if isinstance(e["data"].get("timing"), dict) else None
        if (e["event_type"] == "node_completed" and name.startswith(loop) and "." not in name
                and isinstance(ms, (int, float))):
            by.setdefault(e["step_name"].rsplit("__", 1)[0] if "__" in e["step_name"] else "", []).append(ms / 1000)
    out = []
    for secs in by.values():
        top, mean = max(secs), sum(secs) / len(secs)
        out.append({"n": len(secs), "max": round(top, 1), "mean": round(mean, 1), "loss": round(top - mean, 1)})
    return out


def with_lanes(got: dict, batches: list, stage: str = LANE_STAGE) -> dict:
    """wait_loss の出力に枝の輪の束（lane_wait）を段 stage（既定は TDD の輪の並べの LANE_STAGE）で足す"""
    if batches:
        got["stages"][stage] = {"batches": batches, "loss": round(sum(b["loss"] for b in batches), 1)}
        got["total"] = round(sum(x["loss"] for x in got["stages"].values()), 1)
    return got


def _in_stage(e: dict, heads=FIX_STAGE) -> bool:
    return e["step_name"].startswith(heads)


def _node(e: dict) -> str:
    return report._step_name(e["step_name"])


def _ai_nodes(events: list) -> list:
    return [e for e in events if e["event_type"] == "node_completed" and _in_stage(e)
            and (e["data"].get("node") or {}).get("kind") == AI_KIND]


def _spend(events: list) -> tuple[dict, dict, list]:
    """({fix_stage, fixing} の費用, {step_name: 秒}, 費用の取れない AI の節の理由)"""
    cost = {"fix_stage": 0.0, "fixing": 0.0}
    secs, whys = {}, []
    for e in _ai_nodes(events):
        v, why = report._event_cost(e)
        if v is None:
            whys.append(f"{e['step_name']}: {why}")
        else:
            cost["fix_stage"] += v
            if _in_stage(e, FIX_STAGE[0]):
                cost["fixing"] += v
        ms = (e["data"].get("timing") or {}).get("durationMs")
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            secs[e["step_name"]] = secs.get(e["step_name"], 0) + ms
    return ({k: round(v, 6) for k, v in cost.items()}, {k: round(v / 1000, 1) for k, v in secs.items()}, whys)


def _tool_calls(events: list, shape: str) -> tuple[dict, dict, int, int]:
    """(混ざり {Skill, Agent}, 拒まれた呼び出し {Skill, Agent}, 修正役の節で起きた下請けの数, そのうち最初の周の修正役の節の
    最初の回の数)。走ったかの見分けと最初の回の決まりはモジュールの頭"""
    outcome = {e["data"].get("tool_call_id"): e["data"].get("tool_outcome") for e in events
               if e["event_type"] == "tool_completed" and e["data"].get("tool_call_id")}
    # 節（step_name）ごとの下請けの task_id（起き直した下請けは同じ task_id の started をもう 1 行出すので、行でなく id で数える。
    # id の無い行は 1 行を 1 つ）・拒む Agent の呼び出しの数・最初の周の修正役の節の最初の回の task_id
    ids, asked, first, ended = {}, {}, set(), set()
    for n, e in enumerate(events):
        at_first = _in_stage(e, FIX_STAGE[0]) and _node(e) == G1_FIRST
        if e["event_type"] in NODE_ENDS and at_first:
            ended.add(e["step_name"])
        if (e["event_type"] == "task_activity" and _in_stage(e) and e["data"].get("activity") == "started"
                and e["data"].get("task_type") == LOCAL_AGENT):
            tid = e["data"].get("task_id") or ("row", n)
            ids.setdefault(e["step_name"], set()).add(tid)
            if at_first and e["step_name"] not in ended:
                first.add(tid)
    starts = {step: len(v) for step, v in ids.items()}
    ran, refused = dict.fromkeys(TOOLS, 0), dict.fromkeys(TOOLS, 0)
    for e in events:
        if e["event_type"] != "tool_called" or not _in_stage(e):
            continue
        name = e["data"].get("tool_name")
        if name not in _denied(shape, _node(e)):
            continue
        if name == "Agent":
            asked[e["step_name"]] = asked.get(e["step_name"], 0) + 1
        else:
            (ran if outcome.get(e["data"].get("tool_call_id")) != REFUSED else refused)[name] += 1
    for step, n in asked.items():
        went = min(n, starts.get(step, 0))
        ran["Agent"] += went
        refused["Agent"] += n - went
    agents = sum(n for step, n in starts.items()
                 if step.startswith(FIX_STAGE[0]) and report._step_name(step) in seat.AGENT_NODES)
    return ran, refused, agents, len(first)


# ---------------------------------------------------------------- 盤面
class _Round:
    """盤面の周 n の読み口（conflict・planmarks に渡す）。work は周の作業ファイルのパスを返すだけで、ディレクトリを作らない"""

    def __init__(self, b, n: int):
        self.dir, self.state, self.record, self.round = b.dir, b.state, b.record, n

    def work(self, name: str) -> pathlib.Path:
        return pathlib.Path(self.dir) / f"r{self.round}" / name


def _json(path: pathlib.Path, gaps: list, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        gaps.append(f"{what} {path} が読めない（{type(e).__name__}）")
        return None


def _fields(rounds: list, gaps: list) -> list:
    """修正案の欄（新しい周から、凍結の印の在る最初の物）。控えが印と食い違えば記録の欠け"""
    for r in reversed(rounds):
        try:
            got = planmarks.frozen(r)
        except planmarks.FieldsBroken as e:
            gaps.append(f"修正案の欄の控えが凍結の印と合わない: {' '.join(str(e).split())}")
            return []
        if got is not None:
            return got
    return []


def _states(board: pathlib.Path, gaps: list) -> list:
    out = []
    for p in sorted(board.glob("tdd-*/state.json")):
        st = _json(p, gaps, "輪の状態")
        if isinstance(st, dict):
            out.append(st)
    return out


def _ledgers(rounds: list, gaps: list) -> list:
    """束の帳面の行 [(周, 行)] を周の順に"""
    rows = []
    for r in rounds:
        for p in scopes.each(r, fixgates.LEDGER):   # 修正のブロックの私物は include ごとの scope の根の周の置き場
            doc = _json(p, gaps, "束の帳面")
            if isinstance(doc, dict):
                rows += [(r.round, x) for x in doc.get("rows") or [] if isinstance(x, dict)]
    return rows


def _fix_rejects(rounds: list) -> int:
    """修正の受け付けの拒否の本文 FIX_REJECTS の数（盤面の根と、どれかの周に登録した scope の根。script_io.scope_dir）"""
    roots = dict.fromkeys(root for r in rounds for root in scopes.scope_roots(r))
    return sum(len(list(root.glob(FIX_REJECTS))) for root in roots)


def _faces(board: pathlib.Path, gaps: list) -> int:
    n = 0
    for p in sorted(board.glob("out/r*/*.json")):
        if p.stem in REVIEW_NODES:
            doc = _json(p, gaps, "差分の審査の出力")
            n += len(doc.get("faces") or []) if isinstance(doc, dict) else 0
    return n


def _rulings(rounds: list, gaps: list) -> tuple[dict, dict]:
    """({裁定の語: 件}, {申し出の種類: 件})（0 の語は出さない。種類の無い前の形の行は UNKINDED）"""
    rulings, kinds = {}, {}
    for r in rounds:
        try:
            rows = conflict.items(r)
            counts = conflict.kind_counts(r)
        except BoardGap as e:   # 控えが読めない・形が違う
            gaps.append(f"周 {r.round} の食い違いの控えが読めない: {' '.join(str(e).split())}")
            continue
        for i in rows:
            d = (i.get("ruling") or {}).get("decision") if isinstance(i.get("ruling"), dict) else None
            if d:
                rulings[d] = rulings.get(d, 0) + 1
        for k, n in counts.items():
            k = UNKINDED if k == conflict.UNSET else k
            if n:
                kinds[k] = kinds.get(k, 0) + n
    order = {d: n for n, d in enumerate(conflict.DECISIONS)}
    korder = {k: n for n, k in enumerate((*conflict.DIV_KINDS, UNKINDED))}
    return (dict(sorted(rulings.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))),
            dict(sorted(kinds.items(), key=lambda kv: (korder.get(kv[0], len(korder)), kv[0]))))


def _writes_rows(b, home) -> tuple[pathlib.Path | None, list | None]:
    """(書き込みの記録のパス, 行)。run の作業ツリーが盤面に無ければ (None, None)、記録が読めなければ (パス, None)"""
    cwd = (b.state.get("inputs") or {}).get("cwd")
    if not cwd:
        return None, None
    path = adapter.writes_path(cwd, home)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return path, None
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return path, out


def _empty_board() -> dict:
    return {"report": False, "items": 0,
            "redo": {"fix_rejects": 0, "tdd_rejects": 0, "battery_rejects": 0, "delta_faces": 0, "refix_rounds": 0,
                     "subagent_redos": 0, "compliance_fails": 0, "quality_fails": 0},
            "rulings": {}, "divergences": {}, "gate_misses": 0, "red_green": False, "tdd_calls": 0}


def _g1_items(fields: list, asked: set, owed: set) -> int:
    """g1 の修正役が最初の周に下請けを起こした項目の数（fixrules.g1_values の項目の決まり。モジュールの頭の subagent_redos）"""
    if not asked:
        return len(fields)
    hit = [f for f in fields if isinstance(f, dict) and asked & set(f.get("unit_keys") or [])]
    covered = {k for f in hit for k in f.get("unit_keys") or []}
    return len(hit) + (1 if owed - covered else 0)


def _board_facts(board: pathlib.Path, shape: str, tdd_done: int, agents: int, first: int, home, gaps: list,
                 lane_done: int = 0) -> dict:
    out = _empty_board()
    out["report"] = (board / report.REPORT_FILE).is_file()
    try:
        b = entry.open_board(board, allow_halted=True)
    except Exception as e:
        gaps.append(f"盤面を開けない: {' '.join(str(e).split())}")
        return out
    rounds = [_Round(b, n) for n in range(1, int(b.round) + 1)]
    plain = shape == PLAIN_ARM
    fields = _fields(rounds, gaps)
    states = _states(board, gaps)
    calls = [c for st in states for c in st.get("calls") or [] if isinstance(c, dict)]
    lane_calls = [c for st in states for c in (st.get("lanes") or {}).get("calls") or [] if isinstance(c, dict)]
    asked = {k for st in states for k in st.get("open_units") or []}
    owed = {k for st in states for k in st.get("open_units") or [] if k not in (st.get("excused") or {})}
    by_ai = [c for c in calls if c.get("phase") != JOIN_PHASE]   # 並べを締めた行は AI の節の起動でない
    if tdd_done != len(by_ai):
        gaps.append(f"tdd・tdd-rest の節の node_completed {tdd_done} 件と輪の calls {len(by_ai)} 行（並べの締めの行を除く）が違う")
    if lane_done != len(lane_calls):
        gaps.append(f"並べの枝の役（{LANE_PREFIX}<n>）の node_completed {lane_done} 件と枝の calls {len(lane_calls)} 行が違う")
    if states and shape != G1_ARM:
        have = {k for st in states for k in (st.get("units") or {})}
        lost = [k for f in fields if isinstance(f, dict) and f.get("route") == "tdd"
                for k in f.get("unit_keys") or [] if k in asked and k not in have]
        if lost:
            gaps.append(f"tdd の項目の単位に輪の単位の行が無い: {'、'.join(dict.fromkeys(lost))}")
    if not plain and fields and not any(scopes.each(r, planbrief.LEDGER) for r in rounds):
        gaps.append("平の run でないのに修正案の欄が在って brief の控え（briefs.json）が無い")
    if shape == G1_ARM and agents:
        path, rows = _writes_rows(b, home)
        if rows is None:
            gaps.append(f"g1 で Agent が {agents} 回走ったのに書き込みの記録が無い（{path or '盤面に run の作業ツリーが無い'}。"
                        "--adapter-home で run の包みの家を名指す）")
        elif not any(r.get("agent_id") for r in rows) and any(r.get("tool_name") == "declared" for r in rows):
            gaps.append(f"g1 で Agent が {agents} 回走ったのに、書き込みの記録に下請けの行（agent_id）が無く申告（bash_writes）"
                        "だけが在る（フックの欠けを自己申告が隠した疑い）")
    rows = _ledgers(rounds, gaps)
    items = len(fields) if fields else len(asked)
    battery = len({(n, r.get("pass"), r.get("attempt")) for n, r in rows})
    out["items"] = items
    out["redo"] = {"fix_rejects": max(0, _fix_rejects(rounds) - battery),
                   "tdd_rejects": sum(1 for c in calls + lane_calls if c.get("ok") is False),
                   "battery_rejects": battery,
                   "delta_faces": _faces(board, gaps),
                   "refix_rounds": sum(1 for r in report.trace_rows(b, "done") if r.get("instance") in report.REFIX_NODES),
                   "subagent_redos": max(0, first - 2 * _g1_items(fields, asked, owed)) // 2 if shape == G1_ARM else 0,
                   **_verdict_fails(b)}
    out["rulings"], out["divergences"] = _rulings(rounds, gaps)
    out["gate_misses"] = len(rows)
    out["red_green"] = None if plain else bool(states) and not report.trace_rows(b, fixgates.SKIPPED_OP)
    return out


def _verdict_fails(b) -> dict:
    """差分の審査が受けた 2 判定（盤面の trace の deltamarks.SAVED_OP。受けた回ごとに 1 行）のうち fail の数（VERDICT_FAILS の鍵）"""
    rows = report.trace_rows(b, deltamarks.SAVED_OP)
    return {k: sum(1 for r in rows if r.get(key) == "fail") for k, key in zip(VERDICT_FAILS, deltamarks.KEYS)}


def row(db, run_id: str, board, *, adapter_home=None) -> dict:
    """1 run の行（モジュールの頭の語）。adapter_home は書き込みの記録の置き場の家（省けば包みの既定の家。adapter.home）。
    腕を回したのと同じ works の木（同じ commit）から測る（盤面を開く表の sha・形の語・保守量は測る側の works から読む）"""
    board = pathlib.Path(board)
    status, events = _events(db, run_id)
    gaps = []
    try:
        shape = _shape_at(board)
    except ValueError as e:
        gaps.append(f"修正の形の控えが読めない: {' '.join(str(e).split())}")
        shape = ""
    mark = fixture.adopted(board)
    cost, secs, whys = _spend(events)
    gaps += [f"修正の工程の AI の節の費用（costUsd）が取れない: {w}" for w in whys]
    ran, refused, agents, first = _tool_calls(events, shape)
    tdd_done = sum(1 for e in _ai_nodes(events) if _in_stage(e, FIX_STAGE[0]) and _node(e) in TDD_NODES)
    lane_done = sum(1 for e in _ai_nodes(events) if _in_stage(e, FIX_STAGE[0]) and _node(e).startswith(LANE_PREFIX))
    facts = _board_facts(board, shape, tdd_done, agents, first, adapter_home, gaps, lane_done)
    return {"run_id": run_id, "shape": shape, "fixture": str((mark or {}).get("source_run") or ""),
            "complete": status == "completed" and facts["report"], "items": facts["items"],
            "redo": facts["redo"], "redo_total": sum(v for k, v in facts["redo"].items() if k not in VERDICT_FAILS),
            "cost_usd": cost, "secs": secs,
            "rulings": facts["rulings"], "divergences": facts["divergences"], "gate_misses": facts["gate_misses"],
            "record_gaps": gaps, "contamination": ran, "refused": refused, "red_green_checked": facts["red_green"]}


# ---------------------------------------------------------------- 保守量
def _lines(text: str) -> int:
    return len(text.splitlines())


def _file_lines(paths) -> int:
    return sum(_lines(pathlib.Path(p).read_text(encoding="utf-8")) for p in paths)


def _seam_lines(ids, src: pathlib.Path, seams: dict) -> int:
    """節 ids の包むファイルの行と、効く所・効かない所の箇条の行"""
    n = 0
    for sid in dict.fromkeys(ids):
        sec = seams[sid]
        n += _file_lines(src / f for f in sec.get("files") or [])
        n += len(sec.get("applies") or []) + len(sec.get("not_applies") or [])
    return n


def maintenance(root) -> dict:
    """腕ごとの、その腕で読む文の行の数 {current, af, g3, g1}。own は修正の工程の works の決まりのファイル（blk-fix/rules/*.md・
    blk-delta/commands/delta-review.md・blk-refix/rules/*.md）で、current と af は own。g3 は own と、座（seat.SEATS）の節の包む
    ファイルと箇条、読み替え（unattended.md）。g1 は own と、implementer・task-review の部品と箇条、修正役の節（seat.g1_section。
    読み替えを含む）。写しが固定と合わなければ ValueError"""
    root = pathlib.Path(root)
    own = _file_lines([*sorted((root / "blk-fix" / "rules").glob("*.md")), root / "blk-delta" / "commands" / "delta-review.md",
                       *sorted((root / "blk-refix" / "rules").glob("*.md"))])
    _, src = seat.pinned()
    seams = spseam.load_seams(spseam.BORROW_DIR)
    g3 = own + _seam_lines(seat.SEATS.values(), src, seams) + _file_lines([spseam.BORROW_DIR / spseam.OVERLAY_FILE])
    g1 = own + _seam_lines(("implementer", "task-review"), src, seams) + _lines(seat.g1_section([]))
    return {"current": own, "af": own, "g3": g3, "g1": g1}


# ---------------------------------------------------------------- 採否の判定
def _why_invalid(r: dict) -> list[str]:
    why = []
    if not r.get("complete"):
        why.append("run が終わっていない（Archon の run が completed でないか、盤面に報告が無い）")
    if r.get("shape") not in ARMS:
        why.append(f"形 {r.get('shape')!r} が腕の語でない")
    if not r.get("fixture"):
        why.append("固定材料から始めた run でない")
    mixed = {k: n for k, n in (r.get("contamination") or {}).items() if n}
    if mixed:
        why.append("混ざり（その形で拒む道具が走った: " + "・".join(f"{k} {n} 件" for k, n in mixed.items()) + "。柵が効いていない）")
    if r.get("record_gaps"):
        why.append(f"記録の欠け {len(r['record_gaps'])} 件")
    if r.get("shape") != PLAIN_ARM and r.get("red_green_checked") is not True:
        why.append("束の赤緑が回っていない（実行器が無いか、確かめずに通した回が在る）")
    if not isinstance(r.get("items"), int) or r["items"] <= 0:
        why.append("項目の数が 0")
    return why


def _le(a: float, b: float) -> bool:
    return round(a, 9) <= round(b, 9)


def _sum_dicts(ds) -> dict:
    out = {}
    for d in ds:
        for k, v in (d or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def verdict(rows: list[dict]) -> dict:
    """計画の「採否の決まり」のとおりに判じる。返り {decision, missing, invalid, per_item, misses, import_from_g1, vs_current,
    report_only, fixtures, unverified}。同じ（腕・固定材料）に有効な行が 2 つ在れば後の行（回し直し）を使う"""
    unverified = [k for k, ok in FIELDS_CHECKED.items() if not ok]
    fixtures = sorted({r.get("fixture") for r in rows if r.get("fixture")})
    invalid, valid = [], {}
    for r in rows:
        why = _why_invalid(r)
        if why:
            invalid.append([str(r.get("run_id") or ""), "・".join(why)])
        else:
            valid[(r["shape"], r["fixture"])] = r
    missing = [[a, f] for f in fixtures for a in ARMS if (a, f) not in valid]
    by_arm = {a: [valid[(a, f)] for f in fixtures if (a, f) in valid] for a in ARMS}
    per_item, misses = {}, {}
    for a, rs in by_arm.items():
        items = sum(r["items"] for r in rs)
        per_item[a] = ({"redo": round(sum(r["redo_total"] for r in rs) / items, 6),
                        "cost": round(sum(r["cost_usd"]["fix_stage"] for r in rs) / items, 6)} if items else None)
        misses[a] = sum(r["gate_misses"] for r in rs)
    decision = "incomplete" if unverified or missing or len(fixtures) < MIN_FIXTURES else ""
    if not decision:
        g3, af = per_item["g3"], per_item["af"]
        if misses["g3"] and misses["af"]:
            decision = "fix_gates_first"
        elif misses["g3"] or misses["af"]:   # 抜けの在る腕は既定にしない（決まり 3）。比べは抜けが 0 の腕どうしだけ
            decision = "switch_to_af" if misses["g3"] else "keep_g3"
        elif _le(g3["redo"], af["redo"]) and _le(g3["cost"], COST_MARGIN * af["cost"]):
            decision = "keep_g3"
        else:
            decision = "switch_to_af"
    win = {"keep_g3": "g3", "switch_to_af": "af"}.get(decision)
    imports, vs = [], {}
    if win:
        w, g1, cur = per_item[win], per_item["g1"], per_item["current"]
        if not misses["g1"]:
            if round(g1["redo"], 9) < round(w["redo"], 9):
                imports.append(METRICS[0])
            if _le(g1["cost"], G1_MARGIN * w["cost"]):
                imports.append(METRICS[1])
        vs = {METRICS[0]: round(w["redo"] - cur["redo"], 6), METRICS[1]: round(w["cost"] - cur["cost"], 6)}
    report_only = {
        "secs": {a: round(sum(sum(r["secs"].values()) for r in rs), 1) for a, rs in by_arm.items()},
        "fixing_cost": {a: round(sum(r["cost_usd"]["fixing"] for r in rs), 6) for a, rs in by_arm.items()},
        "rulings": {a: _sum_dicts(r.get("rulings") for r in rs) for a, rs in by_arm.items()},
        "divergences": {a: _sum_dicts(r.get("divergences") for r in rs) for a, rs in by_arm.items()},
        "maintenance": maintenance(PACK),
    }
    return {"decision": decision, "missing": missing, "invalid": invalid, "per_item": per_item, "misses": misses,
            "import_from_g1": imports, "vs_current": vs, "report_only": report_only, "fixtures": fixtures,
            "unverified": unverified}


# ---------------------------------------------------------------- 入口
USAGE = ("usage: fixmeasure.py row [--adapter-home <包みの家>] <archon.db> <run_id> <盤面> | verdict <行の jsonl> | maintenance"
         " | wait <archon.db> <run_id>")


def _read_rows(path) -> list[dict]:
    rows = []
    for n, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        doc = json.loads(line)
        if not isinstance(doc, dict):
            raise ValueError(f"{path} の {n} 行目が JSON の object でない")
        rows.append(doc)
    return rows


def main(argv: list[str]) -> int:
    home = None
    if argv[:2] == ["row", "--adapter-home"] and len(argv) >= 3:
        home, argv = argv[2], ["row", *argv[3:]]
    try:
        if argv[:1] == ["row"] and len(argv) == 4:
            if not pathlib.Path(argv[1]).is_file():
                raise ValueError(f"archon.db {argv[1]} が無い")
            out = json.dumps(row(argv[1], argv[2], argv[3], adapter_home=home), ensure_ascii=False)
        elif argv[:1] == ["verdict"] and len(argv) == 2:
            out = json.dumps(verdict(_read_rows(argv[1])), ensure_ascii=False, indent=1)
        elif argv[:1] == ["wait"] and len(argv) == 3:
            if not pathlib.Path(argv[1]).is_file():
                raise ValueError(f"archon.db {argv[1]} が無い")
            events = _events(argv[1], argv[2])[1]
            got = with_lanes(wait_loss(_task_rows(argv[1], argv[2])), lane_wait(events))
            out = json.dumps(with_lanes(got, lane_wait(events, FIX_LANE_LOOP), FIX_LANE_STAGE), ensure_ascii=False)
        elif argv == ["maintenance"]:
            out = json.dumps(maintenance(PACK), ensure_ascii=False)
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except (OSError, ValueError, sqlite3.Error) as e:
        print(f"fixmeasure: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
