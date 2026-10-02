"""works/dev/fixmeasure.py — 修正の形の腕ごとの測りと採否の判定（計画 220 Task 8。開発の殻。読むだけで何も書かない）。

  python3 fixmeasure.py row [--adapter-home <包みの家>] <archon.db> <run_id> <盤面>   1 run の行（JSON の 1 行）
  python3 fixmeasure.py verdict <行の jsonl>             採否の判定（JSON）
  python3 fixmeasure.py maintenance                      腕ごとの保守量（JSON）

誤り（引数・db が開けない・run が無い・jsonl が読めない）は標準エラーに 1 行で 2、ほかは 0。網に出ない。時刻を入れず、辞書は
書いた順（同じ入力なら同じ出力）。--adapter-home は run の包みの家（書き込みの記録 writes.jsonl の置き場の根。試しの run は
殻の家の下の家を使い、測る側の env の WORKS_ADAPTER_HOME と違う）。盤面も Archon も家を書かないので、省けば測る側の env の家。

語:
- 腕: 修正の形（fixshape.SHAPES の current・af・g3・g1）ごとの run。固定材料: 同じ依頼を同じ所から始める盤面の写し
  （行の fixture は元の run の id。固定材料の印は fixshape.recorded が読む）。
- 修正の工程: Archon の出来事の step_name の頭が FIX_STAGE の節。費用と時間は AI の節（data.node.kind が agent）だけを足す
  （輪の節 loop_group の node_completed は中の AI の節の費用の和を持つので、足すと 2 重になる。実物の archon.db で見た）。
- 混ざり（contamination）: 修正の工程の節の tool_called のうち、その形でその節に拒む道具（fixshape.denied_tools。節は
  step_name の最後の区切り）の呼び出しで、走った物。柵が拒んだ呼び出しも skills: の一覧に残るので tool_called に出る（Task 2 の
  審査 M5）。走ったかの見分けは道具ごと:
  - Skill: 同じ tool_call_id の tool_completed の tool_outcome が REFUSED（error）なら refused に数え、混ざりにしない。完了の行の
    無い呼び出しは走ったかを言えないので混ざりに数える。
  - Agent: tool_outcome は下請けが走っても error になりうるので見ない。同じ節の task_activity の started・task_type LOCAL_AGENT
    （下請けが起きた印）の数までを走った物、残りを refused に数える。
  permissions.deny の素の Skill・Agent が実地で拒むかはまだ確かめていない（Task 3 の審査）——af・current・g1 の行で走った Skill
  は混ざりに出る（最初の試しの run で refused に出るかを見る。下の FIELDS_CHECKED）。
- 記録の欠け（record_gaps）: 盤面を開けない・形の控えが読めない・start の控えに fix_shape が無い（前の版の盤面。形は af と読む）・
  tdd の節の node_completed の数と輪の calls の行の数が違う・tdd の項目の単位（輪に渡した単位のうち）に輪の単位の行が無い（g1 は
  輪を回さないので見ない）・平の run でないのに修正案の欄が在って brief の控えが無い・修正の工程の AI の節の費用が取れない・g1 で
  Agent が走ったのに書き込みの記録に下請けの行（agent_id）が無く、申告（bash_writes。記録の declared の行）だけが在る（フックの
  欠けを自己申告が隠した疑い。Task 7 の審査 M1）・g1 で Agent が走ったのに書き込みの記録が無い（家の取り違えか包みの無い起動。
  黙って空にしない）。g1 の「Agent が走った」は修正役の節の LOCAL_AGENT の started の数。
- 作り直し（redo）: fix_rejects は修正の受け付け（fix-accept・fix-ruled-accept。どちらも accept_fix）の拒否の本文のファイル
  FIX_REJECTS の数（修正の受け付けは role-rejects.json を書かない）から battery_rejects を引いた物（束の拒否も同じ本文を書くので
  2 重に数えない）、tdd_rejects は輪の calls の ok が偽の行、battery_rejects は
  束の行の在る受け付けの回（周・pass・attempt。preflight F23）、delta_faces は差分の審査（p3.delta_review・p3.delta_review2）が
  受け付けた穴、refix_rounds は手直し（report.REFIX_NODES）を受け付けた回（盤面の trace の done の行）、subagent_redos は g1 の
  下請けの作り直しの往復（修正役の節の LOCAL_AGENT の started のうち、項目ごとの 2 本（実装役と審査役）を超えた分を 2 本で 1 回。
  g1 の作り直しは修正役の中で回り、ほかの形の拒否の数に出ないので、比べを揃える。ほかの形は 0）。
- red_green_checked: 受け付けが受けた回に確かめなかった理由を載せる盤面の trace（fixgates.SKIPPED_OP。fixgates.unchecked の
  決まりで、義務の外の項目の OUT_OF_DUTY は除く）に行が 1 つでも在るか、輪の状態が無い（実行器の無い run）なら偽。拒んだ回の
  帳面の skipped は数えない（受け付けが受けた回だけを見る）。平の run（current）は束が赤緑を当てないので None（当てない。確かめたとは数えない）。

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
"""
from __future__ import annotations

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
import entry  # noqa: E402
import fixgates  # noqa: E402
import fixshape  # noqa: E402
import planbrief  # noqa: E402
import planmarks  # noqa: E402
import report  # noqa: E402
import script_io  # noqa: E402
import seat  # noqa: E402
import spseam  # noqa: E402

