"""blk-plan の芯（P1 計画 Task 25。〔線A計〕T11 を P1-R10 で書き直した物）。独立設計（r2.design）・修正案（p2.fix_plan）・
事前審査（p2.plan_review）の 3 つの役を、本線の指示書を engine の描き方で描いて回す（rolekit）。人の関所の項目は盤面の p2.human_gate が組む。
独立設計は盤面の節がまだ待っていない（graph では修正の後）ので、支度・受け付け・控えは core の design に任せる（役 r2-design）。
事前審査の指示書の頭には、その設計（無ければ無い理由）を貼る（design_section）。修正案の指示書の頭には、盤面の根の構造のブロックの
控え（core の structmark）から構造の目の行か、行なしで計画した印を貼る（独立設計の役には渡さない）。

- snap:     役を起こす前の作業ツリーの写し（accept.tree_state。R47）を今の周の <役>-snapshot.json に置き、節が待っているか
            （go）を返す。待っていなければ（判定が直す物を出さなかった・修正案が諦めた）輪を飛ばす
- prep:     rolekit.render_prompt で本線の指示書を描き（頭に役の定義と、並行 PR の外した範囲のパス）、番号の控え（pointer_rows）を
            付けて起こした印（mark_launched）を置く。拒否の後の出し直しは、頭の 1 行が前の拒否の理由のファイルを名指す（R44）
- accept:   rolekit.main_accept（take が狭めない案の欄を欠く narrows の行を拒み、関所の項目の決め手の欄を外して盤面に置き（gatemarks）、entry.take・読むだけの役の作業ツリーの比べ・3 回目の拒否で done・give_up。R50）
- reads:    2 つの役の読んだ証拠（reads.collect）を今の周の reads-<役>.json に書き、その一覧を reads-plan-block.json に
- collect:  出口 {ok, plan_file, review_file, asks_human, gate_kinds, reads_file, gave_up, reason_file}。役の節がこの周に
            待ったまま（3 回とも拒まれた）なら、最後の拒否の理由で盤面を止めて（by works:plan）ok: false・gave_up: true。
            独立設計が 3 回とも拒まれたのは止めず、盤面の trace に設計が無いことを書く（最後の R2 が目の層で言う）
"""
import copy
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
import design  # noqa: E402
from engine import pointers  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import gatemarks  # noqa: E402
import libdocs  # noqa: E402
import node_marker  # noqa: E402
import reads  # noqa: E402
import rolekit  # noqa: E402
import structmark  # noqa: E402

NODE_OF = {"plan": "p2.fix_plan", "plan-review": "p2.plan_review"}   # 役（YAML の役の節の id・印の名）→ 写しの graph の節
ROLES = tuple(NODE_OF)
DESIGN_ROLE = "r2-design"   # 独立設計の役（盤面の節へは渡さない。core の design）
ISOLATED_FLAG = "isolated"  # 道具ゼロの役の印の旗（包みが Git の外の置き場で起こす）
STOP_BY = "works:plan"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER   # 輪の max_iterations と同じ数（tests/test_blk_plan.py が YAML と突き合わせる）
READS_INDEX = "reads-plan-block.json"
NONE_WORDS = ("", "null")               # 入口の「無し」（Archon の入力の既定の空と、ラインが渡す文字列 null）
EXCLUDED_HEAD = "並行 PR の範囲。触らず、単位に入れない"
NO_NARROW_REJECT = (f"narrows の行に狭めない案を探した結果（{gatemarks.NO_NARROW}）が無いか短い（直して done し直す）。狭めを避ける形が"
                    "在ればそれを案に採ってその行を消し、無い時だけ、どの形を当たりなぜ採れないかを書け:")
NOT_OWED_REJECT = "案に、直す義務の無い単位が入っている（nit・info・defer など。受け付けが受けない）。案から外し、入れてよい no は頭の節に在る:"
PLAN_SLOTS_HEAD = ("## 案に入れてよい単位の no（機械が受け付けと同じ述語から作った。下の本文の『今の周に直す単位』の見出しと、"
                   "one_shot_closes に載る単位より、この節が優先する）")
