"""世界の解の行の住処（考え world。地図 docs/concepts.md。計画 docs/plans/2026-10-09-world-solution.md の 5.3 節・5.7 節）。

世界の解の段のブロックが、依頼の行ごとに「問題の類・世の中の定石・依頼の解き方との比べ」を 1 行に書いた JSON Lines（WORLD_FILE）と、
線がその出口を盤面の根に写した控え（STATE_FILE）を読む口の 1 か所。判定・構造の目・修正案・事前審査・関所・報告はここから読み、
行の欄の名と語を自分で持たない。Archon を知らない関数だけを出す。行の形の約束はブロックの行の型（world-row.schema.json）で、
欄と語が FIELDS・VERDICTS・BASES と揃うことは試験 tests/test_worldmark.py が縛る。

行: {finding（依頼の行の番号。1 始まり）, where（その行の where の字のまま）, class_id（問題の類の id。対象の名を持たない）,
problem（問題の類の 1 文）, activity（作業の種類の名）, practice（定石）, sources（[{id, url, excerpt}]。照らして残った抜き書き）,
applies（この依頼にどう当たるか。空なら答えの要らない行）, not_applies, versus（{proposed（依頼の解き方）, verdict, challenge}）,
basis（web: 照らした抜き書きが 1 つ以上・knowledge: 抜き書きが残らず模型の知識だけ）}。
knowledge の行は、頭の節・関所の行に NOT_WEB と名指して並べる（答えと関所の決まりは web の行と同じに掛ける）。

控え: {status: ok|failed, reason, world_file, classes, dropped}（数は類・落とした抜き書き）。段の時間は持たない（流れの道具の
出来事から作れる値は控えに持ち直さない）。

- rows(path)・read(board_dir): 行（読めない・形が違えば ValueError）と控え（無い・読めない・形が違えば None）
- write(board_dir, …)・stage_rows(board_dir): 控えを書く（線の境）・控えが指す行（段が行を出さなかった周を None で分ける＝関所の軸。
  盤面の根から読む判定の支度・修正案の頭・関所が使う。呼び手は None と [] の違いを `stage_rows(d) or []` の 1 式で書く）
- ref_problems(reply, board_dir): 判定の返答の先例の出どころ world:<類の id> が控えの指す行に無い誤りの文（判定の受け付けが拒む）
- section(rows): 判定・修正案・事前審査の頭に貼る節（行が無ければ ""）。修正案の役に行ごとの答えを頼む文は PLAN_ASK
- need(rows)・challenges(rows): 修正案の受け付けに渡す答えの要る行の表（planmarks.Need。答えの仕組みは構造の目の汚れる
  行と同じ 1 つ。行は項目に場所で結ばず、どの項目も答えていない行だけを欠けにする）・類ごとの依頼の解き方との比べの文（事前審査の
  外れの訳に添える）
- needs(row)・answered(item)・unanswered(rows, items): 答えの要る行（applies が空でない）と、修正案の
  項目の欄 structure の答え {world: <類の id>, follows: true} か {world, deviation}
- world_ok(answer, row, own_sources, cite_ok): 関所の軸「世界の解か」（答えの要らない行・従う・依頼の外の出どころで訳の立つ外れ。
  web で確かめていない行（knowledge）は従う答えだけが揃い、外れは人に聞く——計画の 5.5 節「知識だけの定石に従うのは自明側、外れは人へ」）
- gate_line(row, answer)・report_lines(board_dir): 関所の項目と報告の節「世界の解」の行

依頼の解き方（足し欄 means。計画の W6・5.3 節の 1）: 目的の役は目的の文に解き方を書かず、依頼が示した解き方（手段）を役の型の
足し欄 MEANS に分ける。足す・外す・置くの手順は住処 marks（種 means）に任せ、欄の意味（型・読んだ後の使い方）をここが持つ。
目的の文の型は写しのまま。控えは世界の解の段の入力（言い直す役が依頼の解き方として見る）で、独立設計には渡さない（目的だけから設計する）。
- MEANS_NODES・with_means(node, schema)・split_means(reply): 欄を持つ節・役の型に欄を足した写し・（欄を外した返答の写し, 手段の並び）
- write_means(board_dir, means)・means_of(board_dir): 控えを置く（空なら置かない）・読む（無い・読めなければ []）
"""
import json
import pathlib

