"""修正案の項目の works 側の欄（依頼 217 = 206 + 207）。

修正案の役（p2.fix_plan）の項目の行に、直し方の道（route・route_why）・受け入れのテスト（tests）・書き換える既存のテスト
（rewrite_tests）・整えの申告（refactor）を書かせる。承認された案は後で項目ごとの brief に切り出され、修正役・TDD の役が従う
要求の正本になる。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、関所の決め手の欄（gatemarks）と同じく、
役の型にだけ欄を足し、受け付けが盤面へ渡す前に外して盤面の plan-fields.json に置く。
- with_fields(node, schema): 役の型（accept.role_schema が重ねる）
- gaps(reply, repo): 欠けと誤りの行（修正案の受け付けが拒む。拒否の理由は書いた役に戻り、その役が直せる）
- find_test(repo, test_id): テストの id の定義の行（rewrite_tests は在るテストだけ・tests は無いテストだけを名指す）
- line_in(src, test_id): 渡したファイルの中身でのテストの id の定義の行（凍結の検査が輪の後の木で引き直す）
- split(reply, repo)・save(board, rnd, fields)・read(b)・rewrites(b): 欄を外す口・盤面の控え・書き換えてよい既存のテストの並び
- HEAD・REVIEW_HEAD・REVIEW_ASK・review_section(b): 修正案の役と事前審査の役の指示書の頭に足す文

写しの engine の型の検査（engine.schema。L0 の写し）だけを使い、entry・conflict を import しない（conflict がこの模块を読むので、
輪を作らない）。
"""
from __future__ import annotations

import ast
import copy
import json
import pathlib
import posixpath
import sys

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.schema import validate_schema  # noqa: E402

NODE = "p2.fix_plan"
NODES = (NODE,)
FIELDS_FILE = "plan-fields.json"   # 盤面の根の控え {"round": 周, "fields": [項目ごとの欄]}
KEYS = ("route", "route_why", "tests", "rewrite_tests", "refactor")
REQUIRED = ("route", "tests", "rewrite_tests", "refactor")   # route_why は route が direct の時だけ要る（gaps が見る）
ROUTES = ("tdd", "direct")
RED_KINDS = ("assertion", "exception")
MIN_WHY = 10
_WHY = {"type": "string", "minLength": MIN_WHY}
FIELD_SCHEMA = {
    "route": {"type": "string", "enum": list(ROUTES)},
    "route_why": {"type": "string"},
    "tests": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "behavior", "path", "red_kind", "red_why"],
        "properties": {"id": {"type": "string", "pattern": "::"}, "behavior": _WHY, "path": _WHY,
                       "red_kind": {"type": "string", "enum": list(RED_KINDS)}, "red_why": _WHY}}},
    "rewrite_tests": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "behavior", "old", "new"],
        "properties": {"id": {"type": "string", "pattern": "::"}, "behavior": _WHY,
                       "old": {"type": "string", "minLength": 4}, "new": _WHY}}},
    "refactor": {"type": "object", "additionalProperties": False, "required": ["declared", "why"],
                 "properties": {"declared": {"type": "boolean"}, "why": {"type": "string"}}},
}

REJECT = ("修正案の項目の works の欄（route・tests・rewrite_tests・refactor）に欠けか誤りが在る（直して done し直す）。"
          "下の行を直した案を丸ごと出し直せ:")
# 修正案の役の指示書の頭に足す文（写しの指示書はこの欄を知らない）
HEAD = ("修正案の項目の works の欄: 写しの指示書はこの欄を知らないが、plan[] の各項目に必ず書け。"
        "route＝直し方の道（tdd＝先に落ちる受け入れのテストを書いてから直す・direct＝テストを先に書かずに直す）。"
        f"route_why＝direct を選んだ理由（route が direct なら {MIN_WHY} 字以上。tdd なら空でよい）。"
        "tests＝この項目で新しく足す受け入れのテストの並び（route が tdd なら 1 本以上）。各行は id（<パス>::<クラス>::<名前> か "
        "<パス>::<名前>。パスは作業ツリーの根からの相対で、まだ無いテストを名指す）・behavior（確かめる振る舞い）・path（本物の経路を"
        "どう通すか。mock の戻り値を断言しない）・red_kind・red_why（今のコードでなぜ赤になるか）。red_kind は断言の失敗（assertion）か"
        "期待した例外が出ない（exception）のどちらかで、import や収集の失敗は赤に数えない。"
        "rewrite_tests＝依頼で振る舞いが変わるため期待を書き換える既存のテストの並び。各行は id（作業ツリーに在るテストの定義）・"
        "behavior（変わる振る舞い）・old（今の期待）・new（新しい期待）。期待値を実装に合わせるための書き換えは書かない。"
        f"refactor＝整えの申告 {{declared, why}}（整えをするなら declared を true にし、why に {MIN_WHY} 字以上で理由を書く）。"
        "承認された案は項目ごとの brief に切り出され、修正役・TDD の役の要求の正本になる。rewrite_tests に名指さない既存のテストは"
        "修正で変えられない。欠けや誤りは、受け付けが plan[<i>].<欄> の行を名指して拒む")
