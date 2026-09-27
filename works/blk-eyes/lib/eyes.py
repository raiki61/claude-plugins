"""独立の目のブロック（blk-eyes。BLOCKS.md の R11 `gl.eyes.in` → `gl.eyes.out`）の芯。

中の節は写しの graph のまま: 入口の機械の節 p4.assemble（修正後の撮り直しと再発火の数え）・目 7 つ・関所の機械の節
r4.human_gate。どの目を回すか（条件 r1_refire・r2_design_due・r2_compare_due・overview_due・r2_premise_invalid と依存）は
盤面の settle だけが決める。ここは ready の目を起こす支度をし、返答を盤面に渡し、入口の周の箱から出口を組むだけ
（条件を写さない。stop.premise_check の引き金も盤面の r2_premise_invalid のまま）。

- enter:   入口。p4.assemble が今の周に済んでいるかを確かめ（済んでいなければ配線の誤り）、目を起こす前の作業ツリーの写しを撮る
- route:   目 1 つを今起こすか（入口の周に、その目の待っている instance が在るか）
- prep:    engine と同じ描き方（写しの graph の reads だけ・cap なし）で指示書を描き、役の定義（graph の plugin の agents/<役>.md）を
           頭に置き、前の拒否の文を先頭に置き、起こした印を置く。本文は出口の prompt で返し、指示書（commands/）が直の参照で貼る
- accept:  返答を盤面に渡す（entry.take。入口の写しと今の作業ツリーを比べる）。拒否は数え、GIVE_UP_AFTER 回で諦めの印（done）。
           表で skippable の目（r1.comment_candidates）は諦めたら省いて（board.skip）後ろの目を出す
- collect: 出口。入口の周の箱だけを見る（最後の目の受け付けの settle が p4.record・converge を回して周を進めても読み違えない）。
           人に聞いている（r4.human_gate の ask）なら止めずに asking（答えた後にブロックへ入り直すと残りの目が回る）。
           聞いていないのに目が待ちのまま残れば（3 回とも拒まれた）盤面を止めて ok: false

並び: 目は Archon の同じ層の輪で並んで走る。盤面（state.json・record.json）は版の突き合わせで守られているが、並んだ受け付けは
BoardConflict（SystemExit）で落ちるので、このブロックの盤面の読み書きは全部、盤面の置き場の錠（LOCK_NAME。fcntl.flock）の中で行う。

作業ファイルは入口の周の r<N>/ に置く: eyes-snapshot.json（入口の作業ツリーの写し）・eyes-enter.json（p4.assemble が数えた値の控え）・
eyes-rejects.json（拒否の文）・eyes-exit.json（出口）。最後の目の受け付けの settle が周を進めると、次の周の頭が loop の差分の欄を
撮り直し、記録の reviews を空にし、facts_to_add を制約へ移す（写しの RL の on_new_round・p1.worktree_before）ので、出口は
p4.assemble の値を入口の控えから、reviews を周の記録 rounds/round-<N>.json から、facts_to_add を stop.premise_check の出力から読む。
"""
import contextlib
import fcntl
import functools
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （写しの engine を sys.path に入れる。engine より先に）
from engine.advance import agent_type_of  # noqa: E402
from engine.util import now, safe_name  # noqa: E402
from engine.validator import agent_def  # noqa: E402
import accept as _accept  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import rolekit  # noqa: E402

ENTRY_NODE = "p4.assemble"
GATE_NODE = "r4.human_gate"
# 写しの目の節 → 役の名（YAML の節 id・commands の名・包みの印の名）
ROLE_OF = {"r1.comment_candidates": "r1-comments", "r1.minimality": "r1-minimality", "r2.design": "r2-design",
           "r2.compare": "r2-compare", "r3.coherence": "r3-coherence", "r4.hidden_scope": "r4-scope",
           "stop.premise_check": "premise-check"}
NODE_OF = {r: n for n, r in ROLE_OF.items()}
# YAML で縦に並べる筋（graph の依存の順。筋をまたぐ依存は無い——tests/test_blk_eyes.py が graph と突き合わせる）
LANES = (("r1.comment_candidates", "r1.minimality"), ("r2.design", "r2.compare", "stop.premise_check"),
         ("r3.coherence",), ("r4.hidden_scope",))
