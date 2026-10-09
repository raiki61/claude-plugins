"""独立の目のブロック（blk-eyes。BLOCKS.md の R11 `gl.eyes.in` → `gl.eyes.out`）の芯。

中の節は写しの graph のまま: 入口の機械の節 p4.assemble（修正後の撮り直しと再発火の数え）・目 6 つ・関所の機械の節
r4.human_gate。どの目を回すか（条件 r1_refire・r2_compare_due・overview_due・r2_premise_invalid と依存）は
盤面の settle だけが決める。ここは ready の目を起こす支度をし、返答を盤面に渡し、入口の周の箱から出口を組むだけ
（条件を写さない。stop.premise_check の引き金も盤面の r2_premise_invalid のまま）。
R2 の設計の半分（r2.design）はここで起こさない: 修正の前に先に作った設計（core の design。盤面の根の design.json）が、この
ブロックの前に盤面へ渡っている。渡っていなければ（設計の役が諦めた・目的が使えない）比較の目は待ちのまま残り、出口が
設計が取れなかったことを理由にして止める。

- enter:   入口。p4.assemble が今の周に済んでいるかを確かめ（済んでいなければ配線の誤り）、目を起こす前の作業ツリーの写しを撮る
- route:   目 1 つを今起こすか（入口の周に、その目の待っている instance が在るか）
- prep:    engine と同じ描き方（写しの graph の reads だけ・cap なし）で指示書を描き、役の定義（graph の plugin の agents/<役>.md）を
           頭に置き、前の拒否の文を先頭に置き、起こした印を置く。本文は出口の prompt で返し、指示書（commands/）が直の参照で貼る。
           r2.compare には、設計を作った後に分かった前提（人の関所の答え・依頼が名指した設計書の節・修正の中の前提のずれ loop.drift_notes・記録の制約）を頭に貼る
           （設計は修正の前に作るので、それらを知らない。崩れていれば『設計の前提が変わった』と理由つきで言わせる）
- accept:  返答を盤面に渡す（entry.take。入口の写しと今の作業ツリーを比べる）。拒否は数え、GIVE_UP_AFTER 回で諦めの印（done）。
           表で skippable の目（r1.comment_candidates）は諦めたら省いて（board.skip）後ろの目を出す
- collect: 出口。入口の周の箱だけを見る（最後の目の受け付けの settle が p4.record・converge を回して周を進めても読み違えない）。
           人に聞いている（r4.human_gate の ask）なら止めずに ok（答えた後にブロックへ入り直すと残りの目が回る）。
           聞いていないのに目が待ちのまま残れば（3 回とも拒まれた）盤面を止めて ok: false。premise_inputs に、R2 の 2 つの役へ
           渡した前提の入力の控え（design-premises.json・eyes-premises.json。後者の after_design に独立設計の後に来た人の答え）と、
           r2.compare の返答の『渡されていない』の文と、そのうち r2.compare の given に当たる物（compare の claims_given。
           design.claims_given）を並べる（拒まない・verdict を書き換えない。最後の関所の文が R2 の行の下に出す）

並び: 目は Archon の同じ層の輪で並んで走る。盤面（state.json・record.json）は版の突き合わせで守られているが、並んだ受け付けは
BoardConflict（SystemExit）で落ちるので、このブロックの盤面の読み書きは全部、盤面の置き場の錠（LOCK_NAME。fcntl.flock）の中で行う。

作業ファイルは入口の周の r<N>/ に置く: eyes-snapshot.json（入口の作業ツリーの写し）・
eyes-rejects.json（拒否の文）・eyes-premises.json（r2.compare に渡した前提の入力の控え）・eyes-exit.json（出口）。最後の目の受け付けの settle が周を進めると、次の周の頭が loop の差分の欄を
撮り直し、記録の reviews を空にする（写しの RL の on_new_round・p1.worktree_before）ので、出口は reviews を周の記録
rounds/round-<N>.json から読む。
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
from engine.util import now, safe_name  # noqa: E402
import accept as _accept  # noqa: E402
import design  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import node_marker  # noqa: E402
import rolekit  # noqa: E402

ENTRY_NODE = "p4.assemble"
GATE_NODE = "r4.human_gate"
# 写しの目の節 → 役の名（YAML の節 id・commands の名・包みの印の名）
ROLE_OF = {"r1.comment_candidates": "r1-comments", "r1.minimality": "r1-minimality", "r2.compare": "r2-compare", "r3.coherence": "r3-coherence", "r4.hidden_scope": "r4-scope",
           "stop.premise_check": "premise-check"}
NODE_OF = {r: n for n, r in ROLE_OF.items()}
# YAML で縦に並べる筋（graph の依存の順。graph の上で筋をまたぐ依存は無い——tests/test_blk_eyes.py が graph と突き合わせる）。
# r2.compare の依存の r2.design は目の外（修正の前に作った設計がこのブロックの前に盤面へ渡る）
LANES = (("r1.comment_candidates", "r1.minimality"), ("r2.compare", "stop.premise_check"),
         ("r3.coherence",), ("r4.hidden_scope",))
LANE_NAMES = dict(zip(LANES, ("R1", "R2", "R3", "R4")))
# 筋の頭が YAML で待つ筋（graph の依存ではない）。r4.human_gate の問いは盤面を止め、答える場は最後の関所なので、問いより先に
# R1・R2 の目を出し切る。前の筋が落ちても R4 を飛ばさない（YAML の trigger_rule: all_done）
LANE_AFTER = {"r4.hidden_scope": (LANES[0], LANES[1])}
# 役の道具（graph の run_by → Archon の allowed_tools）。graphloops の役の定義（convergence-loops 0.40.0 の agents/<役>.md）の
# 道具から、書く道具と shell を除いた物。comment-analyzer（別 plugin）は定義が全部の道具を持つが、目は読むだけなので同じく書く道具と
# shell を除いた Read・Grep・Glob・WebSearch・WebFetch（tests/test_tool_parity.py の NARROWED）
TOOLS = {"judge": ["Read", "Grep", "Glob", "WebSearch", "WebFetch"], "inspector": ["Read", "Grep", "Glob"],
         "blind-judge": [], "comment-analyzer": ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]}
# 節ごとに足す道具（役の道具に足す）。r2.compare は累積差分をファイルで受け、Read だけで全体を読む（DIFF_HEAD）
NODE_TOOLS = {"r2.compare": ["Read"]}
# 道具ゼロの役（graphloops は Git の外の一時の置き場で起こす。commands._isolated_cwd）。包みの旗 isolated が同じことをする
ISOLATED_RUN_BY = frozenset({"blind-judge"})
ISOLATED_FLAG = "isolated"
GIVE_UP_AFTER = 3        # 輪の max_iterations と同じ数。この数だけ拒んだら done を出し、輪を失敗で抜けさせない（裁定 R50）
# 諦めたら省く目（graph: 取れなくても R1 を not_run に倒さない）。表で skippable のほかの目は、入力 skip_optional の理由が在る時だけ
# 省き、諦めた時は今どおり出口が盤面を止める
GIVE_UP_SKIPS = frozenset({"r1.comment_candidates"})
REJECT_HEADING = rolekit.REJECT_HEADING
R4_NODE = "r4.hidden_scope"   # 直す前の関所で人が通した狭まりを頭に貼る目（gatemarks.carried_section）
PREMISE_NODE = "r2.compare"   # 設計を作った後に分かった前提を頭に貼る目
PREMISE_HEAD = "## 独立設計を作った後に分かった前提（機械が貼った）"
PREMISE_CHANGED = "設計の前提が変わった"
PREMISE_ASK = ("独立設計はこの run の修正の前に、目的と実測した制約・人の関所の答え・依頼が名指した設計書の節・対象のリポジトリの地図から作られた。下の前提のずれ（修正の中で申告された物）と、"
               "今の記録の制約のどれかが、設計の置いた前提を崩していれば、構造の突き合わせに進まず status を redesign-needed にし、"
               f"reason を『{PREMISE_CHANGED}: 』で始めて、どの前提が何で崩れたかを書け（古い前提の設計と差分を黙って比べない）。"
               "崩していなければ、下の指示書のとおり構造で突き合わせよ。")
# r2.compare に累積差分を本文で貼らず、ファイルで渡す（run d7b7a712: 1,061KB の差分を貼った 1.1MB の指示書で役が何も返さず、R2 が
# 落ちた）。量の上限は置かない——役が Read で全体を読む。指示書の『累積差分』の囲みには、本文の代わりに置き場を名指す 1 行
# （DIFF_POINTER）を描く
DIFF_NODE = "r2.compare"
DIFF_HEAD = "## 累積差分の渡し方（機械が貼った）"
DIFF_POINTER_NAME = "r2-compare-diff.txt"   # 囲みに描く 1 行の置き場（入口の周の作業ファイル）
DIFF_POINTER = "（累積差分の本文はここに貼らない。全体はファイル {path}。この指示書の頭の「累積差分の渡し方」のとおり Read で読む）"
DIFF_ASK = ("累積差分は、大きさに依らず本文を貼らない（大きな差分を貼ると指示書が読める量を超える）。全体は次のファイルに在る: "
            "`{path}`（{lines} 行・変わったファイル {files} 本）。\n\n"
            "- Read でこのファイルの全体を読め。長ければ offset と limit で区切り、最後の行まで読み切れ（読み残した所で食い違いを判断しない）。\n"
            "- お前の道具は Read だけで、開いてよいのはこのファイルだけ。リポジトリや盤面のほかのファイルは開くな（独立設計と差分だけで"
            "突き合わせる。調査の経緯を読むと独立が崩れる）。\n"
            "- 読めなかったら（ファイルが無い・途中までしか読めない）、推し量って埋めずに reason にそう書け。")
LATE_HEAD = "### 独立設計の後に来た人の答え（独立設計は見ていない）"
LATE_ASK = ("上の人の関所の答えのうち、次の物は独立設計を作った後に来た。設計がこれを置いていないことを設計の漏れに数えず、"
            "答えに照らした目的で突き合わせよ。")
LOCK_NAME = "board.lock"
SNAPSHOT_NAME = "eyes-snapshot.json"
REJECTS_NAME = "eyes-rejects.json"
EXIT_NAME = "eyes-exit.json"
PREMISES_NAME = "eyes-premises.json"   # r2.compare に渡した前提の入力の控え（入口の周の作業ファイル）
# route が起きた目と go（入口の周の作業ファイル）。Archon の節が落ちた筋を、盤面の順のずれ・設計待ちと見分ける
ROUTES_NAME = "eyes-routes.json"
LANES_NAME = gatemarks.LANES_NAME      # 落ちた筋と、その文（最後の関所の目の行の下に並ぶ。読み手は gatemarks.fell_lanes）
STOP_BY = "works:eyes"
PROMPTS_COPY = rolekit.PROMPTS_COPY
# 写しの目の指示書（r1.comment_candidates・r1.minimality・r3.coherence・r4.hidden_scope）は版を git show・git grep で読めと言うが、
# 目の道具は Read・Grep・Glob だけで shell を持たない（実測: R4 が版を読めないと申告した）。目の cwd の作業ツリーは入口で撮った版の
# まま止まっている（受け付けが入口の写し SNAPSHOT_NAME と今の姿を比べ、変われば拒む）ので、描く時にその文を FROZEN_READ に替える。
# 写しの指示書は 1 バイトも変えない（gl-prompts/COPIED_FROM の注記。文が替われば tests/test_blk_eyes.py の FrozenReadCase が落ちる）
GIT_SHOW_SENTENCE = ("**読むのは、この周に固定したリビジョン**であって、生きた作業ツリーの今の姿ではない。"
                     "`git -C <リポジトリ> show <版>:<パス>` や `git -C <リポジトリ> grep <語> <版>` のように、版を指定して読め"
                     "——同じ周のうちに実装者が直しても、あなたが見る現物は動かない。engine が根拠を数え直すときも同じ版を数える。")
FROZEN_READ = ("**読むのは、この周に固定したリビジョン**。お前の cwd の作業ツリーは、その版のまま止めてある（お前を起こす前に"
               "撮った姿と、受け付けが今の姿を比べる）。Read・Grep・Glob で cwd のファイルをそのまま読め——git や shell は"
               "道具に無く、要らない。engine が根拠を数え直すときも同じ版を数える。")
# 出口の欄（並びも固定）。読み手が在る物だけ: ok・reason・reviews は線の機械の報告（report の残りの数え）、premise_inputs は
# 最後の関所の文（line_edge が eyes-exit.json から読む）。BLOCKS.md 3.3 の R11 の出口に在った読み手の無い欄（目ごとの状態・
# p4.assemble が数えた値・facts_to_add など）は 2026-10-09 の整理で外した
EXIT_FIELDS = ("ok", "reason", "reviews", "premise_inputs")


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
    return [*TOOLS[key], *(t for t in NODE_TOOLS.get(nid, ()) if t not in TOOLS[key])]


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
    """入口の周 rnd の作業ファイルの置き場（盤面の b.work と同じ置き場。周だけを入口の周に固める）"""
    return b.work(name, round_=rnd)


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
        out["ready"] = [ROLE_OF[n] for n in ROLE_OF if _pending(b, n)]
        return out


def _gave_up(rejects) -> list:
    return [ROLE_OF[n] for n in ROLE_OF if sum(1 for r in rejects if r.get("node") == n) >= GIVE_UP_AFTER]


def fallen(b, rnd, lanes=LANES) -> list:
    """Archon の節が落ちた筋 [{lane, eye, state}]。目が残った筋のうち、最後の route が起きていない（前の節が落ちて飛ばされた）か、
    go を返した目が残った（輪が落ちた。3 回拒まれた諦めは除く）物。route が go: false を返して残った目（盤面の順のずれ・設計待ち）は
    数えない"""
    routes = _read_json(_work(b, rnd, ROUTES_NAME), {})
    gave = set(_gave_up(_read_json(_work(b, rnd, REJECTS_NAME), [])))
    out = []
    for lane in lanes:
        left = [n for n in lane if _node_state(b, rnd, n) in ("pending", "waiting")]
        went = [n for n in left if routes.get(ROLE_OF[n]) is True and ROLE_OF[n] not in gave]
        if left and (ROLE_OF[lane[-1]] not in routes or went):
            n = (went or left)[0]
            out.append({"lane": LANE_NAMES[lane], "eye": ROLE_OF[n], "state": _node_state(b, rnd, n)})
    return out


def fell_text(fell, ran="") -> str:
    names = "・".join(f["lane"] for f in fell)
    head = f"{names} の筋が落ちたまま {ran} を回した" if ran else f"{names} の筋が落ちた"
    return head + "（" + "・".join(f"{f['eye']}: {f['state']}" for f in fell) + "。Archon の節が落ちた）"


def route(board_dir, role, rnd, skip: str = "") -> dict:
    """目 role を今起こすか。{go, node, why, stopped}。入口の周（rnd）でない周・止まった盤面・待っている instance の無い目は go: false。
    入口が落ちた周（周が空）は起こさない。LANE_AFTER の筋が落ちていても待っている目は起こし、why と入口の周の LANES_NAME に残す。
    skip（ブロックの入力 skip_optional。省く理由の文）が在り、待っている目が表で skippable なら、起こさずに盤面で省く（board.skip →
    settle。後ろの目が出る。理由は記録の省略した機構に残る）。skippable でない目は skip に依らず今どおり"""
    nid = node_of(role)
    if str(rnd).strip() in ("", "null", "None"):
        return {"go": False, "node": nid, "why": "入口 eyes-enter の周が無い（入口が済んでいない）", "stopped": False}
    rnd = _round_of(rnd)
    with locked(board_dir):
        b = entry.open_board(board_dir, allow_halted=True)
        if _stopped(b):
            return {"go": False, "node": nid, "why": "盤面は止まっている", "stopped": True}
        if b.round != rnd:
            return {"go": False, "node": nid, "why": f"盤面の周が {b.round}（入口は {rnd}）", "stopped": False}
        routes = _work(b, rnd, ROUTES_NAME)
        went = _read_json(routes, {})
        skip = " ".join((skip or "").split())
        if skip and _pending(b, nid) and b.table.nodes[nid].skippable:
            b.skip(nid, skip)
            _write_json(routes, {**went, role: False})
            return {"go": False, "node": nid, "why": f"{nid}: 省いた（{skip}）", "stopped": False}
        if _pending(b, nid):
            why = f"{nid} が待っている"
            fell = fallen(b, rnd, LANE_AFTER.get(nid, ()))
            if fell:
                why += "——" + fell_text(fell, LANE_NAMES[next(lane for lane in LANES if nid in lane)])
                _write_json(_work(b, rnd, LANES_NAME), {"fell": fell, "why": why})
            _write_json(routes, {**went, role: True})
            return {"go": True, "node": nid, "why": why, "stopped": False}
        _write_json(routes, {**went, role: False})
        st = _node_state(b, rnd, nid)
        why = b.rd["na"].get(nid) if st == "na" else st
        if st == "waiting" and b.state.get("pending_human"):
            why = f"人に聞いている間（{b.state['pending_human'].get('node')}）は出ない"
        return {"go": False, "node": nid, "why": f"{nid}: {why}", "stopped": False}


# ---------------------------------------------------------------- 描く
def render(b, nid, ctx_hook=None) -> str:
    """engine の emit_instance と同じ描き方（rolekit.render_body。reads に無い穴は描けない・cap なし・schema の断り）。
    指示書は写しの graph、無ければ同じ commit から写した gl-prompts/。番号で指す一覧（pointers）を持つ節は描かない。
    版を git で読めという写しの文（GIT_SHOW_SENTENCE）は、止めた cwd を Read で読めという文（FROZEN_READ）に替える。
    ctx_hook は描く前に ctx を替える口（r2.compare の累積差分をファイルの名指しに替える。diff_section）"""
    if b.nodes[nid].get("pointers"):
        raise BoardGap(f"{nid} は番号で指す一覧（pointers）を持つ——独立の目の描き方は持たない（写しを見直す）")
    return rolekit.render_body(b, nid, prompts_dir=PROMPTS_COPY, ctx_hook=ctx_hook)[0].replace(GIT_SHOW_SENTENCE, FROZEN_READ)


def diff_section(b, rnd) -> tuple:
    """(r2.compare の頭に貼る節, 描く前の ctx の口)。累積差分（loop.diff_file）の本文は貼らず、置き場と行の数を名指して Read で
    全体を読ませる。指示書の『累積差分』の囲み（写しの {{file:loop.diff_file}}）には、本文の代わりに DIFF_POINTER の 1 行を描く
    （入口の周の作業ファイル DIFF_POINTER_NAME を指させる）。累積差分が盤面に無ければ ("", None)（今どおり描き、描けなければ BoardGap）"""
    ls = b.loop_state
    path = ls.get("diff_file")
    if not path:
        return "", None
    try:
        with open(path, "rb") as f:
            lines = sum(1 for _ in f)
    except OSError:
        lines = "?"
    pointer = _work(b, rnd, DIFF_POINTER_NAME)
    pointer.write_text(DIFF_POINTER.format(path=path) + "\n", encoding="utf-8")

    def hook(ctx):
        ctx["loop"] = {**(ctx.get("loop") or {}), "diff_file": str(pointer)}
    head = f"{DIFF_HEAD}\n\n" + DIFF_ASK.format(path=path, lines=lines, files=len(ls.get("changed_files") or []))
    return head, hook


def _lines(rows) -> str:
    return "\n".join(f"- {r}" for r in rows) if rows else "（無い）"


def premise_section(b, repo) -> tuple:
    """(r2.compare の頭に貼る節, 貼った入力の控え {node, given, withheld, seen, after_design})。節は人が決めた前提
    （design.premises の関所の答え・依頼が名指した設計書の節（この 2 つは在る時だけ）と対象のリポジトリの地図 repo_map（無ければ「地図なし」の 1 行）。先に読ませる）・修正の中の前提のずれ
    （loop.drift_notes）・記録の制約（record.process.constraints）。after_design は、独立設計の控え（design-premises.json）の
    seen の数より後に来た人の答えで、比べる時点の答えまで読むので compare にだけ渡った物（独立設計の控えが在る時だけ。
    節にも LATE_HEAD で分けて貼る）"""
    drift = [f"周 {r.get('round')}: {r.get('text') or '（申告の文なし）'}" for r in b.loop_state.get("drift_notes") or []]
    cons = [f"（{c.get('kind')}）{c.get('text')}" if isinstance(c, dict) else str(c)
            for c in (b.record.get("process") or {}).get("constraints") or []]
    parts, ledger = design.premises(b, repo)
    seen = (_read_json(b.dir / design.PREMISES_FILE, None) or {}).get("seen")
    if isinstance(seen, dict):
        answers = [g["what"] for g in ledger["given"] if g.get("kind") == "human_answer"]
        ledger["after_design"] = answers[seen.get("count") or 0:]
    decided = "".join(f"{s}\n\n" for s in parts)
    if ledger.get("after_design"):
        decided += f"{LATE_HEAD}\n\n{LATE_ASK}\n\n{_lines(ledger['after_design'])}\n\n"
    ledger["given"] += [{"kind": "drift", "what": d} for d in drift] + [{"kind": "constraint", "what": c} for c in cons]
    return (f"{PREMISE_HEAD}\n\n{PREMISE_ASK}\n\n{decided}"
            + f"### 前提のずれ（修正の中の申告）\n\n{_lines(drift)}\n\n"
            f"### 記録の制約\n\n{_lines(cons)}"), {"node": PREMISE_NODE, **ledger}


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
        diff_head, hook = diff_section(b, rnd) if nid == DIFF_NODE else ("", None)
        prompt = render(b, nid, hook)
        if nid == PREMISE_NODE:
            head, ledger = premise_section(b, repo)
            _write_json(_work(b, rnd, PREMISES_NAME), ledger)
            prompt = f"{head}\n\n---\n\n{prompt}"
        if diff_head:
            prompt = f"{diff_head}\n\n---\n\n{prompt}"
        elif nid == R4_NODE and (carried := gatemarks.carried_section(b)):
            prompt = f"{carried}\n\n---\n\n{prompt}"
        prompt, def_file, missing = rolekit.with_role_definition(b, nid, prompt)
        last = _rejects(b, rnd, nid)[-1:]
        if last:   # 拒否の文は本文に入れて渡す
            prompt = rolekit.with_reject(prompt, last[0]["reason"])
        p = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(prompt, encoding="utf-8")
        m = b.mark_launched(nid, inst.get("attempts", 1))
        return {"prompt": prompt, "prompt_file": str(p), "node": nid, "attempt": m["attempt"], "already": m["already"],
                "role_def": def_file, "role_def_missing": missing}


# ---------------------------------------------------------------- 受け付け
def _reject(board_dir, nid, reason) -> dict:
    """拒否の文を入口の周の eyes-rejects.json に積む。この周のこの目の拒否が GIVE_UP_AFTER 回に達したら諦めの印（done）。
    GIVE_UP_SKIPS の目（表で skippable）は諦めたら省く（board.skip → settle。後ろの目が出る）"""
    b = entry.open_board(board_dir)
    rnd = b.round
    path = _work(b, rnd, REJECTS_NAME)
    rows = _read_json(path, [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(path, rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    skipped = False
    if give_up and nid in GIVE_UP_SKIPS and b.table.nodes[nid].skippable:
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
    いないのに目が残っていれば盤面を止めて（by works:eyes）ok: false。ただし Archon の節が落ちて目が残った筋（fallen）だけなら
    止めずに理由を返し、入口の周の LANES_NAME に残す（最後の関所に出す。YAML は all_done で出口を走らせる）。同じ物を入口の周の
    eyes-exit.json に書く"""
    if str(rnd).strip() in ("", "null", "None"):
        raise BoardGap("入口 eyes-enter の周が無い（入口が落ちた。入口の失敗を先に見る）")
    rnd = _round_of(rnd)
    with locked(board_dir):
        b = entry.open_board(board_dir, allow_halted=True)
        states = {ROLE_OF[n]: _node_state(b, rnd, n) for n in ROLE_OF}
        rejects = _read_json(_work(b, rnd, REJECTS_NAME), [])
        gave_up = _gave_up(rejects)
        asking = bool(b.state.get("pending_human")) and b.round == rnd
        left = [r for r, s in states.items() if s in ("pending", "waiting")]
        ok, reason = True, ""
        if not _stopped(b) and left and not asking:
            stuck = [r for r in left if r in gave_up]
            fell, stop = fallen(b, rnd), True
            in_fell = {ROLE_OF[n] for lane in LANES if LANE_NAMES[lane] in {f["lane"] for f in fell} for n in lane}
            if stuck:
                last = [x for x in rejects if x.get("node") == NODE_OF[stuck[0]]][-1]
                reason = (f"独立の目 {stuck[0]} の返答が {GIVE_UP_AFTER} 回とも受け付けで拒まれた"
                          f"（最後の拒否: {last['reason']}）")
            elif _node_state(b, rnd, design.NODE) in ("pending", "waiting"):
                # 修正の前の設計が盤面へ渡っていない（設計の役が諦めた・控えを盤面が受けない）。今までどおり目の層で止める
                reason = f"独立の目 R2: {design.missing(b) or design.MISSING + '（控えは在るが盤面が受けていない）'}"
            elif fell and set(left) <= in_fell:
                ran = (_read_json(_work(b, rnd, LANES_NAME), {}) or {}).get("why")
                reason, stop = "; ".join(x for x in (ran, fell_text(fell)) if x), False
                _write_json(_work(b, rnd, LANES_NAME), {"fell": fell, "why": reason})
            else:
                reason = f"回した後も目 {left} が残った（盤面の順とブロックの筋がずれた——写し直しで増えた依存を筋に足す）"
            if stop:
                ok = False
                b.stop(reason, by=STOP_BY)
        rounded = _read_json(b.dir / "rounds" / f"round-{rnd}.json", None)
        reviews = (rounded if rounded is not None else b.record).get("reviews") or {}
        compare = _read_json(_work(b, rnd, PREMISES_NAME), None)
        claims = design.claims_unpassed(b.output_of_round(PREMISE_NODE, rnd))
        if isinstance(compare, dict):   # 『渡されていない』は r2.compare の文なので、r2.compare に渡した given と突き合わせる
            compare["claims_given"] = design.claims_given(claims, compare.get("given"))
        out = {"ok": ok, "reason": reason, "reviews": {k: reviews.get(k) for k in ("R1", "R2", "R3", "R4")},
               "premise_inputs": {"design": _read_json(b.dir / design.PREMISES_FILE, None),
                                  "compare": compare, "claims": claims}}
        _write_json(_work(b, rnd, EXIT_NAME), out)
        return out


# ---------------------------------------------------------------- スクリプトの入口
# blk-eyes のスクリプトの入口（rolekit.script_main）。盤面のパスに $ の柵（fence）。受け付け（返りが done を持つ）は拒否でも 0 で、
# script_io.emit_result が reason_file（拒否の理由の本文のファイル reject-eyes_<節>-<連番>.txt。裁定 R44）を足す。
# 0 でないのは配線の誤りだけ（環境変数の欠け・BoardGap・写しの Reject・思わぬ誤りは標準エラーに 1 行で 2）
script_main = functools.partial(rolekit.script_main, fence=True, take="eyes")
