"""修正案の項目の works 側の欄（依頼 217 = 206 + 207）。

修正案の役（p2.fix_plan）の項目の行に、直し方の道（route・route_why）・受け入れのテスト（tests）・書き換える既存のテスト
（rewrite_tests）・整えの申告（refactor）・書いてよいパス（allowed_paths）・触らない物（out_of_scope。依頼 218）を書かせる。承認された案は後で項目ごとの brief に切り出され、修正役・TDD の役が従う
要求の正本になる。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、関所の決め手の欄（gatemarks）と同じく、
役の型にだけ欄を足し、受け付けが盤面へ渡す前に外して盤面の plan-fields.json に置く。
- with_fields(node, schema): 役の型（accept.role_schema が重ねる）
- gaps(reply, repo): 欠けと誤りの行（修正案の受け付けが拒む。拒否の理由は書いた役に戻り、その役が直せる）
- find_test(repo, test_id): テストの id の定義の行（rewrite_tests は在るテストだけ・tests は無いテストだけを名指す）
- line_in(src, test_id): 渡したファイルの中身でのテストの id の定義の行（凍結の検査が輪の後の木で引き直す）
- split(reply, repo)・save(board, rnd, fields)・read(b)・rewrites(b): 欄を外す口・盤面の控え・書き換えてよい既存のテストの並び
- 凍結（SAVED_OP・frozen(b)・FieldsBroken）: save は控えを置いた後、盤面の trace に印 {round, sha256（控えのバイトの sha256）} を
  1 行書く。テストの変更の許しの元（rewrites）と brief の切り出しは frozen で読み、今の周の印と控えが食い違えば（受け付けの後に
  書き換えた・消した）FieldsBroken。読む側が盤面を止める（黙って許しを広げない・黙って捨てない）。印の無い控えは無い物（None）
- HEAD・REVIEW_HEAD・REVIEW_ASK・review_section(b): 修正案の役と事前審査の役の指示書の頭に足す文
- climbs(norm): 整えたパスが根の外へ上るか（`..` は段で見る。conflict.parse_limit も同じ物を使う）
- glob_problem(glob): 範囲の欄（allowed_paths・out_of_scope の glob）の誤りの文（\\ の区切り・根の外・`**` のような丸ごとの許し）
- glob_match(path, glob): 根からの相対のパスが glob に当たるか（* ? [..] は / を跨がない・** は段をまたぐ。守りのファイルの
  protect.match もこれを呼ぶ）。gaps は out_of_scope の glob が tests・rewrite_tests の id のファイルに当たる案を拒む
- approved_items(b): 今の周の承認済みの修正案の項目と凍結した欄を同じ番号で合わせた並び（修正の受け付けが差分と照らす）

写しの engine の型の検査と時刻（engine.schema・engine.util。L0 の写し）だけを使い、entry・conflict を import しない（conflict がこの模块を読むので、
輪を作らない）。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pathlib
import posixpath
import re
import sys

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.schema import validate_schema  # noqa: E402
from engine.util import now  # noqa: E402

NODE = "p2.fix_plan"
NODES = (NODE,)
FIELDS_FILE = "plan-fields.json"   # 盤面の根の控え {"round": 周, "fields": [項目ごとの欄]}
SAVED_OP = "plan_fields_saved"     # save が盤面の trace に書く凍結の印 {round, sha256}
KEYS = ("route", "route_why", "tests", "rewrite_tests", "refactor", "allowed_paths", "out_of_scope")
# route_why は route が direct の時だけ要る（gaps が見る）
REQUIRED = ("route", "tests", "rewrite_tests", "refactor", "allowed_paths", "out_of_scope")
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
    # 範囲の欄（依頼 218）: 書いてよいパスの glob と、範囲の中でも触らない物 {glob, why}
    "allowed_paths": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    "out_of_scope": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["glob", "why"],
        "properties": {"glob": {"type": "string", "minLength": 1}, "why": _WHY}}},
}

REJECT = ("修正案の項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope）に欠けか誤りが在る"
          "（直して done し直す）。下の行を直した案を丸ごと出し直せ:")
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
        "修正で変えられない。欠けや誤りは、受け付けが plan[<i>].<欄> の行を名指して拒む。"
        "allowed_paths＝その項目で書いてよいパスの glob の並び（1 つ以上。作業ツリーの根からの相対・/ 区切り・** は段をまたぐ）。"
        "tests・rewrite_tests の id のファイルは書かなくても範囲に入り、out_of_scope の glob をそのファイルに当てた案は拒む。"
        "** や * や **/* のような丸ごとの許しは拒む。"
        "out_of_scope＝範囲の中でも触らない物 {glob, why} の並び（why は "
        f"{MIN_WHY} 字以上。無ければ空の並び）。修正の受け付けは差分をこの範囲と照らし、外れたら同じ brief で返す。"
        "機械は差分で次を探すので、adds の name は識別子（関数・欄・CLI・テストの名）で書き、新設の物の canonical には"
        "置くファイルのパスを書け。removes に識別子を書けば、差分で消えたかを見る")
REVIEW_HEAD = "## 修正案の項目の works の欄（機械が貼った）"
REVIEW_ASK = ("下は修正案の役が項目ごとに書いた works の欄（route・受け入れのテスト tests・書き換える既存のテスト rewrite_tests・"
              "整えの申告 refactor・書いてよいパス allowed_paths・触らない物 out_of_scope）。承認されると項目ごとの brief になり、"
              "修正役・TDD の役の要求の正本になる。受け入れのテストが"
              "本物の経路を通るか・mock の戻り値を断言していないか・文言の比べに寄っていないか、red_kind の赤が今のコードで本当に"
              "起きるか、rewrite_tests が依頼で変わる振る舞いだけを書き換え、期待値を実装に合わせる書き換えでないかを見よ。"
              "allowed_paths が項目の直しに足りて広すぎないか、out_of_scope が依頼の触らない物を覆うかも見よ。"
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


def climbs(norm: str) -> bool:
    """整えたパスが根そのもの・絶対パス・`..` の段で上る物か（`..` は段で見る。`..foo/x.py` は根の中のディレクトリ `..foo` の物）"""
    return norm.startswith("/") or norm == "." or norm.split("/", 1)[0] == ".."


def glob_problem(glob: str) -> str | None:
    """範囲の欄の glob（allowed_paths の行・out_of_scope の glob）の誤りの文。無ければ None。前後の空白・\\ の区切り・絶対パス
    （/・ドライブ文字・~ で始まる）・`..` の段で根の外へ上る・整えた形でない綴り（./x・a/../b・a//b）・全部の段が * か **
    （**・*・**/* のような丸ごとの許し）を拒む。整えずに拒む（差分のパスは整えた綴りなので、整えない綴りの glob は当たらない）。
    ファイルの有無は見ない（新しく置くファイルも書く）"""
    if glob != glob.strip():
        return "前後に空白が在る（空白を外した、作業ツリーの根からの相対の glob にせよ）"
    if "\\" in glob:
        return "\\ が在る（区切りは / で書け。glob は作業ツリーの根からの相対）"
    if glob.startswith(("/", "~")) or re.match(r"[A-Za-z]:", glob):
        return "絶対パス（/・ドライブ文字・~ で始まる。作業ツリーの根からの相対の glob にせよ）"
    norm = posixpath.normpath(glob)
    if climbs(norm):
        return "根の外か根そのものを指す（`..` の段で上らない、根からの相対の glob にせよ）"
    if all(seg in ("*", "**") for seg in norm.split("/")):
        return "丸ごとの許し（全部の段が * か **）は拒む。項目の直しが触るファイルかディレクトリまで狭めよ"
    if norm != glob.rstrip("/"):
        return f"整えた形でない（./・..・// を含む）。整えた形 {norm} で書け"
    return None


def _segment(seg: str) -> str:
    """glob の 1 区切りを正規表現に（* と ? と [..] は / を跨がない。[! は否定）"""
    out, i = [], 0
    while i < len(seg):
        c = seg[i]
        k = -1
        if c == "[":
            j = i + 1 + (seg[i + 1:i + 2] == "!")
            j += seg[j:j + 1] == "]"
            k = seg.find("]", j)
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif k > 0:
            body = seg[i + 1:k]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            i = k
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _glob_regex(glob: str):
    parts = glob.split("/")
    out = []
    for i, seg in enumerate(parts):
        last = i == len(parts) - 1
        if seg == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment(seg) + ("" if last else "/"))
    return re.compile("".join(out) + r"\Z")


def glob_match(path: str, glob: str) -> bool:
    """根からの相対のパスが glob に当たるか（* ? [..] は / を跨がない・** は段をまたぐ）。範囲の欄と守りのファイルの当て方の正本
    （protect.match はこれを呼ぶ。planmarks は protect を import しない: protect → accept → planmarks の輪になる）"""
    return _glob_regex(glob).match(path) is not None


def _resolve(repo: pathlib.Path, path: str):
    """根の中のファイルなら (作業ツリーの根からの相対の綴り, 実体)。根の外（絶対パス・`..` の段・根の外へのリンク）・無いなら
    None。根の外へのリンクは解いた実体の is_relative_to で見る"""
    norm = posixpath.normpath(path)
    if climbs(norm):
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
    """テストの id のファイルの中身 src での定義の行（1 始まり。引き方は find_test と同じ）。id の形が違う・名前が無いなら None。
    .py かは _resolve と同じく整えたパス（posixpath.normpath。`t.py/` は t.py）で決める"""
    got = _parse_id(test_id)
    if got is None or not isinstance(src, str):
        return None
    path, names = got
    if posixpath.normpath(path).endswith(".py"):
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


def _path_problem(repo: pathlib.Path, test_id: str) -> str | None:
    """テストの id のパスの誤りの文（\\ の区切り・作業ツリーの根からの相対でない）。無ければ None。ファイルの有無は見ない
    （tests はまだ無いテストを名指す）"""
    if "\\" in test_id:
        return "パスに \\ が在る（区切りは / で書け。パスは作業ツリーの根からの相対）"
    got = _parse_id(test_id)
    if got is None:
        return None
    norm = posixpath.normpath(got[0])
    root = pathlib.Path(repo).resolve()
    if climbs(norm) or not (root / norm).resolve().is_relative_to(root):
        return "パスが作業ツリーの根からの相対でない（絶対パス・根の外を指す。/ で書いた根からの相対にせよ）"
    return None


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


def test_paths(it: dict) -> list[str]:
    """項目の tests・rewrite_tests の id のファイル（整えた根からの相対の綴り・現れた順・重なりは 1 つ）。書いてよい範囲に入る"""
    out = []
    for key in ("tests", "rewrite_tests"):
        for row in _rows(it, key):
            got = _parse_id(_id_of(row))
            if got:
                norm = posixpath.normpath(got[0])
                if norm not in out:
                    out.append(norm)
    return out


def _scope_overlaps(plan: list) -> list[str]:
    """out_of_scope の glob が、案のどれかの項目の tests・rewrite_tests の id のファイルに当たる行（書けと言うファイルを触るなとも
    言う食い違い。修正の段へ渡さずに案を直させる）"""
    out = []
    named = [(n, p) for n, it in enumerate(plan, 1) if isinstance(it, dict) for p in test_paths(it)]
    for i, it in enumerate(plan):
        for j, row in enumerate(_rows(it, "out_of_scope") if isinstance(it, dict) else []):
            g = row.get("glob") if isinstance(row, dict) else None
            if not isinstance(g, str) or not g or glob_problem(g):
                continue
            for n, p in named:
                if glob_match(p, g):
                    out.append(f"plan[{i}].out_of_scope[{j}].glob（{g}）: 項目 {n} の tests・rewrite_tests の id のファイル {p} に"
                               "当たる（書けと言うファイルを触るなとも言っている。glob を狭めるか、テストの置き場を変えよ）")
    return out


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
            bad = _path_problem(repo, tid) if tid else None
            if bad:
                out.append(f"plan[{i}].tests[{j}].id（{tid}）: {bad}")
                continue
            line = find_test(repo, tid) if tid else None
            if tid:
                new_ids.setdefault(tid, f"plan[{i}].tests[{j}]")
            if line is not None:
                out.append(f"plan[{i}].tests[{j}].id（{tid}）: 既に在るテスト（{_limit(repo, tid)}）。tests はまだ無いテストを名指す。"
                           "既に在るテストの期待を変えるなら rewrite_tests に書け")
        for j, g in enumerate(_rows(it, "allowed_paths")):
            bad = glob_problem(g) if isinstance(g, str) and g else None
            if bad:
                out.append(f"plan[{i}].allowed_paths[{j}]（{g}）: {bad}")
        for j, row in enumerate(_rows(it, "out_of_scope")):
            g = row.get("glob") if isinstance(row, dict) else None
            bad = glob_problem(g) if isinstance(g, str) and g else None
            if bad:
                out.append(f"plan[{i}].out_of_scope[{j}].glob（{g}）: {bad}")
        rf = it.get("refactor")
        if isinstance(rf, dict) and rf.get("declared") is True:
            rwhy = rf.get("why")
            if not (isinstance(rwhy, str) and len(rwhy.strip()) >= MIN_WHY):
                out.append(f"plan[{i}].refactor.why: declared が true なら、整えの理由を {MIN_WHY} 字以上で書く")
    out += _scope_overlaps(plan)
    for i, it in enumerate(plan):
        for j, row in enumerate(_rows(it, "rewrite_tests") if isinstance(it, dict) else []):
            tid = _id_of(row)
            if tid is None:
                continue
            if "\\" in tid:
                out.append(f"plan[{i}].rewrite_tests[{j}].id（{tid}）: {_path_problem(repo, tid)}")
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
class FieldsBroken(ValueError):
    """盤面の控え plan-fields.json が今の周の凍結の印（SAVED_OP）と合わない（受け付けの後に書き換えた・消した・読めない）"""


def save(board, rnd: int, fields: list) -> None:
    """盤面の plan-fields.json を今の周の欄で置き換え（一時のファイルから os.replace。リンクの先へ書かない）、盤面の trace に
    凍結の印 SAVED_OP {round, sha256（置いたバイトの sha256）} を 1 行足す（DiskBoard.trace と同じ行の形 {t, op, …}）"""
    d = pathlib.Path(board)
    raw = (json.dumps({"round": rnd, "fields": fields}, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    p = d / FIELDS_FILE
    tmp = p.with_name(p.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": SAVED_OP, "round": rnd, "sha256": hashlib.sha256(raw).hexdigest()},
                           ensure_ascii=False) + "\n")


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


def _saved_mark(b) -> dict | None:
    """今の周（b.round）の凍結の印（trace の SAVED_OP の行の最後の物）。無ければ None"""
    try:
        lines = (pathlib.Path(b.dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    mark = None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("op") == SAVED_OP and row.get("round") == b.round:
            mark = row
    return mark


def approved_items(b) -> list[dict] | None:
    """今の周の承認済みの修正案の項目（今の周の p2.fix_plan の出力の plan）と凍結した欄（frozen）を同じ番号で合わせた並び
    {"item": <1 始まり>, **案の項目, **欄の KEYS の物}（unit_keys は案の物）。どちらか無ければ None。数が違えば FieldsBroken
    （frozen の食い違いもそのまま FieldsBroken。b は dir・round・output_of_round を読む）"""
    fields = frozen(b)
    doc = b.output_of_round(NODE, b.round)
    plan = doc.get("plan") if isinstance(doc, dict) else None
    if fields is None or not isinstance(plan, list):
        return None
    if len(fields) != len(plan):
        raise FieldsBroken(f"修正案の項目の数 {len(plan)} と盤面の控え {FIELDS_FILE} の欄の数 {len(fields)} が違う"
                           "（同じ周の受け付けが同じ並びで書く物）")
    out = []
    for n, (it, f) in enumerate(zip(plan, fields), 1):
        it = it if isinstance(it, dict) else {}
        f = f if isinstance(f, dict) else {}
        out.append({"item": n, **copy.deepcopy(it), **{k: copy.deepcopy(f[k]) for k in KEYS if k in f}})
    return out


def frozen(b) -> list | None:
    """今の周の凍結した欄の並び（read と同じ物）。今の周の印が無ければ None（印の無い控えは無い物: 変更前の盤面・save の外で
    置いた控え）。印が在るのに控えが読めない・控えのバイトの sha256 が印と違えば FieldsBroken"""
    mark = _saved_mark(b)
    if mark is None:
        return None
    p = pathlib.Path(b.dir) / FIELDS_FILE
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise FieldsBroken(f"盤面の控え {p}（{FIELDS_FILE}）が読めない。周 {b.round} の {SAVED_OP} の印が在る: {e}") from None
    if hashlib.sha256(raw).hexdigest() != mark.get("sha256"):
        raise FieldsBroken(f"盤面の控え {p}（{FIELDS_FILE}）のバイトの sha256 が周 {b.round} の {SAVED_OP} の印と違う"
                           "（受け付けの後に書き換えた）")
    return read(b)


def rewrites(b) -> list[dict]:
    """今の周の承認済みの修正案が名指した、書き換えてよい既存のテストの並び
    {item: 項目の番号（1 始まり）, unit_keys, id, new, limit}。範囲 limit の無い行は並べない（許しを広げない）。
    控えは frozen で読む（印と食い違えば FieldsBroken）"""
    out = []
    for n, f in enumerate(frozen(b) or [], 1):
        if not isinstance(f, dict):
            continue
        for row in f.get("rewrite_tests") or []:
            if isinstance(row, dict) and isinstance(row.get("limit"), str) and row["limit"]:
                out.append({"item": n, "unit_keys": list(f.get("unit_keys") or []), "id": row.get("id"),
                            "new": row.get("new"), "limit": row["limit"]})
    return out


def review_section(b) -> str:
    """事前審査の役の指示書の頭に貼る節（"\\n\\n" で始まる）: 見る点の頼みと、項目ごとの欄の JSON。控えが無ければ空。
    控えは frozen で読む（凍結の印と食い違えば FieldsBroken。読む側が盤面を止める）"""
    fields = frozen(b)
    if fields is None:
        return ""
    rows = [f"### 修正案の項目 {n}\n\n```json\n{json.dumps(f, ensure_ascii=False, indent=1)}\n```" for n, f in enumerate(fields, 1)]
    return f"\n\n{REVIEW_HEAD}\n\n{REVIEW_ASK}\n\n" + "\n\n".join(rows)
