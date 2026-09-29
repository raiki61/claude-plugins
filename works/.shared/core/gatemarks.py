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

問いの台帳（record.questions）のうち人に聞く状態（検証器の ASKING）の問いも、修正前の関所の項目に 1 件 1 行で載せる（持ち主
2026-09-29。run 119 の人の答え）。人に聞くと名乗る問いが人の口に繋がらないまま、出どころの免除（写しの _owed_units）だけが効いて
いたため。この行は決め手の濾しに掛けない。関所の continue はその問いへの答えで、一言が問いに触れなければ修正役は問いの理由の推しで
直す。一言で「保留: <key>」と名指した問いは答えに数えない。無人の run（入力 unattended）では問いの行を項目に載せない——関所を
開けば無人の殻が stop を返し、問いと関係の無い単位の修正まで飛ぶので、出どころだけを今どおり飛ばして報告の冒頭に並べる。
- asks(b)・answered(b, q)・returned(b): 関所に載せる問い・関所で答えたか・答えで直す義務に戻る単位
- held_lines(b)・returned_lines(b): 最後の関所の文と報告に並べる聞いたままの問い・修正役に渡す義務に戻った単位
- unattended(b)・start_doc(board_dir): 無人の run か・盤面の start の控え（START_FILE の読み手はこれ 1 つ。conflict・report も使う）
標準ライブラリだけ。
"""
import copy
import json
import pathlib
import re

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
GATE_NODE = "p2.human_gate"
ASK_HEAD = "問いの台帳の問い"          # 関所の項目の頭。答えの突き合わせもこの頭と key で引く
ASK_KINDS = ("fork", "escalate")       # 関所の項目の kinds（fork の問いと、status が escalate の問い）
HOLD = re.compile(r"保留\s*[:：]\s*([^。；;\n）)」]+)")   # 一言の「保留: <key>」（文の終わりまで。key を並べてよい）
HOLD_SEP = re.compile(r"[\s、，,・/／]+")   # 並べた key の区切り（関所の文も「・」で並べる）。key は区切りの間の全体で突き合わせる
START_FILE = "r1/start.json"           # 盤面の start の控え（書き手は entry.start。conflict・report も start_doc で読む）
UNATTENDED = "true"                   # 入力 unattended の無人の語（entry.UNATTENDED_WORDS）
ASK_GATE_HEAD = ("判定の役が人に聞くと保留にした問い（問いの台帳）が在る。continue の一言に問いごとに選んだ選択肢を書け。"
                 "一言が問いに触れなければ、修正役はその問いの理由の推しで直す（continue でその問いの出どころ・depends は直す義務に戻る）。"
                 "保留を続けたい問いは一言に「保留: <問いの key>」と書け（複数は「・」で並べてよい。その出どころはこの run では直さず、報告の冒頭に並ぶ）")


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
    items = [(kind, text) for kind, text, m in rows if not decided(m)]
    if not unattended(b):
        items += [(_ask_kind(q), ask_text(q)) for q in asks(b) if not answered(b, q)]
    return items


def unattended(b) -> bool:
    """run が無人で回っている（start の控えの unattended。読めなければ人の居る run）"""
    return start_doc(b.dir).get("unattended") == UNATTENDED


def start_doc(board_dir) -> dict:
    """盤面の start の控え（読めない・dict でなければ空の dict）"""
    try:
        doc = json.loads((pathlib.Path(board_dir) / START_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _asking(b) -> list:
    qs = [q for q in (b.record.get("questions") or []) if isinstance(q, dict)]
    if not qs:
        return []
    states = b.rules.validator_module(b).ASKING
    return [q for q in qs if q.get("status") in states]


def asks(b) -> list:
    """関所に載せる問い: 人に聞く状態の fork と、status が escalate の問い（写しの _owed_units・_precedent_errors と同じ選び方）"""
    return [q for q in _asking(b) if q.get("kind") == "fork" or q.get("status") == "escalate"]


def _ask_kind(q) -> str:
    return ASK_KINDS[0] if q.get("kind") == "fork" else ASK_KINDS[1]


def _skips(q) -> list:
    return [k for k in [q.get("origin"), *(q.get("depends") or [])] if isinstance(k, str) and k]


def _prefix(q) -> str:
    return f"{ASK_HEAD} {q.get('key')}（"


def ask_text(q) -> str:
    """関所の項目の 1 行: 問い・選択肢・推し（判定の役が reason に書く）・答えが無いと直さない単位"""
    reason = str(q.get("reason") or "")
    return (f"{_prefix(q)}{q.get('kind')}・{q.get('status')}）: {reason}"
            + ("" if "推し" in reason else "／推し: 判定の役が書いていない")
            + f"／選択肢: {'・'.join(str(o) for o in q.get('options') or []) or '（無し）'}"
            + f"／答えが無いと直さない単位: {'・'.join(_skips(q)) or '（無し）'}")


def answered(b, q) -> bool:
    """修正前の関所の continue がこの問いの行を聞いていて、一言が「保留: <key>」と名指していない"""
    key = str(q.get("key") or "")
    for h in (b.record.get("process") or {}).get("human_items") or []:
        if not (isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"):
            continue
        if not any(isinstance(a, str) and a.startswith(_prefix(q)) for a in h.get("asked") or []):
            continue
        note = str(h.get("note") or "")
        if key not in {k for m in HOLD.findall(note) for k in HOLD_SEP.split(m)}:
            return True
    return False


def returned(b) -> set:
    """関所で答えた fork の出どころ・depends（写しの _owed_units が外した単位のうち、直す義務に戻す物）"""
    return {k for q in asks(b) if q.get("kind") == "fork" and answered(b, q) for k in _skips(q)}


def returned_lines(b) -> list:
    """修正役に渡す行: 関所で答えた問いと、それで直す義務に戻った単位（1 問 1 行）"""
    return [f"関所で答えた{ASK_HEAD} {q.get('key')} の出どころ・depends は直す義務に戻った（fork の出どころとして飛ばさない）: "
            f"{'・'.join(_skips(q))}——一言に案が無ければ問いの理由の推しで直す（問いの理由: {q.get('reason') or ''}）"
            for q in asks(b) if q.get("kind") == "fork" and answered(b, q) and _skips(q)]


def held_lines(b) -> list:
    """最後の関所の文と報告の冒頭に並べる、台帳で人に聞く状態のままの問い（kind を問わず。1 件 1 行）"""
    out = []
    for q in _asking(b):
        mark = "・関所で continue を受けた" if q in asks(b) and answered(b, q) else ""
        out.append(f"{_prefix(q)}{q.get('kind')}・{q.get('status')}{mark}）: {q.get('reason') or ''}"
                   + (f"／答えが無いと直さない単位: {'・'.join(_skips(q))}" if _skips(q) else ""))
    return out


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
