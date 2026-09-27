"""blk-plan の芯（P1 計画 Task 25。〔線A計〕T11 を P1-R10 で書き直した物）。修正案（p2.fix_plan）と事前審査（p2.plan_review）の
2 つの読むだけの役を、本線の指示書を engine の描き方で描いて回す（rolekit）。人の関所の項目は盤面の p2.human_gate が組む。

- snap:     役を起こす前の作業ツリーの写し（accept.tree_state。R47）を今の周の <役>-snapshot.json に置き、節が待っているか
            （go）を返す。待っていなければ（判定が直す物を出さなかった・修正案が諦めた）輪を飛ばす
- prep:     rolekit.render_prompt で本線の指示書を描き（頭に役の定義と、並行 PR の外した範囲のパス）、番号の控え（pointer_rows）を
            付けて起こした印（mark_launched）を置く。拒否の後の出し直しは、頭の 1 行が前の拒否の理由のファイルを名指す（R44）
- accept:   rolekit.main_accept（entry.take・読むだけの役の作業ツリーの比べ・3 回目の拒否で done・give_up。R50）
- reads:    2 つの役の読んだ証拠（reads.collect）を今の周の reads-<役>.json に書き、その一覧を reads-plan-block.json に
- collect:  出口 {ok, plan_file, review_file, asks_human, gate_kinds, reads_file, gave_up, reason_file}。役の節がこの周に
            待ったまま（3 回とも拒まれた）なら、最後の拒否の理由で盤面を止めて（by works:plan）ok: false・gave_up: true
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import accept  # noqa: E402
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import node_marker  # noqa: E402
import reads  # noqa: E402
import rolekit  # noqa: E402

NODE_OF = {"plan": "p2.fix_plan", "plan-review": "p2.plan_review"}   # 役（YAML の役の節の id・印の名）→ 写しの graph の節
ROLES = tuple(NODE_OF)
STOP_BY = "works:plan"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER   # 輪の max_iterations と同じ数（tests/test_blk_plan.py が YAML と突き合わせる）
READS_INDEX = "reads-plan-block.json"
NONE_WORDS = ("", "null")               # 入口の「無し」（Archon の入力の既定の空と、ラインが渡す文字列 null）
EXCLUDED_HEAD = "並行 PR の範囲。触らず、単位に入れない"
HEAD = {
    "plan": ("お前は修正案の役（読むだけ）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も変えてはいけない（受け付けは起こす前の"
             "作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の JSON Schema に合う JSON だけを返せ。"),
    "plan-review": ("お前は修正案の事前審査の役（読むだけ。判定をした役とは別の目）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も"
                    "変えてはいけない（受け付けは起こす前の作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の"
                    " JSON Schema に合う JSON だけを返せ。"),
}


def role_node(role: str) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は blk-plan の役（{' / '.join(ROLES)}）でない")
    return NODE_OF[role]


def snapshot_name(role: str) -> str:
    role_node(role)
    return f"{role}-snapshot.json"


def output_format(role: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役> を付けた物（YAML に貼る値）"""
    return node_marker.mark(accept.role_schema(role_node(role)), role)


def _pending(b, nid: str) -> dict | None:
    inst = b.rd["instances"].get(nid)
    return inst if inst and inst.get("status") == "pending" else None


def _given(value) -> str:
    return "" if value is None or str(value).strip() in NONE_WORDS else str(value)


def head(role: str, excluded_file: str = "") -> str:
    """指示書の頭（役の定義と、並行 PR の外した範囲のパス）"""
    text = HEAD[role]
    ex = _given(excluded_file)
    if ex:
        text += f"\n\n{EXCLUDED_HEAD}: {ex}（先に Read で読め。そこに挙がった範囲は、ほかの PR が扱う）"
    return text


# ---------------------------------------------------------------- 節
def snap(board_dir, role: str, repo) -> dict:
    """<役>-snap: 節が待っていれば作業ツリーの写しを置いて go: true。待っていなければ写しを置かずに go: false"""
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if _pending(b, nid) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(role), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def prep(board_dir, role: str, repo, excluded_file: str = "") -> dict:
    """<役>-prep: 描く → 番号の控え → 起こした印。返り {prompt_file, attempt, out_path, node, already}"""
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    path = rolekit.render_prompt(b, nid, head=head(role, excluded_file))
    ptrs = b.pointer_rows(nid)["pointers"]
    inst = _pending(b, nid)
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=ptrs)
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def main_accept(role: str) -> int:
    """<役>-accept の入口（rolekit.main_accept）"""
    return rolekit.main_accept(role_node(role), snapshot_name=snapshot_name(role), give_up_after=GIVE_UP_AFTER)


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def collect_reads(board_dir, repo, run_id: str, include: str) -> dict:
    """plan-reads: この周に描いた役ごとに、機械が渡したパス（描いた指示書・方針の文書）を読んだ証拠を reads.collect で集め、
    {役: reads-<役>.json} を reads-plan-block.json に書く。受け付けの条件にはしない。返り {ok: True, reads_file}"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    events = reads.events_for(run_id) if run_id else None
    policy = _given(b.state["inputs"].get("policy_md"))
    files = {}
    for role in ROLES:
        prompt = b.work(rolekit.prompt_name(role_node(role)))
        if not prompt.exists():
            continue
        must = [str(prompt)] + ([policy] if policy else [])
        got = reads.collect(pathlib.Path(board_dir), role, reads.node_path(include, f"{role}-loop", role), must, events,
                            repo=pathlib.Path(repo))
        files[role] = got["reads_file"]
    out = b.work(READS_INDEX)
    _write_json(out, files)
    return {"ok": True, "reads_file": str(out)}


def _first_line(path: str) -> str:
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return (text.strip().splitlines() or [""])[0]


def collect(board_dir) -> dict:
    """出口。役の節がこの周に待ったままなら（3 回とも拒まれた・輪が回らなかった）最後の拒否の理由で盤面を止める"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {"ok": True, "plan_file": "", "review_file": "", "asks_human": False, "gate_kinds": [], "reads_file": "",
           "gave_up": False, "reason_file": ""}
    for role, key in (("plan", "plan_file"), ("plan-review", "review_file")):
        nid = role_node(role)
        inst = b.rd["instances"].get(nid) or {}
        if inst.get("status") == "done":
            out[key] = str(pathlib.Path(board_dir) / b.state["outputs"][nid]["file"])
            continue
        if inst.get("status") != "pending":
            continue
        rows = rolekit.rejects(b, nid)
        rf = rolekit.last_reject_file(b, nid)
        out.update(ok=False, gave_up=len(rows) >= GIVE_UP_AFTER, reason_file=rf)
        why = (f"{nid} の返答が {len(rows)} 回とも受け付けで拒まれた（最後の理由: {_first_line(rf)}。全文 {rf}）" if rows
               else f"{nid} が待ったまま、役の返答を受けていない")
        if not b.state.get("halted"):
            b.stop(why, by=STOP_BY)
        break
    ph = b.state.get("pending_human") or {}
    out["asks_human"] = bool(ph)
    out["gate_kinds"] = list(ph.get("kinds") or [])
    idx = b.work(READS_INDEX)
    out["reads_file"] = str(idx) if idx.exists() else ""
    return out