import cite   # 依頼の引用「…」の形と語（決め手の出どころの照らしの住処）
import marks  # 返答の足し欄の住処（種 means）
import planmarks  # 修正案の欄 structure の答えの仕組み（答えの要る行の表 Need）

WORLD_FILE = "world.jsonl"
STATE_FILE = "world-state.json"
VERDICTS = ("same", "differs", "none")
SAME, DIFFERS, NONE = VERDICTS
BASES = ("web", "knowledge")
WEB, KNOWLEDGE = BASES
NOT_WEB = "web で確かめていない"
FIELDS = ("finding", "where", "class_id", "problem", "activity", "practice", "sources", "applies", "not_applies", "versus",
          "basis")
VERSUS_FIELDS = ("proposed", "verdict", "challenge")
ANSWER_KEY = "world"   # 修正案の項目の欄 structure の答えの行で類の id を持つ鍵
SOURCE_PREFIX = "world:"   # 判定の先例の出どころで世界の行を指す頭の字（world:<類の id>）。ANSWER_KEY とは別の約束
VERDICT_WORDS = {SAME: "定石と同じ", DIFFERS: "定石と違う", NONE: "依頼は解き方を示していない"}
HEAD = "## 世界の解の行（依頼の行ごとの問題の類・世の中の定石・依頼の解き方との比べ）"
PLAN_ASK = ("当たる所の在る行（答えの要る行）は、行ごとにどれかの項目が、定石に従う（{world: <類の id>, follows: true}）"
            "か、従わない訳（{world: <類の id>, deviation: <訳と出どころ>}）を項目の works の欄 structure に書け（どの項目も"
            "答えていない行は受け付けが拒む）。依頼の解き方は定石と比べて疑う案で、決め手にならない——依頼そのものを出どころにした外れは修正前の関所で人に回る。"
            f"「{NOT_WEB}」の行も同じに答える")
STATES = ("ok", "failed")
MEANS = "means"
MEANS_NODES = marks.nodes(MEANS)
MEANS_SCHEMA = {"type": "array", "items": {"type": "string", "minLength": 1},
                "note": "依頼が示した解き方（こう直せという手段）の文の並び。目的の文には書かない。解き方を示さない依頼は書かない"}


# ---------------------------------------------------------------- 読む
def _row_problem(r) -> str:
    if not isinstance(r, dict):
        return "JSON のオブジェクトでない"
    missing = [k for k in FIELDS if k not in r]
    if missing:
        return f"欄が無い {missing}"
    if r["basis"] not in BASES:
        return f"basis が {'・'.join(BASES)} のどれでもない（{r['basis']!r}）"
    v = r["versus"]
    if not isinstance(v, dict) or any(k not in v for k in VERSUS_FIELDS) or v["verdict"] not in VERDICTS:
        return f"versus が {{{', '.join(VERSUS_FIELDS)}}}（verdict は {'・'.join(VERDICTS)}）の形でない"
    if not isinstance(r["sources"], list):
        return "sources が配列でない"
    return ""


def rows(path) -> list:
    if not path:
        raise ValueError("世界の解の行のファイルの名が空")
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"世界の解の行のファイルが読めない: {e}") from None
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        try:
            r = json.loads(line)
        except ValueError as e:
            raise ValueError(f"世界の解の行 {i} が JSON でない: {e}") from None
        bad = _row_problem(r)
        if bad:
            raise ValueError(f"世界の解の行 {i}: {bad}")
        out.append(r)
    return out


