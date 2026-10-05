"""blk-plan の芯（P1 計画 Task 25。〔線A計〕T11 を P1-R10 で書き直した物）。独立設計（r2.design）・修正案（p2.fix_plan）・
事前審査（p2.plan_review）の 3 つの役を、本線の指示書を engine の描き方で描いて回す（rolekit）。人の関所の項目は盤面の p2.human_gate が組む。
独立設計は盤面の節がまだ待っていない（graph では修正の後）ので、支度・受け付け・控えは core の design に任せる（役 r2-design）。
事前審査の指示書の頭には、その設計（無ければ無い理由）を貼る（design_section）。修正案の指示書の頭には、盤面の根の構造のブロックの
控え（core の structmark）から構造の目の行か、行なしで計画した印を貼る（独立設計の役には渡さない）。
事前審査の壁打ち（依頼 231。core の converge）で again の時は、直しの役（REVISE_ROLE。修正案の役の会話の続きで、盤面の節は
p2.fix_plan）が案を直す。直しの役が起きるかは壁打ちの控えの事実（converge.held）だけで決める。どの節の分かれも、直しの役と
独立設計の役を関数の頭に置く。

- snap:     役を起こす前の作業ツリーの写し（accept.tree_state。R47）を今の周の <役>-snapshot.json に置き、節が待っているか
            （go）を返す。待っていなければ（判定が直す物を出さなかった・修正案が諦めた）輪を飛ばす。修正案は、必ず入れるのに
            開いていない単位が在れば（stuck_reason。案の形では閉じない）盤面を止めて（by works:plan）輪を飛ばす
- prep:     rolekit.render_prompt で本線の指示書を描き（頭に役の定義と、並行 PR の外した範囲のパス）、番号の控え（pointer_rows）を
            付けて起こした印（mark_launched）を置く。拒否の後の出し直しは、頭の 1 行が前の拒否の理由のファイルを名指す（R44）
- accept:   rolekit.main_accept（take が狭めない案の欄を欠く narrows の行を拒み、関所の項目の決め手の欄を外して盤面に置き（gatemarks）、entry.take・読むだけの役の作業ツリーの比べ・3 回目の拒否で done・give_up。R50）。
            修正案は、項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope）の欠けを
            盤面へ渡す前に拒み、欄を外した案を渡して、
            盤面が受けた時だけ欄を盤面の plan-fields.json に控える（with_plan_fields。planmarks）。事前審査の指示書の頭にはその欄も貼る。
            事前審査はどの往復も盤面が settle なしで受けて往復を記録し（with_converge。core の converge）、新しい block が在れば
            役の節 2 つを同じ周の待ちに戻す（rewind_roles）。2 往復目からの指示書の頭には前の往復の block と答えを貼る
            直しの役は block への答え（converge の block_answers）の欠けと誤りを盤面へ渡す前に拒み、答えを外した案を修正案と同じ口
            （with_plan_fields。比べる作業ツリーの写しは直しの役の snap が置いた物）に渡し、盤面が受けたら答えを控えに置く（revise_take）
- converge-check: 壁打ちの出口 {ok, done, outcome, record_file}。抜け方が again でない・今の往復の役が諦めた・盤面が止まった時に
            done（converge_check。輪を max_iterations で落とさない。R50）。replan では壁打ちを回さない（直しの役の snap は
            go: false、converge-check はいつも 1 往復で done）
- reads:    役の読んだ証拠（reads.collect）を今の周の reads-<役>.json に書き、その一覧を reads-plan-block.json に
- collect:  出口 {ok, plan_file, review_file, asks_human, gate_kinds, reads_file, gave_up, reason_file}。役の節がこの周に
            待ったまま（3 回とも拒まれた）なら、最後の拒否の理由で盤面を止めて（by works:plan）ok: false・gave_up: true。
            独立設計が 3 回とも拒まれたのは止めず、盤面の trace に設計が無いことを書く（最後の R2 が目の層で言う）
- replan:   入力 replan が空でなく文字列 null でもなければ（ラインが同じブロックを 2 度目に include した、同じ run の中の案の直し。
            依頼 226）、snap・prep・main_accept・collect を core の replan の同名の口へ回す（prep は head と、事前審査なら独立設計の節
            design_only を組んで渡す）。独立設計の輪は今どおり design.due で飛ぶ。collect_reads は役の名 replan-<役> で読んだ証拠を
            reads-replan-<役>.json に、索引を replan.READS_INDEX に書く（1 回目の reads-<役>.json・reads-plan-block.json を上書きしない）
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
import converge  # noqa: E402
import design  # noqa: E402
from engine import pointers  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import gatemarks  # noqa: E402
import libdocs  # noqa: E402
import node_marker  # noqa: E402
import planmarks  # noqa: E402
import reads  # noqa: E402
import replan as replan_mod  # noqa: E402  （入力の名 replan と分ける）
import rolekit  # noqa: E402
import structmark  # noqa: E402

NODE_OF = {"plan": "p2.fix_plan", "plan-review": "p2.plan_review"}   # 役（YAML の役の節の id・印の名）→ 写しの graph の節
ROLES = tuple(NODE_OF)
DESIGN_ROLE = "r2-design"   # 独立設計の役（盤面の節へは渡さない。core の design）
REVISE_ROLE = "plan-revise"   # 直しの役（事前審査の壁打ちで修正案の役の会話の続き。盤面の節は p2.fix_plan。NODE_OF・ROLES に入れない）
REVISE_PROMPT = "prompt-plan-revise-{k}.md"   # 直しの役の指示書（今の周の作業ファイル。k は次の事前審査の往復の番号）
READS_LOOP = {"plan": "plan-loop", "plan-review": "converge-loop.plan-review-loop",
              REVISE_ROLE: "converge-loop.plan-revise-loop"}   # 役 → 出来事の節の名の輪（入れ子の輪は <外>.<中>）
ISOLATED_FLAG = "isolated"  # 道具ゼロの役の印の旗（包みが Git の外の置き場で起こす）
STOP_BY = "works:plan"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER   # 輪の max_iterations と同じ数（tests/test_blk_plan.py が YAML と突き合わせる）
READS_INDEX = "reads-plan-block.json"
NONE_WORDS = ("", "null")               # 入口の「無し」（Archon の入力の既定の空と、ラインが渡す文字列 null）
EXCLUDED_HEAD = "並行 PR の範囲。触らず、単位に入れない"
NO_NARROW_REJECT = (f"narrows の行に狭めない案を探した結果（{gatemarks.NO_NARROW}）が無いか短い（直して done し直す）。狭めを避ける形が"
                    "在ればそれを案に採ってその行を消し、無い時だけ、どの形を当たりなぜ採れないかを書け:")
NOT_OWED_REJECT = "案に、直す義務の無い単位が入っている（nit・info・defer など。受け付けが受けない）。案から外せ。案に入れてよい no（必ず入れる物を含む）は"
RESOLVED_REJECT = "前の往復の block の行き先が書かれていない（下の行を全部直して出し直せ）:"
ANSWERS_REJECT = "block への答えに誤りが在る（下の行を全部直して出し直せ）:"
LATER_NODES = ("p2.human_gate", "p3.lane_merge")   # 役の節 2 つを戻す前に、今の周に受けていてはいけない後ろの節（戻しは後ろへ伝わらない）
PLAN_STUCK = "修正案の行き止まり: 必ず案に入れる単位が開いていない"
STUCK_WHY = ("受け付けの写しは開いていない単位を受けず、義務からも外さないので、案の形では閉じない。人が関所で問いの答えを直すか、"
             "単位を開く")
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
             "作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の JSON Schema に合う JSON だけを返せ。"
             "\n\n" + planmarks.HEAD),
    "plan-review": ("お前は修正案の事前審査の役（読むだけ。判定をした役とは別の目）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も"
                    "変えてはいけない（受け付けは起こす前の作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の"
                    " JSON Schema に合う JSON だけを返せ。"),
}


def role_node(role: str) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は blk-plan の盤面へ渡す役（{' / '.join(ROLES)}）でない")
    return NODE_OF[role]


def known_role(role: str) -> str:
    """役の写しの graph の節（独立設計の役・直しの役も含む）。知らない役は BoardGap"""
    if role == REVISE_ROLE:
        return NODE_OF["plan"]
    return design.NODE if role == DESIGN_ROLE else role_node(role)


def snapshot_name(role: str) -> str:
    """役を起こす前の作業ツリーの写しの名（直しの役は自分の snap が置く写し。1 往復目の修正案の写しと比べない）"""
    if role != REVISE_ROLE:
        role_node(role)
    return f"{role}-snapshot.json"


def output_format(role: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役> を付けた物（YAML に貼る値）。
    prep が番号の一覧を貼って控えを固める（mark_launched(pointers=)）ので、番号の欄は番号でも返せる型に開く。
    独立設計の役は番号の欄を持たず、道具ゼロの旗 isolated を付ける。直しの役は修正案の印の付いていない型に答えの欄
    （converge.with_fields）を足し、印に continue=plan（修正案の役の会話の続き）を付ける"""
    if role == REVISE_ROLE:
        schema = converge.with_fields(role, accept.role_schema(NODE_OF["plan"], numbered=True))
        return node_marker.mark(schema, role, cont="plan")
    if role == DESIGN_ROLE:
        return node_marker.mark(accept.role_schema(design.NODE), role, flags=(ISOLATED_FLAG,))
    return converge.with_fields(role, node_marker.mark(accept.role_schema(role_node(role), numbered=True), role))


