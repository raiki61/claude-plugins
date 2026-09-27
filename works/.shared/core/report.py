"""機械が組む短い報告（P1 計画 Task 27・〔線A計〕T15。仕様 6 節・裁定 TA12・TA15）。AI は書かない。文は機械の定型だけ。

**記録が検証器を通らない run に fixed・no_fix_needed を出す道を作らない**（審査 I3）: build は必ず gate_record で
settle → finalize → run_validator を 1 度踏み、受理集合（report_accepts）の外か、今の周の記録（record_round と converge）が
済んでいなければ record_invalid にする。検証器は validator_runner の包み（board_hook.py）が効く b.run_validator で回す。

口（線 B の報告も呼ぶ。線 B の申し送り 3・TA18。どの head_* も盤面を書かない）:
- OUTCOMES・COST_FIELD_VERIFIED
- gate_record(b) -> {exit, accepted, tail, traces, round_closed}
- decide_outcome(b, gate, *, tests=None, judged=None) -> OUTCOMES の 1 つ
- head_decisions(b, gate, …)（冒頭 1）・head_entry(b, start, *, mid=None)（冒頭 2）・head_stop(b, *, interrupted=None)（冒頭 3）・
  head_reads(board_dir, run_id, *, ci=None)（冒頭 4）・head_where(b)（冒頭 5）・head_cost(board_dir, run_id, *, events, launches)・
  absent_lines(b)（末尾の「このラインに無い節」）
- declared_downgrades(line) -> [{node, what, versus}]（PACK/<line>/downgrades.json。無ければ []）
- cost_rows(events, launches) -> [{node, reported, actual, continued_from}]
- next_request(b, *, tests=None) -> 次の run に渡す依頼 [{where, text}]（依頼の型のまま）
- build(board_dir, *, judged, tests, start, mid=None, ci=None, run_id="", events=None, launches=None, interrupted=None) -> dict
- final_result(machine, ai) -> dict（ラインの出口: 機械の報告の出口に AI の報告の結果を足し、最後の報告のファイルを選ぶ）

盤面の上の名前（最後の関所の答え final-gate-answer.json と止めた口 human:final-gate、止め札の trace の op stop_flag_seen、
並行 PR の外した範囲 pr-excluded.json、再審の差分 rejudge-diff.json）は書き手の模块（ライン・ブロック）を import せずに
ファイルの名前として読む（層 L3 は上の層を import しない。裁定 R59）。書き手と名前を揃えるのは試験（test_report）。

この版で持たない物（報告に書く）: 版の一覧の行（P1 Task 18・19 の works_version・書き出しの manifest が無い）、
第三の目の「方針の岐路」の争点（写し a1202d0 の graph に欄が無い）。費用は書き出し（Task 19）の run_facts の代わりに
Archon の出来事と包みの起動の記録から組む（COST_FIELD_VERIFIED が偽の間は「欄の形は未確認」を添える）。
"""
import datetime
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import conflict  # noqa: E402
from board import BoardGap, DiskBoard, RecordInvalid  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.validator import TRACES, report_accepts  # noqa: E402
import entry  # noqa: E402
import reads  # noqa: E402

PACK = CORE.parents[1]
OUTCOMES = ("fixed", "no_fix_needed", "stopped_by_request", "stopped_by_human", "stopped_by_line", "needs_human",
            "record_invalid", "interrupted")
COST_FIELD_VERIFIED = False   # 出来事に節の費用の欄が載るかを P19 で確かめたら真にする
COST_KEYS = ("cost_usd", "costUsd", "total_cost_usd")   # 出来事の data の費用の欄（推測。P19 で確かめる）
REPORT_FILE = "report.md"
NEXT_REQUEST_FILE = "next-request.json"
NEXT_ORIGIN = "works:report"   # 次の run に渡す依頼の出どころ（accept.check_request の reason）
TAIL_LINES = 20
FINAL_GATE_ANSWER = "final-gate-answer.json"   # 最後の関所の答え {decision, text}（境の節 eyes が b.work に書く。P1 Task 26）
FINAL_GATE_BY = "human:final-gate"             # 最後の関所の stop・reject で止めた盤面の state.stop.by
REQUEST_BY = "request:"                        # 止め札で止めた盤面の state.stop.by の頭
HUMAN_BY = "human:"
LINE_BY = "works:"
ANSWER_BY = "answer"                           # 関所の答えの stop（halted.by）
ADAPTER_BY = "works:adapter"                   # 包みの確かめで止めた盤面の by（h-judge の確かめ・CI の役の柵）
REJUDGE_SESSION_BY = "works:rejudge-session"   # 再審の会話を確かめられずに止めた盤面の by
FLAG_SEEN_OP = "stop_flag_seen"                # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
PR_NODE = "p0.parallel_pr"
PR_EXCLUDED = "pr-excluded.json"               # 並行 PR の外した hunk {node, head, excluded}
REJUDGE_DIFF = "rejudge-diff.json"             # 再審の単位の差分の行の列
DOWNGRADES = "downgrades.json"
DOWNGRADE_KEYS = ("node", "what", "versus")
HEADINGS = ("## 1. 人が決めること", "## 2. 入口・段・決めた人", "## 3. 止めたか", "## 4. 読んだ証拠と包み", "## 5. 見る所")
WHERE = (("判定", "p2.diagnose"), ("修正案", "p2.fix_plan"), ("事前審査", "p2.plan_review"), ("修正", "p3.fix"),
         ("差分の審査", "p3.delta_review"), ("手直し", "p3.delta_fix"), ("2 回目の審査", "p3.delta_review2"),
         ("手直し 2 回目", "p3.delta_fix2"), ("最後のテスト", "p4.ci"))