# 役の道具（graph の run_by → Archon の allowed_tools）。graphloops の役の定義（convergence-loops 0.40.0 の agents/<役>.md）の
# 道具から、書く道具と shell を除いた物。comment-analyzer（別 plugin）は定義が全部の道具を持つが、目は読むだけなので同じく書く道具と
# shell を除いた Read・Grep・Glob・WebSearch・WebFetch（tests/test_tool_parity.py の NARROWED）
TOOLS = {"judge": ["Read", "Grep", "Glob", "WebSearch", "WebFetch"], "inspector": ["Read", "Grep", "Glob"],
         "blind-judge": [], "comment-analyzer": ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]}
# 道具ゼロの役（graphloops は Git の外の一時の置き場で起こす。commands._isolated_cwd）。包みの旗 isolated が同じことをする
ISOLATED_RUN_BY = frozenset({"blind-judge"})
ISOLATED_FLAG = "isolated"
GIVE_UP_AFTER = 3        # 輪の max_iterations と同じ数。この数だけ拒んだら done を出し、輪を失敗で抜けさせない（裁定 R50）
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
LOCK_NAME = "board.lock"
SNAPSHOT_NAME = "eyes-snapshot.json"
REJECTS_NAME = "eyes-rejects.json"
ENTER_NAME = "eyes-enter.json"
EXIT_NAME = "eyes-exit.json"
STOP_BY = "works:eyes"
PROMPTS_COPY = rolekit.PROMPTS_COPY
# 出口の欄（BLOCKS.md 3.3 の R11 の出口に、ブロックの回り方の欄を足した物。並びも固定）
EXIT_FIELDS = ("ok", "reason", "complete", "asking", "stopped", "eyes", "gave_up", "after_fix", "open_units", "r1_refire",
               "r2_refire", "purpose_known", "purpose_unusable", "reviews", "premise", "retaken_for_reviews", "exit_file")


# ---------------------------------------------------------------- 写しの形
def node_of(role: str) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は独立の目でない（{sorted(NODE_OF)}）")
    return NODE_OF[role]


@functools.lru_cache(maxsize=1)
def _graph():
    from board import graph_expanded
    return graph_expanded()


def _graph_node(nid):
    return _graph()["nodes"][nid]


def isolated(nid: str) -> bool:
    return _graph_node(nid)["run_by"] in ISOLATED_RUN_BY


def allowed_tools(nid: str) -> list:
    n = _graph_node(nid)
    key = n["run_by"] if n["run_by"] in TOOLS else (n.get("agent_type") or "").rpartition(":")[2]
    if key not in TOOLS:
        raise BoardGap(f"{nid} の役 {n['run_by']}（{n.get('agent_type')}）の道具が決まっていない")
    return list(TOOLS[key])