def _pending(b, nid: str) -> dict | None:
    inst = b.rd["instances"].get(nid)
    return inst if inst and inst.get("status") == "pending" else None


def _given(value) -> str:
    return "" if value is None or str(value).strip() in NONE_WORDS else str(value)


def head(role: str, excluded_file: str = "", lib_docs: str = "", design_part: str = "") -> str:
    """指示書の頭（役の定義と、並行 PR の外した範囲のパスと、ライブラリの今の文書の節 libdocs.section と、事前審査なら
    独立設計の節 design_section・修正案なら構造の目の節 structmark.plan_section と入れてよい no の節 plan_slots_section）。
    修正案の役の定義（HEAD["plan"]）は、項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・
    out_of_scope）の節 planmarks.HEAD を含む。
    事前審査の役は、その欄の JSON を design_section の中の planmarks.review_section で受ける"""
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
    shut = [f"no {no[k]}（label={u.get('label')}・disposition={u.get('disposition', '無し')}）"
            for k, u in units.items() if k not in opened and k not in owed and k in no]
    if not shut:   # 本文の一覧が受け付けの集合と同じ（全部入れてよい）なら貼らない。行き止まりの盤面は役を起こす前に止める（halt_if_stuck）
        return ""
    return (f"{PLAN_SLOTS_HEAD}\n\n- 必ず案に入れる no: {must}\n- 入れてもよい no（人の答え待ちの問いの出どころ・depends。入れなくてもよい）: {may}\n"
            f"- 入れてはいけない no（受け付けが拒む）: {'、'.join(shut) or '無し'}")


