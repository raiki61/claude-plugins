"""承認済みの修正案の項目と修正の差分を機械が照らす（blk-fix。依頼 218）。修正の受け付け（scripts/accept.py の check_plan_scope）が
呼び、外れを同じ brief のまま修正役に返す。AI を通さない。

語:
- 項目: planmarks.approved_items の行（案の項目に、凍結した works の欄 allowed_paths・out_of_scope・tests・rewrite_tests を足した物）
- 行（rows）: 受けた返答の changes を単位の名前に戻した物 {unit_key, files}（files は根からの相対）
- 変わったパス（changes）: 修正前の版からの変更 → (版の中身, 今の中身)。無い側は None
- 項目の範囲: allowed_paths の glob と、tests・rewrite_tests の id のファイル（planmarks.test_paths）。out_of_scope は範囲の中でも
  触らない物で、範囲より強い（修正案の受け付けが、out_of_scope と id のファイルの重なりを先に拒む）
- 外れた項目: unit_keys の全部が、裁定で直す義務から外れた単位（held。conflict.held_by_rulings の {key: 理由}。fix_plan_item は
  その項目の単位の全部を外す）の項目。範囲を与えない（範囲の和・tests の名に入れず、見る項目にしない）。out_of_scope は残す
  （裁定で範囲を広げない）。拒んだパスが外れた項目の範囲に入れば、その項目と外した裁定を名指して戻させる（revert_ruled_units
  は他の単位と共にするファイルを戻さないので、その項目の直しが作業ツリーに残りうる）
- 見る項目: 外れた項目でなく、unit_keys が行のどれかの単位と重なる項目
- 生きた項目: unit_keys の全部が行に在る見る項目。欠けを拒む側（Missing: 範囲の中の変更・adds・removes・tests）は生きた項目
  だけを見る（止めた・外した単位の分の欠けで、残った単位を巻き添えに止めない）。範囲の外れと余分（Extra）は見る項目の全部で見る
- 凍ったファイル（loop）: TDD の輪が凍らせたファイルと凍った時の中身。欠けの証拠は版からの差分の全部で見て、修正役に問う外れと
  余分は凍った後に修正役が変えた分だけで見る（輪が書いた物を修正役のせいにしない・凍った後に足したテストを見逃さない）
- permits: テストの変更の許し（conflict.test_permits の修正案の rewrite_tests）と、裁定の後なら直す裁定（conflict.ruled_paths。
  fix_code_as・fix_test_scope・replace_query）の limits のパス。run の全部の項目の範囲の和に入る（裁定の単位の項目だけに
  結ばない）。裁定で範囲が広がるのはこのパスだけで、裁定を受けた単位の全部を外さない（外せば fix_code_as が案の外の変更を
  通す）。out_of_scope には勝たない（案が外したパスが要るのは案の項目の誤りで、fix_plan_item の道）
- 識別子の形（IDENT）: adds の name・removes の名のうち、差分で機械が探す物。kind を問わず :: と . で割った最後の段で探す。
  日本語や空白を含む説明の文と、/ を含む名（ファイルのパス）は探さず、記録の unchecked に並べる（誤った拒否を重ねて単位を
  止めない）
- 残った（removes）: 修正の後の .py を ast で読み、名がまだ定義されている（名を消した行か定義を足した行を持つファイルで）。
  . か :: の修飾子は、そのファイルの最上位のクラスなら クラス.名、モジュール名か :: の前のパスなら最上位の素の名で照らす。.py でない・構文が読めないファイルは、足した行に定義の行（def・class・代入・関数の形）が在れば
  残る。名を挙げるだけの行（消えたことを確かめる hasattr・変更の記録の注記）は残ったと見ない

拒否の行はどれも、行の単位の key か項目の unit_keys の全部を字のまま含める（輪の 3 回目に accept.bind_problems が単位に結ぶ）。
ただし行に申告の無い変わったパスの外れは単位を名指せないので、パスだけを書く。

- added_removed(base, now): 行の並びの足した行と消した行
- new_test_ids(path, base, now): 試験のモジュールで新しく現れたテストの id
- problems(items, rows, changes, *, held, permits): 拒否の行と記録（純粋な関数）
- check(rows, b, repo, rev, paths, *, pass_): 盤面と作業ツリーから材料を集めて problems に渡す。照らさない盤面では理由を記録に書く
"""
from __future__ import annotations

import ast
import difflib
import pathlib
import posixpath
import re
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import conflict  # noqa: E402
import leftovers  # noqa: E402
import planmarks  # noqa: E402
import tddloop  # noqa: E402   試験のモジュールの名の型（PYTEST_FILE）の正本

