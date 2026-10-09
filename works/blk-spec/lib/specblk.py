"""仕様を固めるブロック（blk-spec。本線 ops/blocks/BLOCKS.md の R2「仕様を固める」、差し込み口 spec）の芯。

仕様の道は run の入力 flow=spec が選ぶ（写しの rules の check_inputs・on_init が loop.flow に写し、spec.* の節の条件 spec_flow が
読む。正本は写しの graph a1202d0。本線は review-loop-spec.json へ移す作業を止めている）。節は写しの graph のまま:
- spec.write（writer）→ spec.review（judge。書いた目と別。読むだけ）→ spec.revise（writer。審査が穴を挙げた時だけ。写しの条件
  spec_revise_due）→ spec.approve（機械。周の途中の問い）→ spec.freeze（機械。承認の後に受け入れ条件の run を走らせて記録に固める）
- 受け付けの検査（schema・post_check の spec_write_output・spec_review_output・spec_revise_output）・問いの文（spec_approve）・
  固める中身（spec_freeze）・答えの記録（on_answer_in_round）は全部写しの rules の物を盤面（entry.open_board）越しに呼ぶ。
  ここは写さない・足さない

人の関所は線 A の policy-gate と同じ仕組みを使う（新しい関所の仕組みを作らない）:
- 文: 線 A の関所の境の節（at gate）と同じ手順。止め札（halt.seen）を見て、盤面の問い（pending_human）を関所の文（gate_text）にし、
  ブロックの置き場の r<N>/spec-gate.md にも置く。境の節の中身はライン darkfactory の模块（層 L6）に移ったので、ブロック（層 L4）からは呼べない。
  関所の語・止め札の by・文の組み方はここに写して持つ（写しの印「線 A の境の節の写し」。core の関所の模块へ 1 つにまとめるのは
  統合の計画 Task 10）
- 答え: Archon の approval（decisions: approve・continue・stop・reject。GATE_GO・GATE_STOP。線 A の境の節と同じ語）の出口を次の
  script の節が with: で受け、盤面の answer に渡す（approve・continue は continue、stop・reject は stop。境の節の policy-gate と
  同じ当て方）。
  continue の後の settle で spec.freeze が走る

口:
- route:    役の輪の前。盤面が止まっていれば go false。止め札が在れば盤面を止めて go false（線 A の境の節と同じ by）。
            書く役の route は、spec.write が na（flow=spec の無い run）・待ちなのに ready でない（依存の CI が済んでいない）なら
            BoardGap（配線の誤り）。返り {go, node, why}
- prep:     指示書を engine と同じ描き方（rolekit.render_body。reads・schema の足し書き）で描き、この節の拒否が在れば最後の拒否の文を頭に
            （$LOOP_PREV で貼らない。R44）。読むだけの役（審査）は 1 回目の前だけ作業ツリーの写しを置く。起こした印を置く
- take:     読むだけの役は作業ツリーを写しと比べる → 盤面の done。拒否は spec-rejects.json に積み、GIVE_UP_AFTER 回目で done・give_up
- refuse:   読めない返答を拒否として数える
- ask:      境の節の at gate と同じ手順（止め札 → 盤面の問い → 文）。問いが spec.approve 以外なら BoardGap（このブロックは
            他の節の問いに答えない）
- answer:   関所の出口を盤面に渡す。問いが無い（再開で呼び直した）なら 2 度答えない
- collect:  出口 {ok, reason, spec_file, tests: [{file, sha}], approved_by, approval_note, frozen_rev, requirements, acceptance,
            faces, handled}。固まっていなければ、止まった理由（人の stop・止め札）か最後の拒否の文で盤面を止めて ok false
- script_main: スクリプトの入口（rolekit.script_main。環境変数の欠け・BoardGap・写しの Reject は終了コード 2）
"""
import json
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True

BLK = pathlib.Path(__file__).resolve().parents[1]
CORE = BLK.parent / ".shared" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
import engine.util as _util  # noqa: E402
from engine.util import AnswerReject, Reject, now, safe_name  # noqa: E402
from accept import TREE_KEYS, role_schema, tree_moved, tree_state  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import halt  # noqa: E402  （止め札の seen だけ。境の節の中身はラインの模块）
import node_marker  # noqa: E402
import rolekit  # noqa: E402
import stopby  # noqa: E402  （L1。止めの理由の住処）