def stuck_reason(b) -> str:
    """必ず入れるのに開いていない単位（関所で答えた問いの出どころが defer など。plan_slots の 必ず入れる − 入れてよい）が在れば、
    盤面を止める理由（PLAN_STUCK・その単位の no と key・STUCK_WHY）。無ければ空。写しの受け付けはこの単位を入れても外しても拒むので、
    役を起こすと同じ拒否を 3 回繰り返して止まる"""
    owed, opened, _ = plan_slots(b)
    stuck = sorted(owed - opened)
    if not stuck:
        return ""
    names = _names(b, NODE_OF["plan"])
    items = "・".join(f"no {names.index(k) + 1}（{k}）" if k in names else f"no の一覧に無い単位（{k}）" for k in stuck)
    return f"{PLAN_STUCK}: {items}。{STUCK_WHY}"


def halt_if_stuck(b) -> str:
    """行き止まりの単位が在れば盤面を止めて（by works:plan。もう止まっていれば止め直さない）理由を返す。無ければ空"""
    why = stuck_reason(b)
    if why and not (b.state.get("halted") or b.state.get("stop")):
        b.stop(why, by=STOP_BY)
    return why


def _resolved(b, nid: str, reply: dict) -> dict:
    """返答の写しの no を engine の pointers.resolve で名前に戻した物（戻せない番号は番号のまま。拒否は entry.take＝engine に任せる）"""
    got = copy.deepcopy(reply)
    pointers.resolve(got, b.nodes[nid].get("pointers"), (b.rd["instances"].get(nid) or {}).get("pointers"))
    return got


def _plan_keys(got) -> list:
    """修正案の返答が案の行に挙げた単位の key（文字列）。形の崩れた行・欄は飛ばす（形の拒否は entry.take＝engine に任せる。再提出の道に乗せる）"""
    rows = got.get("plan") if isinstance(got, dict) else None
    return [k for p in rows if isinstance(p, dict) and isinstance(p.get("unit_keys"), list)
            for k in p["unit_keys"] if isinstance(k, str)] if isinstance(rows, list) else []


def allowed_nos(b, nid: str) -> list:
    """案に入れてよい no（開いている単位の no。必ず入れる単位は開いている＝halt_if_stuck が保つ）"""
    _, opened, _ = plan_slots(b)
    return [i + 1 for i, k in enumerate(_names(b, nid)) if k in opened]