def read(board_dir) -> dict | None:
    try:
        doc = json.loads((pathlib.Path(board_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("status") in STATES else None


def write(board_dir, *, status: str, reason: str, world_file: str, classes, dropped) -> pathlib.Path:
    """控えを盤面の根に書く（線の境が 1 回。書けなければ OSError。受ける側が理由にして返す）"""
    path = pathlib.Path(board_dir) / STATE_FILE
    doc = {"status": status, "reason": reason, "world_file": world_file, "classes": classes, "dropped": dropped}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def stage_rows(board_dir) -> list | None:
    """盤面の根の控えが指す行。段が行を出した周（控えが ok。行の無い段は []）だけ並びで、控えが無い・落ちた・行が読めない周は
    None（関所の軸が今どおりの決まりに戻る目印。拒まない）"""
    st = read(board_dir)
    if st is None or st["status"] != "ok":
        return None
    try:
        return rows(st["world_file"]) if st.get("world_file") else []
    except ValueError:
        return None


def ref_problems(reply, board_dir) -> list:
    """判定の返答（reply）の先例 precedents の出どころ source の world:<類の id> が、盤面の根の控えが指す行の class_id に在るかの
    誤りの文の並び（通れば空）。段の行が無い周（控えが無い・落ちた・行が空）の world: は全部宙に浮いた参照として数える。
    world: の無い出どころは見ない"""
    got = reply.get("precedents") if isinstance(reply, dict) else None
    sources = [p.get("source") for p in got if isinstance(p, dict)] if isinstance(got, list) else []
    known = {r["class_id"] for r in stage_rows(board_dir) or []}
    return [p for s in sources for p in cite.ref_problem(s, SOURCE_PREFIX, known)]


# ---------------------------------------------------------------- 依頼の解き方（足し欄 means）
def with_means(node: str, schema: dict) -> dict:
    """役の型に means（任意の欄。古い返答を拒まない）を足した写し（MEANS_NODES でなければそのまま）"""
    return marks.add(MEANS, node, schema, {MEANS: MEANS_SCHEMA})


def split_means(reply) -> tuple:
    """（欄を外した返答の写し, 手段の並び。欄が無ければ []）。dict でない返答はそのまま"""
    if not isinstance(reply, dict):
        return reply, []
    out, got = marks.split(MEANS, MEANS_NODES[0], reply, (MEANS,))
    return out, [m for m in got.get(MEANS) or [] if isinstance(m, str) and m.strip()]


def write_means(board_dir, means) -> None:
    """手段の並びを盤面の根の控えに置く（空なら置かない）"""
    got = [m for m in means or [] if isinstance(m, str) and m.strip()]
    if got:
        marks.write(marks.path_of(MEANS, board_dir), {MEANS: got})


def means_of(board_dir) -> list:
    doc = marks.load(marks.path_of(MEANS, board_dir))
    got = doc.get(MEANS) if isinstance(doc, dict) else None
    return [m for m in got if isinstance(m, str) and m.strip()] if isinstance(got, list) else []


# ---------------------------------------------------------------- 文
def _mark(r: dict) -> str:
    return f"（{NOT_WEB}）" if r.get("basis") != WEB else ""


def _versus(r: dict) -> str:
    v = r.get("versus") or {}
    word = VERDICT_WORDS.get(v.get("verdict"), str(v.get("verdict")))
    head = f"依頼の解き方「{v.get('proposed')}」は{word}" if v.get("proposed") else word
    return f"{head}——{v['challenge']}" if v.get("verdict") == DIFFERS and v.get("challenge") else head


def section(rows) -> str:
    """行の並びから判定・修正案・事前審査の頭の節（行が無ければ ""）"""
    if not rows:
        return ""
    lines = [HEAD, ""]
    for r in rows:
        lines += [f"- 類 {r['class_id']}（依頼の行 {r['finding']}・{r['where']}）: {r['problem']}（作業: {r['activity']}）",
                  f"  - 定石: {r['practice']}{_mark(r)}",
                  *[f"  - 出どころ {s.get('id')}: {s.get('url')}「{s.get('excerpt')}」" for s in r["sources"] if isinstance(s, dict)],
                  f"  - 当たる所: {r['applies'] or '無い（答えの要らない行）'}" + (f"／当たらない所: {r['not_applies']}" if r["not_applies"] else ""),
                  f"  - {_versus(r)}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 答え
def need(rows) -> planmarks.Need:
    """答えの要る行の表（planmarks.structure_gaps が受ける）。行は項目に場所で結ばない（of は空）。どの項目も答えていない行だけを
    欠け（missing）にする"""
    got = [r for r in rows or [] if needs(r)]
    return planmarks.Need(ANSWER_KEY, "世界の解の行", {r["class_id"]: r["practice"] for r in got}, "定石",
                          "答えの要る世界の解の行の類でない", lambda item: [],
                          lambda items: unanswered(got, items))


def challenges(rows) -> dict:
    """{類の id: 依頼の解き方との比べの文}（事前審査の外れの訳に添える）"""
    return {r["class_id"]: _versus(r) for r in rows or [] if isinstance(r, dict) and r.get("class_id")}


def needs(row) -> bool:
    return isinstance(row, dict) and isinstance(row.get("applies"), str) and bool(row["applies"].strip())


def answered(item) -> list:
    rows_ = item.get("structure") if isinstance(item, dict) and isinstance(item.get("structure"), list) else []
    return [a[ANSWER_KEY] for a in rows_ if isinstance(a, dict) and isinstance(a.get(ANSWER_KEY), str)]


def unanswered(rows, items) -> list:
    done = {cid for it in items or [] for cid in answered(it)}
    out = []
    for r in rows or []:
        if needs(r) and r["class_id"] not in done and r["class_id"] not in out:
            out.append(r["class_id"])
    return out


def _from_request(text: str, own_sources) -> bool:
    """決め手の文が依頼（依頼のファイル・目的の文の出典）を出どころにしているか"""
    return any(s and s in text for s in own_sources or ()) or (cite.REQUEST_WORD in text and cite.QUOTE.search(text) is not None)


def world_ok(answer, row, own_sources, cite_ok) -> tuple:
    if not needs(row):
        return True, "答えの要らない行（この依頼に当たる所が無い）"
    if not isinstance(answer, dict):
        return False, f"世界の解の行 {row.get('class_id')} への答えが無い"
    if answer.get("follows") is True:
        return True, "定石に従う"
    text = str(answer.get("decided_by") or answer.get("deviation") or "").strip()
    if not text:
        return False, "定石から外れる訳が無い"
    if row.get("basis") != WEB:
        return False, f"{NOT_WEB}定石からの外れ（定石を照らしていないので、外れてよいかを人に聞く）"
    bad = cite_ok(text)
    if bad:
        return False, bad
    if _from_request(text, own_sources):
        return False, "依頼（依頼のファイル・目的の文の出典）を出どころにした外れ（定石と比べて疑う案なので人に聞く）"
    return True, "依頼の外の出どころで訳の立つ外れ"


def gate_line(row, answer) -> str:
    head = f"世界の解 {row.get('class_id')}（依頼の行 {row.get('finding')}）: 定石「{row.get('practice')}」{_mark(row)}／{_versus(row)}"
    if not isinstance(answer, dict):
        return f"{head}／答えが無い"
    if answer.get("follows") is True:
        return f"{head}／案は定石に従う"
    return f"{head}／案は外れる——{answer.get('deviation')}"


def report_lines(board_dir) -> list:
    st = read(board_dir)
    if st is None:
        return []
    if st["status"] != "ok":
        return [f"- 世界の解の段が落ちた（行なしで進んだ）: {st.get('reason') or '理由の記録が無い'}"]
    try:
        got = rows(st.get("world_file") or "") if st.get("world_file") else []
    except ValueError as e:
        return [f"- 世界の解の行が読めない: {e}"]
    out = [f"- 類 {r['class_id']}（依頼の行 {r['finding']}）: {r['practice']}{_mark(r)}"
           f"（{_versus(r)}）" for r in got]
    out.append(f"- 類 {st.get('classes', len(got))}・落とした抜き書き {st.get('dropped', 0)}")
    return out
