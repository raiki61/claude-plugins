"""返答の型検査。**JSON Schema そのものではなく engine 固有の型検査**（語を借りているだけ）。

pip 依存を持たない配布方針（issue #6）で jsonschema を使わない。見る語は type / enum / const /
required / properties / patternProperties / additionalProperties / items / minItems / maxItems / minimum / maximum /
minLength / maxLength / pattern だけで、これ以外は無視する（展開されていない $ref だけは無視せず拒む）。本家と意味が違う点を明記する:
  - enum / const は値だけでなく真偽値かどうかも見る（True を [0, 1] に一致させない）
  - minLength は**前後の空白を除いた長さ**（空白だけの返答を「在る」と数えないため）
  - maxLength は**素の長さ**（空白も数える）——上限は「役が作れる大きさ」を縛るもので、
    前後の空白を削ってから測ると、空白で水増しした値が上限をすり抜ける
  - pattern と patternProperties の鍵は Python の re で当てる。本家（JSON Schema 2020-12 validation §6.3.3）の方言は ECMA-262 で、
    揃えてあるのは `$` だけ（入力の末尾にだけ一致する——end_anchored）。\\d・\\w が Unicode の数字・語の字に一致する、`.` が CR や
    U+2028 にも一致する、といった差は残る（graph の pattern はこの差に当たらない字のクラスで書く）
この schema は役に貼るプロンプトにも「返答の形」として載るので、意味の差はここに書いて 1 か所にする。
エラーの一覧を返す（空なら合格）。
"""
import copy
import functools
import pathlib
import re


@functools.lru_cache(maxsize=None)
def end_anchored(pat):
    """pattern の `$`（エスケープの後と文字クラスの中を除く）を `\\Z` に読み替えた、コンパイル済みの正規表現。
    Python の `$` は末尾の改行の手前でも一致するので、`^[^\\n]+$` が改行 1 つで終わる値を通し、その値が git grep の -e で
    空の検索語に割れて全行に一致した（実測 2026-09-24: run_count が 2910 を返し、改行が無ければ 0）。ECMA-262 の `$` は入力の末尾だけ。
    検査（validate_schema）と graph の検査（graphcheck）は、同じこの関数を通した物を使う"""
    # 文字クラスの状態は「クラスの最初の字の位置」で持つ（Python の re の文書: `]` がクラスの中の字になるのは先頭に
    # 置いたときだけ——`[` の直後か、否定の `[^` の直後）。直前の 1 字で見ていたとき、エスケープした `\\[` の直後の `]` を
    # 字と読んでクラスを閉じ損ね、後ろの `$` を読み替えずに素通しした（`[\\[]a$`）
    out, esc, first = [], False, None   # first: クラスの中なら、その最初の字の位置。外なら None
    for i, ch in enumerate(pat):
        out.append("\\Z" if first is None and not esc and ch == "$" else ch)
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif first is None:
            if ch == "[":
                first = i + 2 if pat[i + 1:i + 2] == "^" else i + 1
        elif ch == "]" and i != first:
            first = None
    return re.compile("".join(out))


def _same(a, b):
    """== に真偽値の型も足す（True == 1 を一致にしない）。"""
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def validate_schema(value, schema, path="$"):
    if "$ref" in schema:
        # 展開されていない参照を「知らない語」として無視すると、その欄の型検査が丸ごと消えて何でも通る
        return [f"{path}: schema の $ref {schema['$ref']!r} が展開されていない（graph は load_graph を通して読め）"]
    errs = []
    types = schema.get("type")
    if types:
        if isinstance(types, str):
            types = [types]
        if not any(_is_type(value, t) for t in types):
            return [f"{path}: 型が {'/'.join(types)} でない（{type(value).__name__}）"]
    # 真偽値は int の部分型なので、素の `in` / `==` だと True が語彙 [0, 1] に一致する（実測）。型でも見る。
    if "enum" in schema and not any(_same(value, w) for w in schema["enum"]):
        errs.append(f"{path}: 値 {value!r} が語彙 {schema['enum']} に無い")
    if "const" in schema and not _same(value, schema["const"]):
        errs.append(f"{path}: 値 {value!r} が {schema['const']!r} でない")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: 必須の欄 '{k}' が無い")
        props = schema.get("properties", {})
        pats = schema.get("patternProperties", {})
        for k, v in value.items():
            # properties と patternProperties は両方当てる（JSON Schema 2020-12 と同じ）。どちらにも当たらない名前だけが
            # additionalProperties に回る
            hit = [s for pat, s in pats.items() if end_anchored(pat).search(k)]
            if k in props:
                errs += validate_schema(v, props[k], f"{path}.{k}")
            for s in hit:
                errs += validate_schema(v, s, f"{path}.{k}")
            if k not in props and not hit and schema.get("additionalProperties") is False:
                errs.append(f"{path}: 知らない欄 '{k}'")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: 要素が {schema['minItems']} 個未満")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: 要素が {schema['maxItems']} 個を超えている")
        if "items" in schema:
            for i, v in enumerate(value):
                errs += validate_schema(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {schema['minimum']} 未満")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {schema['maximum']} 超")
    if isinstance(value, str):
        if "minLength" in schema and len(value.strip()) < schema["minLength"]:
            errs.append(f"{path}: 空か短すぎる")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: {schema['maxLength']} 字を超えている")
        if "pattern" in schema and not end_anchored(schema["pattern"]).search(value):
            errs.append(f"{path}: 形が合わない（{schema['pattern']}）")
    return errs


