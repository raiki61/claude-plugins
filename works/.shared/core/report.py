"""機械が組む短い報告（P1 計画 Task 27・〔線A計〕T15。仕様 6 節・裁定 TA12・TA15）。AI は書かない。文は機械の定型だけ。

**記録が検証器を通らない run に fixed・no_fix_needed を出す道を作らない**（審査 I3）: build は必ず gate_record で
settle → finalize → run_validator を 1 度踏み、受理集合（report_accepts）の外か、今の周の記録（record_round と converge）が
済んでいなければ record_invalid にする。検証器は validator_runner の包み（board_hook.py）が効く b.run_validator で回す。
**残り（検証器の阻害・最後のテストが緑でない・独立の目の阻害と走っていない目と結果が無い目）が在る run に fixed を出さない**: 直した周で residue が 1 行でも
返せば round_limit にし、冒頭 1 と次の run の依頼に残りの行を字のまま出す（直す物が無い周は no_fix_needed のまま。赤は冒頭 1 に出る）。

口（線 B の報告も呼ぶ。線 B の申し送り 3・TA18。どの head_* も盤面を書かない）:
- OUTCOMES・COST_FIELD_VERIFIED・FIRST_ROUND_LINE
- gate_record(b) -> {exit, accepted, out, tail, traces, round_closed}
- residue(b, gate, *, tests=None, eyeing=None) -> fixed を名乗らせない残り [{where, text}]
- decide_outcome(b, gate, *, tests=None, judged=None, eyeing=None) -> OUTCOMES の 1 つ
- stop_outcome(b) -> 盤面の止めの (結末の語, by, 一言) か ()・stopped_run(board_dir) -> 当てる前に見る記録の止まり（記録が無いか読めなければ None）
- head_decisions(b, gate, …)（冒頭 1）・head_entry(b, start, *, mid=None, cleaned_runs="")（冒頭 2）・head_stop(b, *, interrupted=None, failed=None, retried=None)（冒頭 3）・
  head_reads(board_dir, run_id, *, ci=None)（冒頭 4）・head_where(b)（冒頭 5）・head_models(board_dir, launches)・head_cost(board_dir, run_id, *, events, launches)
- declared_downgrades(line) -> [{node, what, versus}]（PACK/<line>/downgrades.json。無ければ []）
- cost_rows(events, launches) -> [{node, reported, actual, continued_from, base, aggregate}]
- next_request(b, *, tests=None, left=None) -> 次の run に渡す依頼の findings [{where, text}]（依頼の型のまま。R2 の作り直しの行は除く。
  判定が目的の外として単位にしなかった材料の所見は材料の行の任意の欄 mechanism・measured・false_positive_if と、下書きの印
  draft・source も持つ。印の在る行は依頼の入口が拒むので、人が見直すまで次の run の目的にならない）
- next_doc(b, items, prior) -> next-request.json の中身 {findings, prior_failures, answers?}（answers は無人の run の答えの下書き）
- prior_failures(b, left=None) -> この run で最後まで通らなかった受け付けと R2 の作り直しの理由 [{where, text}]（次の依頼の prior_failures）
- handoff_lines(b) -> 修正役が人に回した物の行（breaks.accepted。冒頭 1・冒頭 3 行と最後の関所が同じ行を出す）
- rejudge_lines(b) -> 決着した再審の結果の行（冒頭 1 と最後の関所の文が同じ行を出す）
- branch_rows(b)・eye_ties(b) -> 差分の審査の穴と独立の目が場所を挙げた行の枝の名札の行（線の木の段 4a。冒頭 1 と最後の関所の文が同じ行を出す。穴も行も無ければ空）
- verify_lines(b) -> 判定の単位の裏取りの行（周ごと。根本でない・証拠が無い・場所が違う・確かめられなかった単位と単位どうしの重複・
  順番。全部の単位が根本で合えば件数の 1 行。単位は消さないので、人が単位を減らすかを決める材料）
- tests_word(b, tests)・eye_counts(b, reviews) -> EyeCounts(blocked, not_run, missing)・rest_outside_validator(b, *, tests, counts, exit_problem="") -> Rest(tests_word, counts, rows)
  （検証器の外の残りの数えの正本。最後の関所と冒頭 1・次の依頼が同じ口を読む。NOT_RUN_GATE_NOTE が not_run の例外の理由）
- always_rows(b, left=None, *, rest=None) -> clean が消したファイル・レンズ・仕組みの異常・残りの件数の行（0 件も、
  走らせていない・調べていない・読めないも。冒頭 1 は left を渡し、最後の関所は rest を渡して数えられる分を言う。どちらも無い呼びは渡し忘れを名指す）・anomalies(b)・anomaly_lines(b, *, full=False, found_only=False)（仕組みの異常。報告の「仕組みの異常」の節）
- build(board_dir, *, judged, tests, start, mid=None, ci=None, run_id="", events=None, launches=None, interrupted=None,
  failed=None, retried=None, eyeing=None, cleaned_runs="") -> dict（盤面を読む前に replan.close_at で、案の直しを待つ行を諦めた行にする）
- final_result(machine, ai) -> dict（ラインの出口: 機械の報告の出口に AI の報告の結果を足し、最後の報告のファイルを選ぶ）

盤面の上の名前（最後の関所の答え final-gate-answer.json と止めた口 human:final-gate、止め札の trace の op stop_flag_seen、
並行 PR の外した範囲 pr-excluded.json、再審の差分 rejudge-diff.json と出口 rejudge-exit.json、判定の単位の裏取りの申し送り
judge-verify.json）は書き手の模块（ライン・ブロック）を import せずに
ファイルの名前として読む（層 L3 は上の層を import しない。裁定 R59）。書き手と名前を揃えるのは試験（test_report）。

この版で持たない物（報告に書く）: 版の一覧の行（P1 Task 18・19 の works_version・書き出しの manifest が無い）、
第三の目の「方針の岐路」の争点（写し a1202d0 の graph に欄が無い）。費用は書き出し（Task 19）の run_facts の代わりに
Archon の出来事（節の data.spend.costUsd）と包みの起動の記録から組む（欄の形は実物で確かめた。COST_FIELD_VERIFIED が偽なら「欄の形は未確認」を添える）。
報告は run の中で走るので run の和は読まず、合計は節の和を「途中」として出す。
"""
import collections
import datetime
import json
import math
import os
import pathlib
import re
import sys
import types
from typing import NamedTuple

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import conflict  # noqa: E402
import converge  # noqa: E402
import design  # noqa: E402
import diverted  # noqa: E402
import gatemarks  # noqa: E402
import impact  # noqa: E402
import outpurpose  # noqa: E402
import querytest  # noqa: E402
import recount  # noqa: E402
import replan  # noqa: E402
from board import BoardGap, DiskBoard, RecordInvalid  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.rules import validator_module  # noqa: E402
from engine.validator import TRACES, report_accepts  # noqa: E402
import entry  # noqa: E402
import fixture  # noqa: E402
import forge  # noqa: E402
import holeties  # noqa: E402
import leftovers  # noqa: E402
import lens  # noqa: E402
import reads  # noqa: E402
import refix  # noqa: E402  （差分の審査の穴の枝の名札 hole_ties・項目 tie_items）
import scopes  # noqa: E402
import script_io  # noqa: E402
import structmark  # noqa: E402
import writes  # noqa: E402

PACK = CORE.parents[1]
OUTCOMES = ("fixed", "no_fix_needed", "round_limit", "stopped_by_request", "stopped_by_human", "stopped_by_line",
            "needs_human", "record_invalid", "interrupted")
# 1 周で止める run で写しの検証器（scripts/review-record.py）が必ず出す帳尻の行。exit 1 の箇条からこの行だけを字の一致で
# 除き、残りを阻害と読む（前の周が在る run の「前ラウンドに阻害要因が N 件あった」は除かない）。写しと字が揃うことは試験が見る
FIRST_ROUND_LINE = "前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）"
BLOCKERS_HEAD = re.compile(r"^収束を妨げるもの (\d+) 件:$")
BULLET = "  - "
UNIT_ROW_HEADS = ("[block] 未解消", "[suggest] do-now 未対応")   # 写しの検証器の blockers が単位の行に付ける頭
EYES = ("R1", "R2", "R3", "R4")
VALIDATOR_WHERE = "検証器の阻害"   # residue の行の where（次の run の依頼にも同じ字で渡す）
EYES_WHERE = "独立の目"
COST_FIELD_VERIFIED = True   # 欄の形を canary の run の出来事の実物で確かめた（tests/events/db-rows-plan.json。2026-10-09）
# 節の費用の欄（node_completed の data の下の道）。録った Archon v0.11.1 の実物（tests/events/verbose-*.json）に在る形。
# 報告されなかった費用は {source: unavailable, reason} で、0 と混ぜない（Archon #3295・#3420）。報告された費用は Archon の
# executionSpendSchema（packages/workflows/src/schemas/node-execution.ts）で {source: provider, value}（実物 tests/events/db-rows-plan.json）
COST_FIELD = ("spend", "costUsd")
COST_FIELD_NAME = "data." + ".".join(COST_FIELD)
ARCHON_VERSION = "Archon v0.11.1"
REPORT_FILE = "report.md"
NEXT_REQUEST_FILE = "next-request.json"   # 次の run の依頼の下書き {findings, prior_failures}（依頼の型の object の形）
PRIOR_FAILURES_FILE = "prior-failures.json"   # この run で最後まで通らなかった受け付けと R2 の作り直しの理由 [{where, text}]
PRIOR_HEADING = "## 次の run に引き継ぐ落ちた理由"
ACCEPT_WHERE = "受け付け"                  # prior_failures の受け付けの行の where の頭
R2_REDESIGN = "R2 が redesign-needed"      # 検証器と独立の目が R2 の作り直しの行に付ける頭（findings から外し prior_failures にだけ載せる）
NO_TURN_FILE = "no-turn-exits.json"   # 包みの終わりの記録の即時の死の行の写し（build が書く。起こし直しの行から辿る）
NEXT_ORIGIN = "works:report"   # 次の run に渡す依頼の出どころ（accept.check_request の reason）
TAIL_LINES = 20
FINAL_GATE_ANSWER = "final-gate-answer.json"   # 最後の関所の答え {decision, text}（境の節 eyes が b.work に書く。P1 Task 26）
FINAL_GATE_FILE = "final-gate.md"              # 最後の関所の文（書き手 line_edge.FINAL_GATE_FILE と同じ字。関所が開いた印）
FINAL_GATE_BY = "human:final-gate"             # 最後の関所の stop・reject で止めた盤面の state.stop.by
FINAL_GATE_STOPS = ("stop", "reject")           # 最後の関所の答えのうち止める語（書き手 line_edge の GATE_STOP）
REQUEST_BY = "request:"                        # 止め札で止めた盤面の state.stop.by の頭
HUMAN_BY = "human:"
LINE_BY = "works:"
ANSWER_BY = "answer"                           # 関所の答えの stop（halted.by）
ADAPTER_BY = "works:adapter"                   # 包みの確かめで止めた盤面の by（h-judge の確かめ・CI の役の柵）
REJUDGE_SESSION_BY = "works:rejudge-session"   # 再審の会話を確かめられずに止めた盤面の by
FLAG_SEEN_OP = "stop_flag_seen"                # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
PR_NODE = "p0.parallel_pr"
FORGE_HEAD = "PR を持つホスト（forge）"   # 冒頭 2 の forge の無い run の 1 行の頭（forge_line）
PR_EXCLUDED = "pr-excluded.json"               # 並行 PR の外した hunk {node, head, excluded}
REJUDGE_DIFF = "rejudge-diff.json"             # 再審の単位の差分の行の列
VERIFY_NOTES = "judge-verify.json"             # 判定の単位の裏取りの申し送り（線の木の段 3。単位ごとの state・verdict と相乗り）
REJUDGE_EXIT = "rejudge-exit.json"             # 再審のブロックの出口（決着した結果 verdicts・objection・new_open_units・lowered）
REJUDGE_WHERE = "判定（再審の結果）"           # 次の run の依頼の再審の結果の行の where
DOWNGRADES = "downgrades.json"
DOWNGRADE_KEYS = ("node", "what", "versus")
READS_INDEX_SUFFIX = "-block.json"   # 読んだ証拠の索引の名の尾（head_reads が行にしない）
HEADINGS = ("## 1. 人が決めること", "## 2. 入口・段・決めた人", "## 3. 止めたか", "## 4. 読んだ証拠と包み", "## 5. 見る所")
WHERE = tuple((gatemarks.PLAIN[n], n) for n in ("p2.diagnose", "p2.fix_plan", "p2.plan_review", "p3.fix", "p3.delta_review",
                                                   "p3.delta_fix", "p3.delta_review2", "p3.delta_fix2", "p4.ci"))
