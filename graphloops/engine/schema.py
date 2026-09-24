"""返答の型検査。**JSON Schema そのものではなく engine 固有の型検査**（語を借りているだけ）。

pip 依存を持たない配布方針（issue #6）で jsonschema を使わない。見る語は type / enum / const /
required / properties / patternProperties / additionalProperties / items / minItems / maxItems / minimum / maximum /
minLength / maxLength / pattern だけで、これ以外は無視する。本家と意味が違う点を明記する:
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
import re


@functools.lru_cache(maxsize=None)
def end_anchored(pat):
    """pattern の `$`（エスケープの後と文字クラスの中を除く）を `\\Z` に読み替えた、コンパイル済みの正規表現。
    Python の `$` は末尾の改行の手前でも一致するので、`^[^\\n]+$` が改行 1 つで終わる値を通し、その値が git grep の -e で
    空の検索語に割れて全行に一致した（実測 2026-09-24: run_count が 2910 を返し、改行が無ければ 0）。ECMA-262 の `$` は入力の末尾だけ。
    検査（validate_schema）と graph の検査（graphcheck）は、同じこの関数を通した物を使う"""
    out, esc, cls = [], False, False
    for i, ch in enumerate(pat):
        if esc:
            out.append(ch)
            esc = False
        elif ch == "\\":
            out.append(ch)
            esc = True
        elif cls:
            out.append(ch)
            cls = not (ch == "]" and pat[i - 1] != "[")   # [] の直後の ] は文字クラスの中の字
        elif ch == "[":
            out.append(ch)
            cls = True
        else:
            out.append("\\Z" if ch == "$" else ch)
    return re.compile("".join(out))


def _same(a, b):
    """== に真偽値の型も足す（True == 1 を一致にしない）。"""
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def validate_schema(value, schema, path="$"):
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
            table = {"": local, "engine": ENGINE_DEFS}.get(src)
            if table is None or not name.startswith("$defs/") and src == "" or name.replace("$defs/", "", 1) not in (table or {}):
                raise ValueError(f"$ref {ref!r} が引けない（引けるのは #/$defs/<名前> と engine#/<名前>）")
            key = name.replace("$defs/", "", 1)
            if (src, key) in seen:
                raise ValueError(f"$ref {ref!r} が自分を引いている")
            return walk(copy.deepcopy(table[key]), seen | {(src, key)})
        return {k: walk(v, seen) for k, v in x.items()}
    out = {k: v for k, v in graph.items() if k != "$defs"}
    out["nodes"] = walk(graph.get("nodes", {}), frozenset())
    return out


def load_graph(path):
    """graph を読んで $ref を展開する ——（graph, ""）か（None, 理由）。graph を読む入口（盤面・init・graphcheck）はこの 1 本を通し、
    理由をどう伝えるか（die か NG の印字か）だけを呼び元が決める"""
    from .util import read_json
    try:
        return expand_refs(read_json(path)), ""
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


def unknown_keywords(schema, path="$"):
    """schema の中で engine が読まない語を列挙する（空なら全部効く語）。"""
    return [f"{p}: '{k}'" for p, s in walk_schema(schema, path) for k in s if k not in KNOWN_KEYWORDS]


def _is_type(v, t):
    return {
        "object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
        "boolean": isinstance(v, bool), "integer": isinstance(v, int) and not isinstance(v, bool),
        "number": isinstance(v, (int, float)) and not isinstance(v, bool), "null": v is None,
    }.get(t, False)
