"""境の節の中身（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4。並びは C18 の順: 計画 P1 Task 26・P1-R3・P1-R4）。
ライン darkfactory の模块（層 L6。裁定 R59）で、使うのは darkfactory/scripts/edge.py だけ。止め札そのもの（置く・読む）は共有の
.shared/core/halt.py。

- edge(board_dir, at, repo, …): 境の節（darkfactory/scripts/edge.py の中身）。止め札・関所の答え・次のブロックを盤面から決める
- judge_edge(b, …): h-judge の固有の仕事（包みの確かめ・前提の実測が盤面に在るか。計画 P1 Task 24・P1-R9）
- plan_edge(b, …): h-plan の固有の仕事（判定の出口の控え・判定の渡し替え・直す物が無い周の締め。計画 P1 Task 23）
- trace_empty_fix(b): 直す物の無い周に機械が p3.fix の空の返答を渡した印（at mid が役の修正と見分ける）
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
import entry  # noqa: E402
import halt  # noqa: E402
import plan  # noqa: E402
import reads  # noqa: E402
import rejudge  # noqa: E402

# ---------------------------------------------------------------- 境の節（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4）
# いつも走る script の節 1 本（darkfactory/scripts/edge.py）を、ラインの中で at を替えて使う。並びは C18 の順（中の関所は無い。
# 人が止まれる所は最後の人の関所 final-gate。P1-R3）。when: と関所の文は境の節の欄だけを読み、go は盤面の ready から決める（TA1）。
# rejudge・eyes は枠（go False。中身は計画 P1 Task 31・33。eyes は最後の関所の答えを受ける）
AT = ("entry", "judge", "plan", "gate", "fix", "rejudge", "mid", "review", "refix", "tests", "final", "eyes")
GO_NODE = {"plan": "p2.fix_plan", "fix": "p3.fix", "review": "p3.delta_review", "refix": "p3.delta_fix", "tests": "p4.ci"}
GATE_AT = ("fix", "eyes")            # 関所の答えを受ける境の節（fix は policy-gate、eyes は final-gate）
GATE_GO = ("approve", "continue")    # approve は continue と、reject は stop と同じ（台帳 R32）
GATE_STOP = ("stop", "reject")
GATE_STOP_NOTE = "関所で止めた"              # policy-gate の stop・reject に一言が無い時の理由
FINAL_GATES = ("always", "when_needed")      # 入力 final_gate の語（空は always。P1-R3: 必ず止まれる所を残す）
FINAL_GATE_FILE = "final-gate.md"            # final-gate の文（b.work）
FINAL_GATE_ANSWER = "final-gate-answer.json" # final-gate の答え {decision, text}（b.work。stop・reject も書く——報告が読む）
FINAL_GATE_BY = "human:final-gate"           # final-gate の stop・reject の by（state.stop.by か、周を締めた後なら trace の行）
FINAL_GATE_STOP_NOTE = "最後の関所で止めた"  # final-gate の stop・reject に一言が無い時の理由
FINAL_GATE_KIND = "final_gate"               # process.human_items の行の kinds
ENDED_BY = "stop_after_round"                # 1 周の run が周を締めた後の盤面の halted.by（最後のテストの後の普通の終わり）
ENDED_AT = ("final", "eyes")                 # 周を締めた後に来る境の節（ENDED_BY の盤面を止めたと読まない）
STOP_AFTER_END_OP = "stop_after_round_end"   # 周を締めた盤面に止める答え・止め札が来た印の trace の行（b.stop は拒まれる）
MID_NOTE = "中の検査: 枠のみ（動かす確かめ・holdout は Task 36、変異は後）"
FLAG_BY_PREFIX = "request:"                  # 止め札で止めた盤面の state.stop.by は "request:<札の by>"（報告の stopped_by_request）
FLAG_SEEN_OP = "stop_flag_seen"              # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
AFTER_HALT_OP = "stop_flag_after_halt"       # 止まった後に見た止め札の trace の行（b.stop は呼ばない。M3）
EMPTY_FIX_OP = "empty_fix"                   # 直す物の無い周に機械が p3.fix の空の返答を渡した印の trace の行（T10b が書く。TA6）
EMPTY_FIX_BY = "works:empty-fix"
JUDGE_BRIDGE_BY = "works:judge-bridge"       # 判定のブロックの出口を盤面が受けなかった時の state.stop.by（h-plan）
ADAPTER_BY = "works:adapter"                 # 包みが通っていない run を止めた state.stop.by（h-judge。blk-ci の柵と同じ名）
PREMISES_BY = "works:premises"               # 前提の実測が盤面に無い・盤面が受けない時の state.stop.by（h-judge）
PREMISES_NODE = "p0.premises"
ADAPTER_HINT = ("Archon の設定 assistants.claude.claudeBinaryPath に包み（works/.shared/core/claude-adapter）の絶対パスを書くか、"
                "包み無しで回すなら入力 adapter に optional を渡す（works/README.md の包みの節）")
JUDGED_FILE = "judged.json"                  # h-plan が受けた判定のブロックの出口の控え（b.work。後ろの境の節が運ぶ。M4）
GATE_FILE = "gate.md"                        # policy-gate の文（b.work）
EMPTY = {"ok": True, "stop": False, "go": False, "ask": False, "gate_text": "", "judgment_file": "", "open_units": "",
         "plan_file": "", "notes": "", "why": "", "premises_file": "",
         "pr_go": False, "premises_go": False, "purpose_go": False, "spec_go": False,
         "runtime_go": False, "holdout_go": False, "mid_note": ""}


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
    try:
        lines = (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("op") == op and all(row.get(k) == v for k, v in kw.items()):
            return True
    return False


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


def _fixed_by_role(b) -> bool:
    """今の周の p3.fix を役が出した（done で、今の周の出力が在り、機械の空の返答の印が無い）"""
    info = b.state["outputs"].get("p3.fix")
    return (b.node_state("p3.fix") == "done" and bool(info) and info.get("round") == b.round
            and not _traced(b, EMPTY_FIX_OP, by=EMPTY_FIX_BY, round=b.round))


def _tests_head(b, tests) -> str:
    """最後のテストの頭の語: 緑・赤・走れなかった・走らなかった（出口が無い）。任せ先の CI の役が走らせた回（by role_needed）は、
    盤面の p4.ci が済んでいれば素材 materials.local_checks の status（blk-tests の final と同じ読み）"""
    if tests is None:
        return "走らなかった"
    if tests.get("by") == "role_needed":
        if b.node_state("p4.ci") != "done":
            return "走れなかった"
        green = ((b.record.get("materials") or {}).get("local_checks") or {}).get("status") == "clean"
        return "緑" if green else "赤"
    if tests.get("ok") is not True:
        return "走れなかった"
    return "緑" if tests.get("green") is True else "赤"


def _faces(b, nid: str) -> int:
    out = b.output_of_round(nid, b.round) or {}
    return len(out.get("faces") or [])


def _final_text(b, head: str, tests, objection: str, repo, run_id: str) -> str:
    """最後の関所の文: 最後のテスト・差分の審査の穴の数・手直しの結果・止めずに残った異議・盤面の問いを 1 枚に"""
    tests = tests or {}
    lines = [f"最後の人の関所（最後のテストの後・独立の目の前）: テストは{head}", "",
             f"- ログ: {tests.get('log') or '（無い）'}"]
    if tests.get("reason"):
        lines.append(f"- 走れなかった理由: {tests['reason']}")
    lines.append(f"- run の作業ツリー: {pathlib.Path(repo).resolve()}")
    lines.append(f"- 差分の審査の穴: {_faces(b, 'p3.delta_review')} 件（2 回目の審査: {_faces(b, 'p3.delta_review2')} 件）")
    handled = (b.output_of_round("p3.delta_fix", b.round) or {}).get("handled") or []
    lines.append(f"- 手直し（p3.delta_fix・{len(handled)} 件）:")
    lines += [f"  - {h.get('key')}: {h.get('handled')}（{h.get('how')}）" for h in handled if isinstance(h, dict)] or ["  - （無い）"]
    lines.append(f"- 止めずに残った異議: {objection or '無い'}")
    asking = b.state.get("pending_human")
    if asking:
        lines.append(f"- 盤面の問い（{asking.get('node')}）: {asking.get('question')}")
        lines += [f"  - {x}" for x in asking.get("items") or []]
    else:
        lines.append("- 盤面の問い: 無い")
    lines += ["", "答え方（approve は continue と、reject は stop と同じ）:",
              f'- 独立の目へ進める: archon workflow respond {run_id} continue "<一言>"',
              f'- 止める: archon workflow respond {run_id} stop "<理由>"'
              f'（archon workflow reject {run_id} --reason "<理由>" でも止まる。報告は出る）']
    return "\n".join(lines) + "\n"


def entry_edge(b) -> dict:
    """h-entry（start の後・判定の前）: 盤面の ready から、任せ先の役・ブロックを回すかの旗。判定から入る run と仕様から入る run の
    両方で、pr-checking・premising・purposing の when: はこの欄だけを読む"""
    ready = b.ready()
    return {"go": True, "pr_go": "p0.parallel_pr" in ready, "premises_go": PREMISES_NODE in ready,
            "purpose_go": "p0.purpose" in ready, "spec_go": any(n.startswith("spec.") for n in ready)}


def final_edge(b, repo, *, run_id: str, mode: str, tests) -> dict:
    """h-final（最後のテストの後）: ask は final_gate always か、when_needed で最後のテストが緑でない（赤・走れなかった・
    走らなかった）・盤面が人に聞いている・止めずに残った異議が在る時。文は b.work(FINAL_GATE_FILE) にも"""
    head = _tests_head(b, tests)
    left = rejudge.unsettled(b)
    objection = "" if left["settled"] else left["text"]
    need = head != "緑" or bool(b.state.get("pending_human")) or bool(objection)
    if mode == "when_needed" and not need:
        return {}
    text = _final_text(b, head, tests, objection, repo, run_id)
    _write_text(b.work(FINAL_GATE_FILE), text)
    return {"ask": True, "gate_text": text}


def _done_this_round(b, nid: str) -> bool:
    info = b.state["outputs"].get(nid)
    return b.node_state(nid) == "done" and bool(info) and info.get("round") == b.round


def _hand(b, board_dir, nid: str, reply: dict, repo) -> dict:
    """機械が役の返答を盤面へ渡す（判定のブロックが受けた判定・直す物が無い周の空の修正）。待っている試行に起こした印を置いてから
    entry.take（盤面の決まり 2）。待っている instance が無ければ BoardGap（線の順の誤り）"""
    inst = next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)
    if inst is None:
        raise _gap(f"{nid} が盤面で待っていない（線の順の誤り。state: {b.node_state(nid)}）")
    b.mark_launched(nid, inst.get("attempts", 1))
    return entry.take(board_dir, nid, reply, repo)


def _judgment(judged) -> tuple:
    """判定のブロックの出口から (判定の返答, 読めない理由)。読めれば理由は空"""
    path = judged.get("judgment_file") if isinstance(judged, dict) else None
    if not isinstance(path, str) or not path:
        return None, "判定のブロックの出口（judgment_file）が届かない"
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"判定のファイル {path} が読めない（{type(e).__name__}: {e}）"
    if not isinstance(doc, dict):
        return None, f"判定のファイル {path} が JSON のオブジェクトでない（{type(doc).__name__}）"
    return doc, ""


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
       optional でなければ b.stop("包みが通っていない: …", by=ADAPTER_BY) で stop
    2. 表で p0.premises が role なのに盤面で今の周に済んでいなければ、前提のブロックの出口 premised の constraints_file を読んで
       entry.take(p0.premises)（起こした印を置いてから。盤面の写しの schema・measured_needs_output・writes が当たる）。
       出口が届かない・読めない・盤面が受けないなら b.stop("前提の実測が盤面に無い: …", by=PREMISES_BY) で stop。
       済んでいれば渡さない（Archon の再開で呼び直しても同じ）
    3. go True・premises_file は盤面の state.outputs["p0.premises"] の置き場（絶対パス。na・表に無い節なら空）"""
    board_dir = pathlib.Path(board_dir)
    if adapter_mode != "optional":
        seen = reads.adapter_seen(board_dir, run_id, repo=repo)
        if not seen["seen"]:
            reason = f"包みが通っていない: {'・'.join(seen['whys'])}。{ADAPTER_HINT}"
            b.stop(reason, by=ADAPTER_BY)
            return {"stop": True, "go": False, "why": reason}
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
    return {"go": True, "premises_file": _out_file(b, PREMISES_NODE)}


