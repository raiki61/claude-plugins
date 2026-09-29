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
- r4_gate_items(rl): 写しの _r4_gate_items の組み手。修正前の関所で人が continue で通した行と種類も本文も同じ行を、修正の後の
  関所（r4.human_gate）で聞き直さず、gate_passes に by human で残す（ADR 0043 の文脈と同じ向き: 答え済みの人の決定を聞き直さない）
- passes(b)・lines(b): 通した行と、最後の関所の文・報告の行

問いの台帳（record.questions）のうち人に聞く状態（検証器の ASKING）の問いも、修正前の関所の項目に 1 件 1 行で載せる（持ち主
2026-09-29。run 119 の人の答え）。人に聞くと名乗る問いが人の口に繋がらないまま、出どころの免除（写しの _owed_units）だけが効いて
いたため。この行は決め手の濾しに掛けない。関所の continue はその問いへの答えで、一言が問いに触れなければ修正役は問いの理由の推しで
直す。一言で「保留: <key>」と名指した問いは答えに数えない。無人の run（入力 unattended）では問いの行を項目に載せない——関所を
開けば無人の殻が stop を返し、問いと関係の無い単位の修正まで飛ぶので、出どころだけを今どおり飛ばして報告の冒頭に並べる。
- asks(b)・answered(b, q)・returned(b): 関所に載せる問い・関所で答えたか・答えで直す義務に戻る単位
- held_lines(b)・returned_lines(b): 最後の関所の文と報告に並べる聞いたままの問い・修正役に渡す義務に戻った単位
- unattended(b)・start_doc(board_dir): 無人の run か・盤面の start の控え（START_FILE の読み手はこれ 1 つ。conflict・report も使う）
- PLAIN・named(node)・eye_named(name, status): 関所の文と報告が主語にする平易な名（内部の名は括弧へ。plan・specblk・境の節・報告が使う）
- LANES_NAME・fell_lanes(b): 独立の目の筋が落ちた文の置き場と読み手（blk-eyes が書き、最後の関所の目の行の下に並ぶ）
- quote(question)・QUOTE_NOTE: 盤面の問いの文を引用として載せる行と、関所で添える答え方の読み替えの 1 行
- head3(happened, decide, push)・pushes(texts)・push_of(texts): 関所の文と報告の冒頭 3 行（起きたこと・決めてほしいこと・推し）と、推しを記録から拾う口
- gate_text(asking, *, run_id, node, record_name): 答えを受ける関所の文（修正前の関所と仕様の関所が呼ぶ 1 つの組み立て）
標準ライブラリと core の answer（L1。答えの行）だけ。
"""
import copy
import json
import pathlib
import re

import answer

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
PASSED_BY_HUMAN = "human"               # 修正の後の関所で、修正前の関所で人が通した行と同じなので聞き直さなかった
GATE_NODE = "p2.human_gate"
R4_GATE_NODE = "r4.human_gate"
# 修正前の関所の行の頭（plan_gate_items と写しの _plan_gate_items が組む形）。r4_gate_items が種類と本文に分ける
NARROW_HEAD = re.compile(r"修正案 \d+ が狭める能力: ")
FACE_HEAD = re.compile(r"事前審査の穴 \[([^\]]+)\] [^\n]*?: ")
CARRIED_HEAD = "## 直す前の関所で人が通した狭まり（機械が貼った）"
CARRIED_ASK = ("下の行は、直す前の関所で人が通すと答えた（continue）。同じ能力の消えを capability_inventory.lost に、同じ方針との"
               "ぶつかりを policy_conflicts に書くなら、[ ] の種類（regression は lost・policy は policy_conflicts）に合わせ、本文を"
               "一字も変えずに写せ。通した条件を超える消え・別の能力は自分の言葉で書け")
ASK_HEAD = "問いの台帳の問い"          # 関所の項目の頭。答えの突き合わせもこの頭と key で引く
ASK_KINDS = ("fork", "escalate")       # 関所の項目の kinds（fork の問いと、status が escalate の問い）
HOLD = re.compile(r"保留\s*[:：]\s*([^。；;\n）)」]+)")   # 一言の「保留: <key>」（文の終わりまで。key を並べてよい）
HOLD_SEP = re.compile(r"[\s、，,・/／]+")   # 並べた key の区切り（関所の文も「・」で並べる）。key は区切りの間の全体で突き合わせる
START_FILE = "r1/start.json"           # 盤面の start の控え（書き手は entry.start。conflict・report も start_doc で読む）
UNATTENDED = "true"                   # 入力 unattended の無人の語（entry.UNATTENDED_WORDS）
ASK_GATE_HEAD = ("判定の役が人に聞くと保留にした問い（問いの台帳）が在る。continue の一言に問いごとに選んだ選択肢を書け。"
                 "一言が問いに触れなければ、修正役はその問いの理由の推しで直す（continue でその問いの出どころ・depends は直す義務に戻る）。"
                 "保留を続けたい問いは一言に「保留: <問いの key>」と書け（複数は「・」で並べてよい。その出どころはこの run では直さず、報告の冒頭に並ぶ）")
# 関所の文と報告が主語にする平易な名（盤面の節 → 流れの図 docs/darkfactory-flow.md の工程の日本語の名）。初めて読む人は盤面の
# 節の名を解けないので、平易な名を主語にし、記録と照らす内部の名は named() が括弧に回す。報告の「見る所」の表もここから引く。
# 図の英語の工程の名はラインの節の id で、層の決まり（下の層はラインの名を書かない）により持たない
PLAIN = {"p2.diagnose": "判定", "p2.fix_plan": "修正案", "p2.plan_review": "事前審査", GATE_NODE: "直す前の関所",
         "p3.fix": "修正", "p3.delta_review": "差分の審査", "p3.delta_fix": "手直し", "p3.delta_review2": "2 回目の審査",
         "p3.delta_fix2": "手直し 2 回目", "p4.ci": "最後のテスト", "r4.human_gate": "独立の目が人に回した問い",
         "spec.approve": "仕様の承認の関所"}
# 独立の目の名 → 何を見る目か（流れの図の 17 項）と、目の判定の状態の語 → 平易な言い方（語は写しの検証器の REVIEW_STATUS）
EYES = {"R1": "直しが最小か・注記が正しいかを見る目", "R2": "独立の設計と構造が合うかを見る目",
        "R3": "前提と全体の筋を見る目", "R4": "依頼の範囲を超えていないかを見る目"}
REVIEW_WORDS = {"pass": "通った", "redesign-needed": "作り直しが要る", "unverifiable": "確かめられない",
                "premise-invalid": "前提が崩れている", "carried_over": "前の周から持ち越した", "not_applicable": "当てはまらない",
                "not_run": "走っていない"}
HANDLED_WORDS = {"fixed": "直した", "declared": "直さずに残すと申告した"}   # 手直しの行の handled の語（写しの graph の enum）
# 独立の目のブロックが Archon の節が落ちた筋とその文を置く作業ファイル（入口の周の箱 r<N>/。書き手は blk-eyes の route・collect、
# 読み手は fell_lanes）。ブロックとラインが名前を写し合わないよう、正本はここ
LANES_NAME = "eyes-lanes.json"


# 盤面の問いの文は写しの規則が本線の道具の書き方（continue --note・--detail）で作り、写しは本線とバイト一致で縛られて直せない。
# 関所の文ではそれを引用として置き、この 1 行で読み替える（--detail は答えの行に口が無い。--exclude は盤面に残るが線は読まない）
QUOTE_NOTE = ("（引用の中の continue --note <…> は本線の道具の書き方。この関所では下の continue の行の一言で答える。"
              "--detail（単位を外す）はこの関所に無い——外したい単位と理由を一言に書けば修正役に届くが、直す義務の数からは外れない）")

# 人が読む関所の文と報告の冒頭 3 行の頭（依頼の「冒頭 3 行で完結」。形は BLUF と本線 report-items.md の冒頭 3 行）
HAPPENED, DECIDE, PUSH = "起きたこと: ", "決めてほしいこと: ", "推し: "
# 推しは機械が作らない: 判定の役が問いの reason に書いた推しだけを拾い、無ければこの言い方（ask_text の項目と同じ）
NO_PUSH = "判定の役が書いていない"
PUSH_IN = re.compile(r"推し\s*[:：]\s*([^／\n]+)")
# 関所の項目の種類（写しの RL の human_gate と gatemarks の問いの kinds）→ 平易な言い方
KIND_WORDS = {"regression": "今ある能力を減らす・狭める変更", "policy": "人の方針とぶつかる変更",
              "policy_changed": "人の方針の文書が変わった", ASK_KINDS[0]: "判定の役が人に聞くと保留にした問い",
              ASK_KINDS[1]: "人でないと決められない問い"}


def quote(question) -> list:
    """盤面の問いの文を引用の行（> ）に。文が無ければそう書く"""
    return [f"> {x}".rstrip() for x in str(question or "").splitlines()] or ["> （問いの文が無い）"]


def named(node) -> str:
    """盤面の節を人が読む名に: 「平易な名（記録の名 <節>）」。表に無い節は「盤面の節（記録の名 <節>）」"""
    return f"{PLAIN.get(str(node), '盤面の節')}（記録の名 {node}）"


def eye_named(name: str, status) -> str:
    """独立の目の 1 行の頭: 「何を見る目（R<n>）: 平易な状態（状態の語）」"""
    return f"{EYES.get(name, '独立の目')}（{name}）: {REVIEW_WORDS.get(str(status), '')}（{status}）"


def fell_lanes(b) -> str:
    """今の周の箱の LANES_NAME の文（独立の目の筋が落ちた理由）。無ければ空"""
    try:
        return str(json.loads((b.dir / f"r{b.round}" / LANES_NAME).read_text(encoding="utf-8")).get("why") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def pushes(texts) -> str:
    """文の列（問いの理由・関所の項目）に判定の役が書いた推しを「；」で繋ぐ。1 つも無ければ NO_PUSH（機械は推しを作らない）"""
    got = [m.strip() for t in texts for m in PUSH_IN.findall(str(t or "")) if m.strip() and m.strip() != NO_PUSH]
    return "；".join(dict.fromkeys(got)) or NO_PUSH


def head3(happened: str, decide: str, push: str, *, other: str = "") -> list:
    """冒頭 3 行: 起きたこと・決めてほしいこと・推し。決めることが無ければ 2 行目に other（次に大事な事実）を置く
    （「無い」と断る決まり文句は書かない。本線 report-items.md の冒頭 3 行の決まり）"""
    return [HAPPENED + happened, DECIDE + decide if decide else other, PUSH + push]


def push_of(texts) -> str:
    """pushes に、推しの無い項目が混じる時の断り（推しの在る項目の推しを全部の項目の推しと読ませない）"""
    got = pushes(texts)
    lacking = [t for t in texts if not PUSH_IN.search(str(t or "")) or PUSH + NO_PUSH in str(t or "")]
    return got + ("（ほかの項目の推しは判定の役が書いていない）" if got != NO_PUSH and lacking else "")


def gate_text(asking: dict, *, run_id: str, node: str, record_name: str) -> str:
    """盤面の問い {node, kinds, question, items, …} を答えを受ける関所の文にする（修正前の関所の plan.gate_text と仕様の関所の
    specblk.gate_text が呼ぶ 1 つの組み立て）。冒頭 3 行（起きたこと＝どの関所に何の項目が何件・決めてほしいこと＝通すか
    止めるか・推し＝項目の問いの理由に判定の役が書いた推し）→ 台帳の問いへの答え方（ASK_GATE_HEAD）→ 問いの文の引用と読み替えの
    1 行（QUOTE_NOTE）→ 項目 1 行ずつ → 答え方（answer.line。一言は record_name の記録に残る）。頭は平易な名で、盤面の節の
    名と種類の語は括弧に回す（named）"""
    if not isinstance(asking, dict):
        raise TypeError(f"盤面の問いが dict でない: {type(asking).__name__}")
    kinds = [str(k) for k in asking.get("kinds") or []]
    items = [str(x) for x in asking.get("items") or []]
    what = "・".join(f"{KIND_WORDS.get(k, '人が決める項目')}（{k}）" for k in kinds) or "人が決める項目"
    ask = bool(set(kinds) & set(ASK_KINDS))   # 写しの問いの文は狭め・後退・方針しか名乗らない
    lines = head3(f"{named(asking.get('node') or node)}が開いた。人が決める項目が {len(items)} 件ある——{what}",
                  "下の項目をこのまま通して直しへ進めるか、止めるか（通すなら通す範囲と条件を一言に書く"
                  + ("。台帳の問いには選ぶ選択肢も一言に書く" if ask else "") + "。打つ行は末尾の答え方）",
                  push_of(items)) + [""]
    if ask:
        lines += [ASK_GATE_HEAD, ""]
    lines += ["問いの文（記録のまま引く）:", *quote(asking.get("question")), QUOTE_NOTE, "", f"項目（{len(items)} 件）:"]
    lines += [f"- {x}" for x in items] or ["- （無し）"]
    lines += ["", "答え方（人が決める関所。依頼者に聞いて、その言葉で答える）:",
              f"- 通す: {answer.line(run_id, 'continue', '<通す範囲と条件>')}（一言は run の記録（記録の名 {record_name}）に残り、"
              "修正役に届く）",
              f"- 止める: {answer.line(run_id, 'stop', '<理由>')}（報告は出る）"]
    return "\n".join(lines) + "\n"


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


def _keep(b, row: dict) -> None:
    kept = b.state.setdefault("works", {}).setdefault("gate_passes", [])
    if row not in kept:
        kept.append(row)


def _record(b, passed) -> None:
    for text, m in passed:
        _keep(b, {"node": GATE_NODE, "round": b.round, "by": PASSED_BY, "item": text, "decided_by": m["decided_by"]})


def _human_passed(b) -> dict:
    """修正前の関所で人が continue で通した行 {(種類, 頭を除いた本文): 答えた周}（台帳の問いの行は数えない）"""
    out = {}
    for h in (b.record.get("process") or {}).get("human_items") or []:
        if not (isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"):
            continue
        for a in h.get("asked") or []:
            m = NARROW_HEAD.match(a) if isinstance(a, str) else None
            f = FACE_HEAD.match(a) if isinstance(a, str) and not m else None
            if m or f:
                out.setdefault(("regression" if m else f.group(1), a[(m or f).end():]), h.get("round"))
    return out


def carried_section(b) -> str:
    """R4（r4.hidden_scope）の指示書の頭に貼る節: 修正前の関所で人が continue で通した行（種類と頭を除いた本文）と、同じ物を書く
    なら本文をそのまま写せという頼み。r4_gate_items は本文の完全一致で照らすので、別の役の自由文を揃える口。無ければ空"""
    rows = [f"- [{kind}] {body}" for kind, body in _human_passed(b)]
    return f"{CARRIED_HEAD}\n\n{CARRIED_ASK}\n\n" + "\n".join(rows) if rows else ""


def r4_gate_items(rl):
    """写しの RL の _r4_gate_items の組み手（board.rl_builder の印で _apply_overrides が開いた RL を渡す）。元の関数の行のうち、
    修正前の関所で人が continue で通した行と種類も頭を除いた本文も同じ物を外し、state.works.gate_passes に by human で残す。
    写しの元は頭込みの文で照らすので、関所ごとに頭の違う同じ狭めを外せない"""
    base, heads = rl._r4_gate_items, {kind: head for kind, _, head in rl.R4_ROWS}

    def items(b):
        passed, out = _human_passed(b), []
        for kind, row in base(b):
            head = heads.get(kind, "")
            key = (kind, row[len(head):]) if row.startswith(head) else None
            if key not in passed:
                out.append((kind, row))
                continue
            _keep(b, {"node": R4_GATE_NODE, "round": b.round, "by": PASSED_BY_HUMAN, "item": row,
                      "passed_at": {"node": GATE_NODE, "round": passed[key]}})
        return out
    return items


def passes(b) -> list:
    return list((b.state.get("works") or {}).get("gate_passes") or [])


def _pass_line(p) -> str:
    if p.get("by") == PASSED_BY_HUMAN:
        at = p.get("passed_at") or {}
        return (f"{named(p['node'])}（周 {p['round']}）で聞き直さなかった——人が通した（周 {at.get('round')}・"
                f"{PLAIN.get(str(at.get('node')), at.get('node'))}）狭まりと同じ: {p['item']}")
    return f"{named(p['node'])}（周 {p['round']}）で決め手が在るので聞かずに通した: {p['item']}（決め手: {p['decided_by']}）"


def lines(b) -> list:
    """最後の関所の文と報告に載せる、決め手で通した行と、修正前の関所で人が通したので聞き直さなかった行（1 件 1 行）"""
    return [_pass_line(p) for p in passes(b)]