def expand_refs(graph):
    """graph の schema の中の `"$ref"` を展開した写しを返す（JSON Schema の $defs / $ref と同じ形）。引けるのは
    `#/$defs/<名前>`（graph の最上位の $defs）と `engine#/<名前>`（engine が持つ定義。engine/util.py の ENGINE_DEFS）だけ。
    節の pointers（番号で指す欄。engine/pointers.py）の型の広げもここで行う。
    **展開は graph を読む入口（盤面・init・graphcheck）で 1 度だけ行い、型検査は展開後の形だけを見る**。
    引けない $ref は ValueError（黙って空の schema にすると、その欄の型検査が消える）"""
    from .util import ENGINE_DEFS
    local = graph.get("$defs") or {}

    def walk(x, seen):
        if isinstance(x, list):
            return [walk(v, seen) for v in x]
        if not isinstance(x, dict):
            return x
        ref = x.get("$ref")
        if ref is not None:
            if set(x) - {"$ref", "note", "description"}:
                raise ValueError(f"$ref {ref!r} に他の語が並んでいる（展開した定義を上書きしない。足すなら定義の側に）")
            src, _, name = ref.partition("#/")
            if src == "" and name.startswith("$defs/"):
                table, key = local, name[len("$defs/"):]
            elif src == "engine":
                table, key = ENGINE_DEFS, name   # engine#/$defs/<名前> は鍵に $defs/ が残るので引けない（名乗りどおり engine#/<名前> だけ）
            else:
                table, key = {}, None
            if key not in table:
                raise ValueError(f"$ref {ref!r} が引けない（引けるのは #/$defs/<名前> と engine#/<名前>）")
            if (src, key) in seen:
                raise ValueError(f"$ref {ref!r} が自分を引いている")
            return walk(copy.deepcopy(table[key]), seen | {(src, key)})
        return {k: walk(v, seen) for k, v in x.items()}
    out = {k: v for k, v in graph.items() if k != "$defs"}
    out["nodes"] = walk(graph.get("nodes", {}), frozenset())
    # 番号で指す欄（pointers）の型も同じ入口で広げる——graph に型を手で書かせず、宣言の誤りはここで ValueError
    from .pointers import widen
    widen(out["nodes"])
    return out


def merge_patch(target, patch):
    """RFC 7396（JSON Merge Patch）で target に patch を重ねた写し: object は鍵ごとに重ね、null は鍵を消し、それ以外（配列も）は置き換える"""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge_patch(out.get(k), v)
    return out


def extends_path(path, g):
    """差し替えの版（最上位に "extends": "<元の graph のファイル名>"）なら元の graph のパス、でなければ None。
    **元は同じ置き場のファイルだけ**——継いだ節の prompt_file・rules の相対パスは、差し替えの版の置き場を基準に読まれる"""
    ref = g.get("extends")
    if ref is None:
        return None
    if not isinstance(ref, str) or not ref or pathlib.PurePath(ref).name != ref:
        raise ValueError(f"extends {ref!r} は同じ置き場の graph のファイル名だけ（継いだ節の相対パスが別の置き場を指さないため）")
    base = pathlib.Path(path).parent / ref
    if base.resolve() == pathlib.Path(path).resolve():
        raise ValueError(f"extends {ref!r} が自分を指している")
    if not base.is_file():
        raise ValueError(f"extends {ref!r} が無い（{base}）")
    return base