REVIEW_HEAD = "## 修正案の項目の works の欄（機械が貼った）"
REVIEW_ASK = ("下は修正案の役が項目ごとに書いた works の欄（route・受け入れのテスト tests・書き換える既存のテスト rewrite_tests・"
              "整えの申告 refactor）。承認されると項目ごとの brief になり、修正役・TDD の役の要求の正本になる。受け入れのテストが"
              "本物の経路を通るか・mock の戻り値を断言していないか・文言の比べに寄っていないか、red_kind の赤が今のコードで本当に"
              "起きるか、rewrite_tests が依頼で変わる振る舞いだけを書き換え、期待値を実装に合わせる書き換えでないかを見よ。"
              "穴は faces に挙げよ")


# ---------------------------------------------------------------- 役の型
def with_fields(node: str, schema: dict) -> dict:
    """役の型の修正案の項目に works の欄を足した写し（NODES の節でなければ渡した物をそのまま返す）"""
    if node not in NODES:
        return schema
    out = copy.deepcopy(schema)
    row = out["properties"]["plan"]["items"]
    row["properties"].update(copy.deepcopy(FIELD_SCHEMA))
    row["required"] = [*row.get("required", []), *(k for k in REQUIRED if k not in row.get("required", []))]
    return out


# ---------------------------------------------------------------- テストの定義の行
def _parse_id(test_id):
    """id → (根からの相対パス, [名前…]（1 つか 2 つ）)。形が違えば None"""
    if not isinstance(test_id, str):
        return None
    path, *names = test_id.split("::")
    if not path or not 1 <= len(names) <= 2 or not all(names):
        return None
    return path, names


def _resolve(repo: pathlib.Path, path: str):
    """根の中のファイルなら (作業ツリーの根からの相対の綴り, 実体)。根の外（絶対パス・..・根の外へのリンク）・無いなら None"""
    norm = posixpath.normpath(path)
    if norm.startswith(("/", "..")) or norm == ".":
        return None
    root = pathlib.Path(repo).resolve()
    real = (root / norm).resolve()
    if not real.is_relative_to(root) or not real.is_file():
        return None
    return norm, real


def _py_line(src: str, names: list):
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    body = tree.body
    *outer, name = names
    for cls in outer:
        got = [n for n in body if isinstance(n, ast.ClassDef) and n.name == cls]
        if not got:
            return None
        body = got[0].body
    fn = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    return fn[0].lineno if fn else None


def line_in(src: str, test_id: str) -> int | None:
    """テストの id のファイルの中身 src での定義の行（1 始まり。引き方は find_test と同じ）。id の形が違う・名前が無いなら None"""
    got = _parse_id(test_id)
    if got is None or not isinstance(src, str):
        return None
    path, names = got
    if path.endswith(".py"):
        return _py_line(src, names)
    return next((i for i, line in enumerate(src.splitlines(), 1) if names[-1] in line), None)


def find_test(repo: pathlib.Path, test_id: str) -> int | None:
    """<パス>::<クラス>::<名前> か <パス>::<名前> のテストの定義の行（1 始まり）。.py は ast でクラスと関数を引き（行は def の行）、
    ほかの拡張子は名前を含む最初の行。根の外・ファイルが無い・構文が壊れている・名前が無いなら None"""
    got = _parse_id(test_id)
    found = _resolve(repo, got[0]) if got else None
    if found is None:
        return None
    try:
        src = found[1].read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return line_in(src, test_id)


def _limit(repo: pathlib.Path, test_id: str):
    """書き換えてよい範囲 "<パス>:<定義の行>"（パスは根からの相対の綴り）。引けなければ None"""
    line = find_test(repo, test_id)
    return f"{posixpath.normpath(_parse_id(test_id)[0])}:{line}" if line else None


# ---------------------------------------------------------------- 受け付け
def _rows(it: dict, key: str) -> list:
    rows = it.get(key)
    return rows if isinstance(rows, list) else []


def _id_of(row):
    tid = row.get("id") if isinstance(row, dict) else None
    return tid if isinstance(tid, str) else None