FIX_STAGE = ("fixing__", "reviewing__", "refixing__")
MIN_FIXTURES = 3
COST_MARGIN = 1.10
G1_MARGIN = 0.90
ARMS = fixshape.SHAPES
AI_KIND = "agent"                      # node_completed の data.node.kind のうち AI の節
REFUSED = "error"                      # tool_completed の tool_outcome のうち、呼び出しが走らなかった（拒まれた）印
TDD_NODE = "tdd"                       # TDD の役の印の名（step_name の最後の区切り）
FIX_REJECTS = f"{script_io.REJECT_PREFIX}accept_fix-*.txt"   # 修正の受け付けの拒否の本文（盤面の根。script_io._write_reason）
REVIEW_NODES = ("p3.delta_review", "p3.delta_review2")      # 差分の審査の節（出力の faces が受け付けた穴）
TOOLS = ("Skill", "Agent")
UNKINDED = "unkinded"                  # 種類の無い申し出（211 の前の形。conflict.UNSET の数）
DECISIONS = ("keep_g3", "switch_to_af", "fix_gates_first", "incomplete")
METRICS = ("redo_per_item", "cost_per_item")
LOCAL_AGENT = "local_agent"            # task_activity の task_type のうち下請け（Agent）の起動
# 測る関数が頼る欄の形の印（最初の試しの run で確かめたら真にする。何を見るかはモジュールの頭）。偽が 1 つでも在れば verdict は incomplete
FIELDS_CHECKED = {"node_kind_cost": False, "tool_outcome_refusal": False, "local_agent_start": False}


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


def _tool_calls(events: list, shape: str) -> tuple[dict, dict, int]:
    """(混ざり {Skill, Agent}, 拒まれた呼び出し {Skill, Agent}, 修正役の節で起きた下請けの数)。走ったかの見分けはモジュールの頭"""
    outcome = {e["data"].get("tool_call_id"): e["data"].get("tool_outcome") for e in events
               if e["event_type"] == "tool_completed" and e["data"].get("tool_call_id")}
    starts, asked = {}, {}   # 節（step_name）ごとの下請けの起動の印の数・拒む Agent の呼び出しの数
    for e in events:
        if (e["event_type"] == "task_activity" and _in_stage(e) and e["data"].get("activity") == "started"
                and e["data"].get("task_type") == LOCAL_AGENT):
            starts[e["step_name"]] = starts.get(e["step_name"], 0) + 1
    ran, refused = dict.fromkeys(TOOLS, 0), dict.fromkeys(TOOLS, 0)
    for e in events:
        if e["event_type"] != "tool_called" or not _in_stage(e):
            continue
        name = e["data"].get("tool_name")
        if name not in fixshape.denied_tools(shape, _node(e)):
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
                 if step.startswith(FIX_STAGE[0]) and report._step_name(step) in fixshape.AGENT_NODES)
    return ran, refused, agents


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
        doc = _json(r.work(fixgates.LEDGER), gaps, "束の帳面")
        if isinstance(doc, dict):
            rows += [(r.round, x) for x in doc.get("rows") or [] if isinstance(x, dict)]
    return rows


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
                     "subagent_redos": 0},
            "rulings": {}, "divergences": {}, "gate_misses": 0, "red_green": False, "tdd_calls": 0}


