"""修正前の関所（p2.human_gate）の項目の決め手（持ち主 2026-09-28。run 46 の人の答え）。

修正案の狭め（narrows）と事前審査の regression・policy の穴のうち、決め手の出どころ（decided_by）が在り、決め手を当たっても
答えが 1 つに決まらない理由（undecided_because）が空で、柵の印（fences）の無い行は、人に聞かずに通す。判定役の問いの
undecided_because の規律（本流 p2.diagnose.md 8 項）を関所の項目に伸ばし、柵は Renovate の automerge:false と同じ明示の除外。
通した行は出どころつきで state.works.gate_passes に残り、報告の冒頭にいつも並び、最後の関所が開いた時はその文にも並ぶ
（通した行は when_needed の最後の関所を開く理由に入れない）。欄の無い行は今までどおり聞く。

写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、querytest の例の欄と同じく、役の型にだけ欄を足し、受け付けが
盤面へ渡す前に外して盤面の gate-marks.json に置く。関所の組み立ては写しの RL の _plan_gate_items を差し替える（entry.CORE_OVERRIDES）。

- with_marks(node, schema)・split(node, reply)・save(board, node, round, marks): 役の型・受け付け
- plan_gate_items(b): 写しの _plan_gate_items の差し替え
- passes(b)・lines(b): 通した行と、最後の関所の文・報告の行
標準ライブラリだけ。
"""
import copy
import json
import pathlib

MARKS_FILE = "gate-marks.json"
FIELDS = ("decided_by", "undecided_because", "fences")
# 決め手が在っても人に聞く行の印（外への書き込み・取り消せない操作・方針の文書の変更・守り（資格・sandbox）を広げる・web の結果が
# 新しい疑いを出した）
FENCES = ("external_write", "irreversible", "policy_doc", "widen_protection", "web_doubt")
MARK_SCHEMA = {
    "decided_by": {"type": "string",
                   "note": "決め手の出どころ（依頼の引用・URL と節・本流の同じ場面・持ち主の前の決定＝ADR・台帳の行）。無ければ書かない"},
    "undecided_because": {"type": "string",
                          "note": "決め手を当たっても答えが 1 つに決まらない理由。書けないなら空（自明なので人に回さない）"},
    "fences": {"type": "array", "uniqueItems": True, "items": {"type": "string", "enum": list(FENCES)},
               "note": "当たる柵の印。1 つでも在れば決め手が在っても人に聞く"},
}
NODES = ("p2.fix_plan", "p2.plan_review")
_RULE = ("に、決め手の欄を書け。decided_by＝決め手の出どころ（依頼の引用・URL と節・本流の同じ場面・持ち主の前の決定＝ADR・台帳の行）。"
         "undecided_because＝決め手を当たっても答えが 1 つに決まらない理由（書けないなら空にせよ——自明なので人に回さない）。"
         "fences＝当たる柵の印（external_write 外への書き込み・irreversible 取り消せない操作・policy_doc 方針の文書の変更・"
         "widen_protection 守り（資格・sandbox）を広げる・web_doubt web の結果が新しい疑いを出した）。decided_by が在り "
         "undecided_because が空で fences が無い行は修正前の関所で人に聞かずに通り、出どころつきで報告に並ぶ（最後の関所が開けばその文にも）。"
         "決め手が無い・決まらない・柵に当たる行は今までどおり人に聞く")
# 役の指示書の頭に足す文（写しの指示書は欄を知らない）
HEAD = {"p2.fix_plan": "関所の項目の決め手: plan[].narrows の各行" + _RULE,
        "p2.plan_review": "関所の項目の決め手: faces のうち kind が regression・policy の各行" + _RULE}
PASSED_BY = "decided"


def _row_props(node: str, schema: dict):
    props = schema.get("properties") or {}
    if node == "p2.fix_plan":
        return props["plan"]["items"]["properties"]["narrows"]["items"]["properties"]
    return props["faces"]["items"]["properties"]


def with_marks(node: str, schema: dict) -> dict:
    """役の型に決め手の欄を足した写し（NODES でなければそのまま）"""
    if node not in NODES:
        return schema
    out = copy.deepcopy(schema)
    _row_props(node, out).update(copy.deepcopy(MARK_SCHEMA))
    return out


