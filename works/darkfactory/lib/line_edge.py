"""境の節の中身（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4）。ライン darkfactory の模块（層 L6。裁定 R59）で、
使うのは darkfactory/scripts/edge.py だけ。止め札そのもの（置く・読む）は共有の .shared/core/halt.py。

- edge(board_dir, at, repo, …): 境の節（darkfactory/scripts/edge.py の中身）。止め札・関所の答え・次のブロックを盤面から決める
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

# ---------------------------------------------------------------- 境の節（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4）
# いつも走る script の節 1 本（darkfactory/scripts/edge.py）を、ラインの中で at を替えて使う。並びはラインの順
# （T22 が "judge"、T23 が "rejudge" を足す）。when: と関所の文は境の節の欄だけを読み、go は盤面の ready から決める（TA1）
AT = ("plan", "gate", "fix", "mid", "midgate", "review", "refix", "tests")
GO_NODE = {"plan": "p2.fix_plan", "fix": "p3.fix", "review": "p3.delta_review", "refix": "p3.delta_fix", "tests": "p4.ci"}
GATE_AT = ("fix", "review")          # 関所の答えを受ける境の節（fix は policy-gate、review は mid-gate）
GATE_GO = ("approve", "continue")    # approve は continue と、reject は stop と同じ（台帳 R32）
GATE_STOP = ("stop", "reject")
GATE_STOP_NOTE = "関所で止めた"              # policy-gate の stop・reject に一言が無い時の理由
MID_GATE_STOP_NOTE = "中の関所で止めた"      # mid-gate の同じ
MID_GATE_BY = "human:mid-gate"               # mid-gate の stop・reject で止めた盤面の state.stop.by（報告の stopped_by_human）
FLAG_BY_PREFIX = "request:"                  # 止め札で止めた盤面の state.stop.by は "request:<札の by>"（報告の stopped_by_request）
FLAG_SEEN_OP = "stop_flag_seen"              # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
AFTER_HALT_OP = "stop_flag_after_halt"       # 止まった後に見た止め札の trace の行（b.stop は呼ばない。M3）
EMPTY_FIX_OP = "empty_fix"                   # 直す物の無い周に機械が p3.fix の空の返答を渡した印の trace の行（T10b が書く。TA6）
EMPTY_FIX_BY = "works:empty-fix"
JUDGE_BRIDGE_BY = "works:judge-bridge"       # 判定のブロックの出口を盤面が受けなかった時の state.stop.by（h-plan）
JUDGED_FILE = "judged.json"                  # h-plan が受けた判定のブロックの出口の控え（b.work。後ろの境の節が運ぶ。M4）
GATE_FILE = "gate.md"                        # policy-gate の文（b.work）
MID_GATE_FILE = "mid-gate.md"                # mid-gate の文（b.work）
MID_GATE_ANSWER = "mid-gate-answer.json"     # mid-gate の continue・approve の答え {decision, text}（b.work）
EMPTY = {"ok": True, "stop": False, "go": False, "ask": False, "gate_text": "", "judgment_file": "", "open_units": "",
         "plan_file": "", "notes": "", "why": ""}


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


def _check_args(at, *, mid_gate, judged, gate, mid) -> str:
    """配線の誤り（知らない at・場違いの入力・形の崩れ）を BoardGap にし、mid_gate の語（空は既定の always）を返す"""
    if at not in AT:
        raise _gap(f"境の節の at {at!r} を知らない（{' / '.join(AT)}）")
    if gate is not None:
        if at not in GATE_AT:
            raise _gap(f"関所の答え（gate）を受けるのは at {' / '.join(GATE_AT)} だけ（at {at}）")
        _gate_words(gate)
    if mid is not None and (at != "midgate" or not isinstance(mid, dict)):
        raise _gap(f"中のテストの出口（mid）を受けるのは at midgate の JSON のオブジェクトだけ（at {at}・{type(mid).__name__}）")
    if judged is not None and (at != "plan" or not isinstance(judged, dict)):
        raise _gap(f"判定の出口（judged）を受けるのは at plan の JSON のオブジェクトだけ（at {at}・{type(judged).__name__}）")
    mode = (mid_gate or "").strip() or entry.MID_GATES[0]
    if mode not in entry.MID_GATES:
        raise _gap(f"mid_gate={mid_gate!r} は知らない値（{' / '.join(entry.MID_GATES)}）")
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


def _answer_mid_gate(b, gate: dict) -> None:
    """mid-gate（Archon だけの関所。盤面の問いでない）の答え: stop・reject は b.stop（by human:mid-gate）、
    continue・approve は b.work(MID_GATE_ANSWER) に {decision, text}"""
    decision, text = _gate_words(gate)
    if decision in GATE_STOP:
        b.stop(text if text.strip() else MID_GATE_STOP_NOTE, by=MID_GATE_BY)
    else:
        _write_json(b.work(MID_GATE_ANSWER), {"decision": decision, "text": text})


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


def _mid_gate_text(b, mid: dict, repo, run_id: str) -> str:
    ok, green = mid.get("ok") is True, mid.get("green") is True
    head = "緑" if ok and green else "赤" if ok else "走れなかった"
    lines = [f"中の関所（修正の後のテスト・審査の前）: テストは{head}", "",
             f"- ログ: {mid.get('log') or '（無い）'}"]
    if mid.get("reason"):
        lines.append(f"- 走れなかった理由: {mid['reason']}")
    lines.append(f"- run の作業ツリー: {pathlib.Path(repo).resolve()}")
    fix = b.output_of_round("p3.fix", b.round) or {}
    lines.append(f"- 修正の要約（p3.fix・{len(fix.get('changes') or [])} 件）:")
    lines += [f"  - {c.get('unit_key')}: {c.get('what')}（{'・'.join(map(str, c.get('files') or []))}）"
              for c in fix.get("changes") or [] if isinstance(c, dict)] or ["  - （修正の出力が無い）"]
    lines += ["", "答え方（approve は continue と、reject は stop と同じ）:",
              f'- 審査へ進める: archon workflow respond {run_id} continue "<一言>"',
              f'- 止める: archon workflow respond {run_id} stop "<理由>"'
              f'（archon workflow reject {run_id} --reason "<理由>" でも止まる。報告は出る）']
    return "\n".join(lines) + "\n"


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


def edge(board_dir, at: str, repo, *, run_id: str, adapter_mode: str, mid_gate: str, judged: dict | None = None,
         gate: dict | None = None, mid: dict | None = None) -> dict:
    """境の節（計画 Task 10a）。返り {ok, stop, go, ask, gate_text, judgment_file, open_units, plan_file, notes, why}（使わない欄は
    空の値。judgment_file・open_units はどの at でも h-plan の控え b.work(JUDGED_FILE) から）。盤面を開くのは 1 回。順:
    1. 盤面を allow_halted で開く。もう止まっている（halted・state.stop）なら、止め札の理由は trace にだけ書いて stop（M3）
    2. at fix の gate（policy-gate の出口。None は開かなかった）: approve・continue は b.answer("continue", 一言)、
       stop・reject は b.answer("stop", 一言 か GATE_STOP_NOTE)（盤面は halted.by == "answer"）
    3. at review の gate（mid-gate の出口）: stop・reject は b.stop(一言 か MID_GATE_STOP_NOTE, by=MID_GATE_BY)、
       continue・approve は b.work(MID_GATE_ANSWER) に {decision, text}
    4. 2・3 で止まったら止め札は trace にだけ（関所の答えが先）。止まっていなければ、止め札（seen）が在れば
       b.stop(理由, by="request:<札の by>") して stop
    5. plan: plan_edge。gate: 盤面の問い（pending_human）が在れば ask と plan.gate_text の文（b.work(GATE_FILE) にも）。
       fix: go は p3.fix が ready・notes は今の周の human_items の一言・plan_file は今の周の p2.fix_plan の出力。
       mid: go は今の周の p3.fix を役が出した（機械の空の返答は trace の by works:empty-fix で見分ける）。
       midgate: mid（None なら開かない）について ask は mid_gate always か、when_needed で緑でないか走れなかった時。
       文は b.work(MID_GATE_FILE) にも。review・refix・tests: go は p3.delta_review・p3.delta_fix・p4.ci が ready。
    ready は DiskBoard.ready（書かない。開き直した盤面でも explicit の機械の節を落とさない）。
    配線の誤り（知らない at・場違いの入力・形の崩れ・知らない mid_gate）は BoardGap"""
    mode = _check_args(at, mid_gate=mid_gate, judged=judged, gate=gate, mid=mid)
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {**EMPTY, **_carried(b)}
    flag = halt.seen(board_dir)
    if _stopped(b):
        return _halted_out(b, out, flag, at)
    if gate is not None:
        (_answer_policy_gate if at == "fix" else _answer_mid_gate)(b, gate)
        if _stopped(b):
            return _halted_out(b, out, flag, at)
    if flag:
        b.trace(FLAG_SEEN_OP, at=at, reason=flag["reason"], by=flag["by"])
        b.stop(flag["reason"], by=FLAG_BY_PREFIX + flag["by"])
        return {**out, "stop": True, "why": flag["reason"]}
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
    if at == "mid":
        return {**out, "go": _fixed_by_role(b)}
    if at == "midgate":
        if mid is None:
            return out
        if mode == "when_needed" and mid.get("ok") is True and mid.get("green") is True:
            return out
        text = _mid_gate_text(b, mid, repo, run_id)
        _write_text(b.work(MID_GATE_FILE), text)
        return {**out, "ask": True, "gate_text": text}
    return {**out, "go": GO_NODE[at] in b.ready()}