def not_allowed(b, nid: str, reply) -> list[str]:
    """修正案の返答が案に入れた単位のうち、受け付けが受けない物（入れてよくなく、必ず入れる物でもない）の理由の行。no は engine の
    pointers.resolve で名前に戻す（範囲外の番号・判定に無い key の拒否は entry.take＝engine に任せる）"""
    if not isinstance(reply, dict):
        return []
    owed, opened, units = plan_slots(b)
    got = _resolved(b, nid, reply)
    names = _names(b, nid)
    lines = []
    for k in _plan_keys(got):
        if k in units and k in names and k not in opened and k not in owed:   # 判定に無い key・番号に無い名前は受け付けの写しの拒否に任せる
            u = units[k]
            lines.append(f"no {names.index(k) + 1} は label={u.get('label')}（disposition={u.get('disposition', '無し')}）"
                         f"で直す対象でない（{k[:40]}）")
    return lines


def design_section(b) -> str:
    """事前審査の指示書の頭に貼る節: 独立設計の節（design_only）と、修正案の項目の works の欄の節（planmarks.review_section。
    控えが無ければ無し）。欄の控えが凍結の印と食い違えば盤面を止めて（by works:plan）控えを名指す理由の BoardGap"""
    try:
        fields = planmarks.review_section(b)
    except planmarks.FieldsBroken as e:   # 受け付けの後に欄の控えを書き換えた: 書き換えた欄を審査に見せず、盤面を止める
        why = f"修正案の項目の works の欄の控え {planmarks.FIELDS_FILE} が凍結と食い違う: {' '.join(str(e).split())}"
        if not (b.state.get("halted") or b.state.get("stop")):
            b.stop(why, by=STOP_BY)
        raise BoardGap(why) from None
    return design_only(b) + fields


def design_only(b) -> str:
    """独立設計の節だけ（項目の works の欄の節は入れない）。設計が問いは立たないと返した・設計が無い時は、突き合わせない旨と理由。
    同じ run の中の案の直しの事前審査の指示書にも貼る"""
    got, _ = design.made(b.dir)
    if got is None:
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NONE.format(why=design.missing(b))
    if not got["question_stands"]:
        r = got.get("premise_invalid_reason") or got["reason"]
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NOT_STANDS.format(reason=r + design.anchor_note(r))
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
def replanning(replan) -> bool:
    """入力 replan が同じ run の中の案の直しの口を指すか（空でも文字列 null でもない）"""
    return bool(_given(replan))