REJECT = "承認済みの修正案の項目から外れた（同じ brief のまま直して出し直せ。範囲の外が要るなら変えずに食い違いの申し出で返せ）: "
SCOPE_OP = "fix_plan_scope"   # 受けた時の盤面の trace の行（照らした印か、照らさなかった理由）
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]*$")
NO_PLAN = "承認済みの修正案か works の欄の控えが無い"
NO_SCOPE = "範囲の欄の無い控え（217 番の形の盤面）"


# ---------------------------------------------------------------- 差分の読み
def _lines(text: str | None) -> list[str]:
    return text.splitlines() if isinstance(text, str) else []


def added_removed(base: str | None, now: str | None) -> tuple[list[str], list[str]]:
    """行の並びを difflib.SequenceMatcher の opcodes で比べた (足した行, 消した行)。insert・replace の新しい側が足した行、
    delete・replace の古い側が消した行。None は空の中身"""
    old, new = _lines(base), _lines(now)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            added += new[j1:j2]
        if tag in ("delete", "replace"):
            removed += old[i1:i2]
    return added, removed


def _test_ids(path: str, src: str | None) -> list[str] | None:
    """src の中のテストの id（名が test で始まる最上位の関数と、最上位のクラスのメソッド）。構文が壊れていれば None"""
    try:
        tree = ast.parse(src or "")
    except (SyntaxError, ValueError):
        return None
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    out = []
    for node in tree.body:
        if isinstance(node, funcs) and node.name.startswith("test"):
            out.append(f"{path}::{node.name}")
        elif isinstance(node, ast.ClassDef):
            out += [f"{path}::{node.name}::{m.name}" for m in node.body if isinstance(m, funcs) and m.name.startswith("test")]
    return out


def new_test_ids(path: str, base: str | None, now: str | None) -> list[str]:
    """path が試験のモジュール（.py で名が test_*.py か *_test.py）の時だけ、now に在って base に無いテストの id
    （<path>::<クラス>::<名>・<path>::<名>）。now の構文が壊れていれば []（base が壊れていれば全部を新しい物に数える）"""
    if not tddloop.PYTEST_FILE.match(posixpath.basename(path)):
        return []
    got = _test_ids(path, now)
    if not got:
        return []
    before = set(_test_ids(path, base) or [])
    return [t for t in got if t not in before]


# ---------------------------------------------------------------- 照らし
def _keys(it: dict) -> list[str]:
    return [k for k in it.get("unit_keys") or [] if isinstance(k, str)]


def _who(it: dict) -> str:
    """項目を名指す頭 "項目 <n>（<unit_keys の全部>）" """
    return f"項目 {it.get('item')}（{'・'.join(_keys(it))}）"


def _globs(it: dict) -> list[str]:
    return [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g]


def _oos(it: dict) -> list[str]:
    return [r["glob"] for r in it.get("out_of_scope") or [] if isinstance(r, dict) and isinstance(r.get("glob"), str)
            and r["glob"]]


def _inside(path: str, it: dict) -> bool:
    """path が項目の範囲（allowed_paths の glob・tests と rewrite_tests の id のファイル）に入るか"""
    return path in planmarks.test_paths(it) or any(planmarks.glob_match(path, g) for g in _globs(it))


def _oos_hit(path: str, items: list[dict]):
    """path に当たる out_of_scope の最初の (項目, glob)。無ければ None"""
    return next(((it, g) for it in items for g in _oos(it) if planmarks.glob_match(path, g)), None)


def _word(name: str):
    return re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")


def _definition(name: str):
    n = re.escape(name)
    return re.compile(rf"(?:def|class)\s+{n}\b|^{n}\s*=|^(?:function\s+)?{n}\s*\(\)")


def _lookup(name) -> str | None:
    """adds の name・removes の名で差分を探す語（:: と . で割った最後の段）。識別子の形でない・/ を含む名は None（確かめない）"""
    if not isinstance(name, str) or not IDENT.match(name) or "/" in name:
        return None
    last = re.split(r"::|\.", name)[-1]
    return last or None


def _defined_names(src: str | None):
    """.py の中身で定義された名 (素の名の集合（最上位の def・class・代入）, クラス.名 の集合（最上位のクラスの中の def・代入）,
    最上位のクラスの名の集合)。構文が読めなければ None"""
    try:
        tree = ast.parse(src or "")
    except (SyntaxError, ValueError):
        return None

    def names(body):
        got = set()
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                got.add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        got.add(t.id)
        return got
    bare = names(tree.body)
    qual = {f"{c.name}.{m}" for c in tree.body if isinstance(c, ast.ClassDef) for m in names(c.body)}
    return bare, qual, {c.name for c in tree.body if isinstance(c, ast.ClassDef)}