DIFFS = (("修正の差分", "fix_delta"), ("手直しの差分", "fix_delta2"))
REFIX_NODES = ("p3.delta_fix", "p3.delta_fix2")
INTERRUPTED_HEAD = "run が途中で終わった: 取り消し・abandon・役の出し直しの上限のどれか"
AI_FIRST_NODE = "report.human_items"   # 盤面が報告の役の節を出したか（AI の報告を回すか。ai_report_go）
AI_REPORT_KEYS = ("ok", "reason", "report_file", "cold_check", "record_invalid")   # 最後の出口に写す AI の報告の欄


# ---------------------------------------------------------------- 小道具
def _read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_text(path: pathlib.Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _latest(board_dir: pathlib.Path, name: str) -> pathlib.Path | None:
    """周の作業ファイル r<N>/<name> のうち、周の番号が一番大きい物（周を仮定しない）。無ければ None"""
    found = []
    for p in pathlib.Path(board_dir).glob(f"r*/{name}"):
        tail = p.parent.name[1:]
        if tail.isdigit() and p.is_file():
            found.append((int(tail), p))
    return max(found)[1] if found else None


def _all_rounds(board_dir: pathlib.Path, pattern: str) -> list:
    """周の作業ファイル r<N>/<pattern> の全部（周の順）"""
    rows = []
    for p in pathlib.Path(board_dir).glob(f"r*/{pattern}"):
        tail = p.parent.name[1:]
        if tail.isdigit() and p.is_file():
            rows.append((int(tail), str(p), p))
    return [p for _, _, p in sorted(rows)]


def _output(b, nid: str):
    """節の最新の出力（state.outputs[節] の周の出力）。無ければ None"""
    info = (b.state.get("outputs") or {}).get(nid)
    if not info:
        return None
    return b.output_of_round(nid, info.get("round", b.round))


def _one_line(text) -> str:
    return " ".join(str(text).split())


def _start_doc(b, start) -> dict:
    """start の出口（渡されなければ盤面の r1 の start の控え）"""
    if isinstance(start, dict):
        return start
    return _read_json(b.dir / "r1" / entry.START_FILE, {}) or {}


STOP_AFTER_END_OP = "stop_after_round_end"   # 周を締めた後の止め（最後の関所の stop・止め札）を境の節が trace に書く op（line_edge と同じ語）


def _stop_info(b) -> tuple:
    """(by, reason, 止めた事実の dict)。stop_after_round の締め（halted.by stop_after_round）は止めた事実に数えない。
    周を締めた盤面では b.stop が拒むので、境の節は止め（最後の関所の stop・reject、止め札）を trace の STOP_AFTER_END_OP の
    行に書く（P1 Task 26）。その最後の行を止めた事実として読む"""
    st = b.state
    stop, halted = st.get("stop") or {}, _halted(b)
    if stop:
        return str(stop.get("by") or ""), str(stop.get("reason") or ""), stop
    if halted and halted.get("by") != "stop_after_round":
        return str(halted.get("by") or ""), str(halted.get("reason") or ""), halted
    ended = _trace_rows(b, STOP_AFTER_END_OP)
    if halted and ended:
        return str(ended[-1].get("by") or ""), str(ended[-1].get("reason") or ""), ended[-1]
    return "", "", {}


def _halted(b) -> dict:
    """盤面の止め（state.halted）。報告の節を出すために退けた周の締めの止め（DiskBoard.report_after_round が state.works に
    移した物）も同じに読む（結末と冒頭 3 を退ける前と同じにする）"""
    return b.state.get("halted") or (b.state.get("works") or {}).get(DiskBoard.AFTER_ROUND) or {}


def _trace_rows(b, op: str) -> list:
    try:
        lines = (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("op") == op:
            rows.append(row)
    return rows


# ---------------------------------------------------------------- 報告の前の関所（TA15）
def gate_record(b) -> dict:
    """engine の cmd_finalize と同じ順: 止めていない盤面（halted が無い）は先に settle（止め札の後に待ちのまま残る報告の節を
    片付ける。M9）。周を締めて止めた盤面（halted.by stop_after_round）は b.report_after_round で報告の節を出す（R61 の B。
    AI の報告を毎回回す）→ finalize → run_validator（validator_runner の包みが効く口）。settle の RecordInvalid（報告の節を表で持つ
    ラインの関所）は捕まえて、同じ検証器を下でもう 1 度回す。
    返り {exit, accepted: exit ∈ report_accepts(b), tail: 出力の末尾, traces: 記録の痕跡の欄（空でない物）,
    round_closed: 今の周に record_round と converge の機械の節が済んだか（止めた印の converge は数えない）}"""
    halted = b.state.get("halted") or {}
    try:
        if halted.get("by") == "stop_after_round":
            b.report_after_round()   # 周を締めて止めた盤面にも報告の節を出す（R61 の B。結末は _halted が退ける前と同じに読む）
        elif not halted:
            b.settle()
    except RecordInvalid:
        pass
    b.finalize()
    v = b.run_validator() or {}
    code = v.get("exit")
    out = str(v.get("out") or "")
    proc = b.record.get("process") or {}
    traces = {field: proc.get(field) for field, _ in TRACES if proc.get(field)}
    done = b.rd.get("done") or {}
    closers = [nid for nid, n in b.nodes.items() if n.get("builtin") in ("record_round", "converge")]
    closed = bool(closers) and all(nid in done and (done[nid] or {}).get("builtin") != "stop" for nid in closers)
    return {"exit": code, "accepted": code in report_accepts(b), "tail": "\n".join(out.rstrip().splitlines()[-TAIL_LINES:]),
            "traces": traces, "round_closed": closed}


def _no_fix(b, judged) -> bool:
    """直す物が無い周: 判定の出口の need_fix が偽（渡されていれば）。無ければ今の周の修正の出力に changes が無い"""
    if isinstance(judged, dict) and isinstance(judged.get("need_fix"), bool):
        return not judged["need_fix"]
    fix = _output(b, "p3.fix")
    return isinstance(fix, dict) and not fix.get("changes")


def decide_outcome(b, gate: dict, *, tests: dict | None = None, judged: dict | None = None) -> str:
    """結末。順: 止め札（by request:）→ stopped_by_request、関所の stop・reject（halted.by answer か by human:）→ stopped_by_human、
    機械の止め（by works:）→ stopped_by_line、人に聞いたまま（pending_human）か食い違いの申し出を人に回した → needs_human、関所が通らない（accepted か
    round_closed が偽）→ record_invalid、直す物が無い周 → no_fix_needed、他 → fixed。
    **fixed・no_fix_needed は accepted と round_closed が真の時だけ**。needs_human を record_invalid の前に置くのは、人に聞いて
    いる盤面は周の記録がまだ無く（検証器が 2）、record_invalid の後ろでは needs_human に届かないため（〔線A計〕T15 の並びから
    替えた。どちらも成功の結末ではない）。tests（最後のテストの出口）は結末を替えない（冒頭 1 に赤を出す）"""
    by, _, info = _stop_info(b)
    if by.startswith(REQUEST_BY):
        return "stopped_by_request"
    if (info and info is b.state.get("halted") and by == ANSWER_BY) or by.startswith(HUMAN_BY):
        return "stopped_by_human"
    if by.startswith(LINE_BY):
        return "stopped_by_line"
    if b.state.get("pending_human") or _asked(b):   # 食い違いの申し出を人に回した単位は直さずに残した
        return "needs_human"
    if not gate.get("accepted") or not gate.get("round_closed"):
        return "record_invalid"
    if _no_fix(b, judged):
        return "no_fix_needed"
    return "fixed"


# ---------------------------------------------------------------- 次の run に渡す依頼
def next_request(b, *, tests: dict | None = None) -> list:
    """次の run に渡す依頼（1 本目の依頼の型 [{where, text}]。key・一言は字のまま）:
    手直し 2 回目が fixed と言った穴（検算が要る）・declared で残した穴・修正の not_done・最後のテストの赤・
    再審されずに残った異議（loop.rejudge_requested。写し直しの前で再審の節が無い run と、会話が無くて止めた run）・
    盤面が人に聞いたままの問い（独立の目の r4.human_gate など。この run では答えを受けないので次の run へ渡す。計画 P1 Task 33 の (b)）・
    食い違いの申し出を人に回して直さずに残した単位（conflict の ask_human）"""
    items = []
    for nid in REFIX_NODES:
        out = _output(b, nid) or {}
        for h in out.get("handled") or []:
            if not isinstance(h, dict) or not isinstance(h.get("key"), str):
                continue
            where = (h.get("files") or [None])[0] or h["key"]
            if h.get("handled") == "declared":
                items.append({"where": str(where), "text": f"{h['key']}（手直しが declared で残した穴: {h.get('how') or ''}）"})
            elif h.get("handled") == "fixed" and nid == REFIX_NODES[-1]:
                items.append({"where": str(where),
                              "text": f"{h['key']}（手直し 2 回目が fixed と言ったが、3 回目の審査は無い——検算が要る: {h.get('how') or ''}）"})
    fix = _output(b, "p3.fix") or {}
    for nd in fix.get("not_done") or []:
        if isinstance(nd, dict) and isinstance(nd.get("unit_key"), str):
            items.append({"where": nd["unit_key"], "text": f"{nd['unit_key']}（修正がやらなかった: {nd.get('why') or ''}）"})
    if isinstance(tests, dict) and not (tests.get("ok") is True and tests.get("green") is True):
        head = "赤" if tests.get("ok") is True else "走れなかった"
        items.append({"where": str(tests.get("log") or "最後のテスト"),
                      "text": f"最後のテストが{head}（{tests.get('reason') or 'ログを読む'}）"})
    req = (b.loop_state or {}).get("rejudge_requested") or {}
    if isinstance(req, dict) and isinstance(req.get("text"), str) and req["text"]:
        items.append({"where": "判定（再審されずに残った異議）", "text": req["text"]})
    for r in _asked(b):
        items.append({"where": r["unit_key"],
                      "text": f"{r['unit_key']}（{conflict.HEAD}を人に回した——直さずに残した: {_one_line(r['ruling']['text'])}。"
                              f"名指し {', '.join(r['between'])}）"})
    ph = b.state.get("pending_human") or {}
    if ph.get("question"):
        asked = "・".join(str(x) for x in ph.get("items") or [])
        items.append({"where": f"人の関所（{ph.get('node')}）",
                      "text": f"{_one_line(ph['question'])}" + (f"（挙がった物: {_one_line(asked)}）" if asked else "")})
    seen, out = set(), []
    for it in items:
        k = (it["where"], it["text"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ---------------------------------------------------------------- 冒頭 1〜5
def head_decisions(b, gate: dict, *, tests: dict | None = None, outcome: str = "", next_items: list | None = None,
                   next_file: str = "") -> list:
    """冒頭 1（人が決めること）: 記録が関所を通らない時の検証器の末尾と痕跡・関所の答え（事前審査の関所と最後の関所）・
    人が止めた一言・最後のテスト・盤面の問い・再審の問いと争点でない単位の変化・前提で測り直せなかった依頼・並行 PR の
    申し送りの下書きと外した範囲・次の run に渡す物の件数"""
    lines = []
    if outcome == "record_invalid":
        lines.append(f"記録が検証器を通らない（exit {gate.get('exit')}・受理 {report_accepts(b)}・今の周の記録が"
                     f"{'済んだ' if gate.get('round_closed') else '済んでいない'}）——fixed・no_fix_needed を出さない")
        if gate.get("tail"):
            lines += ["検証器の出力の末尾:", *[f"    {x}" for x in gate["tail"].splitlines()]]
        for field, val in (gate.get("traces") or {}).items():
            lines.append(f"記録の痕跡 {field}: {json.dumps(val, ensure_ascii=False)[:400]}")
    proc = b.record.get("process") or {}
    for h in proc.get("human_items") or []:
        if isinstance(h, dict):
            lines.append(f"関所 {h.get('node')} の答え: {h.get('answer')}「{h.get('note') or ''}」")
    ans = _latest(b.dir, FINAL_GATE_ANSWER)
    if ans is not None:
        doc = _read_json(ans, {}) or {}
        lines.append(f"最後の関所の答え: {doc.get('decision')}「{doc.get('text') or ''}」（{ans}）")
    by, reason, info = _stop_info(b)
    if by == FINAL_GATE_BY:
        lines.append(f"最後の関所で止めた: 「{reason}」")
    elif by.startswith(HUMAN_BY) or (by == ANSWER_BY and info is b.state.get("halted")):
        lines.append(f"関所で止めた（{by}）: 「{reason}」")
    if by == REJUDGE_SESSION_BY:
        lines.append(f"再審の会話を確かめられずに止めた: 異議を再審するか、新しい run で判定し直すかを決める（{_one_line(reason)}）")
    if tests is None:
        lines.append("最後のテスト: 走っていない")
    elif tests.get("ok") is not True:
        lines.append(f"最後のテスト: 走れなかった（{tests.get('reason') or '理由なし'}・ログ {tests.get('log') or '無い'}）")
    elif tests.get("green") is not True:
        lines.append(f"最後のテストが赤: ログ {tests.get('log') or '無い'}")
    else:
        lines.append(f"最後のテスト: 緑（ログ {tests.get('log') or '無い'}）")
    ph = b.state.get("pending_human")
    if ph:
        lines.append(f"盤面が人に聞いている（{ph.get('node')}）: {ph.get('question') or ''}")
        lines += [f"  - {x}" for x in ph.get("items") or []]
    lines.append(_conflict_line(b))
    lines += _rejudge_changes(b)
    lines += _premise_hypotheses(b)
    lines += _pr_lines(b)
    n = len(next_items or [])
    lines.append(f"次の run に渡す物: {n} 件" + (f"（{next_file}）" if next_file else ""))
    return lines


def _asked(b) -> list:
    """今の周に人に回した食い違いの申し出（控えが読めなければ空。件数の行が「読めない」と言う）"""
    try:
        return conflict.asked(b)
    except BoardGap:
        return []


def _conflict_line(b) -> str:
    """冒頭 1 の食い違いの申し出の件数（run ごと。0 件も出す）"""
    try:
        c = conflict.counts(b)
    except BoardGap as e:
        return f"{conflict.HEAD}: 控えが読めない（{_one_line(str(e))}）"
    return (f"{conflict.HEAD}: {c['parked']} 件（裁定 fix_test_scope {c['fix_test_scope']}・fix_code_as {c['fix_code_as']}・"
            f"ask_human {c['ask_human']}・裁定なし {c['unruled']}）")


def _rejudge_changes(b) -> list:
    """再審で異議に名指されていない単位が変わった行（rejudge-diff.json の changed のうち named が偽の物）"""
    lines = []
    for p in _all_rounds(b.dir, REJUDGE_DIFF):
        for row in _read_json(p, []) or []:
            for c in row.get("changed") or [] if isinstance(row, dict) else []:
                if not isinstance(c, dict) or c.get("named"):
                    continue
                if c.get("kind") == "changed":
                    lines.append(f"再審（{row.get('pass')}）で争点でない単位が変わった: {c.get('key')} の {c.get('field')}: "
                                 f"{json.dumps(c.get('before'), ensure_ascii=False)} → {json.dumps(c.get('after'), ensure_ascii=False)}")
                else:
                    lines.append(f"再審（{row.get('pass')}）で争点でない単位が{'足された' if c.get('kind') == 'added' else '消えた'}: "
                                 f"{c.get('key')}")
    return lines


def _premise_hypotheses(b) -> list:
    """依頼が実測（measured）を持っていたのに、前提の役が仮説でしか書けなかった制約（依頼の where を文に含む物）"""
    proc = b.record.get("process") or {}
    hyp = [c for c in proc.get("constraints") or [] if isinstance(c, dict) and c.get("kind") == "仮説"]
    lines = []
    for batch in proc.get("request_findings") or []:
        for f in (batch.get("findings") or []) if isinstance(batch, dict) else []:
            if not (isinstance(f, dict) and f.get("measured") and f.get("where")):
                continue
            for c in hyp:
                if f["where"] in str(c.get("text") or ""):
                    lines.append(f"依頼の実測を測り直せなかった（前提は仮説）: {f['where']}——{c.get('text')}")
                    break
    return lines


def _pr_lines(b) -> list:
    """並行 PR の申し送りの下書き（note を持つ交差。投稿していない）と、外した範囲"""
    lines = []
    out = _output(b, PR_NODE) or {}
    for c in out.get("conflicts") or []:
        if isinstance(c, dict) and c.get("note"):
            lines.append(f"並行 PR #{c.get('pr')} の担当への申し送りの下書き（{'・'.join(map(str, c.get('files') or []))}。"
                         f"投稿していない）: {c['note']}")
    for p in _all_rounds(b.dir, PR_EXCLUDED):
        for x in (_read_json(p, {}) or {}).get("excluded") or []:
            if isinstance(x, dict):
                lines.append(f"並行 PR #{x.get('pr')} と重なるので外した範囲: {x.get('file')}:{x.get('start')}-{x.get('end')}"
                             f"（{x.get('why') or ''}）")
    return lines


def declared_downgrades(line: str, *, pack: pathlib.Path = PACK) -> list:
    """<pack>/<line>/downgrades.json（[{node, what, versus}]）。無ければ []。形が違えば BoardGap"""
    p = pathlib.Path(pack) / line / DOWNGRADES
    if not p.is_file():
        return []
    doc = _read_json(p)
    if not isinstance(doc, list) or not all(isinstance(r, dict) and all(isinstance(r.get(k), str) for k in DOWNGRADE_KEYS)
                                            for r in doc):
        raise BoardGap(f"{p} の形が違う（[{{{', '.join(DOWNGRADE_KEYS)}}}] の配列）")
    return [{k: r[k] for k in DOWNGRADE_KEYS} for r in doc]


def head_entry(b, start: dict | None, *, mid: dict | None = None) -> list:
    """冒頭 2: 入口・段・gates・最後の関所の形・決めた人（関所の答えの数）・このラインに無い節の数と一覧のパス・下げている所・
    中の検査の枠の行（境の節の mid_note）"""
    s = _start_doc(b, start)
    reqs = s.get("requests")
    if reqs is None:
        reqs = sum(len(x.get("findings") or []) for x in (b.record.get("process") or {}).get("request_findings") or []
                   if isinstance(x, dict))
    parts = [f"入口: 判定から（依頼 {reqs} 件）", f"段: {s.get('thickness') or '（控えが無い）'}", f"gates: {s.get('gates') or '空'}"]
    if s.get("final_gate"):
        parts.append(f"最後の関所: {s['final_gate']}")
    parts.append(f"包み: {'optional（包み無し）' if s.get('adapter') == 'optional' else '通す'}")
    humans = len((b.record.get("process") or {}).get("human_items") or [])
    lines = ["・".join(parts), f"決めた人: 関所の答え {humans} 件（record.process.human_items）"]
    absent = (b.state.get("works") or {}).get("not_in_line") or []
    note = b.dir / "rounds" / "works" / f"round-{b.round}.json"
    lines.append(f"このラインに無い節: {len(absent)} 個（一覧: {note if note.is_file() else 'state.json の works.not_in_line'}。"
                 "報告の末尾にも）")
    downs = declared_downgrades(b.table.line) if b.table is not None else []
    lines.append(f"下げている所: {len(downs)} 個")
    lines += [f"  - {r['node']}: {r['what']}（{r['versus']}）" for r in downs]
    if isinstance(mid, dict) and mid.get("mid_note"):
        lines.append(f"中の検査の枠: {mid['mid_note']}")
    else:
        lines.append("中の検査の枠: 境の節の出口が届いていない（中の検査を回さなかった run）")
    return lines


def absent_lines(b) -> list:
    """報告の末尾の「このラインに無い節」の一覧（state.works.not_in_line。節と理由と、入る時の印）"""
    rows = (b.state.get("works") or {}).get("not_in_line") or []
    return [f"{r.get('node')}: {r.get('reason') or ''}" + (f"（入る時: {r['comes_with']}）" if r.get("comes_with") else "")
            for r in rows if isinstance(r, dict)]


def head_stop(b, *, interrupted: str | None = None) -> list:
    """冒頭 3: 止めたか（止め札・関所の stop・機械の止め。理由と止めた所）。interrupted は Archon の run の状態"""
    lines = []
    if interrupted is not None:
        lines.append(f"{INTERRUPTED_HEAD}。Archon の run の状態は {interrupted or '（不明）'}")
    by, reason, info = _stop_info(b)
    if by.startswith(REQUEST_BY):
        seen = _trace_rows(b, FLAG_SEEN_OP)
        at = seen[-1].get("at") if seen else None
        lines.append(f"止め札で止めた（置いた人 {by[len(REQUEST_BY):]}）: {reason}。止めた境の節: {at or '（trace に無い）'}")
    elif by == ANSWER_BY and info is b.state.get("halted"):
        lines.append(f"関所の答えで止めた（{info.get('node')}）: {reason}")
    elif by.startswith(HUMAN_BY):
        lines.append(f"人が止めた（{by}）: {reason}")
    elif by:
        lines.append(f"機械が止めた（{by}）: {reason}。止めた所: {info.get('node') or '—'}・周 {info.get('round')}")
    elif _halted(b).get("by") == "stop_after_round":
        lines.append(f"止めていない（周の締めの後で止めた: {_halted(b).get('reason')}）")
    elif interrupted is None:
        lines.append("止めていない")
    if by and info.get("report") is False and info.get("no_report"):
        # 止めた周の記録が検証器を通らない（判定の前に止めた周は、awaiting_human の素材を問いの台帳に載せる判定役が走っていない
        # ——run 30）時、本線の cmd_stop は報告の節を出さずに理由を言う。同じ理由をここに出す（記録を機械が繕わない）
        lines.append(f"報告の節は出ない（本線の止めと同じ）: {info['no_report']}")
    return lines


def head_reads(board_dir, run_id: str, *, ci: dict | None = None) -> list:
    """冒頭 4: 読んだ証拠（各役の reads-<役>.json）と包みの行。出来事が unverified なら「出来事: 未確認（P13）」。
    包み無し（adapter optional）の run は「包み無し」の行の横に CI の役の知らせ（blk の collect.note）。包みを通す run で起動の
    記録が無ければ「包みが通っていない」。包みの確かめで止めた盤面は止めた理由。会話を継いだ起動の数。盤面を書かない"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    lines, unverified = [], False
    files = _all_rounds(board_dir, "reads-*.json")
    for p in files:
        doc = _read_json(p, {}) or {}
        src = doc.get("sources") or {}
        unverified = unverified or src.get("events") == "unverified"
        lines.append(f"読んだ証拠 {doc.get('role')}: 渡した {len(doc.get('rows') or [])} 件・読んだ跡の無い "
                     f"{len(doc.get('missing') or [])} 件（フックの記録: {'在る' if src.get('hook') else '無い'}・"
                     f"出来事: {src.get('events')}。{p}）")
    if not files:
        lines.append("読んだ証拠: 集めていない（役の読んだ証拠の節が走っていない）")
    if unverified:
        lines.append("出来事: 未確認（P13）——出来事の行の形を確かめるまで、読んでいない証拠に使わない")
    mode = _start_doc(b, None).get("adapter")
    repo = pathlib.Path((b.state.get("inputs") or {}).get("cwd") or ".")
    note = (ci or {}).get("note") if isinstance(ci, dict) else ""
    if mode == "optional":
        lines.append("包み無し（adapter: optional。役の起動は包みを通さず、読んだ記録と柵は無い）"
                     + (f"・CI の役: {note}" if note else ""))
    else:
        seen = reads.adapter_seen(board_dir, run_id, repo=repo)
        if seen["seen"]:
            lines.append(f"包み: 通った（合わせた起動 {seen['merged']}・素通し {seen['passthrough']}）")
        else:
            lines.append("包みが通っていない")
        lines += [f"  - {w}" for w in seen["whys"]]
    by, reason, _ = _stop_info(b)
    if by == ADAPTER_BY:
        lines.append(f"包みの確かめで止めた: {reason}")
    cont = sum(1 for r in _launches(b, repo) if (r.get("session") or {}).get("mode") == "continued")
    lines.append(f"会話を継いだ起動: {cont} 本")
    return lines


def _time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def _launches(b, repo) -> list:
    """包みの起動の記録のうち、盤面を作った（state.created）後の行（reads.adapter_seen と同じ絞り方）"""
    since = _time(b.state.get("created"))
    rows = []
    for r in adapter.read_launches(pathlib.Path(repo)):
        at = _time(r.get("at"))
        if since is not None and at is not None and at >= since:
            rows.append(r)
    return rows


def head_where(b) -> list:
    """冒頭 5: 見る所（判定・修正案・事前審査・修正・審査・手直し・差分のファイルと run の作業ツリー）。ファイルは
    state.outputs[節]["file"] と loop の差分の欄から（周を仮定しない）。盤面を書かない"""
    lines = []
    outs = b.state.get("outputs") or {}
    for label, nid in WHERE:
        info = outs.get(nid)
        if info and info.get("file"):
            lines.append(f"{label}: {b.dir / info['file']}")
    for label, key in DIFFS:
        f = ((b.loop_state or {}).get(key) or {}).get("file")
        if f:
            lines.append(f"{label}: {f}")
    lines.append(f"run の作業ツリー: {(b.state.get('inputs') or {}).get('cwd') or '（無い）'}")
    return lines


# ---------------------------------------------------------------- 費用
def _step_name(step) -> str:
    """出来事の節の名前（`<include>__<輪>.<節>` など）の最後の 1 語"""
    s = str(step or "")
    return s.rsplit(".", 1)[-1].rsplit("__", 1)[-1]


def _event_cost(e):
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    for k in COST_KEYS:
        v = data.get(k, e.get(k))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def cost_rows(events, launches) -> list:
    """[{node, reported, actual, continued_from}]。events の node_completed の費用の欄（推測。COST_FIELD_VERIFIED）を節の名で
    launches（包みの起動の行。時刻の順に並べ直す。拒んだ起動は除く）と順に結ぶ。session.mode continued の起動は、同じ
    session.id のそれまでの表示（再開した会話の total_cost_usd は累積。〔継試〕）を引いた値を actual にし、continued_from に
    その会話を前に使った節を書く。起動の無い出来事の費用は actual = reported で行にする。events が None か費用の欄が
    1 つも無ければ []"""
    if not events:
        return []
    shown = [(_step_name(e.get("step_name")), _event_cost(e)) for e in events
             if isinstance(e, dict) and e.get("event_type") == "node_completed"]
    shown = [(n, v) for n, v in shown if v is not None]
    if not shown:
        return []
    queues = {}
    for n, v in shown:
        queues.setdefault(n, []).append(v)
    rows_in = sorted((r for r in launches or [] if isinstance(r, dict) and (r.get("session") or {}).get("mode") != "refused"),
                     key=lambda r: str(r.get("at") or ""))
    totals, last_node, out = {}, {}, []
    for r in rows_in:
        node = r.get("node")
        q = queues.get(node) or []
        if not q:
            continue
        v = q.pop(0)
        s = r.get("session") or {}
        sid, mode = s.get("id"), s.get("mode")
        if mode == "continued" and sid in totals:
            out.append({"node": node, "reported": v, "actual": round(v - totals[sid], 6), "continued_from": last_node[sid],
                        "base": totals[sid]})
        else:
            out.append({"node": node, "reported": v, "actual": v, "continued_from": None, "base": None})
        if sid:
            totals[sid], last_node[sid] = v, node
    for n, q in queues.items():
        out += [{"node": n, "reported": v, "actual": v, "continued_from": None, "base": None} for v in q]
    return out


def head_cost(board_dir, run_id: str, *, events=None, launches=None) -> list:
    """冒頭の後の費用の行（書き出しの run_facts の代わりに、Archon の出来事と包みの起動の記録から）。取れなければ 1 行。
    launches を渡さなければ盤面の run の作業ツリーの起動の記録（盤面を作った後の行）"""
    if launches is None:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
        launches = _launches(b, (b.state.get("inputs") or {}).get("cwd") or ".")
    rows = cost_rows(events, launches)
    if not rows:
        why = "出来事を読めない" if events is None else "出来事に節の費用の欄が無い"
        return [f"費用: 取れない（{why}。run {run_id or '（id 無し）'}）"]
    mark = "" if COST_FIELD_VERIFIED else "（欄の形は未確認）"
    lines = []
    for r in rows:
        extra = f"（{r['continued_from']} の会話の累積 {r['base']} を引いた。表示 {r['reported']}）" if r["continued_from"] else ""
        lines.append(f"費用 {r['node']}: {r['actual']} USD{extra}{mark}")
    total = round(sum(r["actual"] for r in rows if isinstance(r["actual"], (int, float))), 6)
    lines.append(f"費用の合計: {total} USD{mark}")
    return lines


# ---------------------------------------------------------------- 組む
def _finish_fields(b, judged, outcome) -> dict:
    """1 本目の finish の欄: ok・outcome・judgment_file、審査が在れば review_file・diff_file・faces"""
    outs = b.state.get("outputs") or {}
    jf = judged.get("judgment_file") if isinstance(judged, dict) else None
    if not (isinstance(jf, str) and jf):
        jf = str(b.dir / outs["p2.diagnose"]["file"]) if (outs.get("p2.diagnose") or {}).get("file") else ""
    out = {"ok": True, "outcome": outcome, "judgment_file": jf}
    info = outs.get("p3.delta_review")
    diff = ((b.loop_state or {}).get("fix_delta") or {}).get("file")
    if info and diff:
        review = _output(b, "p3.delta_review") or {}
        out.update(review_file=str(b.dir / info["file"]), diff_file=str(diff), faces=len(review.get("faces") or []))
    return out


def build(board_dir, *, judged: dict | None, tests: dict | None, start: dict | None, mid: dict | None = None,
          ci: dict | None = None, run_id: str = "", events=None, launches=None, interrupted: str | None = None) -> dict:
    """gate_record → decide_outcome → 部品で <盤面>/report.md と <盤面>/next-request.json を書き、1 本目の finish の欄に
    report_file・next_request_file・tests_green・validator_exit と、書き出しの節が読む export_input {outcome, report_file,
    board_dir} を足して返す。interrupted（Archon の run の状態の語。空も可）を渡せば結末は interrupted（dev の report.sh）。
    record_invalid の時は冒頭 1 に検証器の出力の末尾と痕跡。盤面を開けなければ BoardGap"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    gate = gate_record(b)
    # 盤面が報告の役の節を出したか（表で role のラインだけ。止めた run・収束した run で出る。周を締めて止めた 1 周の run では
    # 出ない）。待ちのままでも結末は替えない——報告の役の節の待ちは「終わっていない」ではない（計画 P1 Task 34）
    ai_go = AI_FIRST_NODE in b.ready()
    outcome = "interrupted" if interrupted is not None else decide_outcome(b, gate, tests=tests, judged=judged)
    items = next_request(b, tests=tests)
    req_p, rep_p = board_dir / NEXT_REQUEST_FILE, board_dir / REPORT_FILE
    _write_json(req_p, items)
    rid = run_id or _start_doc(b, start).get("run_id") or ""
    body = [f"# 報告（run {rid or '—'}）: {outcome}", ""]
    parts = (head_decisions(b, gate, tests=tests, outcome=outcome, next_items=items, next_file=str(req_p)),
             head_entry(b, start, mid=mid), head_stop(b, interrupted=interrupted), head_reads(board_dir, rid, ci=ci),
             head_where(b))
    for title, rows in zip(HEADINGS, parts):
        body += [title, "", *[r if r.startswith("  ") else f"- {r}" for r in rows], ""]
    body += ["## 費用", "", *[f"- {r}" for r in head_cost(board_dir, rid, events=events, launches=launches)], ""]
    body += ["## 周の記録の検証器", "", f"- 終了コード: {gate['exit']}（受理 {report_accepts(b)}）",
             f"- 今の周の記録: {'済んだ' if gate['round_closed'] else '済んでいない'}", ""]
    body += ["## このラインに無い節", "", *[f"- {r}" for r in absent_lines(b)], ""]
    _write_text(rep_p, "\n".join(body))
    green = isinstance(tests, dict) and tests.get("ok") is True and tests.get("green") is True
    return {**_finish_fields(b, judged, outcome), "report_file": str(rep_p), "next_request_file": str(req_p),
            "tests_green": green, "validator_exit": gate["exit"], "ai_report_go": ai_go,
            "export_input": {"outcome": outcome, "report_file": str(rep_p), "board_dir": str(board_dir)}}


def final_result(machine: dict, ai: dict | None) -> dict:
    """ラインの出口（計画 P1 Task 34）: 機械の報告の出口（build の返り）の欄を全部残し、最後の報告のファイルを選ぶ——AI の報告
    （報告の役のブロックの出口）が ok ならその report_file、そうでなければ（回らなかった・諦めた・検証器を通らない）機械の
    report.md。結末（outcome）は機械の報告のまま替えない。足す欄: machine_report_file（機械の報告）・ai_report（AI の報告の
    出口の AI_REPORT_KEYS か None）。export_input の report_file も選んだ方"""
    if not isinstance(machine, dict) or not isinstance(machine.get("report_file"), str):
        raise BoardGap(f"機械の報告の出口が無い・形が違う（{type(machine).__name__}）")
    ai_ok = isinstance(ai, dict) and ai.get("ok") is True and isinstance(ai.get("report_file"), str) and bool(ai["report_file"])
    chosen = ai["report_file"] if ai_ok else machine["report_file"]
    out = {**machine, "report_file": chosen, "machine_report_file": machine["report_file"],
           "ai_report": {k: ai.get(k) for k in AI_REPORT_KEYS} if isinstance(ai, dict) else None}
    exp = machine.get("export_input")
    if isinstance(exp, dict):
        out["export_input"] = {**exp, "report_file": chosen}
    return out