DIFFS = (("修正の差分", "fix_delta"), ("手直しの差分", "fix_delta2"))
REFIX_NODES = ("p3.delta_fix", "p3.delta_fix2")
CLEANED_HEAD = "起動の前に片付けた前の run（use.sh start が worktree・枝・控えを消した。差分のファイルと盤面は残る）"
INTERRUPTED_HEAD = "run が途中で終わった"
RETRIED_HEAD = "前の試みで落ち、続きで済んだ節"
AI_FIRST_NODE = "report"   # 盤面が報告の役の節を出したか（AI の報告を回すか。ai_report_go）。頭と初見検査の節は表で absent
AI_REPORT_KEYS = ("ok", "reason", "report_file", "cold_check", "record_invalid", "rejects")   # 最後の出口に写す AI の報告の欄


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
    """周の作業ファイル r<N>/<name>（scope の根の物も。scopes.all_rounds）のうち、周の番号が一番大きい物（同じ周は最後に
    登録した include の物。周を仮定しない）。無ければ None"""
    found = scopes.all_rounds(pathlib.Path(board_dir), name)
    return found[-1] if found else None


def final_gate_answer(board_dir) -> tuple:
    """最後の関所の答えの読み手（ここだけが final-gate-answer.json を読む）: (状態, 答えの doc, 答えのファイル)。
    answered＝{decision, text} が読めた／unreadable＝答えのファイルが在るのに読めない（doc は {}）、または関所の文が在るのに
    答えのファイルが無い（ファイルは None）／not_asked＝関所の文も答えも無い（関所が開かなかった。final_gate protected_only の既定では正常）"""
    ans = _latest(pathlib.Path(board_dir), FINAL_GATE_ANSWER)
    if ans is None:
        return ("unreadable" if _latest(pathlib.Path(board_dir), FINAL_GATE_FILE) is not None else "not_asked"), {}, None
    doc = _read_json(ans, None)
    if isinstance(doc, dict) and isinstance(doc.get("decision"), str):
        return "answered", doc, ans
    return "unreadable", {}, ans


def _gate_answer_note(board_dir) -> str:
    """盤面の問いの行に添える最後の関所の答えの一言（括弧つき）"""
    state, doc, ans = final_gate_answer(board_dir)
    if state == "answered":
        return f"（最後の関所の答え: {doc['decision']}「{doc.get('text') or ''}」）"
    if state == "unreadable":
        return f"（最後の関所の答えが読めなかった: {ans or '答えのファイルが無い'}）"
    return ""   # 開かなかった（final_gate protected_only の既定では正常）。冒頭 1 の head_decisions も何も出さない


def _all_rounds(board_dir: pathlib.Path, pattern: str) -> list:
    """周の作業ファイル r<N>/<pattern> の全部（include ごとに scope の根に残る物も。周の順。scopes.all_rounds）"""
    return scopes.all_rounds(pathlib.Path(board_dir), pattern)


def _output(b, nid: str):
    """節の最新の出力（state.outputs[節] の周の出力）。無ければ None"""
    info = (b.state.get("outputs") or {}).get(nid)
    if not info:
        return None
    return b.output_of_round(nid, info.get("round", b.round))


def _fix(b):
    """今の周の修正の返答（recount.fix_reply: 盤面の p3.fix か、1 回目に受け付けた返答の控え）。どちらも無い・控えが読めなければ
    None（読めない控えは冒頭 1 の _held_gap_lines が 1 行で言う）"""
    try:
        return recount.fix_reply(b)[0]
    except (recount.Unreadable, BoardGap):
        return None


HELD_HEAD = "1 回目に受け付けた修正の返答"


def _held_gap_lines(b) -> list:
    """冒頭 1 の、修正の返答を 1 回目に受け付けた返答の控えから読もうとして読めなかった 1 行（読めれば・無ければ何も出さない）"""
    try:
        recount.fix_reply(b)
    except recount.Unreadable:
        return []
    except BoardGap as e:
        return [f"{HELD_HEAD}: 控えが読めない（{_one_line(str(e))}）"]
    return []


def _one_line(text) -> str:
    return " ".join(str(text).split())


HANDOFF_HEAD = "修正役が人に回した物（壊すと分かって通した理由 breaks.accepted。役だけで決めた代償なので人が確かめる）"


def handoff_lines(b) -> list:
    """修正役が人に回した物（1 件 1 行。実の利用者の run 97fd532f）: 今の周の修正の返答（_fix）の changes[].breaks.accepted
    （壊すと分かっていて通す理由。空白だけの行は除く）。役だけで決めた代償なのに読む節が無く、人に届かなかった（方針の文書の
    食い違いを「人に回す」と書いた行が、関所にも問いの台帳にも報告にも載らずに消え、独立の目が台帳の外の回付として作り直しを
    求めた）。報告の冒頭 1・冒頭 3 行の決めてほしいこと・最後の関所（開ける理由と節）が同じ行を出す。plan_faces の declared は
    数えない（写しが次の周の判定へ運ぶ別の道を持ち、誤検知の反論・別案を採らない答えも含む）。返答が読めなければ空"""
    out = []
    for c in (_fix(b) or {}).get("changes") or []:
        got = (c.get("breaks") or {}).get("accepted") if isinstance(c, dict) and isinstance(c.get("breaks"), dict) else None
        if isinstance(got, str) and got.strip():
            out.append(f"{c.get('unit_key')}: 壊すと分かって通した——{_one_line(got)}")
    return out


def _start_doc(b, start) -> dict:
    """start の出口（渡されなければ盤面の r1 の start の控え）"""
    if isinstance(start, dict):
        return start
    return gatemarks.start_doc(b.dir)


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
    ended = trace_rows(b, STOP_AFTER_END_OP)
    if halted and ended:
        return str(ended[-1].get("by") or ""), str(ended[-1].get("reason") or ""), ended[-1]
    return "", "", {}


def _halted(b) -> dict:
    """盤面の止め（state.halted）。報告の節を出すために退けた周の締めの止め（DiskBoard.report_after_round が state.works に
    移した物）も同じに読む（結末と冒頭 3 を退ける前と同じにする）"""
    return b.state.get("halted") or (b.state.get("works") or {}).get(DiskBoard.AFTER_ROUND) or {}


