"""判定が凍結した目的の外として単位にしなかった所見を、次の run の依頼へ運ぶ（実の利用者の run f57a5374）。

判定役は目的の外の所見を単位にしない（凍結した目的の決まり。この決まりは変えない）。前は目的の外の所見が判定の framing の散文に
名だけ残り、次の run の依頼の下書き next-request.json には 1 件も載らなかった。利用者は P1 の局所レビューの [block] 3 件を
手で依頼に書き直し、run をもう 1 本回した。

判定役は目的の外の所見を構造の欄 out_of_purpose の行 {source, where, why_outside} で名指す（source＝材料のどの節・どの目の行か、
where＝材料の行の where の写し、why_outside＝目的の外とした理由）。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）
ので、querytest の例の欄と同じく役の型にだけ足し、受け付けが盤面へ渡す前に外して確かめる: where が盤面の材料の行（P1 の節の
出力の where・text を持つ行と、今の周に積まれた依頼の行）のどれにも当たらなければ拒む。通れば当たった材料の行ごと盤面の根の
FILE に周ごとに控え、判定の写し judgment.json に戻す。次の run の依頼（report.next_request）は最後の周に控えた材料の行の全部の欄を、
目的の外から運んだ印 MARK と下書きの印 draft・source つきで載せる（依頼の入口が拒むので、人が見直すまで次の run の目的に
ならない）。この run では直さない。

- FIELD・NODES・ROW_SCHEMA・with_field(node, schema): 欄の名・欄を持つ節・行の型・役の型に欄を足した写し
- split(reply): （欄を外した返答の写し, 行の一覧）
- material_rows(b): 盤面の材料の行 [{where, text, …, from}]（from は出どころの節と目の名）
- problems(rows, material): 行の誤り（形・材料に当たらない where）。1 件 1 文
- save(board_dir, rnd, rows, material)・restore(doc, board_dir, rnd): 周の分を控える・判定の写しに戻す
- next_items(board_dir)・report_lines(board_dir): 次の run の依頼の行・報告の行
標準ライブラリだけ。
"""
import copy
import json
import pathlib

FIELD = "out_of_purpose"
FILE = "out-of-purpose.json"
NODES = ("p2.diagnose",)
MIN_WHY = 10
CARRY_KEYS = ("mechanism", "measured", "false_positive_if")   # 依頼の行の任意の欄（写しの RL の REQUEST_SCHEMA）
MARK = "前の run の判定が凍結した目的の外として単位にしなかった所見を運んだ（この run の目的の内か、別の依頼に分けるかは判定が決める）"
REPORT_HEAD = ("判定が凍結した目的の外として単位にしなかった所見（次の run の依頼の下書きに材料の行の全部の欄で、下書きの印 draft・"
               "source つきで載せた。依頼の入口が拒むので、次の run の目的に入れる行は印を消し、入れない行は消す）")
DRAFT_SOURCE = "前の run の判定が目的の外とした所見"   # next_items の行の source の頭
ROW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["source", "where", "why_outside"],
    "properties": {
        "source": {"type": "string", "minLength": 1, "note": "材料のどの節・どの目の行か（材料の見出しと目の名）"},
        "where": {"type": "string", "minLength": 1, "note": "材料の行の where を一字も変えずに写した物"},
        "why_outside": {"type": "string", "minLength": MIN_WHY, "note": "凍結した目的の外とした理由"},
        "text": {"type": "string", "minLength": 1,
                 "note": "同じ where の材料の行が 2 つ以上在る時だけ、運ぶ行の text の頭を一字も変えずに写した物"},
    },
}


def with_field(node: str, schema: dict) -> dict:
    """役の型に out_of_purpose（任意の欄。古い返答を拒まない）を足した写し（NODES でなければそのまま）"""
    if node not in NODES:
        return schema
    out = copy.deepcopy(schema)
    out.setdefault("properties", {})[FIELD] = {"type": "array", "items": copy.deepcopy(ROW_SCHEMA),
                                               "note": "凍結した目的の外として単位にしなかった材料の所見（次の run の依頼に運ぶ）"}
    return out