def _rows(node: str, reply: dict) -> list:
    """行の一覧（plan は [[narrow…]…]、plan_review は [face…]）"""
    if not isinstance(reply, dict):
        return []
    if node == "p2.fix_plan":
        return [p.get("narrows") or [] if isinstance(p, dict) else [] for p in reply.get("plan") or []]
    return reply.get("faces") or []


def _pop(row) -> dict:
    return {k: row.pop(k) for k in FIELDS if isinstance(row, dict) and k in row}


def split(node: str, reply: dict) -> tuple:
    """（決め手の欄を外した返答の写し, 行と同じ並びの決め手）。NODES でなければ（写し, None）"""
    out = copy.deepcopy(reply)
    if node not in NODES:
        return out, None
    rows = _rows(node, out)
    if node == "p2.fix_plan":
        return out, [[_pop(n) for n in narrows] for narrows in rows]
    return out, [_pop(f) for f in rows]


def _any(marks) -> bool:
    return any(_any(m) for m in marks) if isinstance(marks, list) else bool(marks)


def save(board, node: str, rnd: int, marks) -> None:
    """盤面の gate-marks.json の節の分を今の返答の分で置き換える（周を控える）。決め手が 1 つも無ければ節の分を消し、
    ファイルが無ければ作らない（決め手を書かない役の盤面は今までどおりの姿）"""
    p = pathlib.Path(board) / MARKS_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    if _any(marks):
        doc[node] = {"round": rnd, "marks": marks}
    elif node in doc:
        del doc[node]
    else:
        return
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _saved(b, node: str):
    p = pathlib.Path(b.dir) / MARKS_FILE
    try:
        got = (json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}).get(node) or {}
    except (OSError, ValueError, AttributeError):
        return None
    return got.get("marks") if got.get("round") == b.round else None


def _mark(row: dict, saved, *idx) -> dict:
    """行の決め手: 行が欄を持てばそれ、無ければ盤面の控え（idx の位置）"""
    if any(k in row for k in FIELDS):
        return {k: row[k] for k in FIELDS if k in row}
    try:
        for i in idx:
            saved = saved[i]
    except (TypeError, IndexError, KeyError):
        return {}
    return saved if isinstance(saved, dict) else {}


def decided(mark: dict) -> bool:
    """決め手の出どころが在り、undecided_because が空で、柵の印が無い"""
    return (bool(str(mark.get("decided_by") or "").strip()) and not str(mark.get("undecided_because") or "").strip()
            and not mark.get("fences"))


def plan_gate_items(b) -> list:
    """写しの RL の _plan_gate_items の差し替え: 同じ行を組み、決め手の在る行は項目から外して state.works.gate_passes に残す"""
    rows = []   # (kind, 文, 決め手)
    plan = b.output_of_round("p2.fix_plan", b.round) or {}
    saved = _saved(b, "p2.fix_plan")
    for i, p in enumerate(plan.get("plan") or []):
        rows += [("regression", f"修正案 {i + 1} が狭める能力: {n['what']}——{n['why']}", _mark(n, saved, i, j))
                 for j, n in enumerate(p.get("narrows") or [])]
    saved = _saved(b, "p2.plan_review")
    rows += [(f["kind"], f"事前審査の穴 [{f['kind']}] {f['key']}: {f['why']}", _mark(f, saved, j))
             for j, f in enumerate((b.output_of_round("p2.plan_review", b.round) or {}).get("faces") or [])
             if f["kind"] in b.rules.HUMAN_FACE_KINDS]
    _record(b, [(text, m) for _, text, m in rows if decided(m)])
    return [(kind, text) for kind, text, m in rows if not decided(m)]


def _record(b, passed) -> None:
    kept = b.state.setdefault("works", {}).setdefault("gate_passes", [])
    for text, m in passed:
        row = {"node": "p2.human_gate", "round": b.round, "by": PASSED_BY, "item": text, "decided_by": m["decided_by"]}
        if row not in kept:
            kept.append(row)


def passes(b) -> list:
    return list((b.state.get("works") or {}).get("gate_passes") or [])


def lines(b) -> list:
    """最後の関所の文と報告に載せる、決め手で通した行（1 件 1 行）"""
    return [f"{p['node']}（周 {p['round']}）で決め手が在るので聞かずに通した: {p['item']}（決め手: {p['decided_by']}）"
            for p in passes(b)]
