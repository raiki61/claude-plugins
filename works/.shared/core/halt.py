"""外から止める口（線 A の仕様 5.3）と境の節（仕様 2 節・計画 Task 10a）。止め札の部分は標準ライブラリと写しの engine.util だけ
（dev/stop.sh が軽く読む）。境の節は盤面を開くので entry・plan を呼ぶ時にだけ読む。

止め札は盤面の STOP（{reason, by, at} の JSON）。置くのは dev/stop.sh（人）で、見るのは境の節。見た境の節は盤面の
DiskBoard.stop(理由, by) を呼び、後ろの段を飛ばして report を必ず走らせる（a2695cf の cmd_stop と同じ意味: 理由は必須・
記録に残す・報告は出す・下流だけを走らせない）。走っている AI の節とブロックの中の出し直しの輪は次の境まで走りきる（試し P12）。

- place(board_dir, reason, by): 止め札を置く。最初の理由が正で、2 度目からは上書きせず trace にだけ積む
- seen(board_dir): 止め札の中身（無ければ None）。在れば必ず空でない reason と by を持つ
- over(board_dir): 盤面がもう止まった・終わったなら、その文（cmd_stop の refuse_if_over と同じ判定）。まだなら None
- edge(board_dir, at, repo, …): 境の節（darkfactory/scripts/edge.py の中身）。止め札・関所の答え・次のブロックを盤面から決める
- plan_edge(b, …): h-plan の固有の仕事（この版は判定の出口の控えと go だけ。Task 10b が足す）
- trace_empty_fix(b): 直す物の無い周に機械が p3.fix の空の返答を渡した印（at mid が役の修正と見分ける）
"""
import json
import os
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.util import TERMINAL_STATUS, now  # noqa: E402

STOP_FILE = "STOP"
TRACE_OP = "stop_flag"
HAND_PLACED_BY = "hand-placed"   # by の無い STOP（人が手で置いた等）の by。DiskBoard.stop は空の by を BoardGap にする