def _board_facts(board: pathlib.Path, shape: str, tdd_done: int, agents: int, home, gaps: list) -> dict:
    out = _empty_board()
    out["report"] = (board / report.REPORT_FILE).is_file()
    try:
        b = entry.open_board(board, allow_halted=True)
    except Exception as e:
        gaps.append(f"盤面を開けない: {' '.join(str(e).split())}")
        return out
    rounds = [_Round(b, n) for n in range(1, int(b.round) + 1)]
    plain = shape == fixshape.PLAIN
    fields = _fields(rounds, gaps)
    states = _states(board, gaps)
    calls = [c for st in states for c in st.get("calls") or [] if isinstance(c, dict)]
    asked = {k for st in states for k in st.get("open_units") or []}
    if tdd_done != len(calls):
        gaps.append(f"tdd の節の node_completed {tdd_done} 件と輪の calls {len(calls)} 行が違う")
    if states and shape != seat.G1_SHAPE:
        have = {k for st in states for k in (st.get("units") or {})}
        lost = [k for f in fields if isinstance(f, dict) and f.get("route") == "tdd"
                for k in f.get("unit_keys") or [] if k in asked and k not in have]
        if lost:
            gaps.append(f"tdd の項目の単位に輪の単位の行が無い: {'、'.join(dict.fromkeys(lost))}")
    if not plain and fields and not any(r.work(planbrief.LEDGER).is_file() for r in rounds):
        gaps.append("平の run でないのに修正案の欄が在って brief の控え（briefs.json）が無い")
    if shape == seat.G1_SHAPE and agents:
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
    out["redo"] = {"fix_rejects": max(0, len(list(board.glob(FIX_REJECTS))) - battery),
                   "tdd_rejects": sum(1 for c in calls if c.get("ok") is False),
                   "battery_rejects": battery,
                   "delta_faces": _faces(board, gaps),
                   "refix_rounds": sum(1 for r in report.trace_rows(b, "done") if r.get("instance") in report.REFIX_NODES),
                   "subagent_redos": max(0, agents - 2 * items) // 2 if shape == seat.G1_SHAPE else 0}
    out["rulings"], out["divergences"] = _rulings(rounds, gaps)
    out["gate_misses"] = len(rows)
    out["red_green"] = None if plain else bool(states) and not report.trace_rows(b, fixgates.SKIPPED_OP)
    return out


def row(db, run_id: str, board, *, adapter_home=None) -> dict:
    """1 run の行（モジュールの頭の語）。adapter_home は書き込みの記録の置き場の家（省けば包みの既定の家。adapter.home）。
    腕を回したのと同じ works の木（同じ commit）から測る（盤面を開く表の sha・形の語・保守量は測る側の works から読む）"""
    board = pathlib.Path(board)
    status, events = _events(db, run_id)
    gaps = []
    try:
        shape = fixshape.shape_at(board)
        rec = fixshape.recorded(board)
    except ValueError as e:
        gaps.append(f"修正の形の控えが読めない: {' '.join(str(e).split())}")
        shape, rec = "", {"shape": None, "fixture": None}
    else:
        if rec["shape"] is None:
            gaps.append(f"start の控えに {fixshape.KEY} が無い（前の版の盤面。形は {fixshape.BEFORE} と読む）")
    cost, secs, whys = _spend(events)
    gaps += [f"修正の工程の AI の節の費用（costUsd）が取れない: {w}" for w in whys]
    ran, refused, agents = _tool_calls(events, shape)
    tdd_done = sum(1 for e in _ai_nodes(events) if _in_stage(e, FIX_STAGE[0]) and _node(e) == TDD_NODE)
    facts = _board_facts(board, shape, tdd_done, agents, adapter_home, gaps)
    return {"run_id": run_id, "shape": shape, "fixture": str((rec["fixture"] or {}).get("source_run") or ""),
            "complete": status == "completed" and facts["report"], "items": facts["items"],
            "redo": facts["redo"], "redo_total": sum(facts["redo"].values()), "cost_usd": cost, "secs": secs,
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
    if r.get("shape") != fixshape.PLAIN and r.get("red_green_checked") is not True:
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
USAGE = ("usage: fixmeasure.py row [--adapter-home <包みの家>] <archon.db> <run_id> <盤面> | verdict <行の jsonl> | maintenance")


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
