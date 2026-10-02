"""食い違いの申し出（修正役と TDD の輪の役の出口。持ち主 2026-09-28「おしで」）。

緑にするためにテスト・依頼・コードのどれかを曲げる代わりに、役は「どちらも同時には成り立たない」を証拠つきで返してよい
（ImpossibleBench arXiv 2510.20270: 食い違いを申し出る道を明示すると、テストを曲げる不正が 54% から 9% に減った）。
申し出は拒否に数えず、その単位だけを止め（parked）、ほかの単位は進む。止めた単位は読むだけの裁定役が、持ち主の決まり
（principles）で fix_test_scope・fix_code_as・ask_human・replace_query・fix_plan_item のどれかに裁き、ask_human だけが最後の人の
関所に届く。fix_plan_item は承認済みの修正案の項目そのものの誤りで、その単位はこの run では直さず（直す義務から外す）、次の run の
修正案で項目を直して事前審査に掛ける。範囲 limits を持たず、テストの変更の許しを作らない（直す裁定 FIX_DECISIONS に入れない）。
判定者の問い（class_query）が直した後の正しい形にも当たる時は、which_is_right: query と正しい行（correct_lines）で申し出て、
裁定 replace_query が新しい問いを例（hits・misses と correct_lines）で機械に試させてから置き換える（Semgrep の規則の試験の ruleid・ok）。

この模块が持つ物（盤面の今の周の作業ファイル b.work(FILE) {"items": [...]} と trace の行。どのブロック・ラインの名も書かない）:
- ITEM_SCHEMA・CONFLICTS_SCHEMA: 1 件の形（unit_key・between・why_both_cannot_hold・which_is_right・kind。query なら correct_lines も）と、
  修正役の返答の欄 conflicts。kind は食い違いの起きた場面の種類で、DIV_KINDS の 6 つ（brief_vs_judgment・unnamed_test_broke・
  not_red・scope_needed・query_hits_fixed・needs_context）のどれか。which_is_right（どちらが正しいか）とは別の軸で、
  query_hits_fixed は which_is_right query と対、needs_context は which_is_right unknown と対
- WORD: superpowers の実装役の状態の語（NEEDS_CONTEXT・BLOCKED）を読み替える works の語（216 の seams.json の words の値と同じ綴り）。
  この語に読み替えた出口は conflicts[] の 1 件で、kind は役が DIV_KINDS から選ぶ。機械は状態の語から種類を推さない
- problems(items, repo=, board_dir=, owed=, try_query=, briefs=): 機械の確かめ。形・義務の単位か・重なり・名指した所が在るか
  （<パス>:<行>。依頼の行・テストの行・コードの行が現物に在る）・query の申し出の correct_lines に判定者の問いが当たるか・kind が
  DIV_KINDS のどれかで which_is_right と対になるか・brief_vs_judgment ならその単位の brief の行を between に名指すか（briefs は
  planbrief.by_unit_at の形 {unit_key: [{item, file}]}。None と {} は brief の無い run）。文の一覧（空なら通る）
- cite_problem(cite, repo, roots): 1 つの名指しの確かめ
- brief_cite_problem(key, cites, repo, briefs, what, field): brief を誤りと言う物（申し出 brief_vs_judgment・裁定 fix_plan_item の
  grounds）が、その単位の brief の行を名指すかの確かめ（1 つの決まり）
- park(b, items, source=, ruling=None): 止めた単位を盤面の作業ファイルに積み、trace に 1 行（同じ申し出は積み増さない）
- items(b)・unruled(b)・asked(b)・ruled_fix(b)・asked_keys(b)・replanned(b)・replanned_keys(b)・replaced_queries(b)・counts(b)・
  kind_counts(b): 読む口
- held_by_rulings(b)・ruled_units(row): 直す義務から外す単位と理由。決まりは「直す裁定（FIX_DECISIONS）でない裁定は、それが外す
  単位（申し出の単位と、fix_plan_item ならその項目に載る単位の全部）を直させない」の 1 つ
  （kind の無い前の形の控えの行も読む。種類は「無し」）
- apply_rulings(b, rulings, by=): 裁定を積み、trace に 1 行、裁定の文のファイル（RULINGS_FILE。修正役に reason_file で渡す）を書く。
  fix_plan_item の裁定は、受け付けた機械が欄 plan_items（その単位の brief の項目の番号）と plan_units（その項目に載る単位の全部）を
  足して渡す
- owed_units_but_asked(b): 写しの RL の _owed_units の差し替え（答えていない fork・escalate の問いの出どころを外し、修正前の関所で
  答えた問いの出どころを直す義務に戻し、直す裁定でない裁定（ask_human・fix_plan_item）を受けた単位を直す義務から外す。
  entry.CORE_OVERRIDES）
- test_permits(b, rulings=, source=, skip_ids=): テストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲）の
  唯一の元。凍結の検査と最後の関所はここから引く。source を渡すと、修正案の行の範囲をその木でテストの id から引き直す。
  skip_ids に並べた id の修正案の行は外す（TDD の輪が赤→緑を確かめた書き換え。輪の後に書き換えさせない）。
  修正案の欄の控え plan-fields.json が凍結の印と食い違えば（planmarks.FieldsBroken）、許しを引かずに盤面を止めて
  （by FIELDS_STOP_BY）控えを名指す理由の BoardGap
- frozen_fields(b): 今の周の凍結した修正案の欄の並び（TDD の輪が単位の約束を組む元）。食い違いは test_permits と同じ 1 か所の
  文で盤面を止めて BoardGap
- ruled_test_doc(b): テストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲。test_permits）が名指した
  テストのファイルを、守りのファイルの一覧（protect）の形にした物（最後の関所に出す）
- fix_duty(b)・excused_units(b)・nothing_owed_but_excused(b): 直す義務と、そこから外れた単位と理由（答え待ちの fork・escalate の
  出どころ・depends と held_by_rulings）を 1 回で返す正本（blk-fix の受け付け・TDD の輪が読む）。義務が空で外れた単位が在れば空の
  changes を止めない（blk-fix の assert-changed と recount.collect）
- ruled_test_limits(b, rulings=, source=, skip_ids=)・parse_limit(lim): テストの変更の許し（承認済みの修正案の rewrite_tests と裁定
  fix_test_scope の範囲。test_permits）の範囲の文字列と、その 1 つの読み（TDD の輪の凍結が範囲の中の直しを通す）
- human_lines(b): 最後の関所と報告に載せる ask_human の行
標準ライブラリだけ。期限は持たない。
"""
import json
import os
import pathlib
import posixpath
import re
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import board as _board  # noqa: E402
import gatemarks  # noqa: E402
import planmarks  # noqa: E402  （planmarks は conflict・entry を読まないので輪にならない）
from engine.util import Reject  # noqa: E402  （board が写しの engine を sys.path に足す）