def output_format(nid: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役>[ isolated]"""
    return node_marker.mark(_accept.role_schema(nid), ROLE_OF[nid], flags=(ISOLATED_FLAG,) if isolated(nid) else ())


# ---------------------------------------------------------------- 盤面
@contextlib.contextmanager
def locked(board_dir):
    """盤面の置き場の錠（排他。待つ上限は持たない）。このブロックの盤面の読み書きは全部この中"""
    d = pathlib.Path(board_dir)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / LOCK_NAME, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _box(b, rnd):
    """周 rnd の箱（state.rounds の 1 つ）"""
    for r in b.state["rounds"]:
        if r.get("round") == rnd:
            return r
    raise BoardGap(f"盤面に周 {rnd} の箱が無い")


def _node_state(b, rnd, nid):
    box = _box(b, rnd)
    for k in ("done", "na", "skipped", "stopped"):
        if nid in (box.get(k) or {}):
            return k
    inst = (box.get("instances") or {}).get(nid)
    return "pending" if inst and inst.get("status") == "pending" else "waiting"


def _pending(b, nid):
    inst = b.rd["instances"].get(nid)
    return inst if inst and inst.get("status") == "pending" else None


def _work(b, rnd, name) -> pathlib.Path:
    p = b.dir / f"r{rnd}" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path, default):
    path = pathlib.Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _write_json(path, obj) -> pathlib.Path:
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _stopped(b):
    st = b.state
    return bool(st.get("halted") or st.get("stop"))


def _round_of(raw) -> int:
    try:
        n = int(str(raw).strip())
    except ValueError:
        raise BoardGap(f"周の番号 {raw!r} が整数でない（入口 eyes-enter の round を渡す）") from None
    if n < 1:
        raise BoardGap(f"周の番号 {n} が 1 未満")
    return n


# ---------------------------------------------------------------- 入口・分かれ道
def assembled(b) -> dict:
    """p4.assemble が数えた値（出口の after_fix・open_units・再発火・目的の出典・撮り直しの痕跡）。目は書き換えない"""
    ls = b.loop_state
    return {"after_fix": {"rev": ls.get("reviewed_revision") or "", "diff_file": ls.get("diff_file") or "",
                          "changed_files": list(ls.get("changed_files") or []), "diff_lines": ls.get("diff_lines") or 0},
            "open_units": ls.get("open_units") or 0, "r1_refire": bool(ls.get("r1_refire")),
            "r2_refire": bool(ls.get("r2_refire")), "purpose_known": bool(ls.get("purpose_known")),
            "purpose_unusable": ls.get("purpose_unusable") or "",
            "retaken_for_reviews": (ls.get("retaken_for_reviews") or {}).get("file") or ""}


def enter(board_dir, repo) -> dict:
    """入口。返り {ok, round, stopped, asking, ready: [役], snapshot_file, why}。止まった盤面は stopped（目を起こさない）。
    p4.assemble が今の周に済んでいなければ BoardGap（配線の誤り。修正の後の撮り直しの前に目を起こさない）"""
    with locked(board_dir):
        b = entry.open_board(board_dir, allow_halted=True)
        out = {"ok": True, "round": b.round, "stopped": False, "asking": bool(b.state.get("pending_human")), "ready": [],
               "snapshot_file": "", "why": ""}
        if _stopped(b):
            by = (b.state.get("stop") or b.state.get("halted") or {}).get("by")
            return {**out, "stopped": True, "why": f"盤面は止まっている（{by}）"}
        if b.node_state(ENTRY_NODE) != "done":
            raise BoardGap(f"{ENTRY_NODE} が今の周（{b.round}）に済んでいない（{b.node_state(ENTRY_NODE)}）——修正の後の撮り直しの前に"
                           "目を起こさない（ラインの配線か、機械の節が止まった。盤面の trace を見る）")
        snap = entry.snapshot(board_dir, SNAPSHOT_NAME, repo)
        out["snapshot_file"] = str(snap)
        _write_json(_work(b, b.round, ENTER_NAME), assembled(b))
        out["ready"] = [ROLE_OF[n] for n in ROLE_OF if _pending(b, n)]
        return out


def route(board_dir, role, rnd) -> dict:
    """目 role を今起こすか。{go, node, why, stopped}。入口の周（rnd）でない周・止まった盤面・待っている instance の無い目は go: false"""
    nid, rnd = node_of(role), _round_of(rnd)
    with locked(board_dir):
        b = entry.open_board(board_dir, allow_halted=True)
        if _stopped(b):
            return {"go": False, "node": nid, "why": "盤面は止まっている", "stopped": True}
        if b.round != rnd:
            return {"go": False, "node": nid, "why": f"盤面の周が {b.round}（入口は {rnd}）", "stopped": False}
        if _pending(b, nid):
            return {"go": True, "node": nid, "why": f"{nid} が待っている", "stopped": False}
        st = _node_state(b, rnd, nid)
        why = b.rd["na"].get(nid) if st == "na" else st
        if st == "waiting" and b.state.get("pending_human"):
            why = f"人に聞いている間（{b.state['pending_human'].get('node')}）は出ない"
        return {"go": False, "node": nid, "why": f"{nid}: {why}", "stopped": False}


# ---------------------------------------------------------------- 描く
def render(b, nid) -> str:
    """engine の emit_instance と同じ描き方（rolekit.render_body。reads に無い穴は描けない・cap なし・schema の断り）。
    指示書は写しの graph、無ければ同じ commit から写した gl-prompts/。番号で指す一覧（pointers）を持つ節は描かない"""
    if b.nodes[nid].get("pointers"):
        raise BoardGap(f"{nid} は番号で指す一覧（pointers）を持つ——独立の目の描き方は持たない（写しを見直す）")
    return rolekit.render_body(b, nid, prompts_dir=PROMPTS_COPY)[0]


def role_definition(b, nid) -> tuple:
    """(役の定義の本文, 定義のファイル, 無い時の知らせ)。graph の plugin の役の定義が見つからなければ BoardGap（engine の die と同じ——
    遮断系かどうかが決まらないので起こさない）。別 plugin の役は止めずに知らせを返す（engine の role_def_missing）"""
    atype = agent_type_of(b, b.nodes[nid])
    d = agent_def(atype)
    if d is None:
        if atype.rpartition(":")[0] == b.plugin:
            raise BoardGap(f"{nid}: 役 {atype!r} の定義（agents/<役>.md）が解決できない——遮断系かどうかが決まらないので起こさない"
                           "（plugin の置き場・<PLUGIN>_ROOT・CLAUDE_CONFIG_DIR を確かめよ）")
        return "", "", f"{atype} の定義がこの環境に無い（別 plugin）。役の定義なしで起こす"
    return d["body"], d["file"], ""


def _rejects(b, rnd, nid):
    return [r for r in _read_json(_work(b, rnd, REJECTS_NAME), []) if r.get("node") == nid]


def prep(board_dir, role, rnd, repo) -> dict:
    """目 role を起こす前の支度。返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。
    待っている instance が無い・入口の周でない・止まった盤面は BoardGap か Reject（配線の誤り）"""
    nid, rnd = node_of(role), _round_of(rnd)
    with locked(board_dir):
        b = entry.open_board(board_dir)
        if b.round != rnd:
            raise BoardGap(f"盤面の周が {b.round}（入口は {rnd}）——入口の周の目だけを起こす")
        inst = _pending(b, nid)
        if inst is None:
            raise BoardGap(f"この周に {nid} の待っている instance が無い（route が go の目だけを起こす）")
        body, def_file, missing = role_definition(b, nid)
        prompt = render(b, nid)
        if body:
            prompt = f"## お前の役の定義（{agent_type_of(b, b.nodes[nid])}）\n\n{body}\n\n---\n\n{prompt}"
        last = _rejects(b, rnd, nid)[-1:]
        if last:
            # 拒否の文は本文に入れて渡す（$LOOP_PREV で貼ると Archon が文の中の $… を置き換え直す。裁定 R44）
            prompt = (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                      f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n{prompt}")
        p = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(prompt, encoding="utf-8")
        m = b.mark_launched(nid, inst.get("attempts", 1))
        return {"prompt": prompt, "prompt_file": str(p), "node": nid, "attempt": m["attempt"], "already": m["already"],
                "role_def": def_file, "role_def_missing": missing}


# ---------------------------------------------------------------- 受け付け
def _reject(board_dir, nid, reason) -> dict:
    """拒否の文を入口の周の eyes-rejects.json に積む。この周のこの目の拒否が GIVE_UP_AFTER 回に達したら諦めの印（done）。
    表で skippable の目は諦めたら省く（board.skip → settle。後ろの目が出る）"""
    b = entry.open_board(board_dir)
    rnd = b.round
    path = _work(b, rnd, REJECTS_NAME)
    rows = _read_json(path, [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(path, rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    skipped = False
    if give_up and b.table.nodes[nid].skippable:
        b.skip(nid, f"独立の目 {ROLE_OF[nid]} の返答が {GIVE_UP_AFTER} 回とも受け付けで拒まれた（最後の拒否: {reason}）")
        skipped = True
    return {"ok": False, "done": give_up, "give_up": give_up, "skipped": skipped, "reason": reason, "node": nid}


parse_reply = rolekit.parse_reply   # 役の返答を dict に。読めなければ (None, 理由)


def accept(board_dir, role, raw, repo) -> dict:
    """目 role の返答を受ける。返り {ok, done, give_up, skipped, reason, node}。通れば done。拒否（読めない返答・作業ツリーの変化・
    写しの schema・post_check・記録の整合）は数えて返す。止まった盤面・表で受けない節は Reject・BoardGap（配線の誤り）"""
    nid = node_of(role)
    with locked(board_dir):
        reply, why = parse_reply(raw)
        if reply is None:
            return _reject(board_dir, nid, why)
        got = entry.take(board_dir, nid, reply, repo, snapshot_name=SNAPSHOT_NAME)
        if not got["ok"]:
            return _reject(board_dir, nid, got["reason"])
        return {"ok": True, "done": True, "give_up": False, "skipped": False, "reason": "", "node": nid}


# ---------------------------------------------------------------- 出口
def collect(board_dir, rnd) -> dict:
    """ブロックの出口（EXIT_FIELDS の並び）。入口の周の箱で目の状態を見る。人に聞いていれば止めずに asking。聞いていない・止まって
    いないのに目が残っていれば盤面を止めて（by works:eyes）ok: false。同じ物を入口の周の eyes-exit.json に書く"""
    rnd = _round_of(rnd)
    with locked(board_dir):
        b = entry.open_board(board_dir, allow_halted=True)
        states = {ROLE_OF[n]: _node_state(b, rnd, n) for n in ROLE_OF}
        rejects = _read_json(_work(b, rnd, REJECTS_NAME), [])
        gave_up = [ROLE_OF[n] for n in ROLE_OF if sum(1 for r in rejects if r.get("node") == n) >= GIVE_UP_AFTER]
        asking = bool(b.state.get("pending_human")) and b.round == rnd
        left = [r for r, s in states.items() if s in ("pending", "waiting")]
        ok, reason = True, ""
        if not _stopped(b) and left and not asking:
            ok = False
            stuck = [r for r in left if r in gave_up]
            if stuck:
                last = [x for x in rejects if x.get("node") == NODE_OF[stuck[0]]][-1]
                reason = (f"独立の目 {stuck[0]} の返答が {GIVE_UP_AFTER} 回とも受け付けで拒まれた"
                          f"（最後の拒否: {last['reason']}）")
            else:
                reason = f"回した後も目 {left} が残った（盤面の順とブロックの筋がずれた——写し直しで増えた依存を筋に足す）"
            b.stop(reason, by=STOP_BY)
        at = _read_json(_work(b, rnd, ENTER_NAME), None)
        if at is None:
            raise BoardGap(f"入口の控え r{rnd}/{ENTER_NAME} が無い（eyes-enter が先に走る）")
        rounded = _read_json(b.dir / "rounds" / f"round-{rnd}.json", None)
        reviews = (rounded if rounded is not None else b.record).get("reviews") or {}
        pc = b.output_of_round("stop.premise_check", rnd) or {}
        out = {"ok": ok, "reason": reason, "complete": not left, "asking": asking, "stopped": _stopped(b), "eyes": states,
               "gave_up": gave_up, "after_fix": at["after_fix"], "open_units": at["open_units"],
               "r1_refire": at["r1_refire"], "r2_refire": at["r2_refire"], "purpose_known": at["purpose_known"],
               "purpose_unusable": at["purpose_unusable"],
               "reviews": {k: reviews.get(k) for k in ("R1", "R2", "R3", "R4")},
               "premise": {"facts_to_add": list(pc.get("facts_to_add") or []) if pc.get("verdict") == "resolved" else []},
               "retaken_for_reviews": at["retaken_for_reviews"]}
        path = _work(b, rnd, EXIT_NAME)
        out["exit_file"] = str(path)
        _write_json(path, out)
        return out


# ---------------------------------------------------------------- スクリプトの入口
# blk-eyes のスクリプトの入口（rolekit.script_main）。盤面のパスに $ の柵（fence）。受け付け（返りが done を持つ）は拒否でも 0 で、
# script_io.emit_result が reason_file（拒否の理由の本文のファイル reject-eyes_<節>-<連番>.txt。裁定 R44）を足す。
# 0 でないのは配線の誤りだけ（環境変数の欠け・BoardGap・写しの Reject・思わぬ誤りは標準エラーに 1 行で 2）
script_main = functools.partial(rolekit.script_main, fence=True, take="eyes")