# 役の名（YAML の輪 <役>-loop・節 spec-<役>・包みの印 spec-<役>）→ 写しの graph の節
ROLES = {"write": "spec.write", "review": "spec.review", "revise": "spec.revise"}
READ_ONLY = frozenset({"review"})       # 読むだけの役（judge）。受け付けが作業ツリーの変化を拒む
APPROVE = "spec.approve"
FREEZE = "spec.freeze"
# 輪（loop_group）の max_iterations と同じ数（tests/test_blk_spec.py が YAML と突き合わせる）。この数だけ拒んだら done・give_up を出し、
# 輪を max_iterations で落とさずに collect へ渡す（R50）
GIVE_UP_AFTER = 3
STOP_BY = stopby.declare("spec", "仕様の輪が諦めた・固まらなかった")   # collect が盤面を止める by
GATE_BY = "human:spec-gate"             # 出口の approved_by（人が関所 spec-gate で承認した。境の節の MID_GATE_BY と同じ名づけ）
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
REJECTS = "spec-rejects.json"           # 今の周の作業ファイル（b.work）
SPEC_FILE = "spec.json"                 # 出口が書く record.process.spec の写し（b.work）
PROMPTS = BLK / "prompts"               # 本線 a1202d0 の指示書の写し（COPIED_FROM）
NULL = "null"                           # 飛ばされた節の出力（if_skipped: null）が届く字
RUN_ID_ENV = "WORKFLOW_ID"              # 関所の文の run の id（ラインの境の節と同じ）
# 線 A の境の節の写し（darkfactory/lib/line_edge.py・plan.py。層の決まりでブロックからは import できない。統合の計画 Task 10 で
# core の関所の模块へ 1 つにまとめる）
GATE_GO = ("approve", "continue")       # approve は continue と、reject は stop と同じ（台帳 R32）
GATE_STOP = ("stop", "reject")
GATE_STOP_NOTE = "関所で止めた"          # stop・reject に一言が無い時の理由
FLAG_BY_PREFIX = "request:"             # 止め札で止めた盤面の state.stop.by は "request:<札の by>"（報告の stopped_by_request）
FLAG_SEEN_OP = "stop_flag_seen"         # 止め札を見て止めた trace の行（op・at・reason・by）
GATE_FILE = "spec-gate.md"              # 関所の文（b.work。線の関所の文の公開の名 gate.md と分ける——線に include すると、公開の名は線の持ち物で、ブロックが書くと scope の照らしが盤面を止める）
RUN_ID_HOLE = "<id>"                    # run の id を知らない時の文の穴


def node_of(role: str) -> str:
    if role not in ROLES:
        raise BoardGap(f"役 {role!r} を知らない（{' / '.join(ROLES)}）——blk-spec の with: の role を確かめる")
    return ROLES[role]


def output_format(role: str) -> dict:
    """役の節の output_format: 写しの graph の schema（accept.role_schema）に印 works-node: spec-<役>"""
    return node_marker.mark(role_schema(node_of(role)), f"spec-{role}")


def snapshot_name(nid: str) -> str:
    return f"spec-snapshot-{safe_name(nid)}.json"


# ---------------------------------------------------------------- 盤面
def _open(board_dir, repo=None, *, allow_halted=False):
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=allow_halted)
    if repo is not None:
        _util.GIT_CWD = str(pathlib.Path(repo).resolve())   # 写しの rules の git（post_check のテストのファイルの読み）を対象に
    return b