DESIGN_HEAD = "## 独立設計（修正案を見ない別の目が、目的と実測した制約・人の関所の答え・依頼が名指した設計書の節から作った理想解。機械が貼った）"
DESIGN_ASK = ("修正案をこの設計と構造で突き合わせよ——何を固定し何を派生と見るか・どこに継ぎ目を置くか・目的の当事者が日常で回す"
              "動線が閉じるか。構造の本質的な食い違いは faces に kind contract_drift・severity block で挙げ、why を"
              "『独立設計との構造の食い違い: 』で始めよ。表現の違い・設計が触れていない所は食い違いでない（設計は判定の単位も"
              "実装の事情も知らない）。")
DESIGN_NOT_STANDS = ("設計の役は、目的の問いが立たないと返した（{reason}）。問いが立つかは修正の後の独立の目が前提を実態で検算して"
                     "扱うので、ここでは穴に挙げない。設計との突き合わせはせずに審査せよ。")
DESIGN_NONE = "独立設計は無い（{why}）。設計との突き合わせはせずに審査せよ。"
HEAD = {
    "plan": ("お前は修正案の役（読むだけ）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も変えてはいけない（受け付けは起こす前の"
             "作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の JSON Schema に合う JSON だけを返せ。"),
    "plan-review": ("お前は修正案の事前審査の役（読むだけ。判定をした役とは別の目）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も"
                    "変えてはいけない（受け付けは起こす前の作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の"
                    " JSON Schema に合う JSON だけを返せ。"),
}


def role_node(role: str) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は blk-plan の盤面へ渡す役（{' / '.join(ROLES)}）でない")
    return NODE_OF[role]


def known_role(role: str) -> str:
    """役の写しの graph の節（独立設計の役も含む）。知らない役は BoardGap"""
    return design.NODE if role == DESIGN_ROLE else role_node(role)


def snapshot_name(role: str) -> str:
    role_node(role)
    return f"{role}-snapshot.json"