FILE = "conflicts.json"                 # 盤面の今の周の作業ファイル {"items": [...]}
RULINGS_FILE = "conflict-rulings.md"    # 裁定の文（修正役が 2 回目の起動の 1 行目で Read する。R44）
PARKED_REPLY = "fix-parked-reply.json"  # 申し出を返した回の修正役の返答（裁定の後の出し直しで読む）
KIND_FIELD = "kind"                      # 申し出の種類の欄（食い違いの起きた場面。which_is_right とは別の軸）
FIELDS = ("unit_key", "between", "why_both_cannot_hold", "which_is_right", KIND_FIELD)
CORRECT = "correct_lines"               # which_is_right: query の時だけ要る欄（直した後の正しい行の写し）
QUERY = "query"                         # 判定者の class_query が直した後の正しい形にも当たる
REPLACE = "replace_query"               # 問いを置き換える裁定（新しい問いを hits・misses と申し出の correct_lines で試す）
ASK = "ask_human"
REPLAN = "fix_plan_item"                # 案の項目そのものが誤りと裁く（この run では直さず、次の run の修正案と事前審査へ）
DECISIONS = ("fix_test_scope", "fix_code_as", ASK, REPLACE, REPLAN)
FIX_DECISIONS = ("fix_test_scope", "fix_code_as", REPLACE)   # 直す裁定（REPLAN は直さないので入れない）
PLAN_ITEMS = "plan_items"               # 盤面の裁定の行に機械が足す欄（REPLAN の単位の brief の項目の番号）
PLAN_UNITS = "plan_units"               # 同じく機械が足す欄（PLAN_ITEMS の項目に載る単位の全部。held_by_rulings が外す）
MIN_WHY = 10
MIN_CITES = 2
MAX_LINES = 20
# 申し出の種類（kind の値。設計の 4 つと、今の道を残す 2 つ）
BRIEF_VS_JUDGMENT = "brief_vs_judgment"     # brief と、判定・依頼・人が答えた条件が食い違う
UNNAMED_TEST_BROKE = "unnamed_test_broke"   # 名指していない既存のテストが、直すと落ちる・外すしかない
NOT_RED = "not_red"                         # 受け入れのテスト・名指しの書き換えが、案どおりに書いても赤にならない
SCOPE_NEEDED = "scope_needed"               # brief や案の範囲の外を触らないと緑にならない・問いの数え直しが閉じない
QUERY_HITS_FIXED = "query_hits_fixed"       # 判定の問いが直した後の正しい形にも当たる（which_is_right query と対）
NEEDS_CONTEXT = "needs_context"             # 材料から決められず人か依頼の答えが要る（which_is_right unknown と対）
DIV_KINDS = (BRIEF_VS_JUDGMENT, UNNAMED_TEST_BROKE, NOT_RED, SCOPE_NEEDED, QUERY_HITS_FIXED, NEEDS_CONTEXT)
UNKNOWN = "unknown"                     # which_is_right: どれが正しいか決められない（needs_context の対）
WHICH = ("request", "test", "code", UNKNOWN, QUERY)
UNSET = "unset"                         # kind_counts の鍵: kind の無い前の形の行
WORD = "divergence"                     # superpowers の状態の語を読み替える works の語（216 の seams.json の words と同じ綴り）
KIND = "conflict"                       # process.human_items の行の kinds（申し出の種類 KIND_FIELD とは別物）
BY = "works:conflict"                   # その行の node と、答えの無いまま止めた by
HEAD = "食い違いの申し出"                # 最後の関所の文の節の見出し・報告の行の頭
RULED_TEST_ID = "conflict-ruling"       # 裁定が許したテストの変更を守りのファイルの行にする時の id の頭
PLAN_TEST_ID = "plan-rewrite"           # 承認済みの修正案が名指した既存テストの書き換えを守りのファイルの行にする時の id の頭
FIELDS_STOP_BY = "works:fix"            # 修正案の欄の控えが凍結と食い違った盤面を止めた口（blk-fix の brief の止めと同じ修正の段の印）
FIELDS_TAMPERED = f"承認済みの修正案の欄の控え（盤面の {planmarks.FIELDS_FILE}）が受け付けの後に書き換えられた。"
FIELDS_BROKEN = FIELDS_TAMPERED + "テストの変更の許しを引かずに止めた"   # 修正の段（by FIELDS_STOP_BY）の止めの文
PARK_OP, RULE_OP = "conflict_parked", "conflict_ruled"   # trace の行
CITE = re.compile(r"^(?P<path>.+?):(?P<a>[1-9][0-9]*)(?:-(?P<b>[1-9][0-9]*))?$")

ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(FIELDS),
    "properties": {
        "unit_key": {"type": "string", "minLength": 1},
        "between": {"type": "array", "minItems": MIN_CITES, "items": {"type": "string", "minLength": 3}},
        "why_both_cannot_hold": {"type": "string", "minLength": MIN_WHY},
        "which_is_right": {"type": "string", "enum": list(WHICH)},
        KIND_FIELD: {"type": "string", "enum": list(DIV_KINDS)},
        CORRECT: {"type": "array", "minItems": 1, "maxItems": MAX_LINES, "items": {"type": "string", "minLength": 1}},
    },
}
CONFLICTS_SCHEMA = {"type": "array", "items": ITEM_SCHEMA}
_LINES = {"type": "array", "maxItems": MAX_LINES, "items": {"type": "string", "minLength": 1}}
RULING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "decision", "text", "limits"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "text": {"type": "string", "minLength": MIN_WHY},
        "limits": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "grounds": {"type": "array", "items": {"type": "string", "minLength": 3}},
        "request_searched": {"type": "string", "minLength": MIN_WHY},
        "query": {
            "type": "object",
            "additionalProperties": False,
            "required": ["how", "counts", "hits", "misses"],
            "properties": {
                "how": {"type": "object"},
                "counts": {"type": "string", "enum": ["defects", "population"]},
                "hits": {**_LINES, "minItems": 1},
                "misses": _LINES,
            },
        },
    },
}