def trace_scan(b) -> tuple:
    """盤面の trace.jsonl の読み手の本体: (行の一覧, 調べたか, 飛ばした行の数)。ファイルが読めなければ ([], False, 0)——0 件では
    ない。JSON でない行・オブジェクトでない行は飛ばして数える"""
    try:
        lines = (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return [], False, 0
    rows, skipped = [], 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if isinstance(row, dict):
            rows.append(row)
        elif line.strip():
            skipped += 1
    return rows, True, skipped


def trace_rows(b, op: str) -> list:
    """盤面の trace.jsonl のうち op の行（読めない・壊れた行は飛ばす。数えたい読み手は trace_scan）"""
    return [r for r in trace_scan(b)[0] if r.get("op") == op]


# ---------------------------------------------------------------- 報告の前の関所（TA15）
def gate_record(b) -> dict:
    """engine の cmd_finalize と同じ順: 止めていない盤面（halted が無い）は先に settle（止め札の後に待ちのまま残る報告の節を
    片付ける。M9）。周を締めて止めた盤面（halted.by stop_after_round）は b.report_after_round で報告の節を出す（R61 の B。
    AI の報告を毎回回す。報告の節が出るのは、人か止め札で止めた・収束した・周を締めて止めた盤面で、途中で終わった run
    （interrupted）は build が AI の報告を回さない）→ finalize → run_validator（validator_runner の包みが効く口）。
    settle の RecordInvalid（報告の節を表で持つラインの関所）は捕まえて、同じ検証器を下でもう 1 度回す。
    返り {exit, accepted: exit ∈ report_accepts(b), out: 出力の全文（residue が阻害の箇条を読む）, tail: 出力の末尾,
    traces: 記録の痕跡の欄（空でない物）,
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
    return {"exit": code, "accepted": code in report_accepts(b), "out": out,
            "tail": "\n".join(out.rstrip().splitlines()[-TAIL_LINES:]), "traces": traces, "round_closed": closed}


def _no_fix(b, judged) -> bool:
    """直す物が無い周: 判定の出口の need_fix が偽（渡されていれば）。無ければ今の周の修正の返答（_fix）に changes が無い"""
    if isinstance(judged, dict) and isinstance(judged.get("need_fix"), bool):
        return not judged["need_fix"]
    fix = _fix(b)
    return isinstance(fix, dict) and not fix.get("changes")


def _validator_blockers(out: str) -> list | None:
    """検証器の exit 1 の出力の『収束を妨げるもの N 件:』の下の箇条（bullet の 2 行目以降は字下げの続き）。見出しが無い・
    N と箇条の数が合わなければ None"""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        m = BLOCKERS_HEAD.match(line)
        if not m:
            continue
        items = []
        for x in lines[i + 1:]:
            if x.startswith(BULLET):
                items.append(x[len(BULLET):])
            elif x.startswith(" ") and items:
                items[-1] += "\n" + x.strip()
            else:
                break
        return items if len(items) == int(m.group(1)) else None
    return None


def _closed_units(b) -> set:
    """この周の修正が盤面の受け付け（写しの fix_covers_open_units: 閉鎖の実証と数え直し）を通って閉じた単位の key。
    記録の units は判定の時のラベルのままで、1 周で止める run では次の周の判定が閉じを書かないため、検証器はこれらをいつも
    『未解消』と出す。changes に載っても、今の周の閉鎖の表（querytest.CLOSURE_FILE）で closed が偽の行の単位は外さない。
    表に行が無い単位は外し、閉じたと確かめていない物として最後の関所と報告の冒頭に名指しで並べる（querytest.closure_lines）"""
    rows = {r.get("unit_key"): r.get("closed") for r in querytest.closure_rows(b)}
    return {k for k in claimed_units(b) if rows.get(k, True) is True}


def claimed_units(b) -> list:
    """この周の修正役が changes に載せた単位の key（申告。閉じたかは閉鎖の表が決める）。読むのは今の周の修正の返答（_fix）で、
    前の周の出力の changes は、今の周の表と突き合わせない"""
    fix = _fix(b) or {}
    return [c["unit_key"] for c in fix.get("changes") or [] if isinstance(c, dict) and isinstance(c.get("unit_key"), str)]


def _unit_row_of(row: str, key: str) -> bool:
    """検証器の単位の行（blockers の『[block] 未解消…: <key>』か『[suggest] do-now 未対応…: <key>』）が key の物か。
    問いが付いた行（末尾に帰属や今ラウンドの問いの印）は key で終わらないので数えない"""
    return row.startswith(UNIT_ROW_HEADS) and row.endswith(f": {key}")


def _review_status(b) -> dict:
    """写しの検証器の俯瞰の判定の表（status → blocks を持つ行）。盤面が検証器を持たなければ pack の写しから引く"""
    holder = b if (getattr(b, "state", None) or {}).get("validator") else \
        types.SimpleNamespace(state={"validator": str(CORE / "scripts" / "review-record.py")})
    return validator_module(holder).REVIEW_STATUS


TESTS_TEXT = "最後のテストが"   # residue のテストの赤の行の text の頭（carry_left が落とす行を見分ける）


def _tests_where(tests: dict) -> str:
    return str(tests.get("log") or "最後のテスト")


# 走っていない目（not_run: 返答が無い・止めた周）と結果が無い目（missing: 目を回さなかった）は、目が阻害を返したのでないので
# 最後の関所を開ける理由に数えない（冒頭 1 の残りには数え、fixed を名乗らせない）。残りの行に、その目が在る時だけ添える
NOT_RUN_GATE_NOTE = "走っていない目（not_run）は阻害でないので最後の関所を開ける理由に数えない（残りには数える）"
MISSING_GATE_NOTE = "結果が無い目（missing）も同じ（再実行の要あり）"


def tests_word(b, tests) -> str:
    """最後のテストの頭の語（最後の関所・冒頭 1 の残り・次の依頼・冒頭 1 のテストの行が同じ口を読む）: 緑・赤・環境で起こせなかった
    （赤が全部、起こせない段 entry.env_only_red）・走れなかった・走らなかった（tests が None＝出口が無い）。任せ先の CI の役が走らせた回
    （by role_needed）は、盤面の p4.ci が済んでいれば素材 materials.local_checks の status（blk-tests の final と同じ読み）"""
    if tests is None:
        return "走らなかった"
    if tests.get("by") == "role_needed":
        status = entry.role_ci_status(b, tests)
        if status is None:
            return "走れなかった"
        return "緑" if status == "clean" else "赤"
    if tests.get("ok") is not True:
        return "走れなかった"
    if tests.get("green") is True:
        return "緑"
    return "環境で起こせなかった（コードの赤ではない）" if entry.env_only_red(tests) else "赤"


class EyeCounts(NamedTuple):
    """独立の目（R1〜R4）を 1 回ずつ見て分けた 3 つの欄。各欄は目ごとの {name, status, reason} の list。
    blocked: 表（REVIEW_STATUS）の blocks が真の status か、表に無い status（fail-closed）。
    not_run: status が not_run。目の判定でなく機械が書く欠け（返答が無い・止めた周）なので、最後の関所を開ける理由には数えないが、
    冒頭 1 の残りには表どおり数える（NOT_RUN_GATE_NOTE）。
    missing: 結果の行が無い目（阻害 0 件ではなく判定が無い）。not_run と同じく関所を開ける理由には数えず冒頭 1 の残りには数える（MISSING_GATE_NOTE）。
    表の skipped（軽量で省いた。blocks=False）はどの欄にも入れない。欄の名は表の status の名に合わせ、skipped の語と取り違えない"""
    blocked: list
    not_run: list
    missing: list


def eye_counts(b, reviews) -> EyeCounts:
    """独立の目の結果の控え reviews（{R: {status, reason}}）を EyeCounts に分ける。関所（line_edge._eyes）と冒頭 1（residue）が同じ口を読む"""
    table = _review_status(b)
    blocked, not_run, missing = [], [], []
    for name in EYES:
        r = (reviews or {}).get(name)
        if not isinstance(r, dict):
            missing.append({"name": name, "status": None, "reason": ""})
            continue
        status = r.get("status")
        got = {"name": name, "status": status, "reason": _one_line(r.get("reason") or "")}
        if status == "not_run":
            not_run.append(got)
            continue
        rule = table.get(status) if isinstance(status, str) else None
        if rule is None or rule.blocks:
            blocked.append(got)
    return EyeCounts(blocked, not_run, missing)


class Rest(NamedTuple):
    """検証器の外の残り: tests_word（最後のテストの頭の語）・counts（EyeCounts）・rows（[{where, text}]）"""
    tests_word: str
    counts: EyeCounts
    rows: list


def rest_outside_validator(b, *, tests, counts: EyeCounts, exit_problem: str = "") -> Rest:
    """検証器の外の残りの数えの正本（最後の関所と冒頭 1 の residue が同じ口を読む。検証器の行は持たない: 関所は検証器を回さない）。
    rows: tests が dict で tests_word が緑でなければ『最後のテストが<語>』・exit_problem（独立の目のブロックの出口が ok でない理由）が
    在れば『独立の目のブロックが ok でない: …』・目の行（blocked・not_run は『<R> が <status>: <reason>』、missing は
    『<R> の結果が無い——再実行の要あり』。where は『独立の目 <R>』）"""
    word = tests_word(b, tests)
    rows = []
    if isinstance(tests, dict) and word != "緑":
        rows.append({"where": _tests_where(tests), "text": f"{TESTS_TEXT}{word}"})
    if exit_problem:
        rows.append({"where": EYES_WHERE, "text": f"独立の目のブロックが ok でない: {exit_problem}"})
    said = {e["name"]: f"{e['name']} が {e['status']}: {e['reason']}" for e in [*counts.blocked, *counts.not_run]}
    lost = {e["name"]: f"{e['name']} の結果が無い——再実行の要あり" for e in counts.missing}
    rows += [{"where": f"{EYES_WHERE} {n}", "text": said.get(n) or lost[n]} for n in EYES if n in said or n in lost]
    return Rest(word, counts, rows)


def residue(b, gate: dict, *, tests: dict | None = None, eyeing: dict | None = None) -> list:
    """fixed を名乗らせない残りの行（字のまま冒頭 1 と次の run の依頼に出す）: 検証器の阻害（exit 1 の箇条から名指しの帳尻の行
    FIRST_ROUND_LINE と、この周の受け付けを通った修正で閉じた単位の行だけを除いた物。読めなければ fail-closed で 1 行）と、
    検証器の外の残り（rest_outside_validator。最後のテストが緑でない・走れなかった（tests が None＝飛ばされた時は数えない）・
    独立の目（blk-eyes の出口）が ok でない・目の阻害と走っていない目と結果が無い目）。返りは [{where, text}]"""
    rows = []
    if gate.get("exit") == 1:
        found = _validator_blockers(str(gate.get("out") or ""))
        if found is None:
            rows.append({"where": VALIDATOR_WHERE, "text": "検証器の出力を読めない（exit 1。見出しか箇条の数が合わない）"})
        else:
            closed = _closed_units(b)
            rows += [{"where": VALIDATOR_WHERE, "text": x} for x in found
                     if x != FIRST_ROUND_LINE and not any(_unit_row_of(x, k) for k in closed)]
    counts, problem = EyeCounts([], [], []), ""
    if isinstance(eyeing, dict):
        counts = eye_counts(b, eyeing.get("reviews"))
        problem = "" if eyeing.get("ok") is True else _one_line(eyeing.get("reason") or "理由なし")
    named = {f"{EYES_WHERE} {e['name']}": f"{e['name']} が {e['status']}" for e in [*counts.blocked, *counts.not_run]}
    for r in rest_outside_validator(b, tests=tests, counts=counts, exit_problem=problem).rows:
        said = named.get(r["where"])   # 検証器の blockers が同じ周の記録から既に出した目の行（名と status が同じ）は二重に数えない。status が違う行は残す
        if said and any(x["where"] == VALIDATOR_WHERE and x["text"].startswith(said) for x in rows):
            continue
        rows.append(r)
    return rows


def stop_outcome(b) -> tuple:
    """盤面の止め（_stop_info）を結末の語に分ける: (結末の語, by, 一言)。止めていなければ ()"""
    by, reason, info = _stop_info(b)
    if by.startswith(REQUEST_BY):
        return "stopped_by_request", by, reason
    if (info and info is b.state.get("halted") and by == ANSWER_BY) or by.startswith(HUMAN_BY):
        return "stopped_by_human", by, reason
    if by.startswith(LINE_BY):
        return "stopped_by_line", by, reason
    return ()


def stopped_run(board_dir) -> tuple | None:
    """差分を当てる前（use.sh apply）に見る記録の止まり: 盤面の止めか最後の関所の stop・reject なら (結末の語, by, 一言)、
    記録が止まりでないと言えば ()、止まりかを言える記録（最後の関所の答え・state の stop か halted）が無いか、在るのに
    読めなければ None（decision が文字列でない答えも「読めない」で、旧い式の () からここで None に変わった）。
    盤面は開かずにファイルとして読む（周の途中で終わった run の盤面も読む）"""
    d = pathlib.Path(board_dir)
    state = _read_json(d / "state.json", None)
    unreadable = not isinstance(state, dict) and (d / "state.json").exists()
    state = state if isinstance(state, dict) else {}
    stopped = stop_outcome(types.SimpleNamespace(state=state, dir=d))
    if stopped:
        return stopped
    got, doc, ans = final_gate_answer(d)
    if got == "answered" and doc["decision"] in FINAL_GATE_STOPS:
        return "stopped_by_human", FINAL_GATE_BY, str(doc.get("text") or "")
    if unreadable or (got == "unreadable" and ans is not None):
        return None
    if got == "answered":
        return ()
    return () if state.get("stop") or _halted(types.SimpleNamespace(state=state)) else None


def decide_outcome(b, gate: dict, *, tests: dict | None = None, judged: dict | None = None,
                   eyeing: dict | None = None) -> str:
    """結末。順: 止め札（by request:）→ stopped_by_request、関所の stop・reject（halted.by answer か by human:）→ stopped_by_human、
    機械の止め（by works:）→ stopped_by_line、人に聞いたまま（pending_human）か食い違いの申し出を人に回した（ask_human と、案の直しを
    諦めた fix_plan_item。conflict.asked）→ needs_human、関所が通らない（accepted か round_closed が偽）→ record_invalid、
    直す物が無い周 → no_fix_needed、残り（residue:
    検証器の阻害・最後のテストが緑でない・独立の目の阻害と走っていない目と結果が無い目）が在る → round_limit、他 → fixed。
    **fixed・no_fix_needed は accepted と round_closed が真の時だけ、fixed はさらに残りが無い時だけ**。直す物が無い周の赤は
    直しが起こした物でないので no_fix_needed のまま冒頭 1 に出す。report_accepts が 1 を受けるのは 1 周で止める
    run の帳尻の行を通すためで、1 の中身は residue が見る。needs_human を record_invalid の前に置くのは、人に聞いて
    いる盤面は周の記録がまだ無く（検証器が 2）、record_invalid の後ろでは needs_human に届かないため（〔線A計〕T15 の並びから
    替えた。どちらも成功の結末ではない）"""
    stopped = stop_outcome(b)
    if stopped:
        return stopped[0]
    if b.state.get("pending_human") or _asked(b):   # 食い違いの申し出を人に回した単位は直さずに残した
        return "needs_human"
    if not gate.get("accepted") or not gate.get("round_closed"):
        return "record_invalid"
    if _no_fix(b, judged):
        return "no_fix_needed"
    if residue(b, gate, tests=tests, eyeing=eyeing):
        return "round_limit"
    return "fixed"


# ---------------------------------------------------------------- 次の run に渡す依頼
def _r2_redesign(row) -> bool:
    return str(row.get("text") or "").startswith(R2_REDESIGN)


def _accept_last_files(board_dir: pathlib.Path) -> list:
    """盤面の根と、根の直下の scope の根（include の名・fan_out の子）の accept-last.json（根が先、scope は名の順）。登録
    （scopes.json）でなく置き場を見る: 盤面を開く前に scope の根に書く受け付け（intake の前の役）も拾う"""
    d = pathlib.Path(board_dir)
    return [p for p in [d / script_io.ACCEPT_LAST, *sorted(d.glob(f"*/{script_io.ACCEPT_LAST}"))] if p.is_file()]


def prior_failures(b, left: list | None = None) -> list:
    """この run で最後まで通らなかった物 [{where, text}]（次の run の判定役と修正案の役の材料に貼る。直す穴ではない）:
    ①盤面の根と scope の根の accept-last.json（受け付けの出口が最後の結果を上書きする控え。script_io.note_last）のうち ok で
    ない行。text は最後の理由のファイルの本文（読めなければ行の reason）を 1 行にした物。where は「受け付け <名>」と、scope の根
    なら（<scope>）。控えが読めなければその旨の行（黙って 0 件に見せない）
    ②残り left（residue の返り）のうち R2 の作り直しの行（R2_REDESIGN で始まる。検証器と独立の目の両方の形を 1 行にまとめる）"""
    d = pathlib.Path(b.dir)
    rows = []
    for p in _accept_last_files(d):
        scope = "" if p.parent == d else p.parent.name
        where = lambda name: f"{ACCEPT_WHERE} {name}" + (f"（{scope}）" if scope else "")  # noqa: E731
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("object でない")
        except (OSError, ValueError) as e:
            rows.append({"where": where(script_io.ACCEPT_LAST), "text": f"受け付けの最後の結果の控え {p} が読めない: {_one_line(e)}"})
            continue
        for name, r in doc.items():
            if not isinstance(r, dict) or r.get("ok") is True:
                continue
            text = ""
            if r.get("reason_file"):
                try:
                    text = pathlib.Path(str(r["reason_file"])).read_text(encoding="utf-8")
                except OSError:
                    text = ""
            rows.append({"where": where(name), "text": _one_line(text or r.get("reason") or "理由の記録が無い")})
    r2 = [r for r in left or [] if _r2_redesign(r)]
    if r2:   # 独立の目の形を先に採る（検証器の同じ目の行は二重に載せない）
        pick = next((r for r in r2 if str(r.get("where") or "").startswith(EYES_WHERE)), r2[0])
        rows.append({"where": f"{EYES_WHERE} R2", "text": _one_line(pick["text"])})
    return rows


def prior_lines(rows: list) -> list:
    """報告の節 PRIOR_HEADING の行（件数と 1 件 1 行）"""
    return [f"{len(rows)} 件（次の run の依頼の下書き {NEXT_REQUEST_FILE} の prior_failures に載せた。判定役と修正案の役の材料に"
            "貼る注意で、直す穴ではない）"] + [f"{r['where']}: {r['text']}" for r in rows]


def carry_left(left: list | None, owned: set, tests: dict | None) -> list:
    """残り left（residue の返り）の全件を次の依頼へ運ぶ。落とすのは R2 の作り直しの行（findings でなく prior_failures に
    載せる。findings は目的の役が生のまま読み、独立設計の入力に流れるため）と、次の 2 つの重複だけ: ①最後のテストが緑でない行（tests が赤・
    走れなかった時に residue が足す行。next_request が理由つきの自前の行を持つ）②owned の単位の『[block] 未解消: <key>』の行
    （その単位は not_done・人に回した単位・再審の行が自分の字で持つ）"""
    red = (_tests_where(tests), TESTS_TEXT) if isinstance(tests, dict) else None
    return [r for r in left or []
            if not _r2_redesign(r)
            and not (red and r["where"] == red[0] and r["text"].startswith(red[1]))
            and not any(_unit_row_of(r["text"], k) for k in owned)]


def lens_next_items(b) -> list:
    """レンズの落ちた（観点を誰も見ていない）物を「再実行の要あり」の行で運ぶ。控えが読めなければ、どのレンズが見たか確かめられて
    いないので、それも同じ言い方で運ぶ（読めない物を 0 件に見せない）。仕組みの異常は運ばない（works の不具合で利用者の依頼ではない）"""
    s = lens.summary(b)
    if not s["readable"]:
        return [{"where": "レンズ", "text": f"レンズの控えが読めない——再実行の要あり: {_one_line(s['reason'])}"}]
    return [{"where": f"レンズ {f['lens']}", "text": f"{f['lens']}（再実行の要あり: 落ちて観点を誰も見ていない。理由: {_one_line(f['reason'])}）"}
            for f in s["failed"]]


def next_request(b, *, tests: dict | None = None, left: list | None = None) -> list:
    """次の run に渡す依頼（1 本目の依頼の型 [{where, text}]。key・一言は字のまま）:
    手直し 2 回目が fixed と言った穴（検算が要る）・declared で残した穴（どちらも枝の名札 _tie_notes を text の終わりに添える）・修正の not_done・最後のテストが緑でない行・
    残り（left＝residue の返り）の全件（carry_left。テストの赤は上の行が持つ。not_done と人に回した単位の検証器の単位の行は、
    その単位の行が持つので渡さない）・落ちたレンズの「再実行の要あり」（lens_next_items）・
    再審されずに残った異議（loop.rejudge_requested。写し直しの前で再審の節が無い run と、会話が無くて止めた run）・
    決着した再審の結果（rejudge-exit.json の判定と異議の文・再審が直す単位にした単位・block から下げた単位。単位の行を持つ
    単位は検証器の単位の行を渡さない）・
    盤面が人に聞いたままの問い（独立の目の r4.human_gate など。この run では答えを受けないので次の run へ渡す。計画 P1 Task 33 の (b)。
    最後の関所の答え・読めなかったも、その行の後ろに添える）・
    食い違いの申し出を人に回して直さずに残した単位（conflict.asked: ask_human と、案の直しを諦めた fix_plan_item。裁定が外した
    単位 conflict.ruled_units ごとに 1 行。裁定の文は字のまま）・
    判定が凍結した目的の外として単位にしなかった材料の所見（outpurpose.next_items。最後の周の分を、材料の行の全部の欄で、運んだ
    印と下書きの印 draft・source つきで）"""
    items = []
    for n, nid in enumerate(REFIX_NODES, 1):
        out = _output(b, nid) or {}
        tags = _tie_notes(b, n) if out.get("handled") else {}
        for h in out.get("handled") or []:
            if not isinstance(h, dict) or not isinstance(h.get("key"), str):
                continue
            where = (h.get("files") or [None])[0] or h["key"]
            tag = f"（枝: {tags[h['key']]}）" if h["key"] in tags else ""
            if h.get("handled") == "declared":
                items.append({"where": str(where), "text": f"{h['key']}（手直しが declared で残した穴: {h.get('how') or ''}）{tag}"})
            elif h.get("handled") == "fixed" and nid == REFIX_NODES[-1]:
                items.append({"where": str(where),
                              "text": f"{h['key']}（手直し 2 回目が fixed と言ったが、3 回目の審査は無い——検算が要る: {h.get('how') or ''}）{tag}"})
    fix = _fix(b) or {}
    for nd in fix.get("not_done") or []:
        if isinstance(nd, dict) and isinstance(nd.get("unit_key"), str):
            items.append({"where": nd["unit_key"], "text": f"{nd['unit_key']}（修正がやらなかった: {nd.get('why') or ''}）"})
    if isinstance(tests, dict) and tests_word(b, tests) != "緑":
        items.append({"where": str(tests.get("log") or "最後のテスト"),
                      "text": f"{TESTS_TEXT}{tests_word(b, tests)}（{tests.get('reason') or 'ログを読む'}）"})
    asked = _asked_units(_asked(b))
    settled, settled_keys = _rejudge_next(b)
    # 単位の行（not_done・人に回した単位・再審が開いた・下げた単位）を自分の字で持つ単位は、検証器の『[block] 未解消: <key>』を二重に渡さない
    owned = {nd["unit_key"] for nd in fix.get("not_done") or [] if isinstance(nd, dict) and isinstance(nd.get("unit_key"), str)} \
        | {k for k, _ in asked} | settled_keys
    items += carry_left(left, owned, tests)
    items += lens_next_items(b)
    items += outpurpose.next_items(b.dir)
    req = (b.loop_state or {}).get("rejudge_requested") or {}
    if isinstance(req, dict) and isinstance(req.get("text"), str) and req["text"]:
        items.append({"where": "判定（再審されずに残った異議）", "text": req["text"]})
    items += settled
    for k, r in asked:
        items.append({"where": k,
                      "text": f"{k}（{conflict.HEAD}を人に回した——直さずに残した。裁定の文: {r['ruling']['text']}。"
                              f"名指し {', '.join(r['between'])}"
                              + (f"。案の直し: {r[conflict.REPLAN_WHY]}。{conflict.HELD_WORK_KEPT}" if r.get(conflict.REPLAN_WHY)
                                 else "") + "）"})
    ph = b.state.get("pending_human") or {}
    if ph.get("question"):
        asked = "・".join(str(x) for x in ph.get("items") or [])
        items.append({"where": f"人の関所（{ph.get('node')}）",
                      "text": f"{_one_line(ph['question'])}" + (f"（挙がった物: {_one_line(asked)}）" if asked else "")
                              + _gate_answer_note(b.dir)})
    seen, out = set(), []
    for it in items:
        k = (it["where"], it["text"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ---------------------------------------------------------------- 冒頭 3 行と 1〜5
# 結末の語（decide_outcome の返り）→ 平易な言い方（冒頭 3 行の 1 行目。語は括弧に残す）
OUTCOME_WORDS = {"fixed": "直して、最後のテストまで通った", "no_fix_needed": "直す物が無かった",
                 "round_limit": "決めた周の数のうちに直しきれずに止まった", "stopped_by_request": "止め札で止めた",
                 "stopped_by_human": "人が関所で止めた", "stopped_by_line": "ラインが途中で止めた",
                 "needs_human": "人の判断を待ったまま止まった", "record_invalid": "記録が検証器を通らない（結果を名乗れない）",
                 "interrupted": "run が途中で終わった"}


def fix_split(b) -> dict:
    """今の周の修正の段が受けた単位と止めて持ち越した単位: {"kept": [修正の返答（_fix）の changes の unit_key],
    "parked": [{unit_key, why, patch}]}。parked は trace の conflict.ACCEPT_PARKED_OP の行のうち、控えの patch が今の周の作業の置き場
    （r<今の周>/）に在る行から、行の順に。why は単位に結んだ拒否の行を「 / 」でつないだ物"""
    fix = _fix(b) or {}
    kept = [c["unit_key"] for c in fix.get("changes") or [] if isinstance(c, dict) and isinstance(c.get("unit_key"), str)]
    parked = []
    for row in trace_rows(b, conflict.ACCEPT_PARKED_OP):
        patch = str(row.get("patch") or "")
        if pathlib.Path(patch).parent.name != f"r{b.round}":
            continue
        reasons = row.get("reasons") if isinstance(row.get("reasons"), dict) else {}
        parked += [{"unit_key": k, "why": " / ".join(str(t) for t in reasons.get(k) or []), "patch": patch}
                   for k in row.get("unit_keys") or [] if isinstance(k, str)]
    return {"kept": kept, "parked": parked}


def split_line(b) -> str:
    """冒頭 1 行目に添える、修正の段が受けた単位と止めて持ち越した単位の 1 文（fix_split。止めた単位が無ければ ""）"""
    got = fix_split(b)
    if not got["parked"]:
        return ""
    parked = [p["unit_key"] for p in got["parked"]]
    patches = list(dict.fromkeys(p["patch"] for p in got["parked"]))
    return (f"修正の段は {len(got['kept'])} 単位（{'・'.join(got['kept']) or 'なし'}）を受け、{len(parked)} 単位"
            f"（{'・'.join(parked)}）を止めて持ち越した（直しの控え {'・'.join(patches)}。次の run の依頼に載る）")


def head3(b, outcome: str, *, left: list | None = None, next_items: list | None = None) -> list:
    """報告の冒頭 3 行（gatemarks.head3）: 起きたこと＝結末（修正の段が単位を止めて持ち越したら、受けた単位と止めた単位の 1 文
    split_line を「。」でつなぐ）・決めてほしいこと＝冒頭 1 に並ぶ人が決める物の件数（盤面の問い・保留の
    問い・人に回した食い違い・修正役が人に回した物（handoff_lines）・直しきれずに残った物・記録が通らないこと。無ければ 2 行目は次の run に渡す物の件数）・推し＝判定の役が
    問いの理由に書いた推し（機械は作らない）"""
    ph = b.state.get("pending_human") or {}
    held = gatemarks.held_lines(b)
    parts = [("人に聞いている問い", 1 if ph else 0), ("保留にしたままの問い", len(held)),
             ("人に回した食い違いの申し出", len(_asked(b))), ("修正役が人に回した物", len(handoff_lines(b))),
             ("直しきれずに残った物", len(left or []) if outcome == "round_limit" else 0),
             ("記録が検証器を通らないこと", 1 if outcome == "record_invalid" else 0)]
    parts = [(w, n) for w, n in parts if n]
    decide = (f"{sum(n for _, n in parts)} 件——" + "・".join(f"{w} {n} 件" for w, n in parts) + "（下の「1. 人が決めること」）"
              if parts else "")
    split = split_line(b)
    return gatemarks.head3(f"{OUTCOME_WORDS.get(outcome, '結末が決まらない')}（{outcome}）" + (f"。{split}" if split else ""), decide,
                           gatemarks.pushes([*held, *(ph.get("items") or [])]),
                           other=f"次の run に渡す物: {len(next_items or [])} 件")


def head_decisions(b, gate: dict, *, tests: dict | None = None, outcome: str = "", next_items: list | None = None,
                   next_file: str = "", left: list | None = None) -> list:
    """冒頭 1（人が決めること）: 記録が関所を通らない時の検証器の末尾と痕跡・round_limit の時の残り（left＝residue の返り）の各行・
    clean が消したファイル・レンズ・仕組みの異常・残りの件数（always_rows。結末に依らず常に）・
    関所の答え（事前審査の関所と最後の関所）と読めなかった保留（gatemarks.unread_hold_lines）・事前審査の壁打ちの往復（converge.lines）・
    人が止めた一言・最後のテストと修正前のテスト（entry.baseline_line）・盤面の問い・食い違いの申し出の件数と内訳（_conflict_line）・修正役が人に回した物（handoff_lines）・同じ run の中で直した修正案の項目（_amend_lines）・判定の役が保留にしたままの問い（gatemarks.held_lines）と答え方（gatemarks.ANSWER_HOW）・関所か依頼の answers で答えた問い（gatemarks.answered_lines）・どの問いにも当たらなかった依頼の答え（gatemarks.unmatched_answer_lines）・再審の問い・決着した再審の結果（rejudge_lines）・再審による単位の変化・前提で測り直せなかった依頼・判定の単位の裏取り（verify_lines）・独立設計が問いは立たないと返した根拠の名指しなし（_design_unanchored）・並行 PR の
    申し送りの下書きと外した範囲・次の run に渡す物の件数と、その下に判定が目的の外として単位にしなかった所見（outpurpose.report_lines）と
    無人の run の答えの下書きの件数（gatemarks.draft_line）。行の主語は平易な名で、盤面の節・記録の語は括弧に回す（gatemarks.named）"""
    lines = []
    if outcome == "record_invalid":
        lines.append(f"記録が検証器を通らない（exit {gate.get('exit')}・受理 {report_accepts(b)}・今の周の記録が"
                     f"{'済んだ' if gate.get('round_closed') else '済んでいない'}）——fixed・no_fix_needed を出さない")
        if gate.get("tail"):
            lines += ["検証器の出力の末尾:", *[f"    {x}" for x in gate["tail"].splitlines()]]
        for field, val in (gate.get("traces") or {}).items():
            lines.append(f"記録の痕跡 {field}: {json.dumps(val, ensure_ascii=False)[:400]}")
    if outcome == "round_limit" and left:
        lines.append("直しきれずに残った物（結末を「直した」と名乗らない）:")
        lines += [f"  - {r['where']}: {r['text']}" for r in left or []]
    proc = b.record.get("process") or {}
    for h in proc.get("human_items") or []:
        if isinstance(h, dict):
            lines.append(f"{gatemarks.named(h.get('node'))}の答え: {h.get('answer')}「{h.get('note') or ''}」")
    lines += gatemarks.unread_hold_lines(b)
    lines += gatemarks.lines(b)
    lines += converge.lines(b)
    got, doc, ans = final_gate_answer(b.dir)
    if got == "answered":
        lines.append(f"最後の関所の答え: {doc['decision']}「{doc.get('text') or ''}」（{ans}）")
    elif got == "unreadable":
        lines.append(f"最後の関所の答えが読めなかった（{ans or '答えのファイルが無い'}）")
    by, reason, info = _stop_info(b)
    if by == FINAL_GATE_BY:
        lines.append(f"最後の関所で止めた: 「{reason}」")
    elif by.startswith(HUMAN_BY) or (by == ANSWER_BY and info is b.state.get("halted")):
        lines.append(f"関所で止めた（{by}）: 「{reason}」")
    if by == REJUDGE_SESSION_BY:
        lines.append(f"再審の会話を確かめられずに止めた: 異議を再審するか、新しい run で判定し直すかを決める（{_one_line(reason)}）")
    # 緑・赤の語は最後の関所と同じ口（tests_word。by role_needed で p4.ci が済んでいれば素材の status）
    role = entry.role_ci_status(b, tests) if tests is not None else None
    word = tests_word(b, tests)
    if tests is None:
        lines.append("最後のテスト: 走っていない")
    elif word == "走れなかった":
        lines.append(f"最後のテスト: 走れなかった（{tests.get('reason') or '理由なし'}・ログ {tests.get('log') or '無い'}）")
    elif word != "緑":
        head = f"最後のテスト: {word}" if word.startswith("環境") else f"{TESTS_TEXT}{word}"
        lines.append(f"{head}: {entry.suites_line(tests, role_status=role)}・ログ {tests.get('log') or '無い'}")
    else:
        lines.append(f"最後のテスト: 緑（{entry.suites_line(tests, role_status=role)}・ログ {tests.get('log') or '無い'}）")
    lines.append(entry.baseline_line(b))
    ph = b.state.get("pending_human")
    if ph:
        lines.append(f"{gatemarks.named(ph.get('node'))}が人に聞いている問い（記録のまま引く）:")
        lines += [f"  {x}" for x in gatemarks.quote(ph.get("question"))]
        lines += [f"  - {x}" for x in ph.get("items") or []]
    held = gatemarks.held_lines(b)
    if held:
        lines.append(f"判定の役が人に聞くと保留にしたままの問い（問いの台帳・{len(held)} 件）:")
        lines += [f"  - {x}" for x in held]
        lines.append(f"  {gatemarks.ANSWER_HOW}")
    done = gatemarks.answered_lines(b)
    if done:
        lines.append(f"{gatemarks.ANSWERED_HEAD}（問いの台帳・{len(done)} 件。保留の件数には数えない）:")
        lines += [f"  - {x}" for x in done]
    lines += gatemarks.unmatched_answer_lines(b)
    lines.append(_conflict_line(b))
    handoff = handoff_lines(b)
    if handoff:
        lines.append(f"{HANDOFF_HEAD}（{len(handoff)} 件）:")
        lines += [f"  - {x}" for x in handoff]
    unproven = querytest.unproven_lines(b.dir)
    if unproven:
        lines.append(f"{querytest.UNPROVEN_HEAD}: {len(unproven)} 件")
        lines += [f"  - {x}" for x in unproven]
    stuck = querytest.closure_lines(b, stuck_only=True)
    if stuck:
        lines.append(f"{querytest.STUCK_HEAD}: {len(stuck)} 件")
        lines += [f"  - {x}" for x in stuck]
    closure = querytest.closure_lines(b, claimed=claimed_units(b))
    if closure:
        lines.append(f"{querytest.CLOSURE_HEAD}: {len(closure)} 件")
        lines += [f"  - {x}" for x in closure]
    lines += _amend_lines(b)
    lines += _held_gap_lines(b)
    lines += rejudge_lines(b)
    lines += _rejudge_changes(b)
    lines += _premise_hypotheses(b)
    lines += verify_lines(b)
    lines += _design_unanchored(b)
    lines += _pr_lines(b)
    lines += branch_rows(b)
    n = len(next_items or [])
    lines += always_rows(b, left=left)
    lines.append(f"次の run に渡す物: {n} 件" + (f"（{next_file}）" if next_file else ""))
    lines += outpurpose.report_lines(b.dir)
    drafts = gatemarks.draft_line(gatemarks.answer_drafts(b), next_file)
    if drafts:
        lines.append(drafts)
    return lines


def _amend_lines(b) -> list:
    """冒頭 1 の同じ run の中で直した修正案の項目（replan.lines。無ければ何も出さない。控えが読めなければその 1 行）"""
    try:
        got = replan.lines(b)
    except BoardGap as e:
        return [f"{replan.AMEND_HEAD}: 控えが読めない（{_one_line(str(e))}）"]
    return [f"{replan.AMEND_HEAD}: {len(got)} 件", *[f"  - {x}" for x in got]] if got else []


def _asked(b) -> list:
    """今の周に人に回した食い違いの申し出（控えが読めなければ空。件数の行が「読めない」と言う）"""
    try:
        return conflict.asked(b)
    except BoardGap:
        return []


def _asked_units(rows) -> list:
    """人に回した行（_asked）が外した単位ごとの (単位, 行)（conflict.ruled_units。ask_human は申し出の単位、諦めた fix_plan_item は
    その項目に載る単位の全部）。1 単位に 1 行: 単位自身の申し出の行を先に、無ければ先に当たった行。並びは単位が先に現れた順"""
    own, out = {}, {}
    for r in rows:
        own.setdefault(r["unit_key"], r)
    for r in rows:
        for k in conflict.ruled_units(r):
            out.setdefault(k, own.get(k, r))
    return list(out.items())


def _conflict_line(b) -> str:
    """冒頭 1 の食い違いの申し出の件数（run ごと。0 件も出す）と、裁定の内訳（fix_plan_item は在る時だけ）と種類の内訳
    （DIV_KINDS の順に 0 件も。kind の無い前の形の行は末尾に「種類なし」）"""
    try:
        c = conflict.counts(b)
        k = conflict.kind_counts(b)
    except BoardGap as e:
        return f"{conflict.HEAD}: 控えが読めない（{_one_line(str(e))}）"
    plan_n = f"・案の項目を直す（{conflict.REPLAN}）{c[conflict.REPLAN]}" if conflict.REPLAN in c else ""
    kinds = [f"{x} {k[x]}" for x in conflict.DIV_KINDS] + ([f"種類なし {k[conflict.UNSET]}"] if conflict.UNSET in k else [])
    return (f"{conflict.HEAD}: {c['parked']} 件（裁定の内訳。括弧は記録の名: テストの直しを許す（fix_test_scope）"
            f"{c['fix_test_scope']}・コードをこう直す（fix_code_as）{c['fix_code_as']}・人に回す（ask_human）{c['ask_human']}"
            f"{plan_n}・裁定なし {c['unruled']}）。種類の内訳: " + "・".join(kinds))


def _rejudge_changes(b) -> list:
    """再審で単位が変わった行（rejudge-diff.json の changed の全部。異議に名指されていない物は「争点でない」と印を付ける）"""
    lines = []
    for p in _all_rounds(b.dir, REJUDGE_DIFF):
        for row in _read_json(p, []) or []:
            for c in row.get("changed") or [] if isinstance(row, dict) else []:
                if not isinstance(c, dict):
                    continue
                who = "異議に名指された単位" if c.get("named") else "争点でない単位"
                if c.get("kind") == "changed":
                    lines.append(f"再審（{row.get('pass')}）で{who}が変わった: {c.get('key')} の {c.get('field')}: "
                                 f"{json.dumps(c.get('before'), ensure_ascii=False)} → {json.dumps(c.get('after'), ensure_ascii=False)}")
                else:
                    lines.append(f"再審（{row.get('pass')}）で{who}が{'足された' if c.get('kind') == 'added' else '消えた'}: "
                                 f"{c.get('key')}")
    return lines


def _rejudge_exits(b) -> list:
    """周ごとの再審の出口 [(周の名, パス, 中身)]（周の順）。読めない・形が違う出口の中身は None（黙って飛ばさない）"""
    rows = []
    for p in _all_rounds(b.dir, REJUDGE_EXIT):
        doc = _read_json(p)
        rows.append((p.parent.name, p, doc if isinstance(doc, dict) else None))
    return rows


def _keys(v) -> list:
    return [k for k in v or [] if isinstance(k, str) and k]


def _label_now(b, key: str) -> str:
    return next((str(u.get("label")) for u in b.record.get("units") or [] if u.get("key") == key), "（記録に無い）")


def _settled_rounds(b) -> list:
    """周ごとの決着した再審の結果 [(周の名, パス, (往復の数, 判定の文), 異議の文, 開いた単位, 下げた単位)]。中身が読めない出口は
    判定を None にする。往復も単位も異議も無い出口（再審が無かった周）だけを飛ばす——判定の欄が無い往復は
    「判定の欄が無い」と書き、同じ出口の単位を落とさない"""
    rows = []
    for rnd, p, doc in _rejudge_exits(b):
        if doc is None:
            rows.append((rnd, p, None, "", [], []))
            continue
        raw = doc.get("verdicts") if isinstance(doc.get("verdicts"), list) else []
        opened, lowered = _keys(doc.get("new_open_units")), _keys(doc.get("lowered"))
        obj = _one_line(doc.get("objection") or "")
        if not (raw or opened or lowered or obj):
            continue
        verdicts = [v if isinstance(v, str) and v else "（判定の欄が無い）" for v in raw] or ["（判定の往復が無い）"]
        rows.append((rnd, p, (len(raw), "・".join(verdicts)), obj, opened, lowered))
    return rows


def rejudge_lines(b) -> list:
    """決着した再審の結果（rejudge-exit.json）の行。報告の冒頭 1 と最後の関所の文が同じ行を出す: 周ごとの判定と異議の文・
    再審が直す単位にした単位（この run では直していない）・block から下げた単位（拒まずに見せる）。読めない出口も 1 行"""
    lines = []
    for rnd, p, verdict, obj, opened, lowered in _settled_rounds(b):
        if verdict is None:
            lines.append(f"再審の記録が読めない（{p}）——再審の結果を確かめる")
            continue
        lines.append(f"再審の結果（{rnd}・{verdict[0]} 往復）: {verdict[1]}" + (f"（異議: {obj}）" if obj else ""))
        lines += [f"  - 再審が直す単位にした（この run では直していない——次の run に渡す）: {k}" for k in opened]
        lines += [f"  - 再審が block から {_label_now(b, k)} に下げた（拒まずに見せる——人が確かめる）: {k}" for k in lowered]
    return lines


def _rejudge_next(b) -> tuple:
    """次の run に渡す再審の結果の行 [{where, text}] と、単位の行を持つ key の集合"""
    items, keys = [], set()
    for rnd, p, verdict, obj, opened, lowered in _settled_rounds(b):
        if verdict is None:
            items.append({"where": REJUDGE_WHERE, "text": f"再審の記録が読めない（{p}）——再審の結果を確かめる"})
            continue
        items.append({"where": REJUDGE_WHERE, "text": f"{rnd} の再審: {verdict[1]}" + (f"（異議: {obj}）" if obj else "")})
        items += [{"where": k, "text": f"{k}（再審が直す単位にした——この run では直していない）"} for k in opened]
        items += [{"where": k, "text": f"{k}（再審が block から {_label_now(b, k)} に下げた——人が確かめる）"} for k in lowered]
        keys.update(opened, lowered)
    return items, keys


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


def verify_lines(b) -> list:
    """周ごとの判定の単位の裏取りの申し送り（VERIFY_NOTES）の行。読めない控えはその 1 行（黙って飛ばさない）"""
    lines = []
    for p in _all_rounds(b.dir, VERIFY_NOTES):
        doc = _read_json(p)
        rnd = p.parent.name
        if not isinstance(doc, dict) or not isinstance(doc.get("units"), list):
            lines.append(f"判定の単位の裏取り（{rnd}）: 申し送りが読めない（{p}）")
            continue
        units = [u for u in doc["units"] if isinstance(u, dict)]
        notes = []
        for u in units:
            key = u.get("key")
            if u.get("state") != "checked":
                notes.append(f"確かめられなかった: {key}（{_one_line('・'.join(map(str, u.get('errors') or [])))}）")
                continue
            if u.get("verdict") == "not_root":
                notes.append(f"根本でない: {key}（本当の根: {_one_line(u.get('real_root'))}。{_one_line(u.get('why'))}）")
            elif u.get("verdict") == "unsure":
                notes.append(f"根本か決められない: {key}（{_one_line(u.get('why'))}）")
            if u.get("evidence_found") is False:
                notes.append(f"証拠が無い: {key}（{_one_line(u.get('evidence'))}）")
            if u.get("location_ok") is False:
                notes.append(f"場所が違う: {key}（正しい場所: {_one_line(u.get('location'))}）")
        syn = doc.get("synergy") if isinstance(doc.get("synergy"), dict) else {}
        if syn.get("state") == "checked":
            notes += [f"重複: {'・'.join(map(str, r.get('units') or []))}（{_one_line(r.get('why'))}）"
                      for r in syn.get("duplicates") or [] if isinstance(r, dict)]
            notes += [f"順番: {r.get('first')} → {r.get('then')}（{_one_line(r.get('why'))}）"
                      for r in syn.get("order") or [] if isinstance(r, dict)]
        else:
            notes.append("単位どうしの相乗りは確かめられなかった")
        if not notes:
            lines.append(f"判定の単位の裏取り（{rnd}）: {len(units)} 単位とも根本・証拠・場所が合った（重複・順番の名指しなし）")
            continue
        lines.append(f"判定の単位の裏取り（{rnd}・{len(units)} 単位。単位は消していない。減らすなら関所か再審で）:")
        lines += [f"  - {x}" for x in notes]
    return lines


def _design_unanchored(b) -> list:
    """冒頭 1 の、独立設計が問いは立たないと返したのに根拠にパス:行の名指しが無い 1 行（design.anchor_note。ほかは何も出さない）"""
    got, _ = design.made(b.dir)
    if not got or got.get("question_stands"):
        return []
    r = got.get("premise_invalid_reason") or got.get("reason") or ""
    return [f"独立設計は問いが立たないと返したが、{design.UNANCHORED}（{_one_line(r)}）"] if design.anchor_note(r) else []


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


def head_entry(b, start: dict | None, *, mid: dict | None = None, cleaned_runs: str = "", depth_lines=()) -> list:
    """冒頭 2: 入口・段・gates・最後の関所の形・包み・機能の on でない物（入力 features_off・features_on と既定）・決めた人（関所の答えの数）・このラインに無い節の数と一覧のパス・下げている所・
    線が渡した深さの行（depth_lines。単位ごとの深さと、軽量で省いた物。渡されなければ出さない）・
    中の検査の枠の行（境の節の mid_note）・起動の前に
    片付けた前の run の 1 行（入力 cleaned_runs。空なら出さない）"""
    s = _start_doc(b, start)
    reqs = s.get("requests")
    if reqs is None:
        reqs = sum(len(x.get("findings") or []) for x in (b.record.get("process") or {}).get("request_findings") or []
                   if isinstance(x, dict))
    # 入口の文は start が控えに書く（渡された出口には無い。控えにも無いのは入口が判定の 1 本だった版の run）
    words = s.get("entry_words") or _start_doc(b, None).get("entry_words") or f"判定から（依頼 {reqs} 件）"
    parts = [f"入口: {words}", f"段: {s.get('thickness') or '（控えが無い）'}", f"gates: {s.get('gates') or '空'}"]
    if s.get("final_gate"):
        parts.append(f"最後の関所: {s['final_gate']}")
    parts.append(f"包み: {'optional（包み無し）' if s.get('adapter') == 'optional' else '通す'}")
    # 機能（入力 features_off・features_on）は start の控えの欄（start の出口は機能ごとの on・off・auto だけを持つ）。
    # features_off の欄の無い控えはそれより前の版の run で、語を出さない（features_on の欄だけ無い控えは前の版の全部 on の既定。
    # entry.features_on_of）
    feats = s if entry.FEATURES_KEY in s else _start_doc(b, None)
    if entry.FEATURES_KEY in feats:
        parts.append(entry.features_part(feats.get(entry.FEATURES_KEY) or [], entry.features_on_of(feats)))
    humans = len((b.record.get("process") or {}).get("human_items") or [])
    lines = ["・".join(parts), f"決めた人: 関所の答え {humans} 件（record.process.human_items）"]
    absent = (b.state.get("works") or {}).get("not_in_line") or []
    note = b.dir / "rounds" / "works" / f"round-{b.round}.json"
    lines.append(f"このラインに無い節: {len(absent)} 個（一覧: {note if note.is_file() else 'state.json の works.not_in_line'}）")
    fl = forge_line(b)
    if fl:
        lines.append(fl)
    downs = declared_downgrades(b.table.line) if b.table is not None else []
    lines.append(f"下げている所: {len(downs)} 個")
    lines += [f"  - {r['node']}: {r['what']}（{r['versus']}）" for r in downs]
    lines += [str(x) for x in depth_lines or () if isinstance(x, str) and x]
    if isinstance(mid, dict) and mid.get("mid_note"):
        lines.append(f"中の検査の枠: {mid['mid_note']}")
    else:
        lines.append("中の検査の枠: 境の節の出口が届いていない（中の検査を回さなかった run）")
    if cleaned_runs:
        lines.append(f"{CLEANED_HEAD}: {cleaned_runs}")
    return lines


def forge_line(b) -> str:
    """冒頭 2 の 1 行: run の初めに機械が決めた forge（盤面の loop.forge。entry の on_init の差し替え）が無い種類なら、PR を前提に
    する確かめ（並行 PR）は条件外（not_applicable）と言う。GitHub の run・決めの無い盤面（前の版）は空"""
    why = forge.reason((getattr(b, "loop_state", None) or {}).get(forge.LOOP_KEY))
    return f"{FORGE_HEAD}: 無い——並行 PR の確かめは条件外（not_applicable。{why}）" if why else ""


def head_stop(b, *, interrupted: str | None = None, failed: list | None = None, retried: list | None = None) -> list:
    """冒頭 3: 止めたか（止め札・関所の stop・機械の止め。理由と止めた所）。interrupted は Archon の run の状態（線の中は
    分からないので空）、failed は落ちた節 [{node, error}]（reads.failed_nodes）。落ちた節が在れば節ごとに名前と誤りの文の
    1 行目を出し、無ければ Archon の run の状態を出す。retried は前の試みで落ち、続き（resume）で済んだ節
    [{node, failures, error}]（reads.retried_nodes）で、止めた理由でなく試みの記録として出す（結末は替えない）"""
    lines = []
    if interrupted is not None:
        for f in failed or []:
            error = (str(f.get("error") or "").strip().splitlines() or ["（誤りの文が無い）"])[0]
            lines.append(f"{INTERRUPTED_HEAD}: 節 {f.get('node')} が落ちた（誤り: {error}）")
        if not failed:
            lines.append(f"{INTERRUPTED_HEAD}。Archon の run の状態は {interrupted or '（不明）'}")
    by, reason, info = _stop_info(b)
    if by.startswith(REQUEST_BY):
        seen = trace_rows(b, FLAG_SEEN_OP)
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
    for r in retried or []:
        lines.append(f"{RETRIED_HEAD}: {r.get('node')}（落ちた回 {r.get('failures')}。"
                     f"最後の誤り: {r.get('error') or '（誤りの文が無い）'}）")
    return lines


def head_reads(board_dir, run_id: str, *, ci: dict | None = None) -> list:
    """冒頭 4: 読んだ証拠（各役の reads-<役>.json）と包みの行。出来事が unverified なら「出来事: 未確認（P13）」。部品の窓の
    包み無し（adapter optional）の run は「包み無し」の行の横に CI の役の知らせ（blk の collect.note）。包みを通す run で起動の
    記録が無ければ「包みが通っていない」。仕組みの異常の種別ごとの件数（anomaly_lines。1 件以上の種別だけ。調べていなければ「調べていない」）。包みの確かめで止めた盤面は
    止めた理由。範囲の相談の行（plan_ask_lines）。会話を継いだ起動の数。起動の即時の失敗（包みの終わりの記録の no_turn。節ごとの回と、build が盤面に写した
    NO_TURN_FILE）。盤面を書かない"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    lines, unverified = [], False
    # 索引（blk-plan の reads-plan-block.json・案の直しの reads-replan-block.json。{役: reads-<役>.json}）は役の読んだ証拠でない
    files = [p for p in _all_rounds(board_dir, "reads-*.json") if not p.name.endswith(READS_INDEX_SUFFIX)]
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
    lines += anomaly_lines(b, found_only=True)
    lines += gates_lines(b)
    lines += plan_ask_lines(b)
    by, reason, _ = _stop_info(b)
    if by == ADAPTER_BY:
        lines.append(f"包みの確かめで止めた: {reason}")
    cont = sum(1 for r in _launches(b, repo) if (r.get("session") or {}).get("mode") == "continued")
    lines.append(f"会話を継いだ起動: {cont} 本")
    dead = collections.Counter(r.get("node") or "—" for r in _no_turn_exits(b, repo))
    if dead:
        lines.append("起動の即時の失敗（1 手も進まずに終わり、Archon の起こし直しに任せた）: "
                     + "・".join(f"節 {n} {k} 回" for n, k in dead.items())
                     + f"。写さなかった result の全文: {board_dir / NO_TURN_FILE}（元は {adapter.exits_path(repo)}）")
    return lines


# 仕組みの異常の種別（名・trace の op・説明）。trace に異常の op を足す時はここに 1 行足せば、冒頭 4・仕組みの異常の節・関所の合計に出る
ANOMALY_OPS = (
    ("宣言の外の読み", scopes.READ_OUTSIDE_OP, "部品が manifest の consumes に無い盤面のファイルを読んだ。落とさない"),
    ("必須の出力の欠け", scopes.REQUIRED_MISSING_OP, "部品の窓の終わりに manifest の required の出力が無かった。役が落ちたか諦めた。止めない"),
    ("書き込みの記録が無い run", writes.NO_RECORD_OP, "包みが無い起動。受け付けが書き込みの出どころを突き合わせずに通した回"),
    ("記録の無い変更", writes.LEFT_OP, "書き込みの記録（Edit・Write）も申告も無い変更を、手直しの役で拒まずに残した"),
)
ANOMALY_SHOWN = 10   # 冒頭 4 の 1 行に並べる所在の数（全件は仕組みの異常の節）


def _anomaly_where(op: str, rows: list) -> list:
    """trace の異常の行から所在の一覧: 読み・欠けは「<scope>: <パスか名>」、記録の無い run は節の名（回ごと）、記録の無い変更は
    パス（重複は 1 本）"""
    if op == writes.NO_RECORD_OP:
        return [str(r.get("node") or "—") for r in rows]
    if op == writes.LEFT_OP:
        return sorted({p for r in rows for p in r.get("paths") or [] if isinstance(p, str)})
    key = "paths" if op == scopes.READ_OUTSIDE_OP else "names"
    return [f"{r.get('scope')}: {x}" for r in rows for x in r.get(key) or [] if isinstance(x, str)]


def anomalies(b) -> dict:
    """仕組みの異常（ANOMALY_OPS）の種別ごとの件数と所在の全件。trace.jsonl を調べられなければ examined=False で、種別ごとの
    件数は 0 でなく None（調べていない）。読めた時だけ 0 件も 0 と言う。壊れた行は飛ばして skipped に数える（0 件に見せない）。
    返り: {examined, skipped, total, kinds: {種別: {count, where}}}"""
    rows, examined, skipped = trace_scan(b)
    kinds = {}
    for name, op, _ in ANOMALY_OPS:
        where = _anomaly_where(op, [r for r in rows if r.get("op") == op]) if examined else []
        kinds[name] = {"count": len(where) if examined else None, "where": where}
    return {"examined": examined, "skipped": skipped, "total": sum(k["count"] for k in kinds.values()) if examined else None,
            "kinds": kinds}


def anomaly_lines(b, *, full: bool = False, found_only: bool = False) -> list:
    """仕組みの異常の行（anomalies を文にするだけ）。種別ごとに 1 行（0 件も。所在は ANOMALY_SHOWN 件まで）、full なら
    所在を 1 件 1 行で全件（仕組みの異常の節）。found_only なら 0 件の種別を並べない（冒頭 4。0 件は冒頭 1 の合計と
    仕組みの異常の節が言う）。調べていなければ「調べていない」の 1 行"""
    a = anomalies(b)
    if not a["examined"]:
        return ["仕組みの異常: 調べていない（盤面の trace.jsonl が無い・読めない）"]
    lines = []
    for name, _, note in ANOMALY_OPS:
        k = a["kinds"][name]
        if found_only and not k["count"]:
            continue
        shown = k["where"] if full else k["where"][:ANOMALY_SHOWN]
        if full:
            lines += [f"{name}（{note}）: {k['count']} 件", *[f"  - {w}" for w in shown]]
            continue
        more = f" ほか {k['count'] - len(shown)} 件" if k["count"] > len(shown) else ""
        lines.append(f"{name}（{note}）: {k['count']} 件" + (" " + "・".join(shown) + more if shown else ""))
    if a["skipped"]:
        lines.append(f"trace.jsonl の壊れた行 {a['skipped']} 行を飛ばした（上の件数に入らない）")
    return lines


BRANCH_HEAD = {1: "差分の審査の穴の枝（機械が修正案の項目に結んだ名札。手直しの役にも同じ名札を渡した）",
               2: "2 回目の審査の穴の枝"}
EYE_HEAD = "独立の目が場所を挙げた行の枝（R1 の削除候補・R4 の浮かんだ物。場所の無い R2・R3 は全体）"
EYE_ROWS = (("R1", "r1.minimality", "deletions", "why"), ("R4", "r4.hidden_scope", "surfaced", "text"))


def _ties(b, n: int):
    """n 回目の手直しの穴の名札（refix.hole_ties）か、組めなければ誤りの文（報告を落とさない）"""
    try:
        return refix.hole_ties(b, n)
    except Exception as e:   # 名札は材料。組めない理由を行に出して報告は続ける
        return f"{type(e).__name__}: {_one_line(str(e))}"


def _tie_notes(b, n: int) -> dict:
    """n 回目の手直しの穴の key → 名札の字（holeties.note）。組めなければ空"""
    got = _ties(b, n)
    return {t["key"]: holeties.note(t) for t in got} if isinstance(got, list) else {}


def eye_ties(b) -> list:
    """独立の目が場所を挙げた行（R1 の deletions・R4 の surfaced。今の周の出力）の名札（holeties.tie の path・change・unit の規則。
    key は「R<n>: <場所の先頭 80 字>」、where は場所の頭のパス holeties.lead_path）。行が無ければ空"""
    holes = []
    for name, nid, field, _ in EYE_ROWS:
        for r in (b.output_of_round(nid, b.round) or {}).get(field) or []:
            if isinstance(r, dict) and isinstance(r.get("where"), str) and r["where"].strip():
                holes.append({"key": f"{name}: {_one_line(r['where'])[:80]}", "from": nid,
                              "where": holeties.lead_path(r["where"])})
    if not holes:
        return []
    fix = b.output_of_round(recount.FIX_NODE, b.round) or {}
    return holeties.tie(holes, refix.tie_items(b), changes=fix.get("changes") or [])


def branch_rows(b) -> list:
    """枝の名札の行（線の木の段 4a。設計 docs/plans/2026-10-07-hole-to-branch.md の 2.6）: 手直しの往復ごとに件数の 1 行
    （holeties.count_line）と穴ごとの行、独立の目が場所を挙げた行の名札。穴も行も無ければ空（行を足さない）。名札が組めなければ
    理由の 1 行。冒頭 1 と最後の関所の文が同じ行を出す"""
    rows = []
    for n in (1, 2):
        got = _ties(b, n)
        if isinstance(got, str):
            rows.append(f"{BRANCH_HEAD[n]}: 組めない（{got}）")
        elif got:
            rows.append(f"{BRANCH_HEAD[n]}: {holeties.count_line(got)}")
            rows += [f"  - {x}" for x in holeties.lines(got)]
    try:
        eyes = eye_ties(b)
    except Exception as e:   # 名札は材料。組めない理由を行に出して報告は続ける
        rows.append(f"{EYE_HEAD}: 組めない（{type(e).__name__}: {_one_line(str(e))}）")
        eyes = []
    if eyes:
        rows.append(f"{EYE_HEAD}: {len(eyes)} 件")
        rows += [f"  - {x}" for x in holeties.lines(eyes)]
    return rows


def always_rows(b, left: list | None = None, *, rest: Rest | None = None) -> list:
    """人が決めるのに要る 4 つ（clean が消したファイル・レンズ・仕組みの異常・残り）の行を、0 件でも、走らせていない・調べていない・
    読めないを 0 件と分けて返す。報告の冒頭 1 と最後の関所の文が同じ戻り値を読む（検証器は回さない）。インデントの付いた行は
    直前の行の内訳。残りの行は、冒頭 1 が渡す left（residue の返り。検証器の阻害・最後のテストが緑でない・独立の目の阻害と走っていない目と
    結果が無い目）なら件数、最後の関所が渡す rest（rest_outside_validator の返り）なら数えられる分を件数と語で言う（検証器は数えない）。
    どちらも無い呼びは、呼び元の渡し忘れを名指す（0 件に見せない）"""
    rows = []
    gone = leftovers.removed(b.dir)
    if not gone["readable"]:
        rows.append(f"clean が消したファイル: 読めない（{_one_line(gone['reason'])}）")
    elif not gone["ran"]:
        rows.append("clean が消したファイル: 走らせていない（fix-removed.json が無い。修正の段が無い run か、clean の前に止まった）")
    else:
        rows.append(f"clean が消したファイル: {gone['count']} 本（修正の段ごとに最後に clean が走った周の分だけ。前の周の分は上書きで残っていない）")
        for scope, names in gone["by_scope"].items():
            rows += [f"  - {scope or '（盤面の直下）'}: {n}" for n in names]
    s = lens.summary(b)
    if not s["readable"]:
        rows.append(f"レンズ: 読めない（{_one_line(s['reason'])}）——どのレンズが見たかを確かめられない")
    elif not s["ran"]:
        rows.append("レンズ: 走らせていない（控えが無い）")
    else:
        rows.append(lens.count_line(s))
        for r in s["rows"]:
            got = "調べていない" if r["adopted"] is None else f"採った {r['adopted']}・採らなかった {r['not_adopted']}"
            rows.append(f"  - {r['lens']}: {got}・形の誤りで捨てた {r['dropped']}（出した発見 {r['findings']}）")
        rows += [f"  - 落ちたレンズ {f['lens']}（再実行の要あり）: {_one_line(f['reason'])}" for f in s["failed"]]
    a = anomalies(b)
    if not a["examined"]:
        rows.append("仕組みの異常: 調べていない（盤面の trace.jsonl が無い・読めない）")
    else:
        rows.append(f"仕組みの異常: 合計 {a['total']} 件（" + "・".join(f"{n} {k['count']}" for n, k in a["kinds"].items()) + "。所在の全件は仕組みの異常の節）"
                    + (f"。壊れた行 {a['skipped']} 行を飛ばした" if a["skipped"] else ""))
    if left is not None:
        rows.append(f"残り: {len(left)} 件（検証器の阻害・最後のテストが緑でない・独立の目の阻害と走っていない目と結果が無い目）"
                    + (f"。{NOT_RUN_GATE_NOTE}。{MISSING_GATE_NOTE}" if left else ""))
    if rest is not None:
        def counted(found, tail=""):
            return f"{len(found)} 件（{'・'.join(e['name'] for e in found) or '無し'}{tail}）"
        rows.append(f"残り（最後の関所で数えられる分）: 独立の目の阻害 {counted(rest.counts.blocked)}・走っていない目 {counted(rest.counts.not_run)}・"
                    f"結果が無い目 {counted(rest.counts.missing, '。阻害 0 件ではなく判定が無い')}・最後のテスト: {rest.tests_word}。"
                    f"数えられる分の合計 {len(rest.rows)} 件（目の 3 つの欄と、最後のテストが緑でなければその 1 件）。"
                    "検証器の阻害は最後の関所では数えない（報告の冒頭 1 の残りは検証器の箇条も数え、目の阻害は重なる）"
                    + (f"。{NOT_RUN_GATE_NOTE}。{MISSING_GATE_NOTE}" if rest.counts.not_run or rest.counts.missing else ""))
    if left is None and rest is None:
        rows.append("残り: 数えを渡されていない（always_rows に left も rest も無い——呼び元の渡し忘れで、0 件ではない）")
    return rows


def plan_ask_lines(b) -> list:
    """範囲の相談（修正役が修正案を書いた役の会話を再開して範囲を聞いた 1 問 1 答。trace の conflict.ASKED_OP）の行: 1 行目に
    回数と答えごとの数、続けて 1 相談 1 行（項目・答え・許した範囲か理由。案を書いた役がその項目の out_of_scope を考え直して
    外した物（行の overrode_out_of_scope）か、外したままにした物）。無ければ空。報告の冒頭（head_reads）が載せる"""
    rows = conflict.plan_asks(b)
    if not rows:
        return []
    kinds = collections.Counter(r.get("decision") if r.get("status") == "answered" else r.get("status") for r in rows)
    out = [f"範囲の相談: {len(rows)} 回（" + "・".join(f"{k} {n}" for k, n in kinds.items()) + "）"]
    for r in rows:
        head = f"  - 相談 {r.get('id')}（項目 {r.get('item')}）: "
        if r.get("status") != "answered":
            why = r.get("why_refused") or r.get("why_unavailable") or " / ".join(r.get("notes") or [])
            out.append(f"{head}{r.get('status')}——{str(why)[:300]}")
            continue
        granted = [*(r.get("granted_paths") or []), *(r.get("granted_tests") or [])]
        lifted = [h for h in r.get("overrode_out_of_scope") or [] if isinstance(h, dict)]
        kept = [h for h in r.get("out_of_scope") or [] if isinstance(h, dict) and str(h.get("item")) == str(r.get("item"))]
        oos = ("・out_of_scope を外した: " + "・".join(f"{h.get('path')}（項目 {r.get('item')} の out_of_scope の {h.get('glob')}）"
                                                    for h in lifted) if lifted else
               "・out_of_scope は外したまま: " + "・".join(str(h.get("path")) for h in kept)
               if kept and r.get("decision") != "allow" else "")
        out.append(f"{head}{r.get('decision')}" + (f"（{'・'.join(granted)}）" if granted else "") + oos
                   + f"——{str(r.get('reason') or '')[:300]}")
    return out


def gates_lines(b) -> list:
    """修正の受け付けの事後の関門の束が、受け入れのテストの赤緑を確かめずに受けた回の行（blk-fix の受け付けが盤面の trace に
    impact.ACCEPT_GATES_SKIPPED_OP で積んだ物）: 回の数と理由（同じ理由は 1 度）。報告の冒頭（head_reads）と最後の人の関所の
    文（darkfactory の line_edge._final_text）が載せる"""
    rows = trace_rows(b, impact.ACCEPT_GATES_SKIPPED_OP)
    if not rows:
        return []
    whys = list(dict.fromkeys(w for r in rows for w in r.get("why") or [] if isinstance(w, str)))
    return [f"事後の関門の束: 受け付け {len(rows)} 回が受け入れのテストの赤緑を確かめずに通した（理由: {' / '.join(whys)[:600]}）"]


def _time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def _since_created(b, rows) -> list:
    """盤面を作った（state.created。固定材料から取り込んだ盤面は取り込んだ時刻。fixture.since）後の行（reads.adapter_seen と
    同じ絞り方）"""
    since = _time(fixture.since(b.dir, b.state.get("created")))
    if since is None:
        return []
    out = []
    for r in rows:
        at = _time(r.get("at"))
        if at is not None and at >= since:
            out.append(r)
    return out


def _no_turn_exits(b, repo) -> list:
    """包みの終わりの記録のうち、この run の即時の死（1 手も進まずに終わり、Archon の起こし直しに任せた起動）"""
    return [r for r in _since_created(b, adapter.read_exits(pathlib.Path(repo))) if r.get("kind") == "no_turn"]


def _launches(b, repo) -> list:
    """包みの起動の記録のうち、盤面を作った後の行。即時の死の起動は除く（Archon の node_completed を持たないので、
    cost_rows の結び付けをずらす）"""
    dead = {r.get("pid") for r in _no_turn_exits(b, repo)}
    return [r for r in _since_created(b, adapter.read_launches(pathlib.Path(repo))) if r.get("pid") not in dead]


def _live_launches(board_dir, launches, b=None) -> list:
    """費用と模型が数える起動（どれを数えるかはここだけ）。launches を渡さなければ盤面（b。無ければ board_dir を開く）の
    run の作業ツリーの起動の記録。拒んだ起動は除き、時刻の順に並べ直す"""
    if launches is None:
        b = b or entry.open_board(pathlib.Path(board_dir), allow_halted=True)
        launches = _launches(b, (b.state.get("inputs") or {}).get("cwd") or ".")
    return sorted((r for r in launches if isinstance(r, dict) and (r.get("session") or {}).get("mode") != "refused"),
                  key=lambda r: str(r.get("at") or ""))


def head_where(b) -> list:
    """冒頭 5: 見る所（判定・修正案・事前審査・修正・審査・手直し・独立設計・差分のファイルと run の作業ツリー）。ファイルは
    state.outputs[節]["file"] と loop の差分の欄から（周を仮定しない）。独立設計は graph の外で修正の前に盤面の根へ控える
    （design.DESIGN_FILE）ので、在る時だけ並べる。盤面を書かない"""
    lines = []
    outs = b.state.get("outputs") or {}
    for label, nid in WHERE:
        info = outs.get(nid)
        if info and info.get("file"):
            lines.append(f"{label}: {b.dir / info['file']}")
    designed = pathlib.Path(b.dir) / design.DESIGN_FILE
    if designed.is_file():
        lines.append(f"{gatemarks.PLAIN['r2.design']}: {designed}")
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


def _event_cost(e) -> tuple:
    """(費用, 取れない理由)。data.spend.costUsd が {source: provider, value: 有限の数}（か有限の数）ならその値と ""。
    報告されなかった（source unavailable）か形が違えば None と、見た欄・版を添えた理由"""
    v = e.get("data")
    for k in COST_FIELD:
        v = v.get(k) if isinstance(v, dict) else None
    n = v.get("value") if isinstance(v, dict) and v.get("source") == "provider" else v
    if isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n):
        return float(n), ""
    if isinstance(v, dict) and v.get("source") == "unavailable":
        return None, f"{COST_FIELD_NAME} は source unavailable・reason {v.get('reason') or '無し'}。{ARCHON_VERSION}"
    seen = "欄が無い" if v is None else f"形が違う（{json.dumps(v, ensure_ascii=False)[:120]}）"
    return None, f"{COST_FIELD_NAME} が{seen}。{ARCHON_VERSION} の前提"