def _qualifier(raw: str) -> str | None:
    """名の修飾子（最後の :: か . より前）。修飾子の無い名は None"""
    cut = max(raw.rfind("::"), raw.rfind("."))
    return raw[:cut] if cut > 0 else None


def _owns(qual: str, raw: str, path: str, classes: set) -> str | None:
    """修飾子をファイルごとに解く（1 本の規則）: 修飾子の最後の段がそのファイルの最上位のクラスなら "class"（クラス.名 で照らす）、
    修飾子がそのファイルのモジュール名（拡張子を除いたファイル名・/ を . にした根からのパス）か :: の前のパスなら "module"
    （最上位の素の名で照らす）、どちらでもなければ None（そのファイルの名ではない）"""
    if re.split(r"::|\.", qual)[-1] in classes:
        return "class"
    stem = posixpath.splitext(path)[0]
    if qual in (posixpath.basename(stem), stem.replace("/", ".")):
        return "module"
    if "::" in raw and posixpath.normpath(raw.split("::", 1)[0]) == path and qual == raw.split("::", 1)[0]:
        return "module"
    return None


def _remains(raw: str, name: str, changes: dict, diffs: dict) -> bool:
    """removes の名が修正の後も残っているか。変わった .py は今の中身を ast で読み、その名を消した行か定義を足した行を持つファイルで、
    名がまだ定義されていれば残る。修飾子の無い名は最上位の素の名で照らし、修飾子の在る名はファイルごとに解く（_owns: クラスなら
    クラス.名、モジュールなら最上位の素の名、どちらでもないファイルは見ない）。.py でない・構文が読めないファイルは、足した行に
    定義の行（_definition）が在れば残る"""
    qual = _qualifier(raw)
    word, define = _word(name), _definition(name)
    for p, (_, now) in changes.items():
        added, removed = diffs[p]
        defs = _defined_names(now) if p.endswith(".py") else None
        if defs is None:
            if any(define.search(line) for line in added):
                return True
            continue
        if not (any(word.search(line) for line in removed) or any(define.search(line) for line in added)):
            continue
        bare, qualified, classes = defs
        how = _owns(qual, raw, p, classes) if qual else "module"
        if (how == "class" and f"{re.split(r'::|[.]', qual)[-1]}.{name}" in qualified) or (how == "module" and name in bare):
            return True
    return False


def _test_key(test_id):
    """テストの id を比べる形 (整えたパス, 名の段)。形が違えば None（planmarks._parse_id の型）"""
    got = planmarks._parse_id(test_id)
    return (posixpath.normpath(got[0]), tuple(got[1])) if got else None


def _named_paths(text: str, paths) -> list[str]:
    """文 text に字のまま（前後がパスの字でない所に）現れるパス"""
    return [p for p in paths if re.search(rf"(?<![\w./-]){re.escape(p)}(?![\w/-])", text)]


def _all_held(it: dict, held) -> bool:
    """項目の unit_keys の全部が held に在る（外れた項目。conflict.held_item）。unit_keys の無い項目は外れていない"""
    return bool(conflict.held_item(_keys(it), held))


def _held_note(path: str, items: list[dict], held: dict) -> str:
    """path が外れた項目の範囲に入れば、その項目の番号と外した裁定（held の理由）を名指して戻させる文。無ければ空。単位の key は
    書かない（外れた単位に拒否を結ばない）"""
    out = ""
    for it in items:
        if _all_held(it, held) and _inside(path, it):
            why = conflict.held_item(_keys(it), held)
            out += f"（{path} は項目 {it.get('item')} の範囲で、項目 {it.get('item')} は {why} で直す義務から外れた。その項目の直しなら作業ツリーから戻せ）"
    return out