def resolve_extends(path, read):
    """graph の差し替えの版を元の graph に重ねた姿（extends の無い graph はそのまま）。重ねは 1 段だけ。
    配列は置き換えなので、足すなら元の要素も書く（落としていないかは graphcheck が見る）"""
    g = read(path)
    base = extends_path(path, g)
    if base is None:
        return g
    b = read(base)
    if "extends" in b:
        raise ValueError(f"extends の先 {base.name} がまた extends を持つ——重ねは 1 段だけ")
    return merge_patch(b, {k: v for k, v in g.items() if k != "extends"})


def graph_text(path):
    """graph の本文（差し替えの版なら元の graph の本文も続ける）——init の後に graph が変わったかを sha で見るため"""
    from .util import read_json
    text = pathlib.Path(path).read_text(encoding="utf-8")
    try:
        base = extends_path(path, read_json(path))
    except ValueError:
        return text
    return text if base is None else text + "\n" + base.read_text(encoding="utf-8")


def load_graph(path):
    """graph を読んで（差し替えの版なら元の graph に重ねて）$ref を展開する ——（graph, ""）か（None, 理由）。graph を読む入口（盤面・init・graphcheck）はこの 1 本を通し、
    理由をどう伝えるか（die か NG の印字か）だけを呼び元が決める"""
    from .util import read_json
    try:
        return expand_refs(resolve_extends(path, read_json)), ""
    except ValueError as e:
        return None, f"{path}: {e}"


def walk_schema(schema, path="$"):
    """schema の中の schema を全部（(どこ, schema) の列）。properties・patternProperties・items を辿る——走査を 1 本にして、
    語の検査と正規表現の検査が別々に木を辿らない"""
    if not isinstance(schema, dict):
        return
    yield path, schema
    for k, v in (schema.get("properties") or {}).items():
        yield from walk_schema(v, f"{path}.{k}")
    for k, v in (schema.get("patternProperties") or {}).items():
        yield from walk_schema(v, f"{path}[/{k}/]")
    if isinstance(schema.get("items"), dict):
        yield from walk_schema(schema["items"], f"{path}[]")


# engine が読む語の全部。これ以外（oneOf / not / format / uniqueItems、綴り違い）は validate_schema が黙って無視するので、
# graph に書いても効かない。graphcheck がこの集合で節の schema を走査して落とす（注記で守るのをやめ、仕組みで守る）。
# note / description は説明のための欄で、検査には使わないが書いてよい。
KNOWN_KEYWORDS = frozenset({"type", "enum", "const", "required", "properties", "patternProperties", "additionalProperties", "items",
                            "minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength", "pattern", "note", "description"})


# 節の鍵のうち engine（と graphcheck の実行の形の検査）が読む物と、人が読むための説明の鍵。ループ固有の鍵は rules が NODE_KEYS
# （rules が読む）と NODE_NOTE_KEYS（説明）で宣言する——engine はループ固有の語を持たない。この 4 つの和に無い節の鍵は、綴り違いか
# 誰も読まなくなった鍵で、書いても黙って効かないので graphcheck が落とす（KNOWN_KEYWORDS と同じ閉じた集合。JSON Schema の
# additionalProperties: false と同じ形）。ENGINE_NODE_KEYS の各鍵を engine か graphcheck が読んでいることは pytest が見る
ENGINE_NODE_KEYS = frozenset({
    "active_in", "agent_type", "applies_cond", "builtin", "cond", "delegate", "deps", "engine_run", "fan_out", "forbidden_inputs",
    "fresh_context", "instance_deps", "once", "optional", "outputs", "pointers", "post_check", "pre", "prompt_append", "prompt_file",
    "reads", "run_by", "runner_judgment_by_design", "same_context_as", "save_text_as", "schema", "skills", "text", "thickness_from",
    "thickness_reason_from", "verdict_is_copy", "writes"})
DOC_NODE_KEYS = frozenset({"note", "does", "source", "stage"})


def unknown_keywords(schema, path="$"):
    """schema の中で engine が読まない語を列挙する（空なら全部効く語）。"""
    return [f"{p}: '{k}'" for p, s in walk_schema(schema, path) for k in s if k not in KNOWN_KEYWORDS]


def _is_type(v, t):
    return {
        "object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
        "boolean": isinstance(v, bool), "integer": isinstance(v, int) and not isinstance(v, bool),
        "number": isinstance(v, (int, float)) and not isinstance(v, bool), "null": v is None,
    }.get(t, False)