def plan_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, judged) -> dict:
    """h-plan の固有の仕事（edge の手順 5。計画 P1 Task 23・裁定 TA3・TA6）。包みの確かめはここに置かない（h-judge。P1-R9）。順:
    1. judged（判定のブロックの出口）を b.work(JUDGED_FILE) に控える（後ろの境の節が judgment_file・open_units を返す。M4）
    2. 盤面の p2.diagnose が今の周に済んでいなければ、judged の judgment_file を読んで entry.take(p2.diagnose)。出口が届かない・
       読めない・盤面が受けない（ok False）なら b.stop("盤面が判定を受けない: …", by=JUDGE_BRIDGE_BY) で stop。済んでいれば
       渡さない（Archon の再開・盤面で判定を受けた後も同じ）
    3. p2.fix_plan が ready なら go。p3.fix が ready で p2.fix_plan が na（直す物が無い周）なら、機械が空の返答
       （entry.empty_fix_reply）を渡して trace_empty_fix、go False"""
    if judged is not None:
        _write_json(b.work(JUDGED_FILE), judged)
    carried = _carried(b)
    if not _done_this_round(b, "p2.diagnose"):
        reply, why = _judgment(judged)
        if not why:
            got = _hand(b, board_dir, "p2.diagnose", reply, repo)
            why = "" if got["ok"] else got["reason"]
        if why:
            reason = f"盤面が判定を受けない: {why}"
            entry.open_board(pathlib.Path(board_dir)).stop(reason, by=JUDGE_BRIDGE_BY)
            return {"stop": True, "go": False, "why": reason, **carried}
        b = entry.open_board(pathlib.Path(board_dir))
    ready = b.ready()
    if GO_NODE["plan"] in ready:
        return {"go": True, **carried}
    if GO_NODE["fix"] in ready and b.node_state("p2.fix_plan") == "na":
        got = _hand(b, board_dir, GO_NODE["fix"], entry.empty_fix_reply(), repo)
        if not got["ok"]:
            raise _gap(f"盤面が直す物の無い周の空の修正を受けない: {got['reason']}")
        trace_empty_fix(entry.open_board(pathlib.Path(board_dir)))
    return {"go": False, **carried}