# ---------------------------------------------------------------- 名指しの確かめ
start_doc = gatemarks.start_doc   # 盤面の start の控えの読み手は 1 つ（gatemarks も無人の run かを読む。conflict ⇄ gatemarks の輪を作らない）


def change_only(board_dir) -> bool:
    """ラインの盤面が、依頼を持たずに変更から入った run か（start の控えの entry が change）。
    依頼を読むブロックの intake はこの run でだけ空の依頼を受ける（ブロックを単独で回した時・依頼の在る run の空は今までどおり欠け）"""
    return start_doc(board_dir).get("entry") == "change"


def request_file(board_dir) -> str:
    """run の依頼のファイル（盤面の start の控えの request_file。無ければ空）"""
    got = start_doc(board_dir).get("request_file")
    return got if isinstance(got, str) else ""


def change_only(board_dir) -> bool:
    """ラインの盤面が、依頼を持たずに変更から入った run か（start の控えの entry が change）。
    依頼を読むブロックの intake はこの run でだけ空の依頼を受ける（ブロックを単独で回した時・依頼の在る run の空は今までどおり欠け）"""
    return start_doc(board_dir).get("entry") == "change"


def _inside(p: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def cite_problem(cite, repo, roots=()) -> str:
    """名指し `<パス>:<行>` か `<パス>:<行>-<行>` の確かめ（通れば空）。相対のパスは作業ツリーの根から（外と .git は拒む）、
    絶対のパスは作業ツリーの中か roots（依頼のファイル・盤面の置き場）の中だけ。ファイルが在り、行がその中に在る"""
    if not isinstance(cite, str):
        return f"名指し {cite!r} が文字列でない"
    m = CITE.match(cite.strip())
    if not m:
        return f"名指し {cite!r} が <パス>:<行> の形でない（例 tests/test_x.py:12・src/x.py:30-34・依頼のファイルの絶対パス:3）"
    a, b = int(m["a"]), int(m["b"] or m["a"])
    if b < a:
        return f"名指し {cite!r} の行の範囲が逆"
    repo = pathlib.Path(repo).resolve()
    raw = pathlib.Path(m["path"])
    p = (raw if raw.is_absolute() else repo / raw).resolve()
    allowed = [repo] + [pathlib.Path(r).resolve() for r in roots if r]
    if not any(p == r or _inside(p, r) for r in allowed) or _inside(p, repo / ".git"):
        return f"名指し {cite!r} のパスが作業ツリー・依頼のファイル・盤面の外"
    if not p.is_file():
        return f"名指し {cite!r} のファイルが無い"
    try:
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError as e:
        return f"名指し {cite!r} のファイルが読めない（{type(e).__name__}）"
    if b > n:
        return f"名指し {cite!r} の行がファイルに無い（{n} 行しか無い）"
    return ""


def _correct_problem(it, try_query) -> str:
    """which_is_right: query の申し出の correct_lines の確かめ（通れば空）。try_query(unit_key, lines) が渡れば、判定者の問いを
    その行に当てた結果の文（当たれば空）を足す"""
    lines = it.get(CORRECT)
    if it["which_is_right"] != QUERY:
        return f"{CORRECT} は which_is_right が {QUERY} の時だけ書く" if CORRECT in it else ""
    if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES \
            or not all(isinstance(x, str) and x.strip() for x in lines):
        return (f"which_is_right が {QUERY} なら {CORRECT} に、判定者の問いが当たってしまう直した後の正しい行を 1〜{MAX_LINES} 行"
                "写す（機械が問いを当てて確かめる）")
    return try_query(it["unit_key"], lines) if try_query else ""


def _kind_problem(it, at) -> str:
    """種類の欄 kind の確かめ（通れば空。外れなら at を頭に入れた仕上がりの文）: DIV_KINDS のどれかで、query_hits_fixed ⇔
    which_is_right query、needs_context なら which_is_right unknown。外れの文は両方の欄を名指す（修正役の受け付けと TDD の輪が
    同じ文を返す）"""
    kind, which = it.get(KIND_FIELD), it.get("which_is_right")
    if kind not in DIV_KINDS:
        return f"{at} の {KIND_FIELD} は {' / '.join(DIV_KINDS)} のどれか（{kind!r}）"
    if (kind == QUERY_HITS_FIXED) != (which == QUERY):
        return (f"{at}: {KIND_FIELD} {QUERY_HITS_FIXED} と which_is_right {QUERY} は対で書く"
                f"（{KIND_FIELD} {kind}・which_is_right {which}）")
    if kind == NEEDS_CONTEXT and which != UNKNOWN:
        return f"{at}: {KIND_FIELD} {NEEDS_CONTEXT} の which_is_right は {UNKNOWN}（{KIND_FIELD} {kind}・which_is_right {which}）"
    return ""


def brief_cite_problem(key, cites, repo, briefs, what: str, field: str) -> str:
    """brief を誤りと言う物（申し出 brief_vs_judgment・裁定 fix_plan_item）の確かめの 1 つの決まり（通れば空。外れなら what と
    field を名指す文）: 単位 key に brief が在り（briefs は planbrief.by_unit_at の形。None と {} は brief の無い run）、名指しの並び
    cites（欄 field）のどれか 1 つのパスがその単位の brief のファイルのどれかと同じ。名指しの行がファイルに在るかは cite_problem が見る"""
    rows = ((briefs or {}).get(key) or []) if isinstance(key, str) else []
    files = [r["file"] for r in rows if isinstance(r, dict) and isinstance(r.get("file"), str)]
    if not files:
        return f"{what} は brief の在る単位だけ（{key} に brief が無い——修正案の無い run には brief が無い）"
    want = {pathlib.Path(f).resolve() for f in files}
    root = pathlib.Path(repo).resolve()
    for c in cites if isinstance(cites, list) else []:
        m = CITE.match(c.strip()) if isinstance(c, str) else None
        if m:
            raw = pathlib.Path(m["path"])
            if (raw if raw.is_absolute() else root / raw).resolve() in want:
                return ""
    return f"{what} の {field} に、この単位の brief の行（{' か '.join(files)}:<行>）が無い"


def _brief_problem(it, at, repo, briefs) -> str:
    """kind brief_vs_judgment の確かめ（通れば空。外れなら at を頭に入れた仕上がりの文）: between がその単位の brief の行を
    名指す（brief_cite_problem）"""
    if it.get(KIND_FIELD) != BRIEF_VS_JUDGMENT:
        return ""
    bad = brief_cite_problem(it.get("unit_key"), it.get("between"), repo, briefs, f"kind {BRIEF_VS_JUDGMENT}", "between")
    return f"{at}: {bad}" if bad else ""


def problems(items, *, repo, board_dir, owed, try_query=None, briefs=None) -> list:
    """申し出の一覧の機械の確かめ（受け付けの前）。文の一覧（空なら全部通る）。try_query(unit_key, lines) は which_is_right: query
    の申し出の correct_lines に判定者の問いを当てる口（呼ぶ側が渡す。当たれば空・外れれば文）。briefs は今の周の brief の行
    {unit_key: [{item, file}]}（planbrief.by_unit_at。None と {} は brief の無い run で、brief_vs_judgment を通さない）"""
    if not isinstance(items, list) or not items:
        return ["食い違いの申し出は 1 件以上の配列"]
    roots = [request_file(board_dir), str(board_dir)]
    out, seen = [], set()
    for i, it in enumerate(items):
        at = f"食い違い[{i}]"
        if not isinstance(it, dict) or set(it) - {*FIELDS, CORRECT} or any(k not in it for k in FIELDS):
            out.append(f"{at} の欄は {list(FIELDS)}（which_is_right が {QUERY} の時は {CORRECT} も）")
            continue
        k = it["unit_key"]
        if k not in owed:
            out.append(f"{at} の unit_key {k!r} は今の直す義務の単位に無い（貼られた単位の key を一字も変えずに写す）")
        elif k in seen:
            out.append(f"{at} の unit_key {k!r} を 2 度申し出た（1 単位 1 件。名指しを between に並べる）")
        seen.add(k)
        if not isinstance(it["why_both_cannot_hold"], str) or len(it["why_both_cannot_hold"].strip()) < MIN_WHY:
            out.append(f"{at} の why_both_cannot_hold が {MIN_WHY} 字に足りない（なぜ両方は同時に成り立たないか）")
        if it["which_is_right"] not in WHICH:
            out.append(f"{at} の which_is_right は {' / '.join(WHICH)} のどれか（{it['which_is_right']!r}）")
        else:
            bad = _correct_problem(it, try_query)
            if bad:
                out.append(f"{at}: {bad}")
        bad = _kind_problem(it, at) or _brief_problem(it, at, repo, briefs)
        if bad:
            out.append(bad)
        cites = it["between"]
        if not isinstance(cites, list) or len(cites) < MIN_CITES:
            out.append(f"{at} の between は食い違う所を {MIN_CITES} つ以上（依頼の行・テストのファイル:行・コードのファイル:行）")
            continue
        out += [f"{at}: {e}" for e in (cite_problem(c, repo, roots) for c in cites) if e]
    return out


# ---------------------------------------------------------------- 盤面の作業ファイル
def _path(b) -> pathlib.Path:
    return b.work(FILE)


def _load(b) -> dict:
    try:
        doc = json.loads(_path(b).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"items": []}
    except (OSError, ValueError) as e:
        raise _board.BoardGap(f"食い違いの控え {_path(b)} が読めない: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise _board.BoardGap(f"食い違いの控え {_path(b)} の形が違う（{{items: [...]}}）")
    return doc


def _write(path: pathlib.Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _save(b, doc) -> None:
    _write(_path(b), json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def items(b) -> list:
    return list(_load(b)["items"])


def unruled(b) -> list:
    return [i for i in items(b) if i.get("ruling") is None]


def asked(b) -> list:
    return [i for i in items(b) if (i.get("ruling") or {}).get("decision") == ASK]


def ruled_fix(b) -> list:
    return [i for i in items(b) if (i.get("ruling") or {}).get("decision") in FIX_DECISIONS]


def asked_keys(b) -> set:
    return {i["unit_key"] for i in asked(b)}


def replanned(b) -> list:
    """裁定が fix_plan_item の行（案の項目の誤り。この run では直さない）"""
    return [i for i in items(b) if (i.get("ruling") or {}).get("decision") == REPLAN]


def replanned_keys(b) -> set:
    """fix_plan_item が外す単位の全部（申し出の単位と、その項目の単位）"""
    return {k for i in replanned(b) for k in ruled_units(i)}


def ruled_units(row) -> list:
    """1 件の裁定が外す単位（申し出の単位と、fix_plan_item ならその項目に載る単位 PLAN_UNITS。重ねない・申し出の単位が先）"""
    return list(dict.fromkeys([row["unit_key"], *((row.get("ruling") or {}).get(PLAN_UNITS) or [])]))


def held_by_rulings(b) -> dict:
    """直す義務から外す単位 {unit_key: 理由}。決まりは 1 つ: 直す裁定（FIX_DECISIONS）でない裁定は、それが外す単位（ruled_units。
    fix_plan_item は誤りと裁いた項目の単位の全部）を直させない（ask_human は最後の人の関所で人が、fix_plan_item は次の run の
    修正案で決める）。理由は「<decision> の裁定 <id>」に、在れば案の項目を添える。1 単位に 2 つ当たれば DECISIONS の順で先の
    裁定の理由（並べ替えで決める）"""
    rank = {d: n for n, d in enumerate(DECISIONS)}
    rows = sorted((i for i in items(b) if (i.get("ruling") or {}).get("decision") not in (None, *FIX_DECISIONS)),
                  key=lambda i: rank.get(i["ruling"]["decision"], len(rank)))
    out = {}
    for i in rows:
        ru = i["ruling"]
        nums = ", ".join(map(str, ru.get(PLAN_ITEMS) or []))
        why = f"{ru['decision']} の裁定 {i.get('id') or '（id 無し）'}" + (f"（案の項目 {nums}）" if nums else "")
        for k in ruled_units(i):
            out.setdefault(k, why)
    return out


def replaced_queries(b) -> dict:
    """裁定 replace_query が置き換えた問い {unit_key: {id, how, counts, hits, misses}}（閉鎖の数え直しが判定者の問いの代わりに使う）"""
    return {i["unit_key"]: {"id": i["id"], **i["ruling"]["query"]} for i in items(b)
            if (i.get("ruling") or {}).get("decision") == REPLACE and isinstance(i["ruling"].get("query"), dict)}


def counts(b) -> dict:
    """{parked（申し出の件数）, fix_test_scope, fix_code_as, ask_human, unruled}。replace_query・fix_plan_item は裁いた物が在る
    時だけ足す"""
    rows = items(b)
    out = {"parked": len(rows), "unruled": sum(1 for i in rows if i.get("ruling") is None)}
    for d in DECISIONS:
        n = sum(1 for i in rows if (i.get("ruling") or {}).get("decision") == d)
        if n or d not in (REPLACE, REPLAN):
            out[d] = n
    return out


def kind_counts(b) -> dict:
    """申し出の種類の内訳 {DIV_KINDS の全部: 件数（0 も）}。kind の無い前の形の行が在る時だけ鍵 UNSET を足す"""
    rows = items(b)
    out = {k: sum(1 for r in rows if r.get(KIND_FIELD) == k) for k in DIV_KINDS}
    unset = sum(1 for r in rows if not r.get(KIND_FIELD))
    if unset:
        out[UNSET] = unset
    return out


def park(b, rows, *, source: str, ruling: dict | None = None) -> list:
    """申し出を積む（status parked・ruling は None か渡した物）。同じ単位・同じ名指し・同じ理由の申し出は積み増さない
    （Archon の呼び直し）。trace に 1 行ずつ。返りは積んだ・在った行の id"""
    doc = _load(b)
    ids = []
    for it in rows:
        # 前からの 4 つの欄は必ず在る（受け付けと機械の申し出が確かめてから積む）。kind だけは前の形の行に無いことがある
        body = {**{k: it[k] for k in FIELDS if k != KIND_FIELD}, KIND_FIELD: it.get(KIND_FIELD)}
        same = next((r for r in doc["items"] if {k: r.get(k) for k in FIELDS} == body), None)
        if same is not None:
            ids.append(same["id"])
            continue
        row = {"id": f"c{b.round}-{len(doc['items']) + 1}", "round": b.round, "source": source, **body,
               **({CORRECT: list(it[CORRECT])} if it.get(CORRECT) else {}),
               "status": "ruled" if ruling else "parked", "ruling": ruling}
        doc["items"].append(row)
        ids.append(row["id"])
        b.trace(PARK_OP, id=row["id"], unit_key=row["unit_key"], source=source, which_is_right=row["which_is_right"],
                kind=row.get(KIND_FIELD), between=row["between"], ruled=bool(ruling))
    _save(b, doc)
    return ids


def apply_rulings(b, rulings: dict, *, by: str) -> pathlib.Path:
    """裁定 {id: {decision, text, limits[, grounds, request_searched, query]}} を今の周の申し出に積み（裁かれていない物だけ）、trace に 1 行ずつ、
    裁定の文のファイル（RULINGS_FILE）を書き直してパスを返す。知らない id は BoardGap（回す側が確かめてから渡す）"""
    doc = _load(b)
    by_id = {r["id"]: r for r in doc["items"]}
    unknown = sorted(set(rulings) - set(by_id))
    if unknown:
        raise _board.BoardGap(f"知らない申し出の id に裁定を積もうとした: {unknown}")
    for rid, ruling in rulings.items():
        row = by_id[rid]
        if row.get("ruling") is not None:
            continue
        row.update(status="ruled", ruling={**ruling, "by": by})
        b.trace(RULE_OP, id=rid, unit_key=row["unit_key"], decision=ruling["decision"], by=by)
    _save(b, doc)
    return write_rulings(b)


def write_rulings(b) -> pathlib.Path:
    """裁定の文（修正役が Read する。1 件ずつ単位・名指し・理由・裁定・範囲と、裁定ごとの約束）"""
    rows = [r for r in items(b) if r.get("ruling")]
    lines = [f"# {HEAD}の裁定（機械が書いた。裁いたのは読むだけの裁定役か機械）", ""]
    promise = {
        "fix_test_scope": "テストが誤った動きを書いていると裁いた。テストを直してよいのは「範囲」に並べた所だけで、直したテストは"
                          "最後の人の関所に守りのファイルとして並ぶ。範囲の外のテストは変えるな・緩めるな。この単位も changes に 1 行を書け",
        "fix_code_as": "コードを「裁定」の文のとおりに直せ。テストは変えるな。この単位も changes に 1 行を書け",
        "ask_human": "この単位は直すな（機械が直す義務から外した。最後の人の関所で人が決める）。changes に書くな",
        REPLACE: "判定者の問いが直した後の正しい形にも当たると裁き、問いを「置き換えた問い」に替えた（機械が hits・misses と申し出の"
                 "正しい行で試した）。閉鎖の数え直しは機械がこの問いで数える（coverage.how は書かなくてよい）。テストは変えるな。"
                 "この単位も changes に 1 行を書け",
        REPLAN: "案の項目そのものが誤りと裁いた。この単位も「項目の単位」に並べた同じ項目の単位も直すな（機械が直す義務から"
                "外した。次の run の修正案で項目を直し、事前審査に掛ける）。changes に書くな。1 回目に直した項目の単位の直しは"
                "作業ツリーから戻す（機械も戻す）",
    }
    for r in rows:
        ru = r["ruling"]
        lines += [f"## {r['id']}: {r['unit_key']}", "",
                  f"- 裁定: {ru['decision']}（{ru.get('by') or ''}）——{promise[ru['decision']]}",
                  f"- 裁定の文: {ru['text']}",
                  f"- 範囲: {', '.join(ru.get('limits') or []) or '（無い）'}",
                  *([f"- 案の項目: {', '.join(map(str, ru[PLAN_ITEMS]))}"] if ru.get(PLAN_ITEMS) else []),
                  *([f"- 項目の単位（どれも直すな）: {', '.join(ru[PLAN_UNITS])}"] if ru.get(PLAN_UNITS) else []),
                  *([f"- 裁きの出どころ: {', '.join(ru['grounds'])}"] if ru.get("grounds") else []),
                  *([f"- 依頼で探して答えが無かったこと: {ru['request_searched']}"] if ru.get("request_searched") else []),
                  *([f"- 置き換えた問い: {json.dumps(ru['query'], ensure_ascii=False)}"] if ru.get("query") else []),
                  *([f"- 申し出の正しい行: {json.dumps(r[CORRECT], ensure_ascii=False)}"] if r.get(CORRECT) else []),
                  f"- 申し出の名指し: {', '.join(r['between'])}",
                  f"- 申し出の理由: {r['why_both_cannot_hold']}（正しいと見た側: {r['which_is_right']}）",
                  f"- 申し出の種類: {r.get(KIND_FIELD) or '（無し）'}", ""]
    parked = b.work(PARKED_REPLY)
    if parked.is_file():
        lines += ["## 前の回の返答", "",
                  f"申し出を返した回の返答は {parked} に在る。ほかの単位の直しは作業ツリーに残っている。裁定に従って直し、"
                  "直す義務の単位の全部（直さない裁定 ask_human・fix_plan_item の単位は除く）の changes を持つ返答を丸ごと出し直せ", ""]
    p = b.work(RULINGS_FILE)
    _write(p, "\n".join(lines))
    return p


# ---------------------------------------------------------------- 写しの RL の差し替え・最後の関所
def owed_units_but_asked(b):
    """写しの RL の _owed_units（開いた単位から、人に諮っている fork の出どころ・depends を除いた物）から、関所に載せる問い
    （gatemarks.asks。fork も escalate も）のうち答えていない物の出どころ・depends（gatemarks.withheld。無人の run・「保留: <key>」
    も）を除き、修正前の関所で人が答えた問いの出どころ・depends（gatemarks.returned。問いの status は判定の節しか書けず held の
    まま残るので、関所の答えで見る。開いていない defer の単位も戻す。修正役への約束と受け付けも同じ集合を読む）を戻し、直す裁定
    （FIX_DECISIONS）でない裁定を受けた単位（held_by_rulings。ask_human・fix_plan_item）を除く（直す義務から外すのは裁定の
    後だけ）。元の関数は盤面の graph の RL を新しく読み込んで呼ぶ（差し替えた大域の名前を読まない）"""
    fresh = _board.rules_module(pathlib.Path(b.state["graph"]))
    got = (fresh._owed_units(b) - gatemarks.withheld(b)) | gatemarks.returned(b)
    try:
        return got - set(held_by_rulings(b))
    except _board.BoardGap:   # 控えが読めない盤面は外さない（義務を減らさない側）
        return got


NOTHING_OWED = ("直す義務の単位が残っていない——開いた単位は全部、人の答え待ちか ask_human・fix_plan_item で直す義務から外れた"
                "（changes が空なのが正しい返答。ask_human は最後の人の関所で人が、fix_plan_item は次の run の修正案で決める）")


def fix_duty(b) -> tuple:
    """(直す義務 owed_units_but_asked, 直す義務から外れた単位 {key: 理由})。外れた単位は、答えていない fork・escalate の問いの
    出どころ・depends（gatemarks.withheld_by。理由はそこが組にした問い）と、直す裁定でない裁定を受けた単位（held_by_rulings。
    理由はその裁定）。owed と互いに素で、owed ∪ 外れた単位は gatemarks.fixable を覆う（写しの RL の _owed_units が外す fork の
    出どころは withheld か returned に在る。withheld は開いていない単位も含みうる）。1 単位が withheld と裁定の両方に当たれば
    裁定の理由。控えが読めなければ裁定の単位を外さない（owed_units_but_asked と同じ側）"""
    owed = owed_units_but_asked(b)
    out = {k: f"答え待ちの問い {q.get('key')}（{q.get('kind')}・{q.get('status')}）"
           for k, q in gatemarks.withheld_by(b).items()}
    try:
        out.update(held_by_rulings(b))
    except _board.BoardGap:
        pass
    return owed, {k: why for k, why in out.items() if k not in owed}


def excused_units(b) -> dict:
    """直す義務から外れた単位 {key: 理由}（fix_duty の 2 つ目）"""
    return fix_duty(b)[1]


def nothing_owed_but_excused(b) -> dict:
    """直す義務（owed_units_but_asked）が空で、外れた単位（excused_units）が 1 件以上ある盤面なら外れた単位 {key: 理由}
    （空の changes が正しい返答）。違う・読めなければ空（止める側。義務も外れた単位も無い退化した盤面も止める）"""
    try:
        owed, excused = fix_duty(b)
        return excused if excused and not owed else {}
    except Exception:   # 盤面・控え・写しの RL が読めない: 空の申告は今どおり止める
        return {}


def parse_limit(lim: str):
    """裁定の範囲の 1 つ `<パス>` か `<パス>:<行>[-<行>]` → (作業ツリーの根からのパス, (始め, 終わり) か None（ファイル全体）)。
    根の外・根そのものを指す物は None"""
    m = CITE.match(lim.strip())
    path = posixpath.normpath(m["path"] if m else lim.strip())
    if planmarks.climbs(path):   # `..` は段で見る（`..foo/x.py` は根の中。planmarks.gaps が通す範囲を捨てない）
        return None
    return path, ((int(m["a"]), int(m["b"] or m["a"])) if m else None)


def _plan_limit(r: dict, source):
    """修正案の行の範囲。source（パス → その木での中身。読めなければ None）を渡せば、その木でテストの id の定義の行を引き直す
    （修正案の時の木の行の番号は、後で上に足したテストでずれる）。引けなければ None（許しを捨てる）"""
    if source is None:
        return r["limit"]
    got = parse_limit(r["limit"])
    line = planmarks.line_in(source(got[0]), r["id"]) if got and isinstance(r["id"], str) else None
    return f"{got[0]}:{line}" if line else None


def fields_broken(b, e: Exception, *, by: str = FIELDS_STOP_BY) -> Exception:
    """修正案の欄の控えが壊れた（planmarks.FieldsBroken）時の 1 本の道: 盤面を by で止め（もう止まった盤面は止め直さない）、控えを
    名指す理由の BoardGap を返す（呼ぶ側が raise する。許しや照らしを黙って広げない・黙って捨てない）。文の頭は修正の段
    （by FIELDS_STOP_BY）なら FIELDS_BROKEN、ほかの段は段を名指さない FIELDS_TAMPERED と「読まずに止めた」"""
    head = FIELDS_BROKEN if by == FIELDS_STOP_BY else FIELDS_TAMPERED + "控えを読まずに止めた"
    why = f"{head}: {' '.join(str(e).split())}"
    state = getattr(b, "state", None) or {}
    if hasattr(b, "stop") and not (state.get("halted") or state.get("stop")):
        try:
            b.stop(why, by=by)
        except Reject as r:
            why += f"（盤面を止められない: {' '.join(str(r).split())}）"
    return _board.BoardGap(why)


def _plan_rewrites(b) -> list[dict]:
    """planmarks.rewrites。控えが凍結の印と食い違えば（FieldsBroken）fields_broken の道（盤面を止めて BoardGap）"""
    try:
        return planmarks.rewrites(b)
    except planmarks.FieldsBroken as e:
        raise fields_broken(b, e) from None


def frozen_fields(b) -> list | None:
    """今の周の凍結した修正案の欄の並び（planmarks.frozen。控えが無ければ None）。控えが凍結の印と食い違えば、_plan_rewrites と
    同じく盤面を止めて BoardGap（fields_broken の道。TDD の輪の約束を黙って空にしない）"""
    try:
        return planmarks.frozen(b)
    except planmarks.FieldsBroken as e:
        raise fields_broken(b, e) from None


def test_permits(b, *, rulings: bool = True, source=None, skip_ids=()) -> list[dict]:
    """テストの変更の許しの唯一の元（凍結の検査と最後の関所はここから引く）。行は {limit: 範囲の文字列, id: 守りのファイルの行の
    id の頭, why: 許した理由}。承認済みの修正案の rewrite_tests（いつも。planmarks.rewrites の順）と、rulings が真なら裁定
    fix_test_scope の範囲（ruled_fix の順）。source（パス → 中身か None）を渡すと、修正案の行の範囲をその木でテストの id から
    引き直し、引けない行は捨てる（凍結の検査が読む輪の後の木。tddloop.frozen_source）。skip_ids（修正案の行の id そのまま）に
    在る修正案の行は外す（TDD の輪が赤→緑を確かめた書き換え。tddloop.verified_rewrites）。裁定の行はそのまま。
    修正案の欄の控えが凍結の印と食い違えば、盤面を止めて BoardGap（_plan_rewrites）"""
    out = []
    skip = set(skip_ids)
    for r in _plan_rewrites(b):
        lim = _plan_limit(r, source) if r["id"] not in skip else None
        if lim:
            out.append({"limit": lim, "id": f"{PLAN_TEST_ID}-{r['item']}",
                        "why": f"承認済みの修正案の項目 {r['item']} が名指した既存テストの書き換え（{r['id']}）: {r['new']}"})
    if rulings:
        out += [{"limit": lim, "id": f"{RULED_TEST_ID}-{r['id']}",
                 "why": f"{HEAD}の裁定 {r['id']}（{r['unit_key']}）が許したテストの変更: {r['ruling']['text']}"}
                for r in ruled_fix(b) if r["ruling"]["decision"] == "fix_test_scope" for lim in r["ruling"].get("limits") or []]
    return out


def ruled_test_limits(b, *, rulings: bool = True, source=None, skip_ids=()) -> list[str]:
    """テストの変更の許し（test_permits）の範囲の文字列の並び。rulings が偽なら裁定の範囲を含めない（1 回目の受け付け）。
    source・skip_ids は test_permits と同じ（凍結の検査は輪の後の木の読み口と、輪が確かめた書き換えの id を渡す）"""
    return [p["limit"] for p in test_permits(b, rulings=rulings, source=source, skip_ids=skip_ids)]


def ruled_test_doc(b) -> dict | None:
    """テストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲。test_permits）が名指したテストの
    ファイル（範囲の <パス>[:行]）を、守りのファイルの一覧の形 {rules: [...]} に。無ければ None。
    パスで 1 行（protect.hits は 1 つのパスに最初の行しか返さない）。id は先に並んだ許しの物で、同じパスの許しの理由は
    捨てずに why に " / " でつなぐ（最後の関所に許したテストの変更を全部並べる）"""
    rows, whys = [], {}   # whys: パス → 理由の並び（同じ理由は 1 度だけ。理由の文に " / " が在っても割らない）
    for p in test_permits(b):
        got = parse_limit(p["limit"])
        path = got[0] if got else None
        if path is None:
            continue
        if path not in whys:
            whys[path] = []
            rows.append({"id": f"{p['id']}-{len(rows) + 1}", "glob": path})
        if p["why"] not in whys[path]:
            whys[path].append(p["why"])
    for row in rows:
        row["why"] = " / ".join(whys[row["glob"]])
    return {"rules": rows} if rows else None


def human_lines(b) -> list:
    """最後の関所と報告に載せる ask_human の行（1 件 1 行）"""
    return [f"{r['unit_key']}: {r['ruling']['text']}（名指し {', '.join(r['between'])}・種類 {r.get(KIND_FIELD) or '無し'}・"
            f"正しいと見た側 {r['which_is_right']}・"
            + (f"依頼で探したこと {r['ruling']['request_searched']}・" if r["ruling"].get("request_searched") else "")
            + f"{r['id']}）" for r in asked(b)]