def _write_json(path: pathlib.Path, obj) -> pathlib.Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_json(path: pathlib.Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _stopped(b):
    """盤面がもう止まっているなら止めた事実（state.stop か halted）。まだなら None（halt の境の節と同じ判定）"""
    st = b.state
    return (st.get("stop") or st.get("halted")) if (st.get("halted") or st.get("stop")) else None


def _pending(b, nid):
    inst = b.rd["instances"].get(nid)
    if not (inst and inst.get("status") == "pending"):
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い——route の go が真の時だけ輪を回す")
    return inst


# ---------------------------------------------------------------- route
def route(board_dir, role: str, repo) -> dict:
    """役の輪を回すか。盤面の ready だけで決める（works は順を持たない）"""
    nid = node_of(role)
    b = _open(board_dir, repo, allow_halted=True)
    stop = _stopped(b)
    if stop:
        return {"go": False, "node": nid, "why": f"盤面は止まっている（{stop.get('by')}: {stop.get('reason')}）"}
    flag = halt.seen(board_dir)
    if flag:
        b.trace(FLAG_SEEN_OP, at=f"spec-{role}", reason=flag["reason"], by=flag["by"])
        b.stop(flag["reason"], by=FLAG_BY_PREFIX + flag["by"])
        return {"go": False, "node": nid, "why": f"止め札で止めた: {flag['reason']}"}
    ready = b.ready()
    if nid in ready:
        return {"go": True, "node": nid, "why": f"{nid} が ready"}
    state = b.node_state(nid)
    first = ROLES["write"]
    if role == "write" and state == "na":
        raise BoardGap(f"{first} が na（{b.rd['na'].get(first)}）——仕様の道（flow=spec）を選んでいない run にこのブロックを差した")
    if role == "write" and state == "pending":
        raise BoardGap(f"{first} が待ちなのに ready でない（依存の p0.base・p0.local_checks が済んでいない）——ラインは修正前の CI の後に"
                       "このブロックを回す")
    why = f"{nid} は {state}" + (f"（na: {b.rd['na'].get(nid)}）" if state == "na" else "")
    return {"go": False, "node": nid, "why": why}


# ---------------------------------------------------------------- prep
def render(b, nid: str) -> pathlib.Path:
    """engine の emit_instance と同じ描き方（rolekit.render_body: ctx → pointers.snapshot → Renderer。cap なし。schema の足し書き）で、
    blk-spec/prompts/<節>.md を $B/prompts/r<N>/<節>.md に描く。描けない（reads に無い穴・盤面の欄の欠け）は BoardGap"""
    _pending(b, nid)
    prompt, _snap = rolekit.render_body(b, nid, template=(PROMPTS / f"{nid}.md").read_text(encoding="utf-8"))
    p = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(prompt, encoding="utf-8")
    return p


def prep(board_dir, role: str, repo) -> dict:
    """役を起こす前の支度。返り {prompt_file, attempt, out_path, node, already}（拒否の後の出し直しは同じ試行で already: true）"""
    nid = node_of(role)
    b = _open(board_dir, repo)
    inst = _pending(b, nid)
    path = render(b, nid)
    last = _rejects(b, nid)[-1:]
    if last:
        # 拒否の文は指示書のファイルに書く（役は Read で読む）。$LOOP_PREV で指示に貼ると、文の中の $<節>.output.<欄> を Archon が
        # 置き換え直して輪ごと落ちる（R44）
        path.write_text(f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                        f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n"
                        + path.read_text(encoding="utf-8"), encoding="utf-8")
    if role in READ_ONLY and not b.work(snapshot_name(nid)).is_file():
        _write_json(b.work(snapshot_name(nid)), tree_state(pathlib.Path(repo)))   # 役を起こす前の姿（R47。再開でも最初の姿を残す）
    m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid, "already": m["already"]}


# ---------------------------------------------------------------- accept
def _rejects(b, nid: str) -> list:
    return [r for r in _read_json(b.work(REJECTS), []) if r.get("node") == nid]


