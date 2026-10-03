"""境の節の中身（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4。並びは C18 の順: 計画 P1 Task 26・P1-R3・P1-R4）。
ライン darkfactory の模块（層 L6。裁定 R59）で、使うのは darkfactory/scripts/edge.py と structure.py だけ。止め札そのもの（置く・読む）は共有の
.shared/core/halt.py。

- edge(board_dir, at, repo, …): 境の節（darkfactory/scripts/edge.py の中身）。止め札・関所の答え・次のブロックを盤面から決める
- judge_edge(b, …): h-judge の固有の仕事（包みの確かめ・前提の実測が盤面に在るか。計画 P1 Task 24・P1-R9）
- mat_edge(b, …): h-mat の固有の仕事（目的の文を盤面へ渡し、P1 の目を回すか。計画 P1 Task 32・33）
- rejudge_edge(board_dir, repo): h-rejudge の固有の仕事（修正役の異議の再審を回すか。判定役の会話が無ければ止める。計画 P1 Task 31）
- 同じ run の中の案の直し（依頼 226。core の replan）: h-replan（at replan）は修正の段で fix_plan_item と裁かれた項目を束ね
  （replan.material）、案の直しのブロック（blk-plan の 2 度目の include）を回すか。h-regate（at regate）は直した項目に関所の
  決まりを当て（replan.gate）、関所 replan-gate を開くか。h-refit（at refit）は関所の答えを当て（refit_edge・replan.answer）、
  2 回目の修正の段（blk-fix の 2 度目の include。回の印 refit）を回すか。どれも今の周の replan.json が無ければ何もしない
- eyes_edge(b): h-look の固有の仕事（独立の目を回すか。計画 P1 Task 33）。h-eyes も同じ go を返す（関所の後にまだ目が待つか——報告が
  blk-eyes の落ちを見分ける）。h-look は先に、blk-plan が修正の前に控えた独立設計（core の design。design.json）を、盤面が r2.design を
  待っていれば渡す（目的の文を h-mat が渡すのと同じ形）
- plan_edge(b, …): h-plan の固有の仕事（判定の出口の控え・判定の渡し替え・直す物が無い周の締め。計画 P1 Task 23）。go は修正案か
  独立設計（design.due）のどちらかを blk-plan で起こす周
- structure_edge(board_dir, structured): h-structure（構造の境の節。darkfactory/scripts/structure.py の中身）。構造のブロックの出口を
  確かめ、盤面の根の控え（core の structmark）を書く。planning はこの節を待つ
- trace_empty_fix(b): 直す物の無い周に機械が p3.fix の空の返答を渡した印（at mid が役の修正と見分ける）
- 固定材料（core の fixture。計画 220 Task 5）: h-fix は go の後、1 周目なら盤面を $ARTIFACTS_DIR/fix-fixture へ写す
  （固定材料から始めた盤面は capture が写さない。写せなくても run は止めない）。包みの確かめは「この run で役が 1 つ起きた
  後の最初の境の節で止める」（_adapter_guard）: 通常の盤面は h-judge、固定材料から始めた盤面（fixture.adopted）は h-mid。
  h-mat は今の周の判定が済んでいれば go を偽にする（判定のブロックを回さない）
- 守りのファイル（core の protect・protected.json。ASF の floor.json に倣う）: h-final は run の修正の差分（修正前の版
  state.inputs.review_rev から。固まる前は record.base。未追跡を含む。_protected）が一覧に当たれば最後の関所を final_gate に関わらず開き、冒頭 3 行で名指して直後の最初の節に並べ、process.human_items に 1 行。h-eyes は答えを
  その行に写し、答えが来なければ（関所が開かなかった）止める。通すのは人の continue だけ。テストの変更の許し（承認済みの修正案の
  rewrite_tests と裁定 fix_test_scope の範囲。core の conflict.test_permits）が名指したテストの変更も守りのファイルの行として並ぶ
- 食い違いの申し出（core の conflict）: 裁定役か機械が ask_human に裁いた単位が在れば、h-final は最後の関所を final_gate に関わらず
  開き、文に「食い違いの申し出」の節を並べ、process.human_items に 1 行。答えの写しと、答えが来ない時の止めは守りのファイルと同じ
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_LIB = pathlib.Path(__file__).resolve().parent
_CORE = _LIB.parents[1] / ".shared" / "core"
for _p in (_LIB, _CORE):   # core を頭に（節のスクリプトと同じ順。lib の名前は core と重ねない）
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from board import BoardGap  # noqa: E402
from engine.rules import validator_module  # noqa: E402  （board が写しの engine を sys.path に足した後）
from engine.util import Reject  # noqa: E402
import accept  # noqa: E402
import answer  # noqa: E402
import conflict  # noqa: E402
import converge  # noqa: E402
import design  # noqa: E402
import entry  # noqa: E402
import fixture  # noqa: E402
import gatemarks  # noqa: E402
import halt  # noqa: E402
import impact  # noqa: E402
import plan  # noqa: E402
import premises  # noqa: E402
import protect  # noqa: E402
import purpose  # noqa: E402
import querytest  # noqa: E402
import reads  # noqa: E402
import rejudge  # noqa: E402
import replan  # noqa: E402
import report  # noqa: E402
import scopes  # noqa: E402
import structmark  # noqa: E402

# ---------------------------------------------------------------- 境の節（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4）
# いつも走る script の節 1 本（darkfactory/scripts/edge.py）を、ラインの中で at を替えて使う。並びは C18 の順（中の関所は無い。
# 人が止まれる所は最後の人の関所 final-gate。P1-R3）。when: と関所の文は境の節の欄だけを読み、go は盤面の ready から決める（TA1）。
# rejudge は修正役の異議の再審を回すかを決める（計画 P1 Task 31）。look は最後のテストの後に独立の目を回すかを決め、eyes は
# 独立の目と最後の関所の後に関所の答えを受ける（人は目の結果を見てから答える。本線の r4.human_gate と同じ順。名 h-eyes は前の並びのまま）
# replan・regate・refit は修正の段の後・再審の前の案の直し（依頼 226。1 run に 1 回）
AT = ("entry", "judge", "mat", "plan", "gate", "fix", "replan", "regate", "refit", "rejudge", "mid", "review", "refix", "tests",
      "look", "final", "eyes")
GO_NODE = {"plan": "p2.fix_plan", "fix": "p3.fix", "review": "p3.delta_review", "refix": "p3.delta_fix", "tests": "p4.ci"}
GATE_AT = ("fix", "refit", "eyes")   # 関所の答えを受ける境の節（fix は policy-gate、refit は replan-gate、eyes は final-gate）
GATE_GO = ("approve", "continue")    # approve は continue と、reject は stop と同じ（台帳 R32）
GATE_STOP = ("stop", "reject")
GATE_STOP_NOTE = "関所で止めた"              # policy-gate の stop・reject に一言が無い時の理由
FINAL_GATES = ("always", "when_needed", "protected_only")   # 入力 final_gate の語（空は always。P1-R3: 必ず止まれる所を残す）。
# protected_only は守りのファイルを触った（確かめられなかった）時だけ開く（利用者の既定。ほかの理由は報告の冒頭に並ぶだけ。
# 開いた関所の stop・reject は use.sh apply が読んで差分を当てずに止まり、当てるのは WORKS_USE_ALLOW_STOPPED=1 の時だけ）
FINAL_GATE_FILE = "final-gate.md"            # final-gate の文（b.work）
FINAL_GATE_ANSWER = "final-gate-answer.json" # final-gate の答え {decision, text}（b.work。stop・reject も書く——報告が読む）
FINAL_GATE_BY = "human:final-gate"           # final-gate の stop・reject の by（state.stop.by か、周を締めた後なら trace の行）
FINAL_GATE_STOP_NOTE = "最後の関所で止めた"  # final-gate の stop・reject に一言が無い時の理由
FINAL_GATE_KIND = "final_gate"               # process.human_items の行の kinds
ENDED_BY = "stop_after_round"                # 1 周の run が周を締めた後の盤面の halted.by（最後のテストの後の普通の終わり）
ENDED_AT = ("look", "final", "eyes")         # 周を締めた後に来る境の節（ENDED_BY の盤面を止めたと読まない）
STOP_AFTER_END_OP = "stop_after_round_end"   # 周を締めた盤面に止める答え・止め札が来た印の trace の行（b.stop は拒まれる）
PROTECTED_BY = "works:protected"              # 守りのファイルの行の node（human_items）と、答えの無いまま止めた by
PROTECTED_KIND = "protected_files"            # その行の kinds
PROTECTED_HEAD = "守りのファイルを触った"      # 最後の関所の冒頭 3 行の直後の節の見出し（1 行目でも名指す）
PROTECTED_UNKNOWN = "守りのファイルを確かめられなかった"   # 一覧か git が読めない時の見出し（黙って空にしない）
MID_NOTE = "中の検査: 枠のみ（動かす確かめ・holdout は Task 36、変異は後）"
FLAG_BY_PREFIX = "request:"                  # 止め札で止めた盤面の state.stop.by は "request:<札の by>"（報告の stopped_by_request）
FLAG_SEEN_OP = "stop_flag_seen"              # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
AFTER_HALT_OP = "stop_flag_after_halt"       # 止まった後に見た止め札の trace の行（b.stop は呼ばない。M3）
EMPTY_FIX_OP = "empty_fix"                   # 直す物の無い周に機械が p3.fix の空の返答を渡した印の trace の行（T10b が書く。TA6）
EMPTY_FIX_BY = "works:empty-fix"
JUDGE_BRIDGE_BY = "works:judge-bridge"       # 判定のブロックの出口を盤面が受けなかった時の state.stop.by（h-plan）
ADAPTER_BY = "works:adapter"                 # 包みが通っていない run を止めた state.stop.by（h-judge。blk-ci の柵と同じ名）
PREMISES_BY = premises.STOP_BY                # 前提の実測が盤面に無い・盤面が受けない時の state.stop.by（h-judge）
PREMISES_NODE = "p0.premises"
PURPOSE_NODE = "p0.purpose"
PENDING_REQUEST_BY = "works:pending-request"  # 依頼と変更の両方の run で、判定の前に依頼を積めなかった時の state.stop.by（h-mat）
PURPOSE_BY = purpose.STOP_BY                 # 目的の文が盤面に無い・盤面が受けない時の state.stop.by（h-mat）
MAT_BLOCK = "blk-material"                   # 表の where がこれの節が P1 の目（素材集め）。h-mat の mat_go
EYES_BLOCK = "blk-eyes"                      # 表の where がこれの節が独立の目。h-eyes の go
ADAPTER_HINT = ("Archon の設定 assistants.claude.claudeBinaryPath に包み（works/.shared/core/claude-adapter）の絶対パスを書くか、"
                "包み無しで回すなら入力 adapter に optional を渡す（works/README.md の包みの節）")
FIXTURE_FAILED_OP = "fixture_capture_failed"  # h-fix が固定材料を写せなかった trace の行（run は止めない）
ADAPTER_FIXTURE_OP = "adapter_check_after_fixture"   # 固定材料から始めた盤面で h-judge が包みの確かめを h-mid に回した trace の行
DIAGNOSE_NODE = "p2.diagnose"                # 判定の節（h-mat・h-plan が今の周に済んだかを見る）
JUDGED_FILE = "judged.json"                  # h-plan が受けた判定のブロックの出口の控え（b.work。後ろの境の節が運ぶ。M4）
GATE_FILE = "gate.md"                        # policy-gate の文（b.work）
NOTES_FILE = "human-notes.md"                # 今の周の人の一言（h-fix が書き、修正役がパスで読む。R44: with: に文を貼らない）
# 判定の単位を blk-structure の入力の契約 {id, paths, summary} に写したファイル（b.work。h-plan が書き、include の with: units が読む。
# 写すのは線の側のここ 1 か所で、ブロックは判定役の返答の形を読まない。設計書 structure-block-design 8 節）
STRUCTURE_UNITS_FILE = "structure-units.json"
STRUCTURE_UNITS_OP = "structure_units_dropped"   # 対象の根からの相対のパスが 1 本も取れず写さなかった単位・捨てたパスの trace の行
EMPTY = {"ok": True, "stop": False, "go": False, "ask": False, "gate_text": "", "judgment_file": "", "open_units": "",
         "plan_file": "", "notes": "", "notes_file": "", "why": "", "gate_file": "", "premises_file": "",
         "pr_go": False, "premises_go": False, "purpose_go": False, "spec_go": False,
         "runtime_go": False, "holdout_go": False, "mid_note": "", "purpose_file": "", "mat_go": False,
         "structure_units_file": ""}


def _gap(msg):
    return BoardGap(msg)


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_text(path: pathlib.Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _gate_words(gate) -> tuple:
    """関所の出口 {decision, text?} を (decision, text) にする。text は字のまま（一言は 1 バイトも変えずに盤面へ）"""
    if not isinstance(gate, dict):
        raise _gap(f"関所の答えが JSON のオブジェクトでない: {type(gate).__name__}")
    decision = gate.get("decision")
    if decision not in GATE_GO + GATE_STOP:
        raise _gap(f"関所の答えの語 {decision!r} を知らない（{' / '.join(GATE_GO + GATE_STOP)}）")
    text = gate.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise _gap(f"関所の一言が文字列でない: {type(text).__name__}")
    return decision, text


def _check_args(at, *, final_gate, judged, gate, tests, premised=None, adapter_mode="") -> str:
    """配線の誤り（知らない at・場違いの入力・形の崩れ・語の外の adapter・final_gate）を BoardGap にし、final_gate の語
    （空は既定の always）を返す"""
    if at not in AT:
        raise _gap(f"境の節の at {at!r} を知らない（{' / '.join(AT)}）")
    if (adapter_mode or "") not in entry.ADAPTER_MODES:
        raise _gap(f"adapter={adapter_mode!r} は知らない値（空か optional）")
    if premised is not None and (at != "judge" or not isinstance(premised, dict)):
        raise _gap(f"前提のブロックの出口（premised）を受けるのは at judge の JSON のオブジェクトだけ（at {at}・{type(premised).__name__}）")
    if gate is not None:
        if at not in GATE_AT:
            raise _gap(f"関所の答え（gate）を受けるのは at {' / '.join(GATE_AT)} だけ（at {at}）")
        _gate_words(gate)
    if tests is not None and (at != "final" or not isinstance(tests, dict)):
        raise _gap(f"最後のテストの出口（tests）を受けるのは at final の JSON のオブジェクトだけ（at {at}・{type(tests).__name__}）")
    if judged is not None and (at != "plan" or not isinstance(judged, dict)):
        raise _gap(f"判定の出口（judged）を受けるのは at plan の JSON のオブジェクトだけ（at {at}・{type(judged).__name__}）")
    mode = (final_gate or "").strip() or FINAL_GATES[0]
    if mode not in FINAL_GATES:
        raise _gap(f"final_gate={final_gate!r} は知らない値（{' / '.join(FINAL_GATES)}）")
    return mode


def _carried(b) -> dict:
    """h-plan が控えた判定の出口（b.work(JUDGED_FILE)）から judgment_file・open_units（JSON の配列の文字列）。無ければ空"""
    p = b.work(JUDGED_FILE)
    if not p.is_file():
        return {"judgment_file": "", "open_units": ""}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _gap(f"判定の出口の控え {p} が読めない: {e}") from None
    jf, units = doc.get("judgment_file"), doc.get("open_units")
    return {"judgment_file": jf if isinstance(jf, str) else "",
            "open_units": json.dumps(units, ensure_ascii=False) if isinstance(units, list) else ""}


def _stopped(b) -> dict | None:
    """盤面がもう止まっているなら止めた事実（state.stop か halted）。まだなら None"""
    st = b.state
    if st.get("halted") or st.get("stop"):
        return st.get("stop") or st.get("halted")
    return None


def _ended(b) -> bool:
    """1 周の run が周を締めた（halted.by stop_after_round で、人も線も止めていない）。最後のテストの後の普通の終わり"""
    st = b.state
    return (st.get("halted") or {}).get("by") == ENDED_BY and not st.get("stop")


def _stop_board(b, at: str, reason: str, by: str) -> None:
    """盤面を止める。周を締めた盤面（_ended）は b.stop が拒むので、止めた事実を trace に 1 行（STOP_AFTER_END_OP。at・reason・by）"""
    if _ended(b):
        b.trace(STOP_AFTER_END_OP, at=at, reason=reason, by=by)
    else:
        b.stop(reason, by=by)


def _traced(b, op: str, **kw) -> bool:
    return any(all(row.get(k) == v for k, v in kw.items()) for row in report.trace_rows(b, op))


def _ci_left(b) -> list:
    """修正の受け付けが周をまたいで手元で回さず 手元で回さなかった試験（重ねずに、出た順）"""
    return list(dict.fromkeys(t for row in report.trace_rows(b, impact.ACCEPT_TRACE_OP) for t in row.get("ci_left") or []))


def _halted_out(b, out: dict, flag, at: str) -> dict:
    """止まった盤面の返り。止め札が在っても b.stop を呼ばず（止めた盤面への stop は Reject）、札の理由は trace にだけ 1 行
    （同じ札を同じ理由で止めた盤面・既に積んだ札は積み増さない）"""
    info = _stopped(b) or {}
    if flag:
        same = info.get("reason") == flag["reason"] and info.get("by") == FLAG_BY_PREFIX + flag["by"]
        if not same and not _traced(b, AFTER_HALT_OP, reason=flag["reason"], by=flag["by"]):
            b.trace(AFTER_HALT_OP, at=at, reason=flag["reason"], by=flag["by"])
    return {**out, "stop": True, "go": False, "ask": False, "why": str(info.get("reason") or "")}


def _answer_policy_gate(b, gate: dict) -> None:
    """policy-gate の答えを盤面の answer に渡す（写しの on_answer_in_round → human_gate_answered が process.human_items に積む）。
    問いがもう無い（Archon の再開で同じ境の節を呼び直した）なら 2 度答えない"""
    decision, text = _gate_words(gate)
    if not b.state.get("pending_human"):
        b.trace("gate_answer_unasked", at="fix", decision=decision)
        return
    if decision in GATE_GO:
        b.answer("continue", text)
    else:
        b.answer("stop", text if text.strip() else GATE_STOP_NOTE)


def _answer_final_gate(b, gate: dict) -> tuple:
    """final-gate（Archon だけの関所。盤面の問いでない）の答えを残す: どの答えも b.work(FINAL_GATE_ANSWER) に {decision, text}
    （stop・reject も。報告が読む）と process.human_items に 1 行（kinds final_gate・answer は continue か stop・note は一言の字のまま）。
    同じ答えで呼び直した（Archon の再開）なら積み増さない。返り (止めるか, 止める理由)"""
    decision, text = _gate_words(gate)
    doc = {"decision": decision, "text": text}
    path = b.work(FINAL_GATE_ANSWER)
    try:
        again = json.loads(path.read_text(encoding="utf-8")) == doc
    except (OSError, ValueError):
        again = False
    if not again:
        _write_json(path, doc)
        answer = "continue" if decision in GATE_GO else "stop"
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [FINAL_GATE_KIND], "asked": [FINAL_GATE_FILE],
                                                   "answer": answer, "note": text, "node": FINAL_GATE_BY})
        for row in _waiting_rows(b):   # 守りのファイル・食い違いの申し出の行に人の答えを写す（報告の冒頭 1 に出る）
            row["answer"] = answer
        b.save()
    stop = decision in GATE_STOP
    return stop, (text if text.strip() else FINAL_GATE_STOP_NOTE) if stop else ""


def _out_file(b, nid: str) -> str:
    """今の周に出した節 nid の出力の絶対パス（盤面の外で走る役が読むため。周の番号を仮定しない。今の周に無ければ ""）"""
    info = b.state["outputs"].get(nid)
    return str(b.dir / info["file"]) if info and info.get("round") == b.round else ""


def _notes(b) -> str:
    """今の周の process.human_items の一言（note）を改行で並べた文（字のまま）"""
    items = (b.record.get("process") or {}).get("human_items") or []
    return "\n".join(h["note"] for h in items
                     if isinstance(h, dict) and h.get("round") == b.round and isinstance(h.get("note"), str) and h["note"])


def trace_empty_fix(b) -> None:
    """直す物の無い周に機械が p3.fix の空の返答を渡した印を trace に 1 行（T10b の h-plan が take の後に呼ぶ。TA6）。
    at mid は、この印の在る周の p3.fix を「役が出した修正」と数えない"""
    b.trace(EMPTY_FIX_OP, node="p3.fix", by=EMPTY_FIX_BY, round=b.round)


def _unit_file_paths(u: dict, repo) -> tuple:
    """単位 1 つが名指すファイル（class_query.how.paths。無ければ key の頭の語）のうち、対象の根からの相対で在るファイルの
    パスと、捨てたパス。how.paths は git の pathspec（ディレクトリ・glob・絶対パスも来る）で、measure.py は根の中の
    ファイルしか測らないので、ここで捨てて数を残す（黙って空の実測にしない）"""
    how = (u.get("class_query") or {}).get("how") or {}
    raw = [p for p in how.get("paths") or [] if isinstance(p, str) and p]
    if not raw and isinstance(u.get("key"), str) and u["key"].split():
        raw = [u["key"].split()[0]]
    root = pathlib.Path(repo).resolve()
    kept, dropped = [], []
    for p in raw:
        q = pathlib.PurePosixPath(p[2:] if p.startswith("./") else p)
        ok = (not q.is_absolute() and ".." not in q.parts and not any(c in p for c in "*?[:")
              and (root / q).is_file())
        (kept if ok else dropped).append(str(q) if ok else p)
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def structure_units(b, carried: dict, repo) -> str:
    """判定の直す義務の単位（carried の judgment_file・open_units）を blk-structure の入力の契約 {id, paths, summary} に写して
    b.work(STRUCTURE_UNITS_FILE) に書き、そのパスを返す。paths が 1 本も残らない単位は写さない（stage_a.read_units は 1 行でも
    paths が空ならファイル全体を落とす）。写さなかった単位と捨てたパスは trace の STRUCTURE_UNITS_OP の 1 行に残す"""
    try:
        doc = json.loads(pathlib.Path(carried["judgment_file"]).read_text(encoding="utf-8"))
        keys = set(json.loads(carried["open_units"] or "[]"))
    except (OSError, ValueError, TypeError):
        doc, keys = {}, set()
    rows, skipped, dropped = [], [], []
    for u in (doc.get("units") if isinstance(doc, dict) else None) or []:
        if not isinstance(u, dict) or u.get("key") not in keys:
            continue
        paths, bad = _unit_file_paths(u, repo)
        dropped += bad
        if not paths:
            skipped.append(u["key"])
            continue
        reason = u.get("reason")
        rows.append({"id": u["key"], "paths": paths, "summary": reason if isinstance(reason, str) else ""})
    if skipped or dropped:
        b.trace(STRUCTURE_UNITS_OP, units=skipped, paths=dropped, round=b.round)
    _write_json(b.work(STRUCTURE_UNITS_FILE), rows)
    return str(b.work(STRUCTURE_UNITS_FILE))


def _structure_failed(structured) -> str:
    """構造のブロックの出口が、構造の目の行なしで計画する周か（理由の 1 文。行を受けてよい周は ""）"""
    if not isinstance(structured, dict):
        return "構造のブロックの節が落ちたか走らなかった（出口が無い）"
    if structured.get("status") == "ok":
        return ""
    why = structured.get("reason") or ""
    if not why:
        try:
            doc = json.loads(pathlib.Path(structured.get("structure_file") or "").read_text(encoding="utf-8"))
            why = (doc.get("reason") or "") if isinstance(doc, dict) else ""
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    return f"構造のブロックが status: {structured.get('status') or '無し'} で抜けた" + (f"（{why}）" if why else "")


def structure_edge(board_dir, structured, plan_go=True) -> dict:
    """h-structure: 構造のブロックの出口 structured（飛ばされた・落ちた周は None）を確かめ、盤面の根の控え（structmark）を書く。
    自分の読み書きの失敗（設計の行が読めない・控えを書けない）も節の失敗にせず、status failed と理由で返す（計画は行なしで進む）。
    計画を起こさない周（plan_go が偽）は控えを書かずに status skipped（落ちの印を出さない）"""
    if plan_go is False:
        return {"ok": True, "status": "skipped", "reason": "計画を起こさない周（h-plan の go が偽）", "design_file": "", "wall_s": 0}
    why = _structure_failed(structured)
    got = structured if isinstance(structured, dict) else {}
    design_file, wall = str(got.get("design_file") or ""), got.get("wall_s", 0)
    if not why:
        try:
            structmark.rows(design_file)
        except ValueError as e:
            why = str(e)
    status = "failed" if why else "ok"
    try:
        structmark.write(board_dir, status=status, reason=why, design_file=design_file, wall_s=wall)
    except OSError as e:
        status, why = "failed", (why + "。" if why else "") + f"構造のブロックの控えを書けない: {e}"
    return {"ok": True, "status": status, "reason": why, "design_file": design_file, "wall_s": wall}


def _fixed_by_role(b) -> bool:
    """今の周の p3.fix を役が出した（done で、今の周の出力が在り、機械の空の返答の印が無い）"""
    info = b.state["outputs"].get("p3.fix")
    return (b.node_state("p3.fix") == "done" and bool(info) and info.get("round") == b.round
            and not _traced(b, EMPTY_FIX_OP, by=EMPTY_FIX_BY, round=b.round))


def _tests_head(b, tests) -> str:
    """最後のテストの頭の語: 緑・赤・環境で起こせなかった（赤が全部、起こせない段 entry.env_only_red）・走れなかった・
    走らなかった（出口が無い）。任せ先の CI の役が走らせた回（by role_needed）は、
    盤面の p4.ci が済んでいれば素材 materials.local_checks の status（blk-tests の final と同じ読み）"""
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


def _faces(b, nid: str) -> int:
    out = b.output_of_round(nid, b.round) or {}
    return len(out.get("faces") or [])


def _eyes(b) -> tuple:
    """独立の目（R1〜R4）の判定の行と、目が阻害を返した R の名。判定は周の記録（rounds/round-<N>.json。目の受け付けの settle が
    周を締めて書く）か、まだ無ければ盤面の記録から。not_run は目の判定でなく機械が書く欠け（返答が無い・止めた周）なので、行には
    出すが阻害に数えない"""
    try:
        rounded = json.loads((b.dir / "rounds" / f"round-{b.round}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rounded = b.record
    reviews = rounded.get("reviews") or {}
    status = validator_module(b).REVIEW_STATUS
    lines, blocked = [], []
    for name in ("R1", "R2", "R3", "R4"):
        r = reviews.get(name)
        if not isinstance(r, dict):
            lines.append(f"  - {gatemarks.EYES[name]}（{name}）: 結果が無い")
            continue
        st = r.get("status")
        if st in status and status[st].blocks and st != "not_run":
            blocked.append(name)
        reason = " ".join(str(r.get("reason") or "").split())
        lines.append(f"  - {gatemarks.eye_named(name, st)}" + (f"——理由: {reason}" if reason else ""))
        if name == "R2":
            lines += _r2_inputs(b)
    fell = gatemarks.fell_lanes(b)
    if fell:
        lines.append(f"  - 落ちた筋: {fell}")
    return lines, blocked


ROLE_WORDS = {"design": "独立の設計を作る役", "compare": "独立の設計と差分を比べる役"}   # R2 の 2 つの役の平易な名（記録の名は括弧に回す）


def _r2_inputs(b) -> list:
    """R2 の行の下に、R2 が『渡されていない』と書いた文と、そのうち渡していた物（compare の claims_given）と、支度の時に R2 の 2 つの役へ渡した前提の入力の控え（独立の目の出口の
    premise_inputs。一番新しい周の eyes-exit.json）と、独立設計の後に来た人の答え（compare の after_design）を並べる。人が同じ枚で突き合わせる（受け付けは拒まない）"""
    exits = scopes.all_rounds(b.dir, "eyes-exit.json")   # 独立の目の include の scope の根に在る（周の順）
    try:
        pi = json.loads(exits[-1].read_text(encoding="utf-8")).get("premise_inputs") if exits else None
    except (OSError, ValueError):
        pi = None
    if not isinstance(pi, dict):
        return ["    - 独立の設計と比べる目に渡した入力の控えが無い（R2）"]
    out = [f"    - 独立の設計と比べる目が渡されていないと書いた（R2）: {c}" for c in pi.get("claims") or []]
    led = pi["compare"] if isinstance(pi.get("compare"), dict) else {}
    out += [f"    - 独立の設計と比べる目が渡されていないと書いたが、渡していた（R2）: {m.get('claim')} ← {m.get('kind')}: {m.get('what')}"
            for m in led.get("claims_given") or []]
    late = led.get("after_design")
    if late:
        out.append(f"    - 独立設計の後に来た人の答え（{ROLE_WORDS['compare']}にだけ渡った）: " + "／".join(late))
    for role in ("design", "compare"):
        led = pi.get(role)
        if not isinstance(led, dict):
            out.append(f"    - {ROLE_WORDS[role]}に渡した入力の控えが無い（{role}）")
            continue
        given = "／".join(f"{g.get('kind')}: {g.get('what')}" for g in led.get("given") or []) or "（前提の入力は無い）"
        out.append(f"    - {ROLE_WORDS[role]}に渡した前提の入力（{role}）: {given}")
        held = led.get("withheld") or []
        if held:
            out.append("    - run に在ったが渡していない: "
                       + "／".join(f"{w.get('kind')}: {w.get('what')}（{w.get('why')}）" for w in held))
    return out


def _final_text(b, head: str, tests, objection: str, eyes: tuple, repo, run_id: str) -> str:
    """最後の関所の文: 最後のテストと修正前のテスト（entry.baseline_line）・受け付けが手元で回さなかった試験・受け付けの束が
    赤緑を確かめずに通した回（report.gates_lines）・差分の審査の穴の数・手直しの結果・止めずに残った異議・
    決着した再審の結果（report.rejudge_lines。関所を開ける理由には数えない）・構造のブロックが落ちた周の印
    （structmark.note）・事前審査の壁打ちの往復（converge.lines）・独立の目の判定・盤面の問い・判定の役が保留にしたままの問い（gatemarks.held_lines）・関所で答えた問い（gatemarks.answered_lines）・読めなかった保留（gatemarks.unread_hold_lines）を 1 枚に。「盤面の問い: 無い」はどれも無い時だけ。行の主語は平易な名で、
    盤面の節・目の名・状態の語は括弧に回す（gatemarks.named・eye_named）"""
    tests = tests or {}
    lines = [f"最後の人の関所（最後のテストと独立の目の後・報告の前）: テストは{head}", ""]
    if tests.get("by"):
        lines.append(f"- テストの一式: {entry.suites_line(tests, role_status=entry.role_ci_status(b, tests))}")
    lines.append(f"- {entry.baseline_line(b)}")
    left = _ci_left(b)
    if left:
        lines.append(f"- 修正の受け付けが手元で回さなかった試験（{len(left)} 件。run はその緑を確かめない——取り込みの前に人が回すか CI で確かめる）:")
        lines += [f"  - {t}" for t in left]
    lines += [f"- {x}" for x in report.gates_lines(b)]   # 修正の受け付けの束が受け入れのテストの赤緑を確かめずに通した回
    lines.append(f"- ログ: {tests.get('log') or '（無い）'}")
    if tests.get("reason"):
        lines.append(f"- 走れなかった理由: {tests['reason']}")
    lines.append(f"- run の作業ツリー: {pathlib.Path(repo).resolve()}")
    lines.append(f"- 差分の審査の穴: {_faces(b, 'p3.delta_review')} 件（2 回目の審査: {_faces(b, 'p3.delta_review2')} 件）")
    handled = (b.output_of_round("p3.delta_fix", b.round) or {}).get("handled") or []
    lines.append(f"- {gatemarks.named('p3.delta_fix')}の結果（{len(handled)} 件）:")
    lines += [f"  - {h.get('key')}: {gatemarks.HANDLED_WORDS.get(h.get('handled'), '')}（{h.get('handled')}）——{h.get('how')}"
              for h in handled if isinstance(h, dict)] or ["  - （無い）"]
    lines.append(f"- 止めずに残った異議: {objection or '無い'}")
    settled = report.rejudge_lines(b)
    lines += ["- 再審で決着した結果:", *[f"  {x}" if x.startswith("  ") else f"  - {x}" for x in settled]] if settled \
        else ["- 再審: 無い"]
    missing = structmark.note(structmark.read(b.dir))
    if missing:
        lines.append(f"- 構造のブロック: {missing}")
    passed = gatemarks.lines(b)
    if passed:
        lines.append(f"- 直す前の関所で通した項目（決め手が在るので聞かずに通した行と、人が通したので後の関所で聞き直さなかった行。{len(passed)} 件）:")
        lines += [f"  - {x}" for x in passed]
    lines += [x if x[:1].isspace() else f"- {x}" for x in converge.lines(b)]   # 往復ごとの行は自分の「  - 」を持つ
    rows, blocked = eyes
    lines.append(f"- 独立の目の判定（阻害: {'・'.join(blocked) or '無い'}）:")
    lines += rows
    asking = b.state.get("pending_human")
    if asking:
        lines.append(f"- {gatemarks.named(asking.get('node'))}が人に聞いている問い（記録のまま引く）:")
        lines += [f"  {x}" for x in gatemarks.quote(asking.get("question"))]
        lines += [f"  - {x}" for x in asking.get("items") or []]
        lines.append("  - この関所の答えはこの問いに答えない。問いは報告の冒頭と次の run の依頼の下書きへ渡る")
    held = gatemarks.held_lines(b)
    if held:
        lines.append(f"- 判定の役が人に聞くと保留にしたままの問い（問いの台帳・{len(held)} 件。この関所の答えは問いに答えない。"
                     "問いは報告の冒頭に並ぶ）:")
        lines += [f"  - {x}" for x in held]
    done = gatemarks.answered_lines(b)
    if done:
        lines.append(f"- 関所で答えた問い（問いの台帳・{len(done)} 件。保留の件数には数えない）:")
        lines += [f"  - {x}" for x in done]
    lines += [f"- {x}" for x in gatemarks.unread_hold_lines(b)]
    if not asking and not held and not done:
        lines.append("- 盤面の問い: 無い")
    lines += ["", "答え方（人が決める関所。依頼者に聞いて、その言葉で答える）:",
              f"- 報告へ進める: {answer.line(run_id, 'continue', '<一言>')}",
              f"- 止める: {answer.line(run_id, 'stop', '<理由>')}（報告は出る）"]
    return "\n".join(lines) + "\n"


def _protected(b, repo) -> tuple:
    """run の修正の差分（修正前の版＝state.inputs.review_rev。固まる前は record.base＝p0.base が固めた版。そこから今の作業ツリー
    まで。commit・消した物・未追跡を含む）のうち守りのファイルに当たる物と、テストの変更の許し（承認済みの修正案の rewrite_tests と
    裁定 fix_test_scope の範囲。conflict.test_permits）が名指したテストの物。変更から入る run の record.base は merge-base で、
    PR にもとからある変更まで数えてしまうので起点にしない。
    返り (rows, rev, 確かめられなかった理由)。一覧・版・git・申し出の控えが読めなければ rows は空で理由を返す（fail closed）"""
    rev = ""
    try:
        rev = accept.resolve_rev(repo, (b.state.get("inputs") or {}).get("review_rev") or b.record.get("base") or "")
        ruled = conflict.ruled_test_doc(b)
        return protect.touched(repo, rev) + (protect.touched(repo, rev, ruled) if ruled else []), rev, ""
    except (protect.Broken, Reject, BoardGap) as e:
        return [], rev, str(e)


def _stat(r) -> str:
    return f"+{r['added']} −{r['deleted']}" if r.get("added") is not None else "行数なし"


def _protected_text(rows, rev: str, err: str, repo) -> str:
    """最後の関所の文の冒頭 3 行の直後の節（触った守りのファイル・行数・規則・差分の見方。確かめられなければその理由）"""
    if err:
        return (f"## {PROTECTED_UNKNOWN}（差分が一覧に触れていないとは言えない）\n\n- 理由: {err}\n"
                f"- 一覧: {protect.MANIFEST}\n\n")
    lines = [f"## {PROTECTED_HEAD}（{len(rows)} 件。works 自身の試験・柵・受け付けの口。通すのは人の continue だけ）", ""]
    lines += [f"- {x}" for x in protect.lines(rows)]
    lines += [f"- 差分: git -C {pathlib.Path(repo).resolve()} diff {rev[:12]} -- <パス>（未追跡は新しいファイル）",
              f"- 一覧: {protect.MANIFEST}", "", ""]
    return "\n".join(lines)


def _row(b, node: str):
    """今の周の process.human_items の node の行（無ければ None）"""
    items = (b.record.get("process") or {}).get("human_items") or []
    return next((h for h in items if isinstance(h, dict) and h.get("node") == node and h.get("round") == b.round), None)


def _protected_row(b):
    return _row(b, PROTECTED_BY)


def _waiting_rows(b) -> list:
    """最後の関所の答えを写す今の周の行（守りのファイル・食い違いの申し出）"""
    return [r for r in (_row(b, PROTECTED_BY), _row(b, conflict.BY)) if r is not None]


def _record_conflict(b, asks: list) -> None:
    """process.human_items に今の周の 1 行（kinds conflict・answer は最後の関所の答えまで None・note に件数と単位）。
    呼び直しでは積み増さず、答えの前なら中身だけを今の申し出に合わせる"""
    note = f"{conflict.HEAD} {len(asks)} 件: " + "、".join(asks) + "——最後の関所で人が決める（通すのは continue だけ）"
    row = _row(b, conflict.BY)
    if row is None:
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [conflict.KIND], "asked": list(asks),
                                                   "answer": None, "note": note, "node": conflict.BY})
    elif row.get("answer") is None and (row.get("asked"), row.get("note")) != (list(asks), note):
        row.update(asked=list(asks), note=note)
    else:
        return
    b.save()


def _conflict_text(asks: list) -> str:
    """最後の関所の文の節（裁定役か機械が人に回した食い違いの申し出。どの単位を直さずに残したか）"""
    lines = [f"## {conflict.HEAD}（{len(asks)} 件。裁定役か機械が人に回した。単位は直さずに残した。通すのは人の continue だけ）", ""]
    lines += [f"- {x}" for x in asks]
    return "\n".join(lines + ["", ""])


def _unproven_text(unproven: list) -> str:
    """最後の関所の文の節（判定者の問いを例で試していない単位。閉鎖の数え直しはその問いのまま）"""
    lines = [f"## {querytest.UNPROVEN_HEAD}（{len(unproven)} 件。閉鎖の数え直しは例で試していない問いのまま）", ""]
    lines += [f"- {x}" for x in unproven]
    return "\n".join(lines + ["", ""])


def _closure_text(closure: list, head: str = querytest.CLOSURE_HEAD) -> str:
    """最後の関所の文の節（修正の受け付けが判定者の問いで数え直した単位ごとの表のうち、head の見出しに載せる単位。
    同じ run の中で直した修正案の項目の行も、見出し replan.AMEND_HEAD でこの形に並べる）"""
    lines = [f"## {head}（{len(closure)} 件）", ""]
    lines += [f"- {x}" for x in closure]
    return "\n".join(lines + ["", ""])


def _record_protected(b, rows, err: str) -> None:
    """process.human_items に今の周の 1 行（kinds protected_files・answer は最後の関所の答えまで None・note に一覧）。
    呼び直し（Archon の再開）では積み増さず、答えの前なら中身だけを今の差分に合わせる"""
    if err:
        asked, note = [f"{PROTECTED_UNKNOWN}: {err}"], f"{PROTECTED_UNKNOWN}——最後の関所で人が決める（{err}）"
    else:
        asked = protect.lines(rows)
        note = (f"{PROTECTED_HEAD} {len(rows)} 件: " + "、".join(f"{r['path']}（{_stat(r)}・規則 {r['id']}）" for r in rows)
                + "——最後の関所で人が決める（通すのは continue だけ）")
    row = _protected_row(b)
    if row is None:
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [PROTECTED_KIND], "asked": asked,
                                                   "answer": None, "note": note, "node": PROTECTED_BY})
    elif row.get("answer") is None and (row.get("asked"), row.get("note")) != (asked, note):
        row.update(asked=asked, note=note)
    else:
        return
    b.save()


def entry_edge(b) -> dict:
    """h-entry（start の後・判定の前）: 盤面の ready から、任せ先の役・ブロックを回すかの旗。判定から入る run と仕様から入る run の
    両方で、pr-checking・premising・purposing の when: はこの欄だけを読む"""
    ready = b.ready()
    return {"go": True, "pr_go": "p0.parallel_pr" in ready, "premises_go": PREMISES_NODE in ready,
            "purpose_go": "p0.purpose" in ready, "spec_go": any(n.startswith("spec.") for n in ready)}


def _guard(b, repo) -> tuple:
    """守りのファイルと食い違いの申し出を確かめ、在れば今の周の行（答えは最後の関所まで None）に書く。返り (rows, rev, err, asks)。
    h-final と、関所の答えの無い h-eyes が呼ぶ（独立の目のブロックが落ちて h-final が飛ばされた run でも、行を見ずに通さない）"""
    rows, rev, err = _protected(b, repo)
    try:
        asks = conflict.human_lines(b)
    except BoardGap as e:   # 申し出の控えが読めない: 黙って空にせず、人に回す
        asks = [f"申し出の控えが読めない（{e}）"]
    if rows or err:
        _record_protected(b, rows, err)
    if asks:
        _record_conflict(b, asks)
    return rows, rev, err, asks


def _final_needs(b, head: str, objection: str, eyes: tuple, rows, err: str, asks: list, mismatched: list) -> list:
    """最後の関所を開ける理由（1 件 1 句）。when_needed で開くかはこの列の空でなさだけで決め、_final_head の 1 行目もこの列を
    並べる（理由を足すのはここだけ）"""
    why = []
    if err:
        why.append(f"{PROTECTED_UNKNOWN}（人の確かめが要る）")
    elif rows:
        why.append(f"{PROTECTED_HEAD}（{len(rows)} 件。人の確かめが要る）")
    if head != "緑":
        why.append(f"最後のテストが{head}")
    if asks:
        why.append(f"食い違いの申し出を人に回した（{len(asks)} 件）")
    if eyes[1]:
        why.append(f"独立の目が阻害を返した（{'・'.join(eyes[1])}）")
    if mismatched:
        why.append(f"直したという申告と機械の数え直しが合わない単位が在る（{len(mismatched)} 件）")
    if b.state.get("pending_human"):
        why.append("人に聞いている問いが盤面に在る")
    if objection:
        why.append("止めずに残った異議が在る")
    return why


def _final_head(b, head: str, why: list, guarded: bool) -> list:
    """最後の関所の冒頭 3 行（gatemarks.head3）。起きたこと＝関所を開けた理由（_final_needs。守りのファイルはこの行で名指す）・
    決めてほしいこと＝報告へ進めるか止めるか・推し＝判定の役が問いの理由に書いた推し（機械は作らない）"""
    held = gatemarks.held_lines(b)
    happened = (f"最後のテストと独立の目が済み、報告の前で止まった。テストは{head}。"
                + ("開けた理由: " + "・".join(why) if why else "関所はいつも開く設定（final_gate always）で、ほかに開けた理由は無い")
                + (f"。判定の役が人に聞くと保留にしたままの問いも在る（{len(held)} 件。関所を開ける理由には数えない）" if held else ""))
    decide = ("報告へ進めて run を終えるか、止めるか（打つ行は末尾の答え方）"
              + ("。守りのファイルの変更は下の最初の節を確かめてから通す" if guarded else ""))
    asking = b.state.get("pending_human") or {}
    return gatemarks.head3(happened, decide, gatemarks.pushes([*held, *(asking.get("items") or [])]))


def final_edge(b, repo, *, run_id: str, mode: str, tests) -> dict:
    """h-final（最後のテストと独立の目の後）: ask は final_gate always か、when_needed で最後のテストが緑でない（赤・環境で起こせなかった・
    走れなかった・走らなかった）・盤面が人に聞いている・止めずに残った異議が在る・守りのファイルを触った（確かめられなかった）・独立の目が
    阻害を返した・修正の受け付けの数え直しが修正役の申告と合わない単位が在る時。文は冒頭 3 行（_final_head。開けた理由・決めて
    ほしいこと・推し）で始まり、守りのファイルはその 1 行目で名指し、3 行の直後の最初の節と process.human_items の 1 行にもなる。
    開いた関所の文は、例で証明できない単位と、同じ run の中で直した修正案の項目（replan.lines）も並べる（開ける理由には数えない）。案の直しを諦めた fix_plan_item の単位は ask_human と
    同じ食い違いの申し出の行（conflict.human_lines）。文は b.work(FINAL_GATE_FILE) にも"""
    head = _tests_head(b, tests)
    eyes = _eyes(b)
    left = rejudge.unsettled(b)
    objection = "" if left["settled"] else left["text"]
    rows, rev, err, asks = _guard(b, repo)
    if _stopped(b) and not _ended(b):   # 確かめが盤面を止めた（修正案の欄の控えの食い違い）: 答えが効かない関所は開かない
        return {}
    guarded = bool(rows) or bool(err)
    # 申告と数え直しが合わない単位は、前は返答全体を拒んだ形なので関所を開ける。閉じていないだけの単位（修正役が remaining で
    # 残した）は前も通っていたので、見せるだけ
    mismatched = querytest.closure_lines(b, mismatched_only=True)
    why = _final_needs(b, head, objection, eyes, rows, err, asks, mismatched)
    if (mode == "when_needed" and not why) or (mode == "protected_only" and not guarded):
        return {}
    unproven = querytest.unproven_lines(b.dir)   # 人に見せる印で、関所を開ける理由（why）には数えない
    stuck = querytest.closure_lines(b, stuck_only=True)
    closure = querytest.closure_lines(b, claimed=report.claimed_units(b))
    try:   # 案の直しの記録の行（関所を開ける理由には数えない）。控えが読めなければその文を 1 行に
        amend = replan.lines(b)
    except BoardGap as e:
        amend = [str(e)]
    text = ("\n".join(_final_head(b, head, why, guarded)) + "\n\n"
            + (_protected_text(rows, rev, err, repo) if guarded else "") + (_conflict_text(asks) if asks else "")
            + (_closure_text(stuck, querytest.STUCK_HEAD) if stuck else "")
            + (_unproven_text(unproven) if unproven else "") + (_closure_text(closure) if closure else "")
            + (_closure_text(amend, replan.AMEND_HEAD) if amend else "")
            + _final_text(b, head, tests, objection, eyes, repo, run_id))
    _write_text(b.work(FINAL_GATE_FILE), text)
    return {"ask": True, "gate_text": text, "gate_file": str(b.work(FINAL_GATE_FILE))}


def _done_this_round(b, nid: str) -> bool:
    info = b.state["outputs"].get(nid)
    return b.node_state(nid) == "done" and bool(info) and info.get("round") == b.round


def _hand(b, board_dir, nid: str, reply: dict, repo) -> dict:
    """機械が役の返答を盤面へ渡す（判定のブロックが受けた判定・直す物が無い周の空の修正）。手順は entry.hand の 1 か所（待っている
    instance が無ければ BoardGap——線の順の誤り）"""
    return entry.hand(b, board_dir, nid, reply, repo)


def _judgment(judged) -> tuple:
    """判定のブロックの出口から (判定の返答, 読めない理由)。読めれば理由は空。judgment.json の class_query の例（hits・misses）は
    写しの型が持てないので外す（querytest.split）"""
    path = judged.get("judgment_file") if isinstance(judged, dict) else None
    if not isinstance(path, str) or not path:
        return None, "判定のブロックの出口（judgment_file）が届かない"
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"判定のファイル {path} が読めない（{type(e).__name__}: {e}）"
    if not isinstance(doc, dict):
        return None, f"判定のファイル {path} が JSON のオブジェクトでない（{type(doc).__name__}）"
    return querytest.split(doc)[0], ""


def _premises_reply(premised) -> tuple:
    """前提のブロックの出口から (実測役の返答, 読めない理由)。読めれば理由は空"""
    path = premised.get("constraints_file") if isinstance(premised, dict) else None
    if not isinstance(path, str) or not path:
        return None, "前提のブロックの出口（constraints_file）が届かない"
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"前提のファイル {path} が読めない（{type(e).__name__}: {e}）"
    if not isinstance(doc, dict):
        return None, f"前提のファイル {path} が JSON のオブジェクトでない（{type(doc).__name__}）"
    return doc, ""


def judge_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, premised=None) -> dict:
    """h-judge の固有の仕事（前提の役の後・判定の前。計画 P1 Task 24・P1-R9・〔線A計〕T22）。順:
    1. 包みの確かめ: reads.adapter_seen（この run の worktree の包みの起動の記録。盤面を作った後の行）が偽で adapter_mode が
       optional でなければ b.stop("包みが通っていない: …", by=ADAPTER_BY) で stop（_adapter_guard）。決まりは「包みの確かめは、
       この run で役が 1 つ起きた後の最初の境の節で止める」。固定材料から始めた盤面（fixture.adopted）はここまでに起きた役が
       無いので確かめず、trace に ADAPTER_FIXTURE_OP の 1 行を残して h-mid（修正のブロックの後）に回す
    2. 表で p0.premises が role なのに盤面で今の周に済んでいなければ、前提のブロックの出口 premised の constraints_file を読んで
       entry.take(p0.premises)（起こした印を置いてから。盤面の写しの schema・measured_needs_output・writes が当たる）。
       出口が届かない・読めない・盤面が受けないなら b.stop("前提の実測が盤面に無い: …", by=PREMISES_BY) で stop。
       済んでいれば渡さない（Archon の再開で呼び直しても同じ）
    3. go True・premises_file は盤面の state.outputs["p0.premises"] の置き場（絶対パス。na・表に無い節なら空）・
       purpose_go は目的の文（p0.purpose）が盤面で待っているか（前提を渡した後の ready。purposing の when:）"""
    board_dir = pathlib.Path(board_dir)
    if adapter_mode != "optional" and fixture.adopted(board_dir) is not None:
        # 固定材料から始めた run は修正役が最初の役で、ここまでに起きた役が無い。確かめは h-mid で
        b.trace(ADAPTER_FIXTURE_OP, at="judge")
    else:
        stopped = _adapter_guard(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode)
        if stopped:
            return stopped
    row = b.table.nodes.get(PREMISES_NODE) if b.table is not None else None
    if row is not None and row.by == "role" and b.node_state(PREMISES_NODE) != "na" and not _done_this_round(b, PREMISES_NODE):
        reply, why = _premises_reply(premised)
        if not why:
            got = _hand(b, board_dir, PREMISES_NODE, reply, repo)
            why = "" if got["ok"] else f"盤面が前提の実測を受けない: {got['reason']}"
        if why:
            reason = f"前提の実測が盤面に無い: {why}"
            entry.open_board(board_dir).stop(reason, by=PREMISES_BY)
            return {"stop": True, "go": False, "why": reason}
        b = entry.open_board(board_dir)
    return {"go": True, "premises_file": _out_file(b, PREMISES_NODE), "purpose_go": PURPOSE_NODE in b.ready()}


def _adapter_guard(b, board_dir, repo, *, run_id: str, adapter_mode: str) -> dict | None:
    """包みの確かめ: adapter_mode が optional でなく、reads.adapter_seen（この run の worktree の包みの起動の記録）が偽なら
    b.stop("包みが通っていない: …", by=ADAPTER_BY) をして stop の返りを返す。通れば None。呼ぶのは、この run で役が 1 つ
    起きた後の最初の境の節（通常の盤面は h-judge、固定材料から始めた盤面は h-mid）"""
    if adapter_mode == "optional":
        return None
    seen = reads.adapter_seen(pathlib.Path(board_dir), run_id, repo=repo)
    if seen["seen"]:
        return None
    reason = f"包みが通っていない: {'・'.join(seen['whys'])}。{ADAPTER_HINT}"
    b.stop(reason, by=ADAPTER_BY)
    return {"stop": True, "go": False, "why": reason}


def _capture_fixture(b, board_dir, repo, run_id: str) -> None:
    """h-fix の go の後の 1 段: 1 周目なら fixture.capture（既に写していれば書き直さない。固定材料から始めた盤面は capture が
    写さない）。OSError・ValueError は盤面の trace に FIXTURE_FAILED_OP の 1 行を残して続ける（写せなくても run を止めない）"""
    if b.round != 1:
        return
    try:
        fixture.capture(pathlib.Path(board_dir), repo, run_id=run_id, pack_root=entry.PACK)
    except (OSError, ValueError) as e:
        b.trace(FIXTURE_FAILED_OP, at="fix", error=f"{type(e).__name__}: {' '.join(str(e).split())}")


def _role_ready(b, where: str) -> list:
    """盤面の ready のうち、表の where が where の役の節"""
    return [n for n in b.ready() if b.table is not None and n in b.table.nodes and b.table.nodes[n].by == "role"
            and b.table.nodes[n].where == where]


def mat_edge(b, board_dir, repo) -> dict:
    """h-mat の固有の仕事（目的の文の後・P1 の目の前。計画 P1 Task 32・33）。順:
    1. 表で p0.purpose が role なのに盤面で今の周に済んでいなければ、目的の文のブロックが盤面の根に置いた purpose.json
       （core の purpose.read_purpose。blk-purpose の受け付けが書く）を読んで entry.take(p0.purpose)（起こした印を置いてから。
       盤面の写しの schema が当たる）。無い・読めない・盤面が受けないなら b.stop("目的の文が盤面に無い: …", by=PURPOSE_BY) で
       stop。済んでいれば渡さない（Archon の再開で呼び直しても同じ）。na（条件）なら渡さない
    2. 依頼と変更の両方で始めた run の依頼がまだ積まれていなければ entry.add_pending_request で積む（CI の役の後の run でも、
       判定の前に必ず届ける）。版がまだ固まっていない（積むと入口の印が立つ）なら b.stop(…, by=PENDING_REQUEST_BY) で stop
    3. go True（判定へ）・mat_go は P1 の目（表の where が blk-material の役の節）が盤面で 1 つでも待っているか・
       purpose_file は盤面の state.outputs["p0.purpose"] の置き場（無ければ空）。今の周の判定（p2.diagnose）が既に済んだ盤面
       （固定材料から始めた run）は go 偽（判定の支度は待っていない p2.diagnose を線の順の誤りとして拒む）"""
    board_dir = pathlib.Path(board_dir)
    row = b.table.nodes.get(PURPOSE_NODE) if b.table is not None else None
    if row is not None and row.by == "role" and b.node_state(PURPOSE_NODE) == "pending" and not _done_this_round(b, PURPOSE_NODE):
        try:
            _, reply = purpose.read_purpose(board_dir)
            why = ""
        except Reject as e:   # 無い・読めない・型の外。理由は盤面の止めの文へ
            reply, why = None, str(e)
        if not why:
            got = _hand(b, board_dir, PURPOSE_NODE, reply, repo)
            why = "" if got["ok"] else f"盤面が目的の文を受けない: {got['reason']}"
        if why:
            reason = f"目的の文が盤面に無い: {why}"
            entry.open_board(board_dir).stop(reason, by=PURPOSE_BY)
            return {"stop": True, "go": False, "why": reason}
        b = entry.open_board(board_dir)
    if entry.add_pending_request(b) == "waiting":
        reason = f"依頼を判定の前に積めない: {entry.PENDING_WAIT_NODE} がまだ済んでいない（今積むと入口の印が立ち P1 の目が外れる）"
        b.stop(reason, by=PENDING_REQUEST_BY)
        return {"stop": True, "go": False, "why": reason}
    return {"go": not _done_this_round(b, DIAGNOSE_NODE), "mat_go": bool(_role_ready(b, MAT_BLOCK)),
            "purpose_file": _out_file(b, PURPOSE_NODE)}


def rejudge_edge(board_dir, repo) -> dict:
    """h-rejudge の固有の仕事（修正の後・中の検査の前。計画 P1 Task 31・rejudge 設計 23c）: 修正役が判定に異議
    （rejudge_requested）を出した周は、盤面が再審の節（p2.rejudge）を出して待つ。その節は p4.ci・p3.gates_cut の deps なので、
    回さないと最後のテストが出ない（run 28）。core の rejudge.route が盤面を settle し、待っている再審の節の役を返す——判定役の
    会話の続きで起こす役なら会話を確かめ（session_ready）、確かめられなければ役を起こさずに盤面を止める（by works:rejudge-session）。
    返り: go は回す役が在るか、止めたら stop と理由"""
    got = rejudge.route(pathlib.Path(board_dir), repo)
    if got["stopped"]:
        info = _stopped(entry.open_board(pathlib.Path(board_dir), allow_halted=True)) or {}
        return {"stop": True, "go": False, "why": str(info.get("reason") or got["why"])}
    return {"go": bool(got["next"])}


def refit_edge(board_dir, repo, gate) -> dict:
    """h-refit の固有の仕事（関所 replan-gate の後・2 回目の修正の段の前。依頼 226）: 関所の答え gate（開かなかったなら None）を
    replan.answer で当てる。stop（答えが盤面を止めた）なら {"stop": True}。そうでなければ go は戻った単位が在り p3.fix が盤面で
    待っているか、open_units は戻った単位だけの JSON の配列（1 回目に受け付けた単位を 2 回目の段の直す義務の並びに入れない——
    TDD の輪の頭が『直すな・not_done に書け』と並べ、受け付けがその行を拒むので）、plan_file は差し替えた承認済みの修正案、
    notes_file は修正の前の関所の条件（h-fix が書いた NOTES_FILE。2 回目の段にも効く）・人の一言・採った項目の事前審査の穴。
    今の周の replan.json が無ければ go 偽"""
    board_dir = pathlib.Path(board_dir)
    fix_notes = entry.open_board(board_dir, allow_halted=True).work(NOTES_FILE)
    got = replan.answer(board_dir, repo, gate, fix_notes=str(fix_notes))
    if got["stop"]:
        return {"stop": True}
    b = entry.open_board(board_dir, allow_halted=True)
    return {"go": bool(got["returned"]) and GO_NODE["fix"] in b.ready(),
            "open_units": json.dumps(got["returned"], ensure_ascii=False),
            "plan_file": got["plan_file"], "notes_file": got["notes_file"], "why": got["why"]}


def eyes_edge(b) -> dict:
    """h-look の固有の仕事（最後のテストの後・最後の関所の前。計画 P1 Task 33）: go は独立の目（表の where が blk-eyes の役の節）が
    盤面で 1 つでも待っているか（p4.assemble が済み、条件に当たった目）。r4.human_gate が人に聞いたら、残りの目は答えるまで出ない——
    ブロックは止めずに asking で抜け、最後の関所の文に問いが載り、報告が needs_human と問いを次の run へ渡す（計画 Task 33 の (b)）。
    h-eyes（関所の後）も同じ go を返し、報告が「目を回すと言ったのに blk-eyes の出口が無い」を見分ける"""
    return {"go": bool(_role_ready(b, EYES_BLOCK))}


def plan_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, judged) -> dict:
    """h-plan の固有の仕事（edge の手順 5。計画 P1 Task 23・裁定 TA3・TA6）。包みの確かめはここに置かない（h-judge。P1-R9）。順:
    1. judged（判定のブロックの出口）を b.work(JUDGED_FILE) に控える（後ろの境の節が judgment_file・open_units を返す。M4）
    2. 盤面の p2.diagnose が今の周に済んでいなければ、judged の judgment_file を読んで entry.take(p2.diagnose)。出口が届かない・
       読めない・盤面が受けない（ok False）なら b.stop("盤面が判定を受けない: …", by=JUDGE_BRIDGE_BY) で stop。済んでいれば
       渡さない（Archon の再開・盤面で判定を受けた後も同じ）
    3. p2.fix_plan が ready なら go。p3.fix が ready で p2.fix_plan が na（直す物が無い周）なら、機械が空の返答
       （entry.empty_fix_reply）を渡して trace_empty_fix
    4. 修正案が無くても、独立設計を修正の前に作る周（design.due）なら go（最後の R2 の比較が設計を要る。blk-plan は設計の輪だけを回す）
    5. go なら判定の単位を構造のブロックの入力の契約に写し（structure_units）、structure_units_file で返す"""
    if judged is not None:
        _write_json(b.work(JUDGED_FILE), judged)
    carried = _carried(b)
    if not _done_this_round(b, DIAGNOSE_NODE):
        reply, why = _judgment(judged)
        if not why:
            got = _hand(b, board_dir, DIAGNOSE_NODE, reply, repo)
            why = "" if got["ok"] else got["reason"]
        if why:
            reason = f"盤面が判定を受けない: {why}"
            entry.open_board(pathlib.Path(board_dir)).stop(reason, by=JUDGE_BRIDGE_BY)
            return {"stop": True, "go": False, "why": reason, **carried}
        b = entry.open_board(pathlib.Path(board_dir))
    ready = b.ready()
    if GO_NODE["plan"] not in ready:
        if GO_NODE["fix"] in ready and b.node_state("p2.fix_plan") == "na":
            got = _hand(b, board_dir, GO_NODE["fix"], entry.empty_fix_reply(), repo)
            if not got["ok"]:
                raise _gap(f"盤面が直す物の無い周の空の修正を受けない: {got['reason']}")
            trace_empty_fix(entry.open_board(pathlib.Path(board_dir)))
        b = entry.open_board(pathlib.Path(board_dir))
        if not design.due(b)[0]:
            return {"go": False, **carried}
    return {"go": True, **carried, "structure_units_file": structure_units(b, carried, repo)}


def edge(board_dir, at: str, repo, *, run_id: str, adapter_mode: str, final_gate: str, judged: dict | None = None,
         gate: dict | None = None, tests: dict | None = None, premised: dict | None = None) -> dict:
    """境の節（計画 Task 10a。並びは C18 の順・計画 P1 Task 26）。返りは EMPTY の欄の全部（使わない欄は空の値。judgment_file・
    open_units はどの at でも h-plan の控え b.work(JUDGED_FILE) から）。盤面を開くのは 1 回（渡し替えの後は開き直す）。順:
    0. at rejudge は、盤面を開く前に replan.settle（案の直しを待つ行を諦めた行にする。止まった盤面でも。待つ行が残れば BoardGap）。
    1. 盤面を allow_halted で開く。もう止まっている（halted・state.stop）なら、止め札の理由は trace にだけ書いて stop（M3）。
       ただし at look・final・eyes は、1 周の run が周を締めた盤面（halted.by stop_after_round。最後のテストの後の普通の終わり）を
       止めたと読まない
    2. at fix の gate（policy-gate の出口。None は開かなかった）: approve・continue は b.answer("continue", 一言)、
       stop・reject は b.answer("stop", 一言 か GATE_STOP_NOTE)（盤面は halted.by == "answer"）。at refit の gate（replan-gate の
       出口）は refit_edge（replan.answer。stop・reject は盤面を止める——止めた盤面を _halted_out で返す）。最後の関所の答えの
       ファイル（FINAL_GATE_ANSWER）には書かない
    3. at eyes の gate（final-gate の出口）: どの答えも b.work(FINAL_GATE_ANSWER) に {decision, text} と human_items に 1 行。
       stop・reject は b.stop(一言 か FINAL_GATE_STOP_NOTE, by=FINAL_GATE_BY)——周を締めた盤面では b.stop が拒むので、
       trace に STOP_AFTER_END_OP の 1 行（by FINAL_GATE_BY）を書いて stop。守りのファイルの行（h-final が書いた）にも答えを写す。
       gate が null（関所が開かなかった）なら守りのファイルと食い違いを確かめ直し（_guard。h-final が飛ばされた run でも行を書く）、
       今の周の行が答えを待っていれば、止める（by PROTECTED_BY・conflict.BY）。at final・eyes の確かめ（_guard）が盤面を止めた
       （修正案の欄の控え plan-fields.json の食い違い。conflict.test_permits）なら、関所を開かず止め直さずに _halted_out
    4. 2・3 で止まったら止め札は trace にだけ（関所の答えが先）。止まっていなければ、止め札（seen）が在れば
       b.stop(理由, by="request:<札の by>")（周を締めた盤面では trace の 1 行）して stop
    5. entry: 盤面の ready から pr_go・premises_go・purpose_go・spec_go（go True）。judge: judge_edge。plan: plan_edge。
       gate: 盤面の問い（pending_human）が在れば ask と plan.gate_text の文（b.work(GATE_FILE) にも）。
       fix: go は p3.fix が ready・notes は今の周の human_items の一言と、関所で答えた問いで直す義務に戻った単位の行
       （gatemarks.returned_lines。notes_file はそれを書いた b.work のファイル。空なら ""）・plan_file は今の周の p2.fix_plan の出力。
       go なら _capture_fixture（1 周目の盤面を固定材料に写す。写せなくても止めない）。
       mat: mat_edge（目的の文を盤面へ・mat_go）。look・eyes: eyes_edge（go は独立の目が待っているか。look は先に design.hand で
       修正の前に控えた独立設計を盤面へ渡す）。rejudge: rejudge_edge
       （go は再審の節が待っているか。判定役の会話を確かめられなければ止める）。replan: go は replan.material の go（案の直しを
       待つ行が在り、今の周の p3.fix をまだ受けていない）。regate: replan.gate の ask・gate_text・gate_file（今の周の replan.json が
       無ければ何もせず ask 偽）。refit: refit_edge（関所が開かなかった周も答え None で当てる）。
       mid: go は今の周の p3.fix を役が出した（機械の空の返答は trace の by works:empty-fix で
       見分ける）・runtime_go・holdout_go は False・mid_note。review・refix・tests: go は p3.delta_review・p3.delta_fix・p4.ci が ready。
       final: final_edge（final_gate と最後のテストの出口 tests と独立の目の判定から ask と文）。
    ready は DiskBoard.ready（書かない。開き直した盤面でも explicit の機械の節を落とさない）。
    配線の誤り（知らない at・場違いの入力・形の崩れ・知らない final_gate・adapter）は BoardGap"""
    mode = _check_args(at, final_gate=final_gate, judged=judged, gate=gate, tests=tests, premised=premised,
                       adapter_mode=adapter_mode)
    if at == "rejudge":   # 修正の段を抜ける所: 止まっているかを見る前に、案の直しを待つ行を締める（止まった盤面でも）
        replan.settle(board_dir, repo)
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {**EMPTY, **_carried(b)}
    flag = halt.seen(board_dir)
    if _stopped(b) and not (at in ENDED_AT and _ended(b)):
        return _halted_out(b, out, flag, at)
    refit = None
    if gate is not None:
        if at == "fix":
            _answer_policy_gate(b, gate)
            if _stopped(b):
                return _halted_out(b, out, flag, at)
        elif at == "refit":
            refit = refit_edge(board_dir, repo, gate)
            b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
            if refit.get("stop"):
                return _halted_out(b, out, flag, at)
        elif at == "eyes":
            stop, reason = _answer_final_gate(b, gate)
            if stop:
                _stop_board(b, at, reason, FINAL_GATE_BY)
                if flag:
                    b.trace(AFTER_HALT_OP, at=at, reason=flag["reason"], by=flag["by"])
                return {**out, "stop": True, "why": reason}
    if at == "eyes" and gate is None:
        _guard(b, repo)   # h-final が飛ばされた（独立の目のブロックが落ちた）run では行がまだ無い
        if _stopped(b) and not _ended(b):   # 確かめが盤面を止めた（修正案の欄の控えの食い違い）: 2 度止めず、その理由で止まる
            return _halted_out(b, out, flag, at)
        guarded = _protected_row(b)
        if guarded is not None and guarded.get("answer") is None:   # 守りのファイルを触ったのに最後の関所が開かなかった
            reason = f"{PROTECTED_HEAD}のに最後の関所の答えが無い（関所が開かなかった）——通すのは人の continue だけ: {guarded.get('note')}"
            _stop_board(b, at, reason, PROTECTED_BY)
            return {**out, "stop": True, "why": reason}
        asked = _row(b, conflict.BY)
        if asked is not None and asked.get("answer") is None:   # 食い違いの申し出が人に回ったのに最後の関所が開かなかった
            reason = f"{conflict.HEAD}が人に回ったのに最後の関所の答えが無い（関所が開かなかった）: {asked.get('note')}"
            _stop_board(b, at, reason, conflict.BY)
            return {**out, "stop": True, "why": reason}
    if flag:
        b.trace(FLAG_SEEN_OP, at=at, reason=flag["reason"], by=flag["by"])
        _stop_board(b, at, flag["reason"], FLAG_BY_PREFIX + flag["by"])
        return {**out, "stop": True, "why": flag["reason"]}
    if at == "entry":
        return {**out, **entry_edge(b)}
    if at == "judge":
        return {**out, **judge_edge(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode, premised=premised)}
    if at == "plan":
        return {**out, **plan_edge(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode, judged=judged)}
    if at == "gate":
        asking = b.state.get("pending_human")
        if not asking:
            return out
        text = plan.gate_text(asking, run_id=run_id)
        _write_text(b.work(GATE_FILE), text)
        return {**out, "ask": True, "gate_text": text, "gate_file": str(b.work(GATE_FILE))}
    if at == "fix":
        notes = "\n".join(x for x in (_notes(b), *gatemarks.returned_lines(b)) if x)
        notes_file = ""
        if notes:
            _write_text(b.work(NOTES_FILE), notes)
            notes_file = str(b.work(NOTES_FILE))
        go = GO_NODE["fix"] in b.ready()
        if go:
            _capture_fixture(b, board_dir, repo, run_id)
        return {**out, "go": go, "notes": notes, "notes_file": notes_file, "plan_file": _out_file(b, "p2.fix_plan")}
    if at == "replan":
        return {**out, "go": replan.material(b)["go"]}
    if at == "regate":
        return {**out, **replan.gate(b, run_id=run_id)}
    if at == "refit":
        return {**out, **(refit if refit is not None else refit_edge(board_dir, repo, None))}
    if at == "rejudge":
        return {**out, **rejudge_edge(board_dir, repo)}
    if at == "mat":
        return {**out, **mat_edge(b, board_dir, repo)}
    if at == "look":
        design.hand(b, pathlib.Path(board_dir), repo)   # 渡せなければ（設計が無い）目のブロックの出口が理由を言う
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    if at in ("look", "eyes"):
        return {**out, **eyes_edge(b)}
    if at == "mid":
        if fixture.adopted(board_dir) is not None:   # 固定材料の盤面で役が 1 つ起きた後の最初の境の節（h-judge は回した）
            stopped = _adapter_guard(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode)
            if stopped:
                return {**out, **stopped}
        return {**out, "go": _fixed_by_role(b), "mid_note": MID_NOTE}
    if at == "final":
        got = final_edge(b, repo, run_id=run_id, mode=mode, tests=tests)
        if _stopped(b) and not _ended(b):   # final_edge の確かめ（_guard）が盤面を止めた: 関所を開かず、その理由で止まる
            return _halted_out(b, out, flag, at)
        return {**out, **got}
    return {**out, "go": GO_NODE[at] in b.ready()}