def _trace(board: pathlib.Path, **kw) -> None:
    """盤面の trace.jsonl に 1 行足す（DiskBoard.trace と同じ行の形 {t, op, …}）"""
    with open(board / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": TRACE_OP, **kw}, ensure_ascii=False) + "\n")


def place(board_dir, reason: str, by: str) -> dict:
    """止め札を置く。理由が空・空白だけなら書かずに {ok: False, reason: "理由が要る"}（by が空も同じく書かない）。
    STOP が無ければ {reason, by, at} を一時ファイルに書いてから STOP の名で出し {ok: True, first: True}。
    既に在れば上書きせず {ok: True, first: False}。どちらも trace に 1 行（op stop_flag・reason・by・first）。

    一時ファイルから出すのに os.replace でなく os.link を使う（裁定 R43）: link は「無ければ作る」を 1 手で行うので、
    2 人が同時に置いても後の方が先の理由を上書きしない（最初の理由が正）。読む側からは replace と同じく、
    STOP は無いか中身が全部在るかのどちらか。

    正は STOP で、trace は控え。STOP を出した後に trace へ積めなければ、置いたことは変わらないので
    {ok: True, first: True, warning: 文} を返す。2 度目で trace に積めなければ何も残っていないので {ok: False, reason: 文}"""
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        return {"ok": False, "reason": "理由が要る"}
    by = by.strip() if isinstance(by, str) else ""
    if not by:
        return {"ok": False, "reason": "止めた人（by）が要る"}
    board = pathlib.Path(board_dir)
    fd, tmp = tempfile.mkstemp(dir=board, prefix=f".{STOP_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"reason": reason, "by": by, "at": now()}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        try:
            os.link(tmp, board / STOP_FILE)
            first = True
        except FileExistsError:
            first = False
    finally:
        os.unlink(tmp)
    try:
        _trace(board, reason=reason, by=by, first=first)
    except OSError as e:
        why = f"盤面の trace.jsonl に積めない（{e}）"
        if not first:
            return {"ok": False, "reason": f"止め札は既に在り、今の理由は {why}"}
        return {"ok": True, "first": True, "warning": f"止め札は置いた。{why}"}
    return {"ok": True, "first": first}


def seen(board_dir):
    """STOP の中身 {reason, by, at}。無ければ None。例外を上げない。
    在るのに読めない（JSON でない・UTF-8 でない・ディレクトリ・権限が無い等）・理由が無いなら、読めない旨を理由にした dict
    （unreadable: True）を返す——STOP を置いた人の意図は止めることなので、読めないからといって走り続けない。
    by が無い・空なら HAND_PLACED_BY（境の節がそのまま DiskBoard.stop に渡せるように）"""
    path = pathlib.Path(board_dir) / STOP_FILE
    doc = None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        why = f"ファイルとして読めない（{type(e).__name__}: {e}）"
    else:
        try:
            doc = json.loads(text)
            why = None if isinstance(doc, dict) else "JSON のオブジェクトでない"
        except ValueError as e:
            why = f"JSON として読めない（{e}）"
        if why is None and not (isinstance(doc.get("reason"), str) and doc["reason"].strip()):
            why = "理由（reason）が無い"
    by = doc.get("by") if isinstance(doc, dict) else None
    by = by.strip() if isinstance(by, str) and by.strip() else HAND_PLACED_BY
    if why:
        return {"reason": f"止め札 {path} が読めない: {why}", "by": by, "at": None, "unreadable": True}
    return {"reason": doc["reason"].strip(), "by": by, "at": doc.get("at")}


def over(board_dir):
    """盤面がもう止まった（halted）・終わった（status が engine の TERMINAL_STATUS）なら、止め札を置いても効かないので
    その文を返す（a2695cf の cmd_stop の refuse_if_over と同じ判定と文）。まだ・state.json が無い・読めないなら None
    （読めない盤面でも札は害を持たないので、置く側を止めない）"""
    try:
        state = json.loads((pathlib.Path(board_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    if state.get("halted"):
        h = state["halted"]
        return f"もう止まっている（halted: {h.get('by') if isinstance(h, dict) else h}）——止める物が無い"
    if state.get("status") in TERMINAL_STATUS:
        return f"run は既に {state['status']}——止める物が無い"
    return None


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
JUDGED_FILE = "judged.json"                  # h-plan が受けた判定のブロックの出口の控え（b.work。後ろの境の節が運ぶ。M4）
GATE_FILE = "gate.md"                        # policy-gate の文（b.work）
MID_GATE_FILE = "mid-gate.md"                # mid-gate の文（b.work）
MID_GATE_ANSWER = "mid-gate-answer.json"     # mid-gate の continue・approve の答え {decision, text}（b.work）
EMPTY = {"ok": True, "stop": False, "go": False, "ask": False, "gate_text": "", "judgment_file": "", "open_units": "",
         "plan_file": "", "notes": "", "why": ""}


def _gap(msg):
    from board import BoardGap
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
    from entry import MID_GATES
    mode = (mid_gate or "").strip() or MID_GATES[0]
    if mode not in MID_GATES:
        raise _gap(f"mid_gate={mid_gate!r} は知らない値（{' / '.join(MID_GATES)}）")
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


def plan_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, judged) -> dict:
    """h-plan の固有の仕事（edge の手順 5）。この版は判定の出口の控え（M4）と「p2.fix_plan が ready なら go」だけ。
    包みの確かめ・判定の渡し替え・直す物が無い周の締めは計画 Task 10b が足す"""
    if judged is not None:
        _write_json(b.work(JUDGED_FILE), judged)
    return {"go": GO_NODE["plan"] in b.ready(), **_carried(b)}


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
    import entry
    import plan
    mode = _check_args(at, mid_gate=mid_gate, judged=judged, gate=gate, mid=mid)
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {**EMPTY, **_carried(b)}
    flag = seen(board_dir)
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