def output_format(role: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役> を付けた物（YAML に貼る値）。
    prep が番号の一覧を貼って控えを固める（mark_launched(pointers=)）ので、番号の欄は番号でも返せる型に開く。
    独立設計の役は番号の欄を持たず、道具ゼロの旗 isolated を付ける"""
    if role == DESIGN_ROLE:
        return node_marker.mark(accept.role_schema(design.NODE), role, flags=(ISOLATED_FLAG,))
    return node_marker.mark(accept.role_schema(role_node(role), numbered=True), role)


def _pending(b, nid: str) -> dict | None:
    inst = b.rd["instances"].get(nid)
    return inst if inst and inst.get("status") == "pending" else None


def _given(value) -> str:
    return "" if value is None or str(value).strip() in NONE_WORDS else str(value)


def head(role: str, excluded_file: str = "", lib_docs: str = "", design_part: str = "") -> str:
    """指示書の頭（役の定義と、並行 PR の外した範囲のパスと、ライブラリの今の文書の節 libdocs.section と、事前審査なら
    独立設計の節 design_section・修正案なら構造の目の節 structmark.plan_section と入れてよい no の節 plan_slots_section）"""
    text = HEAD[role] + "\n\n" + gatemarks.HEAD[role_node(role)]
    ex = _given(excluded_file)
    if ex:
        text += f"\n\n{EXCLUDED_HEAD}: {ex}（先に Read で読め。そこに挙がった範囲は、ほかの PR が扱う）"
    if lib_docs:
        text += "\n\n" + lib_docs
    if design_part:
        text += "\n\n" + design_part
    return text


def plan_slots(b) -> tuple[set, set, dict]:
    """(必ず入れる, 入れてよい, 単位の key → 単位)。写しの受け付け fix_plan_covers_units が読むのと同じ物（want＝b.rules._owed_units、
    opened＝validator の is_open）から作る。見せる頭の節と take の事前の拒否が、ここだけを読む"""
    V = b.rules.validator_module(b)
    units = {u["key"]: u for u in b.record["units"]}
    return set(b.rules._owed_units(b)), {k for k, u in units.items() if V.is_open(u)}, units


def _names(b, nid: str) -> list:
    return next((p.get("names") or [] for p in b.pointer_rows(nid)["pointers"] or []), [])


def plan_slots_section(b) -> str:
    """修正案の指示書の頭に貼る、入れてよい no・入れてはいけない no の節（本文の見出し・one_shot_closes より優先する）"""
    owed, opened, units = plan_slots(b)
    names = _names(b, NODE_OF["plan"])
    no = {k: i + 1 for i, k in enumerate(names)}
    must = sorted(no[k] for k in owed if k in no)
    may = sorted(no[k] for k in opened - owed if k in no)
    stuck = sorted(no[k] for k in owed - opened if k in no)
    shut = [f"no {no[k]}（label={u.get('label')}・disposition={u.get('disposition', '無し')}）"
            for k, u in units.items() if k not in opened and k not in owed and k in no]
    if not shut and not stuck:   # 本文の一覧が受け付けの集合と同じ（全部入れてよい）なら貼らない
        return ""
    text = (f"{PLAN_SLOTS_HEAD}\n\n- 必ず案に入れる no: {must}\n- 入れてもよい no（人の答え待ちの問いの出どころ・depends。入れなくてもよい）: {may}\n"
            f"- 入れてはいけない no（受け付けが拒む）: {'、'.join(shut) or '無し'}")
    if stuck:
        text += (f"\n- 必ず入れる no のうち開いていない単位（関所で答えた問いの出どころ。受け付けの写しの食い違いで、入れても入れなくても"
                 f"拒まれうる）: {stuck}——入れて、拒まれたら理由をそのまま返せ")
    return text


def not_allowed(b, nid: str, reply) -> list[str]:
    """修正案の返答が案に入れた単位のうち、受け付けが受けない物（入れてよくなく、必ず入れる物でもない）の理由の行。no は engine の
    pointers.resolve で名前に戻す（範囲外の番号・判定に無い key の拒否は entry.take＝engine に任せる）"""
    if not isinstance(reply, dict):
        return []
    owed, opened, units = plan_slots(b)
    inst = b.rd["instances"].get(nid) or {}
    got = copy.deepcopy(reply)
    pointers.resolve(got, b.nodes[nid].get("pointers"), inst.get("pointers"))
    names = _names(b, nid)
    lines = []
    for p in got.get("plan") or []:
        for k in p.get("unit_keys") or []:
            if k in units and k in names and k not in opened and k not in owed:   # 判定に無い key・番号に無い名前は受け付けの写しの拒否に任せる
                u = units[k]
                lines.append(f"no {names.index(k) + 1} は label={u.get('label')}（disposition={u.get('disposition', '無し')}）"
                             f"で直す対象でない（{k[:40]}）")
    return lines


def design_section(b) -> str:
    """事前審査の指示書の頭に貼る独立設計の節。設計が問いは立たないと返した・設計が無い時は、突き合わせない旨と理由"""
    got, _ = design.made(b.dir)
    if got is None:
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NONE.format(why=design.missing(b))
    if not got["question_stands"]:
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NOT_STANDS.format(reason=got.get("premise_invalid_reason") or got["reason"])
    return (f"{DESIGN_HEAD}\n\n{DESIGN_ASK}\n\n設計の役の理由: {got['reason']}\n\n=====独立設計ここから=====\n"
            f"{got['design']}\n=====独立設計ここまで=====")


def lib_section(b, repo) -> str:
    """判定の単位のファイルが使うライブラリの今の文書の節（同じ周の 2 つ目の役は盤面の控えを読み、網に出ない）"""
    out = (b.state.get("outputs") or {}).get("p2.diagnose") or {}
    judgment = str(pathlib.Path(b.dir) / out["file"]) if out.get("file") else ""
    files, why = libdocs.unit_files(repo, judgment) if judgment else ([], "判定の出力が盤面に無い")
    text = libdocs.section(b, repo, files)
    return text + (f"\n- 単位のファイルの引き: {why}" if why else "")


# ---------------------------------------------------------------- 節
def snap(board_dir, role: str, repo) -> dict:
    """<役>-snap: 節が待っていれば作業ツリーの写しを置いて go: true。待っていなければ写しを置かずに go: false。
    独立設計の役は core の design.snap（起こすかは design.due）"""
    if role == DESIGN_ROLE:
        return design.snap(board_dir, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if _pending(b, nid) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(role), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def prep(board_dir, role: str, repo, excluded_file: str = "") -> dict:
    """<役>-prep: 描く → 番号の控え → 起こした印。返り {prompt_file, attempt, out_path, node, already}。
    独立設計の役は core の design.prep（返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。
    道具ゼロなので指示書の本文を返し、commands/r2-design.md が直の参照で貼る）"""
    if role == DESIGN_ROLE:
        return design.prep(board_dir, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    part = design_section(b) if role == "plan-review" else "\n\n".join(x for x in (structmark.plan_section(b.dir), plan_slots_section(b)) if x)
    path = rolekit.render_prompt(b, nid, head=head(role, excluded_file, lib_section(b, pathlib.Path(repo)), part))
    ptrs = b.pointer_rows(nid)["pointers"]
    inst = _pending(b, nid)
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=ptrs)
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def take(role: str):
    """rolekit.accept_role の take: 関所の項目の行の決め手の欄（gatemarks）を外した返答を entry.take に渡す（写しの型は欄を
    持たない）。決め手は渡す前に盤面の gate-marks.json に置く（事前審査を受けた settle の中で関所が読む）。修正案の narrows の行が
    狭めない案を探した結果を欠けば、盤面へ渡さずに拒む（gatemarks.narrow_gaps）"""
    nid = role_node(role)

    def run(board, reply, repo):
        gaps = gatemarks.narrow_gaps(nid, reply)
        if gaps:
            return {"ok": False, "reason": NO_NARROW_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if role == "plan":
            closed = not_allowed(entry.open_board(pathlib.Path(board)), nid, reply)
            if closed:
                return {"ok": False, "reason": NOT_OWED_REJECT + "\n" + "\n".join(f"  - {c}" for c in closed)}
        bare, marks = gatemarks.split(nid, reply)
        gatemarks.save(board, nid, entry.open_board(pathlib.Path(board)).round, marks)
        return entry.take(pathlib.Path(board), nid, bare, pathlib.Path(repo), snapshot_name=snapshot_name(role))
    return run


def main_accept(role: str) -> int:
    """<役>-accept の入口（rolekit.main_accept）。独立設計の役は core の design.accept_reply（盤面の節へ渡さない。拒否の理由は
    reason_file に書く）"""
    if role == DESIGN_ROLE:
        return rolekit.script_main(lambda board, repo, env: design.accept_reply(board, env["INPUTS_REPLY"], repo),
                                   ("INPUTS_REPLY",), fence=True, take="plan")
    return rolekit.main_accept(role_node(role), snapshot_name=snapshot_name(role), give_up_after=GIVE_UP_AFTER,
                               take=take(role))


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
    gave = rolekit.given_up_reason(pathlib.Path(board_dir), design.NODE, give_up_after=design.GIVE_UP_AFTER)
    if gave:   # 止めない（事前審査は設計なしで進んだ）。設計が無いことを記録に残し、最後の R2 が目の層で言う
        b.trace(design.MISSING_OP, reason=f"{design.MISSING}: {gave}")
    ph = b.state.get("pending_human") or {}
    out["asks_human"] = bool(ph)
    out["gate_kinds"] = list(ph.get("kinds") or [])
    idx = b.work(READS_INDEX)
    out["reads_file"] = str(idx) if idx.exists() else ""
    return out