def split(reply) -> tuple:
    """（欄を外した返答の写し, 行の一覧。欄が無ければ []）。dict でない返答はそのまま"""
    if not isinstance(reply, dict):
        return reply, []
    out = copy.deepcopy(reply)
    return out, out.pop(FIELD, [])


def _squeeze(v) -> str:
    return " ".join(str(v or "").split())


def _walk(node, origin: str, out: list) -> None:
    if isinstance(node, list):
        for x in node:
            _walk(x, origin, out)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("where"), str) and isinstance(node.get("text"), str):
        out.append({"where": node["where"], "text": node["text"],
                    **{k: node[k] for k in CARRY_KEYS if isinstance(node.get(k), str) and node[k].strip()},
                    "from": origin})
        return
    here = f"{origin} / {node['skill']}" if isinstance(node.get("skill"), str) and node["skill"] else origin
    for v in node.values():
        _walk(v, here, out)


def material_rows(b) -> list:
    """盤面の材料の行: P1 の節（p1.*）の最新の出力の中の where・text を持つ行の全部と、今の周に積まれた依頼の行。
    行は {where, text, 任意の mechanism・measured・false_positive_if, from（出どころの節と目の名）}"""
    out = []
    for nid in sorted((b.state.get("outputs") or {})):
        if nid.startswith("p1."):
            _walk(b.latest_output(nid), nid, out)
    for batch in ((b.record.get("process") or {}).get("request_findings") or []):
        if isinstance(batch, dict) and batch.get("round") == b.round:
            _walk(batch.get("findings") or [], f"依頼（{batch.get('origin') or ''}）", out)
    return out


def _hits(row: dict, material: list) -> list:
    """行が当たる材料の行（where が空白を詰めて等しく、行が text を持てば材料の text がその頭で始まる物。text が全文と等しい
    行が在ればその行だけ）。where と text が同じ材料の行（同じ所見の写し）は 1 つにまとめる"""
    want, head = _squeeze(row.get("where")), _squeeze(row.get("text"))
    seen, out = set(), []
    for m in material:
        key = (_squeeze(m["where"]), _squeeze(m["text"]))
        if key[0] == want and key[1].startswith(head) and key not in seen:
            seen.add(key)
            out.append(m)
    exact = [m for m in out if head and _squeeze(m["text"]) == head]   # 全文を写した行は、それを頭に持つ長い行より先
    return exact or out


def problems(rows, material: list) -> list:
    """out_of_purpose の行の誤り（1 件 1 文）: 配列でない・行が object でない・source が空・why_outside が MIN_WHY 字に満たない・
    where が材料の行のどれにも当たらない（空白は詰めて比べる）・2 行以上に当たる（同じ where の別の所見。text に材料の行の text の
    頭を写して 1 行に絞らせる——where だけで当てると、目的の内で直す行まで目的の外として運ぶ）"""
    if not isinstance(rows, list):
        return [f"{FIELD} が配列でない（{type(rows).__name__}）"]
    out = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            out.append(f"{FIELD}[{i}] が {{source, where, why_outside}} の object でない")
            continue
        if not _squeeze(r.get("source")):
            out.append(f"{FIELD}[{i}] の source が空（材料のどの節・どの目の行かを書く）")
        if len(_squeeze(r.get("why_outside"))) < MIN_WHY:
            out.append(f"{FIELD}[{i}] の why_outside が {MIN_WHY} 字に満たない（凍結した目的の外とした理由を書く）")
        if "text" in r and not _squeeze(r.get("text")):
            out.append(f"{FIELD}[{i}] の text が空（書くなら材料の行の text の頭を写す）")
            continue
        hits = _hits(r, material)
        if not hits:
            out.append(f"{FIELD}[{i}] の where {_squeeze(r.get('where'))!r}"
                       + (f"・text の頭 {_squeeze(r.get('text'))!r}" if "text" in r else "")
                       + " が盤面の材料の行（P1 の所見と依頼の行）のどれにも当たらない（材料の行の where を一字も変えずに写す）")
        elif len(hits) > 1:
            out.append(f"{FIELD}[{i}] の where {_squeeze(r.get('where'))!r} が材料の {len(hits)} 行に当たる（同じ where の別の所見）——"
                       "text に、運ぶ行の text の頭を一字も変えずに写して 1 行に絞る")
    return out