def gaps(reply: dict, repo: pathlib.Path) -> list[str]:
    """修正案の返答の works の欄の欠けと誤りの行（"plan[<i>].<欄>…: <理由>"）。空なら通る。返答や plan が形を成さなければ空
    （写しの規則が型で拒む）。例外で拒まない"""
    plan = reply.get("plan") if isinstance(reply, dict) else None
    if not isinstance(plan, list):
        return []
    out, new_ids = [], {}
    for i, it in enumerate(plan):
        if not isinstance(it, dict):
            out.append(f"plan[{i}]: 項目が object でない")
            continue
        for k in REQUIRED:
            if k not in it:
                out.append(f"plan[{i}].{k}: 無い（works の欄。修正案の頭の『修正案の項目の works の欄』を見よ）")
        for k in KEYS:
            if k in it:
                out += validate_schema(it[k], FIELD_SCHEMA[k], f"plan[{i}].{k}")
        route, tests = it.get("route"), it.get("tests")
        if route == "tdd" and isinstance(tests, list) and not tests:
            out.append(f"plan[{i}].tests: route が tdd の項目は受け入れのテストを 1 本以上書く"
                       "（先に書けないなら route を direct にし、route_why に理由を書く）")
        why = it.get("route_why")
        if route == "direct" and not (isinstance(why, str) and len(why.strip()) >= MIN_WHY):
            out.append(f"plan[{i}].route_why: route が direct の項目は、テストを先に書かない理由を {MIN_WHY} 字以上で書く")
        for j, row in enumerate(_rows(it, "tests")):
            tid = _id_of(row)
            line = find_test(repo, tid) if tid else None
            if tid:
                new_ids.setdefault(tid, f"plan[{i}].tests[{j}]")
            if line is not None:
                out.append(f"plan[{i}].tests[{j}].id（{tid}）: 既に在るテスト（{_limit(repo, tid)}）。tests はまだ無いテストを名指す。"
                           "既に在るテストの期待を変えるなら rewrite_tests に書け")
        rf = it.get("refactor")
        if isinstance(rf, dict) and rf.get("declared") is True:
            rwhy = rf.get("why")
            if not (isinstance(rwhy, str) and len(rwhy.strip()) >= MIN_WHY):
                out.append(f"plan[{i}].refactor.why: declared が true なら、整えの理由を {MIN_WHY} 字以上で書く")
    for i, it in enumerate(plan):
        for j, row in enumerate(_rows(it, "rewrite_tests") if isinstance(it, dict) else []):
            tid = _id_of(row)
            if tid is None:
                continue
            if find_test(repo, tid) is None:
                out.append(f"plan[{i}].rewrite_tests[{j}].id（{tid}）: 作業ツリーの根の中に在るテストの定義として引けない"
                           "（<パス>::<クラス>::<名前> か <パス>::<名前>。パスは根からの相対）")
            if tid in new_ids:
                out.append(f"plan[{i}].rewrite_tests[{j}].id（{tid}）: 同じ id を {new_ids[tid]} にも書いた"
                           "（新しく足すテストか書き換える既存のテストのどちらか 1 つにせよ）")
    return out


def split(reply: dict, repo: pathlib.Path) -> tuple[dict, list[dict]]:
    """（works の欄を外した返答の写し, 項目と同じ並びの欄）。欄の行は外した欄に、項目の unit_keys の写しと、rewrite_tests の
    各行の書き換えてよい範囲 limit（"<パス>:<定義の行>"。引けない行には付けない）を足した物。gaps を通った返答に使う"""
    out = copy.deepcopy(reply)
    fields = []
    for it in (out.get("plan") if isinstance(out, dict) else None) or []:
        if not isinstance(it, dict):
            fields.append({})
            continue
        got = {k: it.pop(k) for k in KEYS if k in it}
        got["unit_keys"] = copy.deepcopy(it.get("unit_keys") or [])
        for row in got.get("rewrite_tests") or []:
            lim = _limit(repo, _id_of(row)) if _id_of(row) else None
            if lim:
                row["limit"] = lim
        fields.append(got)
    return out, fields


# ---------------------------------------------------------------- 盤面の控え
def save(board, rnd: int, fields: list) -> None:
    """盤面の plan-fields.json を今の周の欄で置き換える"""
    doc = {"round": rnd, "fields": fields}
    (pathlib.Path(board) / FIELDS_FILE).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read(b) -> list | None:
    """今の周（b.round）の欄の並び。控えが無い・周が違う・読めないなら None（b.dir・b.round だけを読む）"""
    p = pathlib.Path(b.dir) / FIELDS_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("round") != b.round or not isinstance(doc.get("fields"), list):
        return None
    return doc["fields"]


def rewrites(b) -> list[dict]:
    """今の周の承認済みの修正案が名指した、書き換えてよい既存のテストの並び
    {item: 項目の番号（1 始まり）, unit_keys, id, new, limit}。範囲 limit の無い行は並べない（許しを広げない）"""
    out = []
    for n, f in enumerate(read(b) or [], 1):
        if not isinstance(f, dict):
            continue
        for row in f.get("rewrite_tests") or []:
            if isinstance(row, dict) and isinstance(row.get("limit"), str) and row["limit"]:
                out.append({"item": n, "unit_keys": list(f.get("unit_keys") or []), "id": row.get("id"),
                            "new": row.get("new"), "limit": row["limit"]})
    return out


def review_section(b) -> str:
    """事前審査の役の指示書の頭に貼る節（"\\n\\n" で始まる）: 見る点の頼みと、項目ごとの欄の JSON。控えが無ければ空"""
    fields = read(b)
    if fields is None:
        return ""
    rows = [f"### 修正案の項目 {n}\n\n```json\n{json.dumps(f, ensure_ascii=False, indent=1)}\n```" for n, f in enumerate(fields, 1)]
    return f"\n\n{REVIEW_HEAD}\n\n{REVIEW_ASK}\n\n" + "\n\n".join(rows)