def _completed(events) -> list:
    return [e for e in events or [] if isinstance(e, dict) and e.get("event_type") == "node_completed"]


def _is_aggregate(e) -> bool:
    """輪（loop_group）の集計の出来事か。Archon が data.accounting="aggregate"（か data.aggregate が真）で印を付ける。
    印が無ければ節として数える"""
    d = e.get("data")
    d = d if isinstance(d, dict) else {}
    return d.get("accounting") == "aggregate" or d.get("aggregate") is True


def cost_rows(events, launches) -> list:
    """[{node, reported, actual, continued_from, base, aggregate}]。aggregate は輪の集計の行（合計に数えない）。events の node_completed の費用の欄（COST_FIELD）を節の名で
    launches（包みの起動の行。時刻の順に並べ直す。拒んだ起動は除く）と順に結ぶ。session.mode continued の起動は、continued_from に
    その会話を前に使った節、base にその時の表示を書く。costUsd が累積か 1 回分かは測れていないので引かず、actual = reported。
    events が None か費用が 1 つも取れなければ []"""
    if not events:
        return []
    shown = [(_step_name(e.get("step_name")), _event_cost(e)[0], _is_aggregate(e)) for e in _completed(events)]
    shown = [(n, v, a) for n, v, a in shown if v is not None]
    if not shown:
        return []
    queues = {}
    for n, v, a in shown:
        queues.setdefault(n, []).append((v, a))
    totals, last_node, out = {}, {}, []
    for r in _live_launches(None, launches or []):
        node = r.get("node")
        q = queues.get(node) or []
        if not q:
            continue
        v, agg = q.pop(0)
        s = r.get("session") or {}
        sid, mode = s.get("id"), s.get("mode")
        if mode == "continued" and sid in totals:
            out.append({"node": node, "reported": v, "actual": v, "continued_from": last_node[sid], "base": totals[sid],
                        "aggregate": agg})
        else:
            out.append({"node": node, "reported": v, "actual": v, "continued_from": None, "base": None,
                        "aggregate": agg})
        if sid:
            totals[sid], last_node[sid] = v, node
    for n, q in queues.items():
        out += [{"node": n, "reported": v, "actual": v, "continued_from": None, "base": None, "aggregate": a}
                for v, a in q]
    return out