def snap(board_dir, role: str, repo, replan: str = "") -> dict:
    """<役>-snap: 節が待っていれば作業ツリーの写しを置いて go: true。待っていなければ写しを置かずに go: false。修正案の
    行き止まりの盤面（stuck_reason）は止めて go: false。独立設計の役は core の design.snap（起こすかは design.due）。
    直しの役は壁打ちの抜け方が again（converge.held）で p2.fix_plan が待つ時だけ go: true（写しは plan-revise-snapshot.json）。
    replan なら直しの役はいつも go: false（案の直しは壁打ちを回さない。事前審査の穴は関所 replan-gate が項目ごとに読む）、
    ほかの役は core の replan.snap"""
    if role == REVISE_ROLE:
        return {"ok": True, "go": False, "snapshot_file": ""} if replanning(replan) else _revise_snap(board_dir, repo)
    if role == DESIGN_ROLE:
        return design.snap(board_dir, repo)
    if replanning(replan):
        return replan_mod.snap(board_dir, role, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if _pending(b, nid) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    if role == "plan" and halt_if_stuck(b):   # 行き止まりの盤面は止めて輪を飛ばす（役を起こさない）
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(role), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def prep(board_dir, role: str, repo, excluded_file: str = "", replan: str = "") -> dict:
    """<役>-prep: 描く → 番号の控え → 起こした印。返り {prompt_file, attempt, out_path, node, already}。
    独立設計の役は core の design.prep（返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。
    道具ゼロなので指示書の本文を返し、commands/r2-design.md が直の参照で貼る）。直しの役は _revise_prep（replan では snap が
    go: false なので届かない）。replan なら core の replan.prep に、頭（head。修正案の頭は planmarks.HEAD を含む）と、事前審査
    なら独立設計の節だけ（design_only）を渡す"""
    if role == REVISE_ROLE:
        return _revise_prep(board_dir)
    if role == DESIGN_ROLE:
        return design.prep(board_dir, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if replanning(replan):
        return replan_mod.prep(board_dir, role, repo, head=head(role, excluded_file, lib_section(b, pathlib.Path(repo))),
                               design_part=design_only(b) if role == "plan-review" else "")
    if role == "plan":
        why = halt_if_stuck(b)
        if why:   # snap が先に止めて輪を飛ばすので、ここに届くのは配線の誤り。指示書を書かずに 2 で落とす（役を起こさせない）
            raise BoardGap(why)
    part = "\n\n".join(x for x in ((design_section(b), converge.review_section(b)) if role == "plan-review"
                                    else (structmark.plan_section(b.dir), plan_slots_section(b))) if x)
    path = rolekit.render_prompt(b, nid, head=head(role, excluded_file, lib_section(b, pathlib.Path(repo)), part))
    ptrs = b.pointer_rows(nid)["pointers"]
    inst = _pending(b, nid)
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=ptrs)
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def _plan_malformed(reply) -> bool:
    """修正案の返答の形が崩れているか（dict でない・plan が list でない・plan の行が dict でない・narrows が list でない。空の narrows は gatemarks と同じく無い物と読む）"""
    if not isinstance(reply, dict) or not isinstance(reply.get("plan"), list):
        return True
    return any(not isinstance(p, dict) or not isinstance(p.get("narrows") or [], list) for p in reply["plan"])


def take(role: str, *, snapshot: str | None = None, settle: bool = True):
    """rolekit.accept_role の take: 関所の項目の行の決め手の欄（gatemarks）を外した返答を entry.take に渡す（写しの型は欄を
    持たない）。決め手は渡す前に盤面の gate-marks.json に置く（事前審査を受けた settle の中で関所が読む）。修正案の narrows の行が
    狭めない案を探した結果を欠けば、盤面へ渡さずに拒む（gatemarks.narrow_gaps）。形の崩れた修正案は前段を飛ばして entry.take に渡す。
    snapshot は entry.take が作業ツリーを比べる写しの名（既定は snapshot_name(role)）、settle はそのまま entry.take へ
    （偽なら盤面は受けるが進めない。事前審査の壁打ち with_converge が往復を記録してから進める）"""
    nid = role_node(role)
    snap_name = snapshot or snapshot_name(role)

    def run(board, reply, repo):
        if role == "plan" and _plan_malformed(reply):   # gatemarks は形の整った返答を前提に読む（変えない部品）。形の拒否は entry.take が言い、再提出の道に乗せる
            return entry.take(pathlib.Path(board), nid, reply, pathlib.Path(repo), snapshot_name=snap_name, settle=settle)
        gaps = gatemarks.narrow_gaps(nid, reply)
        if gaps:
            return {"ok": False, "reason": NO_NARROW_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if role == "plan":
            closed = not_allowed(entry.open_board(pathlib.Path(board)), nid, reply)
            if closed:
                allowed = allowed_nos(entry.open_board(pathlib.Path(board)), nid)
                return {"ok": False, "reason": f"{NOT_OWED_REJECT} {allowed}。外す単位:\n" + "\n".join(f"  - {c}" for c in closed)}
        bare, marks = gatemarks.split(nid, reply)
        gatemarks.save(board, nid, entry.open_board(pathlib.Path(board)).round, marks)
        return entry.take(pathlib.Path(board), nid, bare, pathlib.Path(repo), snapshot_name=snap_name, settle=settle)
    return with_plan_fields(run) if role == "plan" else run


def rewind_roles(b) -> None:
    """壁打ちの again で役の節 2 つ（修正案・事前審査）を同じ周の待ちに戻して settle する（修正案の待ちが出る。事前審査の待ちは
    案を受けるまで出ない）。後ろの節（LATER_NODES）が今の周に受けていれば、戻しは後ろへ伝わらないので戻さずに盤面を止めて
    （by converge.BY。もう止まっていれば止め直さない）BoardGap。機械の節は渡さない（engine が戻さずに落ちる）"""
    later = [n for n in LATER_NODES if n in b.rd["done"]]
    if later:
        why = f"事前審査の壁打ちで修正案と事前審査を戻せない: 後ろの節 {'・'.join(later)} がこの周に受けた後（戻しは後ろへ伝わらない）"
        if not (b.state.get("halted") or b.state.get("stop")):
            b.stop(why, by=converge.BY)
        raise BoardGap(why)
    b.rewind([NODE_OF["plan"], NODE_OF["plan-review"]], by=converge.BY)
    b.settle()


def with_converge(run):
    """事前審査の take の包み（依頼 231 の壁打ち）。run は take("plan-review", settle=False)。どの往復も盤面が settle なしで
    受けてから往復を記録する（again の返答も作業ツリーの比べと盤面の受け付けを通る）:
    1. 形の崩れた返答（dict でない・faces が list でない）は run に渡す（entry.take が拒み、出し直しの道に乗せる）
    2. 壁打ちの欄 resolved を外し、前の往復の block の行き先の欠けと誤り（converge.resolved_gaps）が在れば盤面へ渡さずに拒む
    3. 外した返答を run に渡す。拒まれたら往復を記録せずに拒否を返す
    4. 受けたら往復を記録する（converge.record_pass。今の周の修正案・事前審査の出力、盤面の根の欄の控え、指示書を写す）。
       記録できなければ盤面を止めて BoardGap（revise_take の答えの控えと同じ）
    5. 抜け方が again なら、今の周の役の節 2 つの拒否の控えを往復の行へ移し（出し直しを往復ごとに数え直す）、役の節 2 つを
       戻す（rewind_roles）。返りの again が真（受け付けは done で、事前審査の輪を抜ける）
    6. ほかの抜け方は settle して（関所が記録を読んで設計だけの行を組む）、その進みを返す"""
    def wrapped(board, reply, repo):
        if not isinstance(reply, dict) or not isinstance(reply.get("faces"), list):
            return run(board, reply, repo)
        bare, resolved = converge.split("plan-review", reply)
        gaps = converge.resolved_gaps(entry.open_board(pathlib.Path(board)), bare["faces"], resolved)
        if gaps:
            return {"ok": False, "reason": RESOLVED_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        got = run(board, bare, repo)
        if got.get("ok") is not True:
            return got
        b = entry.open_board(pathlib.Path(board))
        plan_out = (b.state["outputs"].get(NODE_OF["plan"]) or {}).get("file")
        files = {"p2.fix_plan.json": str(b.dir / plan_out) if plan_out else "",
                 "p2.plan_review.json": str(b.dir / got["out_file"]),
                 planmarks.FIELDS_FILE: str(b.dir / planmarks.FIELDS_FILE),
                 rolekit.prompt_name(NODE_OF["plan-review"]): str(b.work(rolekit.prompt_name(NODE_OF["plan-review"])))}
        try:
            row = converge.record_pass(b, bare, resolved=resolved, fence=GIVE_UP_AFTER, files=files)
        except Exception as e:   # 書けない: 盤面は受けたが往復の行が無い（settle もしない）まま節を抜けさせない
            raise BoardGap(rolekit.halt_unsaved(board, converge.RECORD, e, by=STOP_BY)) from None
        if row["outcome"] == converge.AGAIN:
            converge.stash_rejects(b, rolekit.take_rejects(b, [NODE_OF["plan"], NODE_OF["plan-review"]]))
            rewind_roles(b)
            return {"ok": True, "again": True, "reason": "", "ready": [], "asking": False, "halted": False, "out_file": ""}
        p = b.settle()
        return {**got, "ready": p["ready"], "asking": bool(p["asking"]), "halted": bool(p["halted"])}
    return wrapped


def with_plan_fields(run):
    """修正案の take の包み: 項目の works の欄（planmarks）の欠けと誤りが在れば盤面へ渡さずに拒み（planmarks.REJECT と行）、
    無ければ欄を外した返答を run に渡す。run が受けた（ok）時だけ、欄を盤面の plan-fields.json に控える。控えの周は包みの頭で
    1 度だけ読んだ盤面の周（受けた後に開き直さない）。控えの unit_keys は、返答の no を engine の pointers.resolve で名前に
    戻した物（not_allowed と同じ戻し方。盤面が受けた案と同じ名前）。盤面が受けた後で控えを置けなければ、黙って欄の無い run に
    せず盤面を止めて（by works:plan）控えを名指す理由の BoardGap"""
    def wrapped(board, reply, repo):
        if _plan_malformed(reply):   # 形の崩れた返答は欄を読まずに run へ（run が前段を飛ばして entry.take に拒ませる。再提出の道）
            return run(board, reply, repo)
        gaps = planmarks.gaps(reply, pathlib.Path(repo))
        if gaps:
            return {"ok": False, "reason": planmarks.REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if not isinstance(reply, dict):
            return run(board, reply, repo)
        b = entry.open_board(pathlib.Path(board))
        rnd = b.round
        named = _resolved(b, planmarks.NODE, reply)
        _, fields = planmarks.split(named, pathlib.Path(repo))
        bare, _ = planmarks.split(reply, pathlib.Path(repo))
        got = run(board, bare, repo)
        if got.get("ok") is True:
            try:
                planmarks.save(board, rnd, fields, trace=b.trace)
            except Exception as e:   # 書けない・形にできない: 受けた案に欄が無いまま進ませない
                raise BoardGap(rolekit.halt_unsaved(board, planmarks.FIELDS_FILE, e, by=STOP_BY)) from None
        return got
    return wrapped


def _revise_snap(board_dir, repo) -> dict:
    """直しの役の snap: 壁打ちの抜け方が again で p2.fix_plan が待てば作業ツリーの写しを置いて go: true。ほかは go: false"""
    b = entry.open_board(pathlib.Path(board_dir))
    if converge.held(b) is None or _pending(b, NODE_OF["plan"]) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(REVISE_ROLE), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def _revise_prep(board_dir) -> dict:
    """直しの役の prep: 指示書 prompt-plan-revise-<k>.md（読むだけの役の決まり・返した block の節・入れてよい no の節。前の拒否が
    在れば頭の 1 行がその理由のファイルを名指す）を書き、p2.fix_plan に番号の控えつきの起こした印を置く。独立設計の節は貼らない
    （修正案の役の頭と指示書は会話に在る）。返りは修正案の prep と同じ鍵。待ちが無ければ配線の誤り（BoardGap）"""
    nid = NODE_OF["plan"]
    b = entry.open_board(pathlib.Path(board_dir))
    inst = _pending(b, nid)
    section = converge.revise_section(b)
    if inst is None or not section:
        raise BoardGap(f"直しの役（{REVISE_ROLE}）を起こす待ちが無い: 事前審査の壁打ちの抜け方が again でないか、{nid} が待っていない")
    path = b.work(REVISE_PROMPT.format(k=converge.pass_no(b)))
    path.write_text(rolekit.compose([HEAD["plan"].split("\n\n")[0], section, plan_slots_section(b)],
                                    reject_file=rolekit.last_reject_file(b, nid)), encoding="utf-8")
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=b.pointer_rows(nid)["pointers"])
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def revise_take():
    """直しの役の take（rolekit.accept_role の take）:
    1. 形の崩れた返答（dict でない）は修正案の口に渡す（entry.take が拒み、出し直しの道に乗せる）
    2. 答えの欄 block_answers を外し（converge.split）、返した block への答えの欠けと誤り（converge.answer_gaps）が在れば
       盤面へ渡さずに拒む（ANSWERS_REJECT と行）
    3. 外した返答を修正案の口 take("plan", snapshot=直しの役の写し)（with_plan_fields で包んだ物）に渡す
    4. 盤面が受けたら答えを壁打ちの控えに置く（converge.note_answers。次の往復の行へ移る）。置けなければ盤面を止めて BoardGap"""
    run = take("plan", snapshot=snapshot_name(REVISE_ROLE))

    def wrapped(board, reply, repo):
        if not isinstance(reply, dict):
            return run(board, reply, repo)
        bare, answers = converge.split(REVISE_ROLE, reply)
        gaps = converge.answer_gaps(entry.open_board(pathlib.Path(board)), answers)
        if gaps:
            return {"ok": False, "reason": ANSWERS_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        got = run(board, bare, repo)
        if got.get("ok") is True:
            try:
                converge.note_answers(entry.open_board(pathlib.Path(board), allow_halted=True), answers)
            except Exception as e:   # 書けない: 答えの無い往復の行にしない
                raise BoardGap(rolekit.halt_unsaved(board, converge.RECORD, e, by=STOP_BY)) from None
        return got
    return wrapped


def converge_check(board_dir, replan: str = "") -> dict:
    """converge-check: 壁打ちの出口。done は「控えの抜け方が again でない」か「今の往復で p2.fix_plan か p2.plan_review の拒否が
    GIVE_UP_AFTER 件に達した」か「盤面が止まっている」（止まった盤面では役が起きず抜け方が again のまま残るので、輪を
    max_iterations で落とさずに抜ける。R50。報告は collect が出す）。止めた盤面でも開ける。
    replan ならいつも 1 往復で done（outcome・record_file は空。同じ周の 1 回目の控えを読まない。案の直しは壁打ちを回さず、
    事前審査の穴は関所 replan-gate が項目ごとに読む）。
    返り {ok: True, done, outcome（控えの語。無ければ ""）, record_file}"""
    if replanning(replan):
        return {"ok": True, "done": True, "outcome": "", "record_file": ""}
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    outcome = converge.read(b)["outcome"]
    gave = any(len(rolekit.rejects(b, nid)) >= GIVE_UP_AFTER for nid in NODE_OF.values())
    stopped = bool(b.state.get("halted") or b.state.get("stop"))
    return {"ok": True, "done": outcome != converge.AGAIN or gave or stopped, "outcome": outcome or "",
            "record_file": str(b.work(converge.RECORD))}


def _accept_args(role: str) -> tuple[str, dict]:
    """役の受け付けの（盤面の節, rolekit.accept_role の引数）。直しの役は盤面の節 p2.fix_plan へ revise_take で渡す（take を
    渡すので作業ツリーの比べは take の中）。事前審査は壁打ちの包み with_converge で渡す"""
    if role == REVISE_ROLE:
        return NODE_OF["plan"], {"take": revise_take()}
    return role_node(role), {"snapshot_name": snapshot_name(role),
                             "take": with_converge(take(role, settle=False)) if role == "plan-review" else take(role)}


def accept_reply(board_dir, role: str, raw: str, repo) -> dict:
    """<役>-accept の本体（rolekit.accept_role。独立設計の役は除く）。main_accept と同じ口を、ラインの試験（tests/linekit.py）が
    子のプロセスを起こさずに回す"""
    nid, kw = _accept_args(role)
    return rolekit.accept_role(pathlib.Path(board_dir), nid, raw, pathlib.Path(repo), give_up_after=GIVE_UP_AFTER, **kw)


def main_accept(role: str, replan: str = "") -> int:
    """<役>-accept の入口（rolekit.main_accept）。独立設計の役は core の design.accept_reply（盤面の節へ渡さない。拒否の理由は
    reason_file に書く）。replan なら core の replan.accept_reply（同じ包み。直しの役は replan では snap が go: false なので
    届かず、役の名の誤りとして落とす）。ほかの役は _accept_args の口"""
    if role == DESIGN_ROLE:
        return rolekit.script_main(lambda board, repo, env: design.accept_reply(board, env["INPUTS_REPLY"], repo),
                                   ("INPUTS_REPLY",), fence=True, take="plan")
    if replanning(replan):
        role_node(role)
        return rolekit.script_main(lambda board, repo, env: replan_mod.accept_reply(board, role, env["INPUTS_REPLY"], repo),
                                   ("INPUTS_REPLY",), fence=True, take="plan")
    nid, kw = _accept_args(role)
    return rolekit.main_accept(nid, give_up_after=GIVE_UP_AFTER, **kw)


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def collect_reads(board_dir, repo, run_id: str, replan: str = "") -> dict:
    """plan-reads: この周に描いた役ごとに、機械が渡したパス（描いた指示書・方針の文書）を読んだ証拠を reads.collect で集め、
    {役: reads-<役>.json} を reads-plan-block.json に書く。直しの役は今の周に書いた往復ごとの指示書（方針の文書は修正案の
    会話に在るので求めない）。出来事の節の名は READS_LOOP の輪の名で組む（include の名は core の reads.node_here が引く）。受け付けの条件にはしない。返り {ok: True, reads_file}。
    replan なら案の直しの役（直しの役は replan で起きないので数えない）の指示書について、役の名 replan-<役> で
    reads-replan-<役>.json に、索引を replan.READS_INDEX に書く（1 回目の控えを上書きしない）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    events = reads.events_for(run_id) if run_id else None
    policy = _given(b.state["inputs"].get("policy_md"))
    again = replanning(replan)
    files = {}
    for role in ROLES if again else (*ROLES, REVISE_ROLE):
        if role == REVISE_ROLE:
            prompts = [b.work(REVISE_PROMPT.format(k=k)) for k in range(1, converge.pass_no(b) + 1)]
        else:
            prompts = [b.work(rolekit.prompt_name(replan_mod.node_of(role) if again else role_node(role)))]
        must = [str(p) for p in prompts if p.exists()]
        if not must:
            continue
        must += [policy] if policy and role != REVISE_ROLE else []
        name = f"{replan_mod.READS_PREFIX}{role}" if again else role
        got = reads.collect(pathlib.Path(board_dir), name, reads.node_here(READS_LOOP[role], role), must, events,
                            repo=pathlib.Path(repo))
        files[name] = got["reads_file"]
    out = b.work(replan_mod.READS_INDEX if again else READS_INDEX)
    _write_json(out, files)
    return {"ok": True, "reads_file": str(out)}


def _first_line(path: str) -> str:
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return (text.strip().splitlines() or [""])[0]


def collect(board_dir, replan: str = "") -> dict:
    """出口。役の節がこの周に待ったままなら（3 回とも拒まれた・輪が回らなかった）最後の拒否の理由で盤面を止める。replan なら
    core の replan.collect（役の諦めは盤面を止めない）"""
    if replanning(replan):
        return replan_mod.collect(board_dir)
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