def edge(board_dir, at: str, repo, *, run_id: str, adapter_mode: str, final_gate: str, judged: dict | None = None,
         gate: dict | None = None, tests: dict | None = None, premised: dict | None = None) -> dict:
    """境の節（計画 Task 10a。並びは C18 の順・計画 P1 Task 26）。返りは EMPTY の欄の全部（使わない欄は空の値。judgment_file・
    open_units はどの at でも h-plan の控え b.work(JUDGED_FILE) から）。盤面を開くのは 1 回（渡し替えの後は開き直す）。順:
    1. 盤面を allow_halted で開く。もう止まっている（halted・state.stop）なら、止め札の理由は trace にだけ書いて stop（M3）。
       ただし at final・eyes は、1 周の run が周を締めた盤面（halted.by stop_after_round。最後のテストの後の普通の終わり）を
       止めたと読まない
    2. at fix の gate（policy-gate の出口。None は開かなかった）: approve・continue は b.answer("continue", 一言)、
       stop・reject は b.answer("stop", 一言 か GATE_STOP_NOTE)（盤面は halted.by == "answer"）
    3. at eyes の gate（final-gate の出口）: どの答えも b.work(FINAL_GATE_ANSWER) に {decision, text} と human_items に 1 行。
       stop・reject は b.stop(一言 か FINAL_GATE_STOP_NOTE, by=FINAL_GATE_BY)——周を締めた盤面では b.stop が拒むので、
       trace に STOP_AFTER_END_OP の 1 行（by FINAL_GATE_BY）を書いて stop
    4. 2・3 で止まったら止め札は trace にだけ（関所の答えが先）。止まっていなければ、止め札（seen）が在れば
       b.stop(理由, by="request:<札の by>")（周を締めた盤面では trace の 1 行）して stop
    5. entry: 盤面の ready から pr_go・premises_go・purpose_go・spec_go（go True）。judge: judge_edge。plan: plan_edge。
       gate: 盤面の問い（pending_human）が在れば ask と plan.gate_text の文（b.work(GATE_FILE) にも）。
       fix: go は p3.fix が ready・notes は今の周の human_items の一言・plan_file は今の周の p2.fix_plan の出力。
       rejudge・eyes: 枠（go False）。mid: go は今の周の p3.fix を役が出した（機械の空の返答は trace の by works:empty-fix で
       見分ける）・runtime_go・holdout_go は False・mid_note。review・refix・tests: go は p3.delta_review・p3.delta_fix・p4.ci が ready。
       final: final_edge（final_gate と最後のテストの出口 tests から ask と文）。
    ready は DiskBoard.ready（書かない。開き直した盤面でも explicit の機械の節を落とさない）。
    配線の誤り（知らない at・場違いの入力・形の崩れ・知らない final_gate・adapter）は BoardGap"""
    mode = _check_args(at, final_gate=final_gate, judged=judged, gate=gate, tests=tests, premised=premised,
                       adapter_mode=adapter_mode)
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {**EMPTY, **_carried(b)}
    flag = halt.seen(board_dir)
    if _stopped(b) and not (at in ENDED_AT and _ended(b)):
        return _halted_out(b, out, flag, at)
    if gate is not None:
        if at == "fix":
            _answer_policy_gate(b, gate)
            if _stopped(b):
                return _halted_out(b, out, flag, at)
        else:
            stop, reason = _answer_final_gate(b, gate)
            if stop:
                _stop_board(b, at, reason, FINAL_GATE_BY)
                if flag:
                    b.trace(AFTER_HALT_OP, at=at, reason=flag["reason"], by=flag["by"])
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
        return {**out, "ask": True, "gate_text": text}
    if at == "fix":
        return {**out, "go": GO_NODE["fix"] in b.ready(), "notes": _notes(b), "plan_file": _out_file(b, "p2.fix_plan")}
    if at in ("rejudge", "eyes"):
        return out
    if at == "mid":
        return {**out, "go": _fixed_by_role(b), "mid_note": MID_NOTE}
    if at == "final":
        return {**out, **final_edge(b, repo, run_id=run_id, mode=mode, tests=tests)}
    return {**out, "go": GO_NODE[at] in b.ready()}
