"""世界の解の行の住処（考え world。地図 docs/concepts.md。計画 docs/plans/2026-10-09-world-solution.md の 5.3 節・5.7 節）。

世界の解の段のブロックが、依頼の行ごとに「問題の類・世の中の定石・依頼の解き方との比べ」を 1 行に書いた JSON Lines（WORLD_FILE）と、
線がその出口を盤面の根に写した控え（STATE_FILE）を読む口の 1 か所。判定・構造の目・修正案・事前審査・関所・報告はここから読み、
行の欄の名と語を自分で持たない。Archon を知らない関数だけを出す。行の形の約束はブロックの行の型（world-row.schema.json）で、
欄と語が FIELDS・VERDICTS・BASES と揃うことは試験 tests/test_worldmark.py が縛る。

行: {finding（依頼の行の番号。1 始まり）, where（その行の where の字のまま）, class_id（問題の類の id。対象の名を持たない）,
problem（問題の類の 1 文）, activity（作業の種類の名）, practice（定石）, sources（[{id, url, excerpt}]。照らして残った抜き書き）,
applies（この依頼にどう当たるか。空なら答えの要らない行）, not_applies, versus（{proposed（依頼の解き方）, verdict, challenge}）,
basis（web: 照らした抜き書きが 1 つ以上・knowledge: 抜き書きが残らず模型の知識だけ）, cached（run をまたぐ控えの類を使ったか）}。
knowledge の行は、頭の節・単位の要点・関所の行・報告に NOT_WEB と名指して並べる（答えと関所の決まりは web の行と同じに掛ける）。

控え: {status: ok|failed, reason, world_file, classes, cached, skipped, dropped}（数は類・控えから使った類・飛ばした依頼の行・
落とした抜き書き）。段の時間は持たない（流れの道具の出来事から作れる値は控えに持ち直さない）。

- rows(path)・read(board_dir): 行（読めない・形が違えば ValueError）と控え（無い・読めない・形が違えば None）
- where_paths(where): 場所の字のパスの形の語（行の番号の尾を落とす）
- section(world_file): 判定・修正案・事前審査の頭に貼る節（行が無ければ ""）
- unit_note(rows, paths): 単位のパスと類の where が重なる行の要点（無ければ ""）
- needs(row)・answered(item)・required(rows, item, inside)・unanswered(rows, items): 答えの要る行（applies が空でない）と、修正案の
  項目の欄 structure の答え {world: <類の id>, follows: true} か {world, deviation}。inside(path, item) は項目の範囲の当て方
  （修正案の範囲の照らしの住処の口を呼び手が渡す。ここから import すると関所の決め手の住処との輪になる）
- world_ok(answer, row, own_sources, cite_ok): 関所の軸「世界の解か」（答えの要らない行・従う・依頼の外の出どころで訳の立つ外れ）
- gate_line(row, answer)・report_lines(board_dir): 関所の項目と報告の行
"""
import json
import pathlib
import posixpath

import cite   # 依頼の引用「…」の形と語（決め手の出どころの照らしの住処）

WORLD_FILE = "world.jsonl"
STATE_FILE = "world-state.json"
VERDICTS = ("same", "differs", "none")
SAME, DIFFERS, NONE = VERDICTS
BASES = ("web", "knowledge")
WEB, KNOWLEDGE = BASES
NOT_WEB = "web で確かめていない"
FIELDS = ("finding", "where", "class_id", "problem", "activity", "practice", "sources", "applies", "not_applies", "versus",
          "basis", "cached")
VERSUS_FIELDS = ("proposed", "verdict", "challenge")
ANSWER_KEY = "world"   # 修正案の項目の欄 structure の答えの行で類の id を持つ鍵
VERDICT_WORDS = {SAME: "定石と同じ", DIFFERS: "定石と違う", NONE: "依頼は解き方を示していない"}
HEAD = "## 世界の解の行（依頼の行ごとの問題の類・世の中の定石・依頼の解き方との比べ）"
STATES = ("ok", "failed")


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


def where_paths(where) -> list:
    out = []
    for m in cite.TOKEN.finditer(str(where or "")):
        tok = m.group(0).split(":", 1)[0].rstrip(".")
        if ("/" in tok or "." in tok) and any(c.isalpha() for c in tok):
            p = posixpath.normpath(tok)
            if p not in out:
                out.append(p)
    return out


# ---------------------------------------------------------------- 文
def _mark(r: dict) -> str:
    return f"（{NOT_WEB}）" if r.get("basis") != WEB else ""


def _versus(r: dict) -> str:
    v = r.get("versus") or {}
    word = VERDICT_WORDS.get(v.get("verdict"), str(v.get("verdict")))
    head = f"依頼の解き方「{v.get('proposed')}」は{word}" if v.get("proposed") else word
    return f"{head}——{v['challenge']}" if v.get("verdict") == DIFFERS and v.get("challenge") else head


def section(world_file) -> str:
    got = rows(world_file) if world_file else []
    if not got:
        return ""
    lines = [HEAD, ""]
    for r in got:
        lines += [f"- 類 {r['class_id']}（依頼の行 {r['finding']}・{r['where']}）: {r['problem']}（作業: {r['activity']}）",
                  f"  - 定石: {r['practice']}{_mark(r)}",
                  *[f"  - 出どころ {s.get('id')}: {s.get('url')}「{s.get('excerpt')}」" for s in r["sources"] if isinstance(s, dict)],
                  f"  - 当たる所: {r['applies'] or '無い（答えの要らない行）'}" + (f"／当たらない所: {r['not_applies']}" if r["not_applies"] else ""),
                  f"  - {_versus(r)}"]
    return "\n".join(lines) + "\n"


def _overlap(a: str, b: str) -> bool:
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def unit_note(rows, paths) -> str:
    mine = [posixpath.normpath(p) for p in paths or [] if isinstance(p, str) and p]
    hit = [r for r in rows or [] if any(_overlap(w, p) for w in where_paths(r.get("where")) for p in mine)]
    if not hit:
        return ""
    return "世界の解: " + "／".join(f"{r['class_id']}: {r['practice']}{_mark(r)}（{_versus(r)}）" for r in hit)


# ---------------------------------------------------------------- 答え
def needs(row) -> bool:
    return isinstance(row, dict) and isinstance(row.get("applies"), str) and bool(row["applies"].strip())


def answered(item) -> list:
    rows_ = item.get("structure") if isinstance(item, dict) and isinstance(item.get("structure"), list) else []
    return [a[ANSWER_KEY] for a in rows_ if isinstance(a, dict) and isinstance(a.get(ANSWER_KEY), str)]


def required(rows, item, inside) -> list:
    out = []
    for r in rows or []:
        if needs(r) and r["class_id"] not in out and any(inside(p, item) for p in where_paths(r.get("where"))):
            out.append(r["class_id"])
    return out


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
    out = [f"- 類 {r['class_id']}（依頼の行 {r['finding']}）: {r['practice']}{_mark(r)}（{_versus(r)}）" for r in got]
    out.append(f"- 類 {st.get('classes', len(got))}・控えから使った類 {st.get('cached', 0)}・飛ばした行 {st.get('skipped', 0)}"
               f"・落とした抜き書き {st.get('dropped', 0)}")
    return out