def problems(items: list[dict], rows: list[dict], changes: dict, *, held=None,
             permits=(), loop=None) -> tuple[list[str], dict]:
    """承認済みの修正案の項目（items）と差分の外れの行と記録 {"checked": True, "unchecked": [識別子の形でない名], "items": [見た
    項目の番号]}。純粋な関数（ファイル・盤面を読まない）。見る物は模块の docstring の語と、下の 1〜6:
    1. 行の files の各パスが、その単位の項目のどれかの範囲に入り、どの項目の out_of_scope にも当たらない（その単位の項目が
       無い行は 2 に回す）
    2. 1 で見なかった変わったパスが、外れた項目を除く全項目の範囲の和か permits に入り、どの項目の out_of_scope にも当たらない
    3. 生きた項目の範囲の中に変わったパスが 1 つも無ければ Missing
    4. adds: 探す語（_lookup）が、生きた項目ならどれかのパスの足した行に語の境で現れる（無ければ Missing）。canonical の文に
       変わったパスが字のまま在れば、ほかのパスの足した行の同名の定義は Extra（見る項目の全部）
    5. removes: 生きた項目なら、探す語がどれかのパスの消した行に現れ、どの足した行にも定義として現れない
    6. tests: 新しく現れたテストのうち、外れた項目を除くどの項目の tests にも無い物は Extra。生きた項目の tests の各 id は、
       そのパスが変わり、今の中身に定義の行が在る
    held は外れた単位と理由 {key: 理由}（conflict.held_by_rulings の形）。範囲（allowed_paths・tests の名）を与えるのは外れた項目を
    除く項目、out_of_scope は全項目の物。permits のパスは 1 でも範囲に入る。out_of_scope は permits にも勝つ（1・2 とも先に見る）。
    1・2 の範囲の外れのパスが外れた項目の範囲に入れば、行にその項目と裁定を足す（_held_note）。
    loop は TDD の輪が凍らせたファイル（パス → 凍った時の中身。無ければ None）。規則は 1 本: 欠け（Missing）の証拠は版からの差分の
    全部（changes）で見て、修正役に問う外れと余分（1・2・6 の Extra・canonical の外の定義）は凍った後に修正役が変えた分だけ
    （凍った時の中身と今の中身の差分）で見る。凍った後に変わっていないファイルは 1・2 で照らさない"""
    held, permits, loop = dict(held or {}), set(permits), dict(loop or {})
    granting = [it for it in items if not _all_held(it, held)]   # 範囲を与える項目（out_of_scope は items の全部で見る）
    out, unchecked = [], []
    row_keys = {r.get("unit_key") for r in rows if isinstance(r.get("unit_key"), str)}
    diffs = {p: added_removed(*pair) for p, pair in changes.items()}
    added_all = [(p, line) for p, (add, _) in diffs.items() for line in add]
    removed_all = [line for _, rem in diffs.values() for line in rem]
    # 修正役に問う側の差分: 凍ったファイルは凍った時の中身から今まで
    # 凍った時の中身が無い（凍った時の木で読めない）ファイルは版からの差分に戻す
    since = {p: (loop[p], pair[1]) if loop.get(p) is not None else pair for p, pair in changes.items()}
    fixer_added = [(p, line) for p, pair in since.items() for line in added_removed(*pair)[0]]
    untouched = {p for p in loop if loop[p] is not None and p in changes and changes[p][1] == loop[p]}

    def oos_line(head, path, hit):
        return f"{head}{path} は項目 {hit[0].get('item')} の out_of_scope（{hit[1]}）に当たる"

    # 1. 行の申告したファイル
    seen = set()          # 1 で見たパス（2 で重ねて書かない）
    for r in rows:
        key = r.get("unit_key")
        files = [f for f in r.get("files") or [] if isinstance(f, str)]
        mine = [it for it in granting if key in _keys(it)]
        if not mine:
            continue
        for f in files:
            seen.add(f)
            if f in untouched:
                continue
            hit = _oos_hit(f, items)
            if hit:
                out.append(oos_line(f"{key}: ", f, hit))
            elif not (f in permits or any(_inside(f, it) for it in mine)):
                nums = "・".join(str(it.get("item")) for it in mine)
                out.append(f"{key}: {f} は項目 {nums} の allowed_paths の外{_held_note(f, items, held)}")
    # 2. 変わったパスの全部
    for p in sorted(changes):
        if p in seen or p in untouched:
            continue
        hit = _oos_hit(p, items)
        if hit:
            out.append(oos_line("", p, hit))
        elif not (p in permits or any(_inside(p, it) for it in granting)):
            out.append(f"{p} はどの項目の allowed_paths にも無い{_held_note(p, items, held)}")
    # 3〜6. 見る項目（Missing 側は生きた項目だけ）
    looked = []
    named = {_test_key(row.get("id")) for it in granting for row in it.get("tests") or [] if isinstance(row, dict)}
    for it in granting:
        if not set(_keys(it)) & row_keys:
            continue
        looked.append(it.get("item"))
        who = _who(it)
        skip = not set(_keys(it)) <= row_keys
        if not skip and not any(_inside(p, it) for p in changes):
            out.append(f"{who}: 範囲の中に変えたファイルが無い")
        for add in it.get("adds") or []:
            raw = add.get("name") if isinstance(add, dict) else None
            if not isinstance(raw, str):
                continue
            name = _lookup(raw)
            if name is None:
                unchecked.append(raw)
                continue
            word = _word(name)
            if not skip and not any(word.search(line) for _, line in added_all):
                out.append(f"{who}: adds の {raw} が差分の足した行に無い")
            home = _named_paths(add.get("canonical") or "", changes) if isinstance(add.get("canonical"), str) else []
            if home:
                define = _definition(name)
                for p in sorted({p for p, line in fixer_added if p not in home and define.search(line)}):
                    out.append(f"{who}: adds の {raw} の canonical（{'・'.join(home)}）の外に同名の定義（{p}）")
        for raw in it.get("removes") or []:
            if not isinstance(raw, str):
                continue
            name = _lookup(raw)
            if name is None:
                unchecked.append(raw)
                continue
            if skip:
                continue
            word = _word(name)
            if not any(word.search(line) for line in removed_all) or _remains(raw, name, changes, diffs):
                out.append(f"{who}: removes の {raw} が差分で消えていない（消した行に無いか、足した行に定義が残る）")
        for row in [] if skip else it.get("tests") or []:
            tid = row.get("id") if isinstance(row, dict) else None
            key = _test_key(tid)
            if key is None:
                continue
            path = key[0]
            now = changes.get(path, (None, None))[1]
            if path not in changes or planmarks.line_in(now, tid) is None:
                out.append(f"{who}: tests の {tid} が修正の後の木に無い（変えたファイルにその定義が無い）")
    for p in sorted(since):
        for tid in new_test_ids(p, *since[p]):
            if _test_key(tid) in named:
                continue
            keys = [r["unit_key"] for r in rows if isinstance(r.get("unit_key"), str) and p in (r.get("files") or [])]
            head = f"{'・'.join(dict.fromkeys(keys))}: " if keys else ""
            out.append(f"{head}{tid} は修正案のどの項目の tests にも無いテストを足した")
    return out, {"checked": True, "unchecked": unchecked, "items": looked}