def head_cost(board_dir, run_id: str, *, events=None, launches=None) -> list:
    """冒頭の後の費用の行（書き出しの run_facts の代わりに、Archon の出来事と包みの起動の記録から）。1 つも取れなければ、
    最初の理由と件数の 1 行。取れない節は 0 と数えず、件数と理由を別の行に出す。報告は run の中で走り、run の和
    （metadata.total_cost_usd）は走っている間の値なので読まない——合計は節の和を途中の値として出す。
    launches を渡さなければ盤面の run の作業ツリーの起動の記録（盤面を作った後の行）"""
    rows = cost_rows(events, _live_launches(board_dir, launches))
    whys = [w for _, w in map(_event_cost, _completed(events)) if w]
    missing = f"{whys[0]}。取れない節 {len(whys)} 件" if whys else f"node_completed が無い。{ARCHON_VERSION} の前提"
    if not rows:
        why = "出来事を読めない" if events is None else missing
        return [f"費用: 取れない（{why}。run {run_id or '（id 無し）'}）"]
    mark = "" if COST_FIELD_VERIFIED else "（欄の形は未確認）"
    lines = []
    for r in rows:
        extra = f"（{r['continued_from']} の会話を継いだ。costUsd が累積かどうか未確認で引いていない）" if r["continued_from"] else ""
        agg = "（輪の和。合計に数えない）" if r["aggregate"] else ""
        lines.append(f"費用 {r['node']}: {r['actual']} USD{extra}{agg}{mark}")
    if whys:
        lines.append(f"費用の取れない節: {missing}（合計に数えない）")
    nodes = round(sum(r["actual"] for r in rows if not r["aggregate"]), 6)
    lines.append(f"費用の合計: {nodes} USD（途中。報告は run の中で走るので run の和は読まず節の和）{mark}")
    return lines