def _reject(b, nid: str, reason: str) -> dict:
    rows = _read_json(b.work(REJECTS), [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(b.work(REJECTS), rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "node": nid}


def take(board_dir, role: str, reply: dict, repo) -> dict:
    """役の返答を受け付ける。読むだけの役は作業ツリーを prep の写しと比べ（共通の accept.tree_moved。R47）、次に盤面の done
    （写しの schema → post_check → check_record → settle）。拒否は {ok: False, done, give_up, reason, node}（盤面の層のファイルは
    書かない）。ほかの Reject（止めた run など）・BoardGap は投げる。通れば {ok: True, done: True, give_up: False, reason: "", node}"""
    nid = node_of(role)
    b = _open(board_dir, repo)
    _pending(b, nid)
    if role in READ_ONLY:
        snap = _read_json(b.work(snapshot_name(nid)))
        if not (isinstance(snap, dict) and set(TREE_KEYS) <= set(snap)):
            raise BoardGap(f"{b.work(snapshot_name(nid))} が無い・形が違う——prep が先に走る（役を起こす前の作業ツリーと比べられない）")
        moved = tree_moved({k: snap[k] for k in TREE_KEYS}, pathlib.Path(repo))
        if moved:
            return _reject(b, nid, "読むだけの役が作業ツリーを変えた: 仕様の審査は読むだけの役で、作業ツリー・HEAD・枝・git が無視する"
                                   "ファイルを変えてはいけない（変えた物を元に戻せ）（" + "・".join(moved) + "）")
    try:
        b.done(nid, reply)
    except AnswerReject as e:
        return _reject(b, nid, str(e))
    return {"ok": True, "done": True, "give_up": False, "reason": "", "node": nid}


def refuse(board_dir, role: str, reason: str) -> dict:
    """返答を受け付けの前に拒む（読めない返答）。拒否の文は take の拒否と同じく数える"""
    nid = node_of(role)
    b = _open(board_dir)
    _pending(b, nid)
    return _reject(b, nid, reason)


parse_reply = rolekit.parse_reply   # 役の返答を dict に。読めなければ (None, 理由)


# ---------------------------------------------------------------- 関所（線 A の policy-gate と同じ仕組み）
def gate_text(asking: dict, *, run_id: str = RUN_ID_HOLE) -> str:
    """盤面の問い {node, kinds, question, items, …} を仕様の関所の文にする（線 A の修正前の関所と同じ組み立て gatemarks.gate_text。
    一言は run の記録の仕様の承認に残る）"""
    return gatemarks.gate_text(asking, run_id=run_id or RUN_ID_HOLE, node=APPROVE, record_name="process.spec.approval")


def ask(board_dir, repo, run_id: str) -> dict:
    """関所を開くか・文 {ask, stop, gate_text, why}。線 A の境の節の at gate と同じ手順: 盤面が止まっていれば stop・止め札が
    在れば盤面を止めて stop（by request:<札の by>）・盤面の問いが在れば文（b.work(GATE_FILE) にも置く）。
    盤面の問いが spec.approve 以外なら BoardGap"""
    b = _open(board_dir, repo, allow_halted=True)
    out = {"ask": False, "stop": False, "gate_text": "", "why": ""}
    stop = _stopped(b)
    if stop:
        return {**out, "stop": True, "why": str(stop.get("reason") or "")}
    ph = b.state.get("pending_human")
    if ph and ph.get("node") != APPROVE:
        raise BoardGap(f"盤面は {ph.get('node')} を聞いている——blk-spec は {APPROVE} の問いだけに関所を開く（ラインの順を確かめる）")
    flag = halt.seen(board_dir)
    if flag:
        b.trace(FLAG_SEEN_OP, at="spec-ask", reason=flag["reason"], by=flag["by"])
        b.stop(flag["reason"], by=FLAG_BY_PREFIX + flag["by"])
        return {**out, "stop": True, "why": flag["reason"]}
    if not ph:
        return out
    text = gate_text(ph, run_id=run_id)
    tmp = b.work(GATE_FILE).with_name(GATE_FILE + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, b.work(GATE_FILE))
    return {**out, "ask": True, "gate_text": text}


def parse_gate(raw: str):
    """関所の出口（with: の {from: $spec-gate.output, if_skipped: null}）を dict か None（開かなかった）に。形の誤りは BoardGap"""
    if raw.strip() in ("", NULL):
        return None
    try:
        gate = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BoardGap(f"関所の答えが JSON として読めない（{e}）: {raw[:200]!r}") from None
    if gate is None:
        return None
    if not isinstance(gate, dict):
        raise BoardGap(f"関所の答えが JSON のオブジェクトでない: {type(gate).__name__}")
    decision = gate.get("decision")
    if decision not in GATE_GO + GATE_STOP:
        raise BoardGap(f"関所の答えの語 {decision!r} を知らない（{' / '.join(GATE_GO + GATE_STOP)}）")
    text = gate.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise BoardGap(f"関所の一言が文字列でない: {type(text).__name__}")
    return {"decision": decision, "text": text}


def answer(board_dir, gate) -> dict:
    """関所の出口を盤面の answer に渡す（approve・continue は continue、stop・reject は stop。一言は字のまま）。
    返り {answered, decision, stop, why}。開かなかった（gate None）・問いがもう無い（再開で呼び直した）・盤面が止まっているなら
    答えない。continue の後の settle で spec.freeze が走る（承認の後に受け入れ条件の run を走らせる）"""
    b = _open(board_dir, allow_halted=True)
    stop = _stopped(b)
    if gate is None or stop:
        return {"answered": False, "decision": (gate or {}).get("decision", ""), "stop": bool(stop),
                "why": f"盤面は止まっている（{stop.get('by')}）" if stop else "関所は開かなかった"}
    ph = b.state.get("pending_human")
    if not ph:
        b.trace("gate_answer_unasked", at="spec", decision=gate["decision"])
        return {"answered": False, "decision": gate["decision"], "stop": False, "why": "盤面は何も聞いていない（答え済み）"}
    if ph.get("node") != APPROVE:
        raise BoardGap(f"盤面は {ph.get('node')} を聞いている——blk-spec の関所の答えは {APPROVE} にだけ渡す")
    if gate["decision"] in GATE_GO:
        b.answer("continue", gate["text"])
    else:
        b.answer("stop", gate["text"] if gate["text"].strip() else GATE_STOP_NOTE)
    stopped = bool(_stopped(b))
    return {"answered": True, "decision": gate["decision"], "stop": stopped, "why": ""}


# ---------------------------------------------------------------- collect
def _head(repo) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise Reject(f"git rev-parse HEAD が失敗した: {r.stderr.strip()[-300:]}")
    return r.stdout.strip()


def _counts(b) -> dict:
    rv = b.latest_output(ROLES["review"]) or {}
    rs = b.latest_output(ROLES["revise"]) or {}
    return {"faces": len(rv.get("faces") or []), "handled": len(rs.get("handled") or [])}


EMPTY = {"ok": False, "reason": "", "spec_file": "", "tests": [], "approved_by": "", "approval_note": "", "frozen_rev": "",
         "requirements": 0, "acceptance": 0, "faces": 0, "handled": 0}


def collect(board_dir, repo) -> dict:
    """ブロックの出口。固まった仕様（record.process.spec）を b.work(SPEC_FILE) に写し、テストの {file, sha}（ファイルごとに 1 行。
    sha は承認の時点の sha256。本文はテストのファイルが正本）・承認した人と一言・固めた版（HEAD。受け入れ条件のテストは未コミットで、
    同一性は sha で持つ）を出す。固まっていなければ ok false:
    - 盤面が止まっている（関所の stop・止め札）: 止めた理由
    - 役の返答が GIVE_UP_AFTER 回とも拒まれた: 最後の拒否の文で盤面を止める（by works:spec）
    - 他（輪が回らなかった）: その旨で盤面を止める"""
    b = _open(board_dir, repo, allow_halted=True)
    out = {**EMPTY, **_counts(b)}
    spec = (b.record.get("process") or {}).get("spec")
    if b.node_state(FREEZE) == "done" and isinstance(spec, dict):
        seen, tests = set(), []
        for a in spec.get("acceptance") or []:
            if a["file"] not in seen:
                seen.add(a["file"])
                tests.append({"file": a["file"], "sha": a.get("sha256")})
        path = _write_json(b.work(SPEC_FILE), spec)
        approval = spec.get("approval") or {}
        return {**out, "ok": True, "spec_file": str(path), "tests": tests, "approved_by": GATE_BY,
                "approval_note": approval.get("note") or "", "frozen_rev": _head(repo),
                "requirements": len(spec.get("requirements") or []), "acceptance": len(spec.get("acceptance") or [])}
    stop = _stopped(b)
    if stop:
        by = stop.get("by")
        head = "人が関所で仕様を承認しなかった" if by == "answer" and stop.get("node") == APPROVE else f"盤面は止まっている（{by}）"
        return {**out, "reason": f"{head}: {stop.get('reason') or '（理由なし）'}"}
    reason = ""
    for role, nid in ROLES.items():
        rejects = _rejects(b, nid)
        if b.node_state(nid) == "pending" and rejects:
            reason = f"{nid} の返答が {len(rejects)} 回とも受け付けで拒まれた（最後の拒否: {rejects[-1]['reason']}）"
            break
    if not reason:
        pend = [nid for nid in (*ROLES.values(), APPROVE, FREEZE) if b.node_state(nid) == "pending"]
        reason = f"仕様が固まっていない（待ちの節: {'・'.join(pend) or '無し'}）——輪か関所が回らなかった"
    b.stop(reason, by=STOP_BY)
    return {**out, "reason": reason}


# ---------------------------------------------------------------- スクリプトの入口
# blk-spec のスクリプトの入口（rolekit.script_main。blk-rejudge と同じ約束）。予定の状態（拒否・止めた・回す物が無い）は fn が
# dict で返して 0。環境変数の欠け・BoardGap・写しの Reject・思わぬ誤りは標準エラーに 1 行で 2（標準出力には何も出さない）
script_main = rolekit.script_main
