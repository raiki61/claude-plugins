"""修正案の項目の works 側の欄（依頼 217 = 206 + 207）。

修正案の役（p2.fix_plan）の項目の行に、直し方の道（route・route_why）・受け入れのテスト（tests）・書き換える既存のテスト
（rewrite_tests）・整えの申告（refactor）・書いてよいパス（allowed_paths）・触らない物（out_of_scope。依頼 218）を書かせる。承認された案は後で項目ごとの brief に切り出され、修正役・TDD の役が従う
要求の正本になる。写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、足す・外す・置く・読むの手順は住処
marks（種 plan。役の型にだけ欄を足し、受け付けが盤面へ渡す前に外して盤面の plan-fields.json に置く）に任せる。
- with_fields(node, schema): 役の型（accept.role_schema が重ねる）
- gaps(reply, repo, exists=): 欠けと誤りの行（kind が関数・欄の adds の name がファイルの名・パスだけの行も。修正案の受け付けが拒む。拒否の理由は書いた役に戻り、その役が直せる）。exists は
  受け入れのテストが既に在るかを引く口（既定は作業ツリー。同じ run の中の案の直しは修正の起点の版の木）
- find_test(repo, test_id): テストの id の定義の行（rewrite_tests は在るテストだけ・tests は無いテストだけを名指す）
- line_in(src, test_id): 渡したファイルの中身でのテストの id の定義の行（凍結の検査が輪の後の木で引き直す）
- split(reply, repo)・save(board, rnd, fields)・read(b)・rewrites(b): 欄を外す口・盤面の控え・書き換えてよい既存のテストの並び
- unit_contract(fields, key): 1 つの単位の約束（その単位を名指す項目の道・受け入れのテスト・書き換えの id・整えの申告を合わせた物。TDD の輪が読む）
- 凍結（SAVED_OP・frozen(b)・FieldsBroken）: save は控えを置いた後、盤面の trace に印 {round, sha256（控えのバイトの sha256）} を
  1 行書く。テストの変更の許しの元（rewrites）と brief の切り出しは frozen で読み、今の周の印と控えが食い違えば（受け付けの後に
  書き換えた・消した）FieldsBroken。読む側が盤面を止める（黙って許しを広げない・黙って捨てない）。印の無い控えは無い物（None）
- HEAD・REVIEW_HEAD・REVIEW_ASK・review_section(b): 修正案の役と事前審査の役の指示書の頭に足す文
- climbs(norm): 整えたパスが根の外へ上るか（`..` は段で見る。conflict.parse_limit も同じ物を使う）
- glob_problem(glob): 範囲の欄（allowed_paths・out_of_scope の glob）の誤りの文（\\ の区切り・根の外・`**`・`**/?*` のような字の無い丸ごとの許し）
- glob_match(path, glob): 根からの相対のパスが glob に当たるか（* ? [..] は / を跨がない・** は段をまたぐ。守りのファイルの
  protect.match もこれを呼ぶ）。gaps は out_of_scope の glob が tests・rewrite_tests の id のファイルに当たる案を拒む
- approved_items(b): 今の周の承認済みの修正案の項目と凍結した欄を同じ番号で合わせた並び（修正の受け付けが差分と照らす）
- 約束の欄と手段の欄（依頼 226）: CONTRACT_KEYS・CONTRACT_TEST_KEYS（tests[] の行の約束の欄）は変えると関所に戻す物、
  MEANS_KEYS は修正案の役が同じ run の中で直してよい物。contract_diff(old, new) が違う約束の欄の名を返す
  widened(old, new) は違いが範囲を広げる欄（WIDEN_KEYS: allowed_paths に足す・out_of_scope から外す）だけの時に足した・外した glob を返す
- 承認済みの項目の差し替え（依頼 226）: amend(b, items, repo) が直した項目の欄の行を split で作り直し、核の欄（CORE_KEYS）を
  控えの AMENDED_KEY に置いて save し直し（凍結し直し）、trace に AMEND_OP を書く。amended(b)・plan_items(b) が読む
- scoped(items)・scoped_items(b): 範囲の欄の在る項目の並びか（217 番の形の控えは範囲の無い run と同じに扱う 1 つの決まり。
  修正の受け付けの範囲の照らしと差分の審査の準拠の受け付けが使う）

写しの engine の型の検査と時刻（engine.schema・engine.util。L0 の写し）と住処 marks（L1）だけを使い、entry・conflict を import しない（conflict がこの模块を読むので、
輪を作らない）。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import pathlib
import posixpath
import re
import sys

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.schema import validate_schema  # noqa: E402
from engine.util import now  # noqa: E402
import marks  # noqa: E402

NODES = marks.nodes("plan")
NODE = NODES[0]
FIELDS_FILE = marks.KINDS["plan"].file   # 盤面の根の控え {"round": 周, "fields": [項目ごとの欄], "amended"?: {番号: 核の欄}}
SAVED_OP = "plan_fields_saved"     # save が盤面の trace に書く凍結の印 {round, sha256}
KEYS = ("route", "route_why", "tests", "rewrite_tests", "refactor", "allowed_paths", "out_of_scope")
# 写しの graph の修正案の項目の欄（核）。差し替えた項目のこの欄を控えの AMENDED_KEY に置く（approved_items が足す鍵 item は外す）
CORE_KEYS = ("unit_keys", "approach", "adds", "removes", "shrink_first", "narrows")
# 約束の欄（変えると関所に戻す物）と手段の欄（同じ run の中で修正案の役が直してよい物）。tests[] の行は CONTRACT_TEST_KEYS の
# 欄だけが約束で、ほかの欄（id・path・red_kind・red_why）は手段
CONTRACT_KEYS = ("unit_keys", "narrows", "removes", "allowed_paths", "out_of_scope", "rewrite_tests")
CONTRACT_TEST_KEYS = ("behavior",)
MEANS_KEYS = ("approach", "adds", "shrink_first", "route", "route_why", "tests", "refactor")
# 範囲を広げる欄（widened が見る）: allowed_paths に足す・out_of_scope から外すだけの直しは、範囲を広げるだけの直し
WIDEN_KEYS = ("allowed_paths", "out_of_scope")
AMENDED_KEY = "amended"            # 控えの鍵 {"<項目の番号>": {CORE_KEYS の欄}}（差し替えた項目の核の欄）
AMEND_OP = "plan_amended"          # amend だけが書く trace の行 {round, items: [番号…]}（SAVED_OP の行の直後）
# route_why は route が direct の時だけ要る（gaps が見る）
REQUIRED = ("route", "tests", "rewrite_tests", "refactor", "allowed_paths", "out_of_scope")
ROUTES = ("tdd", "direct")
RED_KINDS = ("assertion", "exception")
MIN_WHY = 10
_WHY = {"type": "string", "minLength": MIN_WHY}
# adds の kind のうち name が識別子（関数・欄の名）の物。ファイルの名・パスだけの name（_file_name）を gaps が拒む（依頼 194c:
# receivers.py と書いた名を TDD の輪が 'py' と比べた）。文書・設定・CLI・柵・腕・テストなどはファイルを名指すのが筋の時が在るので見ない
SYMBOL_KINDS = ("function", "record_field")
_PATHLIKE = re.compile(r"[A-Za-z0-9_./-]+")
_FILE_EXT = re.compile(r".*\.(?:py|md|json|ya?ml|sh|js|ts|toml|txt|cfg|ini|csv|html?)")   # / を含む名の最後の段のファイルの拡張子
# canonical の頭（か頭の『新設』の後）の .py のパス。canonical に『新設』が在る時だけ、split がそのパスを宣言した名前に足す
_NEW_MODULE = re.compile(r"^\s*(?:新設[\s:：、。]*)?([A-Za-z0-9_./-]+\.py)(?![\w.])")
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

REJECT = ("修正案の項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope）か adds の name に欠けか誤りが在る"
          "（直して done し直す）。下の行を直した案を丸ごと出し直せ:")
# 修正案の役の指示書の頭に足す文（写しの指示書はこの欄を知らない）
HEAD = ("修正案の項目の works の欄: 写しの指示書はこの欄を知らないが、plan[] の各項目に必ず書け。"
        "route＝直し方の道（tdd＝先に落ちる受け入れのテストを書いてから直す・direct＝テストを先に書かずに直す）。"
        f"route_why＝direct を選んだ理由（route が direct なら {MIN_WHY} 字以上。tdd なら空でよい）。"
        "tests＝この項目で新しく足す受け入れのテストの並び（route が tdd なら 1 本以上）。各行は id（<パス>::<クラス>::<名前> か "
        "<パス>::<名前>。パスは作業ツリーの根からの相対で、まだ無いテストを名指す）・behavior（確かめる振る舞い）・path（本物の経路を"
        "どう通すか。mock の戻り値を断言しない）・red_kind・red_why（今のコードでなぜ赤になるか）。red_kind は断言の失敗（assertion）か"
        "期待した例外が出ない（exception）のどちらかで、項目の adds に宣言した名前の失敗は赤に数え、宣言の外の名前・import や収集の失敗は赤に数えない。"
        "tests の id と置き場は、名指すファイル（無ければ同じディレクトリの既存のテストのファイル）の既存のテストの置き方"
        "（クラスの中か一番外か・クラス名の付け方）に合わせよ。"
        "rewrite_tests＝依頼で振る舞いが変わるため期待を書き換える既存のテストの並び。各行は id（作業ツリーに在るテストの定義）・"
        "behavior（変わる振る舞い）・old（今の期待）・new（新しい期待）。期待値を実装に合わせるための書き換えは書かない。"
        f"refactor＝整えの申告 {{declared, why}}（整えをするなら declared を true にし、why に {MIN_WHY} 字以上で理由を書く）。"
        "承認された案は項目ごとの brief に切り出され、修正役・TDD の役の要求の正本になる。rewrite_tests に名指さない既存のテストは"
        "修正で変えられない。欠けや誤りは、受け付けが plan[<i>].<欄> の行を名指して拒む。"
        "allowed_paths＝その項目で書いてよいパスの glob の並び（1 つ以上。作業ツリーの根からの相対・/ 区切り・** は段をまたぐ）。"
        "tests・rewrite_tests の id のファイルは書かなくても範囲に入り、out_of_scope の glob をそのファイルに当てた案は拒む。"
        "移す・消すファイルの元のパスも allowed_paths に書け。"
        "** や * や **/* や **/?* や **/*.* のような字の無い（* と ? と [..] と . だけの）丸ごとの許しは拒む。"
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
    return marks.add("plan", node, schema, FIELD_SCHEMA, required=REQUIRED)


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
    （/・ドライブ文字・~ で始まる）・`..` の段で根の外へ上る・整えた形でない綴り（./x・a/../b・a//b）・字の無い glob（* と ? と
    [..] と / と . だけ。**・*・**/*・**/?*・[a-z]*・**/*.* のような丸ごとの許し。全部のファイルに当たり得る）を拒む。整えずに拒む（差分のパスは整えた綴りなので、整えない綴りの glob は当たらない）。
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
    if not any(_literal(seg) for seg in norm.split("/")):
        return "丸ごとの許し（字が無く * と ? と [..] と . だけの glob）は拒む。項目の直しが触るファイルかディレクトリまで狭めよ"
    if norm != glob.rstrip("/"):
        return f"整えた形でない（./・..・// を含む）。整えた形 {norm} で書け"
    return None


def _literal(seg: str) -> bool:
    """glob の 1 区切りに、* と ? と [..]（_segment と同じ読み）と . の外の字が在るか"""
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "[":
            j = i + 1 + (seg[i + 1:i + 2] == "!")
            j += seg[j:j + 1] == "]"
            k = seg.find("]", j)
            if k > 0:
                i = k + 1
                continue
        if c not in "*?.":   # . だけの字（*.*・**/.*）は拡張子を持つ全部・隠しの全部に当たる
            return True
        i += 1
    return False


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


# ---------------------------------------------------------------- 約束の欄の比べ
def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _contract_value(it: dict, key: str) -> str:
    """約束の欄 key の比べる字（欄が無い・None は空の並びと同じ。unit_keys は並べ替える。rewrite_tests の行は型の欄
    （FIELD_SCHEMA）だけで比べる——凍結の控えの行は split が足した範囲 limit を持ち、返答の行は型で持てないので）"""
    v = it.get(key) if isinstance(it, dict) else None
    v = [] if v is None else v
    if key == "unit_keys" and isinstance(v, list):
        v = sorted(v, key=_canon)
    if key == "rewrite_tests" and isinstance(v, list):
        props = FIELD_SCHEMA["rewrite_tests"]["items"]["properties"]
        v = [{k: row[k] for k in props if k in row} if isinstance(row, dict) else row for row in v]
    return _canon(v)


def _test_contract(it: dict) -> str:
    """tests[] の行の約束の欄（CONTRACT_TEST_KEYS）の並べ替えた並びの字"""
    rows = [{k: row.get(k) for k in CONTRACT_TEST_KEYS} for row in _rows(it, "tests") if isinstance(row, dict)] \
        if isinstance(it, dict) else []
    return _canon(sorted(rows, key=_canon))


def contract_diff(old: dict, new: dict) -> list[str]:
    """2 つの項目の約束の欄のうち違う物の名（CONTRACT_KEYS の順。最後に tests[] の behavior の並びが違えば "tests.behavior"）。
    手段の欄（MEANS_KEYS・tests[] の id・path・red_kind・red_why）だけの違いは空。比べは json.dumps（sort_keys）の字で、
    unit_keys と tests の行は並べ替えて比べ、欄が無いのと空の並びは同じと読む。narrows は関所の決め手の欄を外した形で渡す。純粋"""
    out = [k for k in CONTRACT_KEYS if _contract_value(old, k) != _contract_value(new, k)]
    if _test_contract(old) != _test_contract(new):
        out.append("tests.behavior")
    return out


def _item_value(it: dict, key: str) -> str:
    """項目の欄 key の比べる字（約束の欄は _contract_value、tests は行の全部の欄を並べ替えた並び、ほかは字のまま。無いのは None）"""
    if key in CONTRACT_KEYS:
        return _contract_value(it, key)
    v = it.get(key) if isinstance(it, dict) else None
    if key == "tests" and isinstance(v, list):
        v = sorted(v, key=_canon)
    return _canon(v)


def _scope_rows(it: dict, key: str) -> list:
    return _rows(it, key) if isinstance(it, dict) else []


def widened(old: dict, new: dict) -> dict | None:
    """直した項目 new が承認済みの項目 old の範囲を広げただけか。違いが allowed_paths に足した行と out_of_scope から外した行
    （WIDEN_KEYS）だけで、どちらかが 1 行以上在れば {"allowed_paths": [足した glob…], "out_of_scope": [外した行の glob…]}（new・old
    の並びの順）。ほかの欄（約束の欄も手段の欄も。tests は行の全部の欄）が 1 つでも違う・allowed_paths から外した・out_of_scope に
    足したか行を書き換えた・何も広げていない・足した glob が誤り（glob_problem。**/?* のような丸ごとの許しも）・old が
    allowed_paths を持たない（範囲の縛りの無い項目）なら None。比べは contract_diff と同じ読み（unit_keys と tests の並べ替え・
    rewrite_tests の範囲 limit は数えない）。narrows は関所の決め手の欄を外した形で渡す。純粋"""
    if not isinstance(old, dict) or "allowed_paths" not in old:   # 範囲の欄の無い項目（縛りが無い）に書くのは狭める物
        return None
    keys = (set(old) | set(new)) - set(WIDEN_KEYS)
    if any(_item_value(old, k) != _item_value(new, k) for k in keys):
        return None
    old_paths = {_canon(p) for p in _scope_rows(old, "allowed_paths")}
    new_paths = {_canon(p) for p in _scope_rows(new, "allowed_paths")}
    old_oos = {_canon(r) for r in _scope_rows(old, "out_of_scope")}
    new_oos = {_canon(r) for r in _scope_rows(new, "out_of_scope")}
    if not old_paths <= new_paths or not new_oos <= old_oos:
        return None
    added = list(dict.fromkeys(p for p in _scope_rows(new, "allowed_paths") if _canon(p) not in old_paths))
    if any(not isinstance(p, str) or glob_problem(p) for p in added):   # 誤った・丸ごとの glob は広げるだけと数えない（聞く）
        return None
    removed = [r.get("glob") if isinstance(r, dict) else r for r in _scope_rows(old, "out_of_scope") if _canon(r) not in new_oos]
    if not added and not removed:
        return None
    return {"allowed_paths": added, "out_of_scope": removed}


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


def _file_name(name: str) -> bool:
    """name がファイルの名・パスだけか: ASCII の語・. ・- ・/ だけで、.py で終わるか、/ を含み最後の段がファイルの拡張子
    （_FILE_EXT）で終わるか、/ で始まらずに / を含み最後の段に . が無い（app/receivers）。/ の無いほかの拡張子の名
    （Response.json・event.ts）・パスの後ろの属性（tests/_real_db.SKIP_REASON・app/stats.mean）・/ で始まる欄の指し（/plan/adds）は
    修飾した識別子と分けられないので当たらない。説明の文・<パス>::<名前>・Stats.median も当たらない"""
    s = name.strip()
    if not _PATHLIKE.fullmatch(s):
        return False
    if s.endswith(".py"):
        return True
    last = s.rsplit("/", 1)[-1]
    return "/" in s and (bool(_FILE_EXT.fullmatch(last)) or ("." not in last and not s.startswith("/")))


def gaps(reply: dict, repo: pathlib.Path, *, exists=None) -> list[str]:
    """修正案の返答の works の欄の欠けと誤りの行と、kind が SYMBOL_KINDS の adds の name がファイルの名・パスだけの行
    （"plan[<i>].<欄>…: <理由>"）。空なら通る。返答や plan が形を成さなければ空
    （写しの規則が型で拒む）。例外で拒まない。exists(test_id) -> 定義の行 | None は、受け入れのテスト（tests）が既に在るかを
    引く口（None なら find_test で作業ツリーを引く。同じ run の中の案の直しは修正の起点の版の木で引く）"""
    plan = reply.get("plan") if isinstance(reply, dict) else None
    if not isinstance(plan, list):
        return []
    if exists is None:
        def exists(tid):
            return find_test(repo, tid)
    out, new_ids, kinds = [], {}, {}
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
            line = exists(tid) if tid else None
            if tid:
                new_ids.setdefault(tid, f"plan[{i}].tests[{j}]")
                first, kind = kinds.setdefault(tid, (f"plan[{i}].tests[{j}]", row.get("red_kind")))
                if kind != row.get("red_kind"):
                    out.append(f"plan[{i}].tests[{j}].id（{tid}）: 同じ id を {first} にも別の red_kind（{kind}）で書いた"
                               "（同じテストの赤の種類は 1 つにそろえよ）")
            if line is not None:
                out.append(f"plan[{i}].tests[{j}].id（{tid}）: 既に在るテスト（{posixpath.normpath(_parse_id(tid)[0])}:{line}）。"
                           "tests はまだ無いテストを名指す。"
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
        for j, add in enumerate(it.get("adds") if isinstance(it.get("adds"), list) else []):
            name = add.get("name") if isinstance(add, dict) and add.get("kind") in SYMBOL_KINDS else None
            if isinstance(name, str) and _file_name(name):
                out.append(f"plan[{i}].adds[{j}].name（{name}）: kind が {add['kind']} の name はファイルの名・パスでなく識別子"
                           "（足す関数・欄の名。例 handle・Receiver.handle・app.receivers.handle）で書け。置くファイルのパスは "
                           "canonical に書け（新しいモジュールは canonical を『<パス>.py（新設。理由）』と書けば、そのモジュールも宣言した"
                           "名前になる。TDD の輪は宣言した名前を名前・import の失敗の無い名前と比べ、修正の受け付けは name を差分の足した行で探す）")
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


def _new_module(repo: pathlib.Path, canonical) -> str | None:
    """canonical が『新設』で頭に名指す .py のパス（_NEW_MODULE）のうち、作業ツリーの根の中でまだ無いファイルの物。ほかは None
    （在るファイルに新設の関数を足す行・根の外のパスは、モジュールを宣言しない）"""
    m = _NEW_MODULE.match(canonical) if isinstance(canonical, str) and "新設" in canonical else None
    norm = posixpath.normpath(m.group(1)) if m else None
    if norm is None or norm.startswith("/") or climbs(norm) or (pathlib.Path(repo) / norm).exists():
        return None
    return m.group(1)


def _declared(adds, repo: pathlib.Path) -> list[str]:
    """項目の adds の宣言した名前の並び: 各行の name（今までどおり全部）と、canonical が新設の無いモジュールを名指す行のその
    パス（_new_module。まだ並びに無ければ。新しいモジュールの import の失敗を TDD の輪が宣言の赤に数える。依頼 194c の nodeio.py）"""
    out = []
    for a in adds if isinstance(adds, list) else []:
        if not (isinstance(a, dict) and isinstance(a.get("name"), str)):
            continue
        out.append(a["name"])
        mod = _new_module(repo, a.get("canonical"))
        if mod and mod not in out:
            out.append(mod)
    return out


def split(reply: dict, repo: pathlib.Path) -> tuple[dict, list[dict]]:
    """（works の欄を外した返答の写し, 項目と同じ並びの欄）。欄の行は外した欄に、項目の unit_keys の写しと、宣言した名前 adds
    （_declared: adds の name と、canonical が新設の無いモジュールを名指す行のパス）と、rewrite_tests の各行の書き換えてよい範囲
    limit（"<パス>:<定義の行>"。引けない行には付けない）を足した物。gaps を通った返答に使う"""
    out, rows = marks.split("plan", NODE, reply, KEYS)
    items = out.get("plan") if isinstance(out, dict) else None
    for it, got in zip(items if isinstance(items, list) else [], rows):
        if not isinstance(it, dict):   # 形の崩れた項目の欄は空のまま
            continue
        got["unit_keys"] = copy.deepcopy(it.get("unit_keys") or [])
        got["adds"] = _declared(it.get("adds"), repo)
        for row in got.get("rewrite_tests") or []:
            lim = _limit(repo, _id_of(row)) if _id_of(row) else None
            if lim:
                row["limit"] = lim
    return out, rows


# ---------------------------------------------------------------- 盤面の控え
class FieldsBroken(ValueError):
    """盤面の控え plan-fields.json が今の周の凍結の印（SAVED_OP）と合わない（受け付けの後に書き換えた・消した・読めない）"""


def save(board, rnd: int, fields: list, amended: dict | None = None, *, trace=None) -> None:
    """盤面の plan-fields.json を今の周の欄で置き換え（一時のファイルから os.replace。リンクの先へ書かない）、盤面の trace に
    凍結の印 SAVED_OP {round, sha256（置いたバイトの sha256）} を 1 行足す。trace は開いた盤面の書き口（DiskBoard.trace。行に
    部品の scope が載る）で、渡さなければ同じ行の形 {t, op, …} で trace.jsonl に直に足す。
    amended（{番号: 核の欄}）が在れば鍵 AMENDED_KEY に番号を字にして置く（無ければ鍵を書かない）"""
    d = pathlib.Path(board)
    doc = {"round": rnd, "fields": fields}
    if amended is not None:
        doc[AMENDED_KEY] = {str(n): core for n, core in amended.items()}
    raw = marks.write(marks.path_of("plan", d), doc)
    row = {"round": rnd, "sha256": hashlib.sha256(raw).hexdigest()}
    if trace is not None:
        trace(SAVED_OP, **row)
        return
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": SAVED_OP, **row}, ensure_ascii=False) + "\n")


def _doc(b) -> dict | None:
    """今の周（b.round）の控えの全体。控えが無い・周が違う・読めない・fields が並びでないなら None"""
    doc = marks.load(marks.path_of("plan", b))
    if not isinstance(doc, dict) or doc.get("round") != b.round or not isinstance(doc.get("fields"), list):
        return None
    return doc


def read(b) -> list | None:
    """今の周（b.round）の欄の並び。控えが無い・周が違う・読めないなら None（b.dir・b.round だけを読む）"""
    doc = _doc(b)
    return doc["fields"] if doc else None


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
    """今の周の承認済みの修正案の項目（plan_items。差し替えた項目は直した核の欄）と凍結した欄（frozen）を同じ番号で合わせた並び
    {"item": <1 始まり>, **案の項目, **欄の KEYS の物}（unit_keys は案の物）。どちらか無ければ None。数が違えば FieldsBroken
    （frozen の食い違いもそのまま FieldsBroken。b は dir・round・output_of_round を読む）"""
    fields = frozen(b)
    plan = plan_items(b)
    if fields is None or plan is None:
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


def scoped(items: list | None) -> bool:
    """承認済みの項目の並び items が範囲の欄を持つか（並びが在り、どの項目にも allowed_paths が在る）。偽なら範囲の無い run
    （修正案の無い run・217 番の形の控え）として扱う"""
    return items is not None and all(isinstance(it, dict) and "allowed_paths" in it for it in items)


def scoped_items(b) -> list[dict] | None:
    """範囲の欄の在る承認済みの項目（approved_items が scoped の時だけ。ほかは None）。控えの食い違いは FieldsBroken"""
    items = approved_items(b)
    return items if scoped(items) else None


def frozen(b) -> list | None:
    """今の周の凍結した欄の並び（read と同じ物）。今の周の印が無ければ None（印の無い控えは無い物: 変更前の盤面・save の外で
    置いた控え）。印が在るのに控えが読めない・控えのバイトの sha256 が印と違えば FieldsBroken"""
    doc = _frozen_doc(b)
    return doc["fields"] if doc else None


def _frozen_doc(b) -> dict | None:
    """今の周の凍結した控えの全体（frozen の決まりで読む: 印が無ければ None・食い違えば FieldsBroken）"""
    mark = _saved_mark(b)
    if mark is None:
        return None
    p = marks.path_of("plan", b)
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise FieldsBroken(f"盤面の控え {p}（{FIELDS_FILE}）が読めない。周 {b.round} の {SAVED_OP} の印が在る: {e}") from None
    if hashlib.sha256(raw).hexdigest() != mark.get("sha256"):
        raise FieldsBroken(f"盤面の控え {p}（{FIELDS_FILE}）のバイトの sha256 が周 {b.round} の {SAVED_OP} の印と違う"
                           "（受け付けの後に書き換えた）")
    return _doc(b)


def amended(b) -> dict[int, dict]:
    """今の周の凍結した控えの差し替えた項目の核の欄 {番号（int）: {CORE_KEYS の欄}}。控えか鍵 AMENDED_KEY が無ければ {}。
    印と食い違えば・形が違えば FieldsBroken"""
    doc = _frozen_doc(b)
    got = doc.get(AMENDED_KEY) if doc else None
    if got is None:
        return {}
    try:
        out = {int(n): core for n, core in got.items()}
    except (AttributeError, TypeError, ValueError):
        out = None
    if out is None or not all(isinstance(c, dict) for c in out.values()):
        raise FieldsBroken(f"盤面の控え {FIELDS_FILE} の {AMENDED_KEY} の形が違う（{{番号: 核の欄}} でない）")
    return out


def plan_items(b) -> list | None:
    """今の周の修正案の項目の並び: p2.fix_plan の出力の plan に、amended(b) の核の欄を番号ごとに重ねた物（差し替えの後の案）。
    出力の plan が無ければ None。控えの番号が案の外なら FieldsBroken（b は dir・round・output_of_round を読む）"""
    doc = b.output_of_round(NODE, b.round)
    plan = doc.get("plan") if isinstance(doc, dict) else None
    if not isinstance(plan, list):
        return None
    out = copy.deepcopy(plan)
    for n, core in amended(b).items():
        if not 1 <= n <= len(out):
            raise FieldsBroken(f"盤面の控え {FIELDS_FILE} の {AMENDED_KEY} の項目 {n} が修正案の項目（{len(out)} 個）の外")
        base = out[n - 1] if isinstance(out[n - 1], dict) else {}
        out[n - 1] = {**base, **copy.deepcopy(core)}
    return out


def amend(b, items: dict, repo) -> None:
    """承認済みの項目を直した項目に差し替えて凍結し直す。items は {番号: 直した項目（CORE_KEYS と KEYS の欄の全部。鍵 item は
    外す）}。直した項目を split に通して欄の行を作り直し（adds の名と rewrite_tests[].limit を repo から引き直す）、今の控え
    （frozen。食い違えば FieldsBroken）の fields[n-1] をその行に替え、核の欄を AMENDED_KEY[n] に置いて save し直し、trace に
    AMEND_OP {round, items} を書く。知らない番号・unit_keys が元と違う項目は ValueError（受け付けが先に拒む物）で、その時は控えも
    trace も変えない。b は dir・round・output_of_round・trace（盤面の trace の書き口）だけを使う"""
    current = approved_items(b)
    if current is None:
        raise ValueError(f"差し替える承認済みの修正案が無い（周 {b.round} の案か凍結した控え {FIELDS_FILE} が無い）")
    fields = copy.deepcopy(frozen(b))
    done = amended(b)
    for n in items:
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(current):
            raise ValueError(f"知らない項目の番号 {n!r}（承認済みの項目は 1〜{len(current)}）")
        it = {k: copy.deepcopy(v) for k, v in items[n].items() if k != "item"}
        if _contract_value(it, "unit_keys") != _contract_value(current[n - 1], "unit_keys"):
            raise ValueError(f"項目 {n} の unit_keys が元と違う（元 {current[n - 1].get('unit_keys')!r}・"
                             f"直した物 {it.get('unit_keys')!r}。差し替えは同じ単位の項目だけ）")
        _, rows = split({"plan": [it]}, repo)
        fields[n - 1] = rows[0]
        done[n] = {k: it[k] for k in CORE_KEYS if k in it}
    save(b.dir, b.round, fields, amended=dict(sorted(done.items())), trace=b.trace)
    b.trace(AMEND_OP, round=b.round, items=sorted(items))


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


def unit_contract(fields: list | None, key: str) -> dict | None:
    """単位 key の約束 {items: 項目の番号（1 始まり）, route, tests: [{id, red_kind}], rewrites: [id], refactor: [{item, why}], names: [宣言した名前（欄の adds）]}。
    key を unit_keys に含む項目の欄を合わせる: route はどれかの項目が tdd なら tdd（ほかは direct）・tests は項目の順で id の重複を
    除く（同じ id に別の red_kind は gaps が拒む）・rewrites は範囲 limit の在る行の id だけ（rewrites と同じ選び方）・refactor は
    refactor.declared が真の項目の番号と理由（申告が無ければ空）・names は項目の欄の adds（split の宣言した名前）を項目の順で重複を除いた列。
    fields が None か、当たる項目が無ければ None。純粋（盤面もファイルも読まない）"""
    if not isinstance(fields, list):
        return None
    items, tests, rws, names = [], {}, {}, {}
    route, refactor = "direct", []
    for n, f in enumerate(fields, 1):
        keys = f.get("unit_keys") if isinstance(f, dict) else None
        if not isinstance(keys, list) or key not in keys:
            continue
        items.append(n)
        route = "tdd" if f.get("route") == "tdd" else route
        for row in _rows(f, "tests"):
            if _id_of(row):
                tests.setdefault(row["id"], row.get("red_kind"))
        for row in _rows(f, "rewrite_tests"):
            if _id_of(row) and isinstance(row.get("limit"), str) and row["limit"]:
                rws.setdefault(row["id"])
        for nm in f.get("adds") or []:
            if isinstance(nm, str) and nm:
                names.setdefault(nm)
        rf = f.get("refactor")
        if isinstance(rf, dict) and rf.get("declared") is True:
            refactor.append({"item": n, "why": rf.get("why").strip() if isinstance(rf.get("why"), str) else ""})
    if not items:
        return None
    return {"items": items, "route": route, "tests": [{"id": i, "red_kind": k} for i, k in tests.items()],
            "rewrites": list(rws), "refactor": refactor, "names": list(names)}


def review_section(b) -> str:
    """事前審査の役の指示書の頭に貼る節（"\\n\\n" で始まる）: 見る点の頼みと、項目ごとの欄の JSON。控えが無ければ空。
    控えは frozen で読む（凍結の印と食い違えば FieldsBroken。読む側が盤面を止める）"""
    fields = frozen(b)
    if fields is None:
        return ""
    rows = [f"### 修正案の項目 {n}\n\n```json\n{json.dumps(f, ensure_ascii=False, indent=1)}\n```" for n, f in enumerate(fields, 1)]
    return f"\n\n{REVIEW_HEAD}\n\n{REVIEW_ASK}\n\n" + "\n\n".join(rows)