# ---------------------------------------------------------------- 盤面から
def _base_text(repo: pathlib.Path, rev: str, path: str) -> str | None:
    try:
        return leftovers.git(repo, "show", f"{rev}:{path}")
    except leftovers.Unreadable:
        return None   # 版に無い（新しいファイル）


def _now_text(repo: pathlib.Path, path: str) -> str | None:
    try:
        return (pathlib.Path(repo) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None   # 消した・読めない


def check(rows: list[dict], b, repo: pathlib.Path, rev: str, paths: list[str], *, pass_: str, loop_tree: str | None = None,
          frozen=()) -> tuple[list[str], dict]:
    """盤面 b の承認済みの修正案の項目（planmarks.approved_items）と、版 rev からの変わったパス paths の版と今の中身を problems に
    渡す。テストの変更の許し（conflict.test_permits）を先に引く（欄の控えが凍結の印と食い違えば、そこで盤面を止めて BoardGap）。
    裁定で直す義務から外れた単位（conflict.held_by_rulings）を held に渡す。裁定の後（pass_ が ruled）は直す裁定
    （conflict.ruled_paths）のパスを permits に足す（裁定を受けた単位の全部は外さない）。項目が無い・範囲の欄の無い
    控えなら照らさず ([], {"checked": False, "why": 理由})。項目と控えの欄の数が違えば conflict.fields_broken（盤面を止めて BoardGap）。
    loop_tree（TDD の輪が凍らせた時の木）と frozen（凍らせたファイル）を渡せば、凍った時の中身を problems の loop に渡す"""
    permits = []
    for p in conflict.test_permits(b, rulings=False):
        got = conflict.parse_limit(p["limit"])
        if got and got[0] not in permits:
            permits.append(got[0])
    if pass_ == "ruled":
        permits += [p for p in conflict.ruled_paths(b) if p not in permits]
    try:
        items = planmarks.approved_items(b)
    except planmarks.FieldsBroken as e:   # 控えが壊れた時の 1 本の道（盤面を止めて BoardGap）
        raise conflict.fields_broken(b, e) from None
    if items is None:
        return [], {"checked": False, "why": NO_PLAN}
    if not planmarks.scoped(items):
        return [], {"checked": False, "why": NO_SCOPE}
    changes = {p: (_base_text(repo, rev, p), _now_text(repo, p)) for p in paths}
    loop = {p: _base_text(repo, loop_tree, p) for p in paths if p in set(frozen)} if loop_tree else {}
    return problems(items, rows, changes, held=conflict.held_by_rulings(b), permits=tuple(permits), loop=loop)