def _read(board_dir) -> dict:
    """控え {"rounds": {周: [行…]}}。無ければ空。読めなければ ValueError"""
    p = pathlib.Path(board_dir) / FILE
    if not p.is_file():
        return {"rounds": {}}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"目的の外の所見の控え {p} が読めない: {e}") from None
    if not (isinstance(doc, dict) and isinstance(doc.get("rounds"), dict)):
        raise ValueError(f"目的の外の所見の控え {p} の形が違う（rounds が要る）")
    return doc


def save(board_dir, rnd: int, rows: list, material: list) -> None:
    """周 rnd の分を今の行で置き換える（行ごとに当たった材料の行 found を添える）。行が無く控えも無ければ書かない"""
    p = pathlib.Path(board_dir) / FILE
    try:
        doc = _read(board_dir)
    except ValueError:   # 読めない控えは書き直さない（前の周の分を黙って消さない。読めないことは next_items・report_lines が言う）
        return
    if not rows and not p.is_file():
        return
    doc["rounds"][str(rnd)] = [{**r, "found": [dict(m) for m in _hits(r, material)]} for r in rows]
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def restore(doc: dict, board_dir, rnd: int) -> dict:
    """判定の写し doc に周 rnd の行（役が書いた形。found は外す）を戻した写し。控えに周が無い・読めなければそのまま"""
    try:
        rows = _read(board_dir)["rounds"].get(str(rnd))
    except ValueError:
        return doc
    if rows is None:
        return doc
    return {**doc, FIELD: [{k: v for k, v in r.items() if k != "found"} for r in rows]}


def _carried(board_dir) -> list:
    """最後の周（数の大きい周）の (行, 材料の行)、同じ材料の行（where・text）は 1 度だけ。判定は周ごとに目的の外を決め直すので、
    前の周に目的の外とした所見が後の周に単位になれば運ばない"""
    doc = _read(board_dir)
    seen, out = set(), []
    last = max(doc["rounds"], key=lambda k: int(k) if str(k).isdigit() else 0, default=None)
    for rnd in [] if last is None else [last]:
        for r in doc["rounds"][rnd] or []:
            if not isinstance(r, dict):
                continue
            for m in r.get("found") or []:
                ok = isinstance(m, dict) and isinstance(m.get("where"), str) and isinstance(m.get("text"), str)
                key = (m["where"], m["text"]) if ok else None
                if key is not None and key not in seen:
                    seen.add(key)
                    out.append((r, m))
    return out


def next_items(board_dir) -> list:
    """次の run の依頼の行: 控えた材料の行の where・text（尾に MARK と出どころと目的の外とした理由）と任意の欄に、下書きの印
    draft: true と出どころ source（DRAFT_SOURCE）を付けた物（依頼の入口 ghreads が拒むので、人が見直して印を消すまで次の run の
    目的にならない。答えの下書きと同じ扱い）。控えが読めなければその 1 行（読めない物を 0 件に見せない。印は付けない）"""
    try:
        got = _carried(board_dir)
    except ValueError as e:
        return [{"where": "判定（目的の外の所見）", "text": f"{_squeeze(e)}——前の run の目的の外の所見を確かめられない"}]
    return [{"where": m["where"],
             "text": f"{m['text'].split(f'（{MARK}')[0]}（{MARK}。出どころ: {_squeeze(r.get('source'))}・目的の外とした理由: "
                     f"{_squeeze(r.get('why_outside'))}）",
             **{k: m[k] for k in CARRY_KEYS if isinstance(m.get(k), str)},
             "draft": True, "source": f"{DRAFT_SOURCE}（{_squeeze(r.get('source'))}）"}
            for r, m in got]


def report_lines(board_dir) -> list:
    """報告の行: 件数の見出しと 1 件 1 行（where と出どころと理由）。無ければ空。読めなければその 1 行"""
    try:
        got = _carried(board_dir)
    except ValueError as e:
        return [f"{REPORT_HEAD}: {_squeeze(e)}"]
    if not got:
        return []
    return [f"{REPORT_HEAD}: {len(got)} 件"] + [
        f"  - {m['where']}（出どころ: {_squeeze(r.get('source'))}・目的の外とした理由: {_squeeze(r.get('why_outside'))}）"
        for r, m in got]