# ---------------------------------------------------------------- 模型
def head_models(board_dir, launches=None) -> list:
    """費用の前の模型の行。全体は <盤面の親＝ARTIFACTS_DIR>/versions.json の model（start の時に archon.sh が渡した要求と
    出どころ）、節ごとは包みの起動の記録の model（子に渡した --model。包みが run の明示の模型で替えた段は model_declared の
    段の宣言も添える。応答が名乗る模型は読まない）。同じ節で値が
    替われば順に全部並べる。取れない値は理由を書き、全体の値で埋めない。launches を渡さなければ head_cost と同じ起動の記録"""
    path = pathlib.Path(board_dir).parent / "versions.json"
    try:
        glob = json.loads(path.read_text(encoding="utf-8")).get("model")
    except (OSError, ValueError, AttributeError) as e:
        glob, why = None, f"{path} を読めない（{type(e).__name__}）"
    else:
        why = f"{path} に model が無い（開発の殻 archon.sh を通さずに起こした run）"
    if isinstance(glob, dict) and glob.get("value"):
        lines = [f"模型（全体・start の時）: {glob['value']}（出どころ {glob.get('from') or '記録が無い'}）"]
    else:
        lines = [f"模型（全体）: 取れない（{why}）"]
    per = {}
    for r in _live_launches(board_dir, launches):
        seen = per.setdefault(r.get("node") or "（印の無い起動）", [])
        m = r.get("model") if "model" in r else "（記録の無い版の包み）"
        if r.get("model_declared"):   # 包みが run の明示の模型で替えた段（adapter.py の頭の 19）
            m = f"{m}（段の宣言 {r['model_declared']} を run の明示の模型で替えた）"
        if not seen or seen[-1] != m:
            seen.append(m)
    if not per:
        return lines + ["模型（節ごと）: 取れない（包みの起動の記録が無い。包みを通さない run か、まだ起動が無い）"]
    for node, ms in per.items():
        shown = " → ".join(m or "--model 無し（Archon が渡さず CLI の既定。値は取れない）" for m in ms)
        lines.append(f"模型 {node}: {shown}{'（run の途中で替わった）' if len(ms) > 1 else ''}")
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
          ci: dict | None = None, run_id: str = "", events=None, launches=None, interrupted: str | None = None,
          failed: list | None = None, retried: list | None = None, eyeing: dict | None = None, cleaned_runs: str = "",
          depth_lines=()) -> dict:
    """gate_record → decide_outcome（eyeing＝独立の目のブロックの出口。残りに数える）→ 部品で <盤面>/report.md と
    <盤面>/next-request.json（{findings: next_request の返り, prior_failures}）と <盤面>/prior-failures.json（prior_failures の返り）
    （と、包みが即時の死を記録した run は <盤面>/NO_TURN_FILE）を書き、1 本目の finish の欄に
    report_file・next_request_file・prior_failures_file・tests_green・validator_exit と、書き出しの節が読む export_input {outcome, report_file,
    board_dir} を足して返す。interrupted（Archon の run の状態の語。空も可）を渡せば結末は interrupted（線の中の報告の節は
    落ちた節 failed と空、dev の report.sh は run の状態）。retried（前の試みで落ち、続きで済んだ節）は冒頭 3 の試みの記録で、
    結末も AI の報告の可否も替えない。
    record_invalid の時は冒頭 1 に検証器の出力の末尾と痕跡。盤面を開けなければ BoardGap"""
    board_dir = pathlib.Path(board_dir)
    try:   # 案の直しを待つ行を諦めた行にしてから読む（h-rejudge が飛ばされた run でも、待つ行を報告から落とさない）
        replan.close_at(board_dir)
    except BoardGap:   # 申し出の控えが読めない: 冒頭 1 の件数の行（_conflict_line）が「読めない」と言う
        pass
    b = entry.open_board(board_dir, allow_halted=True)
    gate = gate_record(b)
    # 盤面が報告の役の節を出したか（表で role のラインだけ。いつ出るかは gate_record の docstring。stop_after_round で周を
    # 締めた 1 周の run でも出る）。待ちのままでも結末は替えない——報告の役の節の待ちは「終わっていない」ではない（計画 P1 Task 34）
    # 途中で終わった run は機械の報告だけ（AI の報告の役は最後まで来た盤面を前提にする）。
    # 報告の頭の段を AI の報告のブロックがもう受けた（done）盤面も出した物に数える: Archon の resume はこの節を毎回回し直す
    # （ラインの always_run）ので、値が替わると AI の報告のブロックが古いと数えられ、when: が偽で済んだ段ごと飛ばされる
    ai_go = interrupted is None and (AI_FIRST_NODE in b.ready() or b.node_state(AI_FIRST_NODE) == "done")
    outcome = "interrupted" if interrupted is not None else decide_outcome(b, gate, tests=tests, judged=judged, eyeing=eyeing)
    left = residue(b, gate, tests=tests, eyeing=eyeing)
    items = next_request(b, tests=tests, left=left)
    prior = prior_failures(b, left)
    req_p, rep_p, prior_p = board_dir / NEXT_REQUEST_FILE, board_dir / REPORT_FILE, board_dir / PRIOR_FAILURES_FILE
    _write_json(prior_p, prior)
    _write_json(req_p, next_doc(b, items, prior))
    dead = _no_turn_exits(b, (b.state.get("inputs") or {}).get("cwd") or ".")
    if dead:   # 即時の死の result は Archon の出来事に載らないので、全文を盤面にも残す（head_reads の行から辿る）
        _write_json(board_dir / NO_TURN_FILE, dead)
    rid = run_id or _start_doc(b, start).get("run_id") or ""
    body = [f"# 報告（run {rid or '—'}）", "", *head3(b, outcome, left=left, next_items=items), ""]
    parts = (head_decisions(b, gate, tests=tests, outcome=outcome, next_items=items, next_file=str(req_p), left=left),
             head_entry(b, start, mid=mid, cleaned_runs=cleaned_runs, depth_lines=depth_lines), head_stop(b, interrupted=interrupted, failed=failed, retried=retried),
             head_reads(board_dir, rid, ci=ci), head_where(b))
    for title, rows in zip(HEADINGS, parts):
        body += [title, "", *[r if r.startswith("  ") else f"- {r}" for r in rows], ""]
    launches = _live_launches(board_dir, launches, b)
    body += ["## 模型", "", *[f"- {r}" for r in head_models(board_dir, launches)], ""]
    body += ["## 費用", "", *[f"- {r}" for r in head_cost(board_dir, rid, events=events, launches=launches)], ""]
    body += ["## 周の記録の検証器", "", f"- 終了コード: {gate['exit']}（受理 {report_accepts(b)}）",
             f"- 今の周の記録: {'済んだ' if gate['round_closed'] else '済んでいない'}", ""]
    structure = structmark.report_lines(board_dir)
    if structure:
        body += ["## 構造の目", "", *[f"- {r}" for r in structure], ""]
    body += [PRIOR_HEADING, "", *[f"- {r}" for r in prior_lines(prior)], ""]
    # 局所レビュー（P1）の fork のレンズの戻した・見ていない（diverted）を先に、修正の後のレンズ（lens）を後に
    body += ["## 未確認のレンズ", "", *[f"- {r}" for r in [*diverted.report_lines(board_dir), *lens.report_lines(b)]], ""]
    body += ["## 仕組みの異常", "", *[r if r.startswith("  ") else f"- {r}" for r in anomaly_lines(b, full=True)], ""]
    _write_text(rep_p, "\n".join(body))
    green = isinstance(tests, dict) and tests.get("ok") is True and tests.get("green") is True
    return {**_finish_fields(b, judged, outcome), "report_file": str(rep_p), "next_request_file": str(req_p),
            "prior_failures_file": str(prior_p),
            "tests_green": green, "validator_exit": gate["exit"], "ai_report_go": ai_go,
            "export_input": {"outcome": outcome, "report_file": str(rep_p), "board_dir": str(board_dir)}}


def next_doc(b, items: list, prior: list) -> dict:
    """次の run の依頼の下書き {findings, prior_failures}。無人の run が人の判断を待つ項目（関所で止めた項目・保留のままの問い）を残せば、答えの下書き
    （gatemarks.answer_drafts。draft: true・source つき。依頼の入口が拒むので人が見直してから使う）を answers に足す"""
    doc = {"findings": items, "prior_failures": prior}
    drafts = gatemarks.answer_drafts(b)
    if drafts:
        doc["answers"] = drafts
    return doc


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
