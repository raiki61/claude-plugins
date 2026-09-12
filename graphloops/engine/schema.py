"""返答の型検査。**JSON Schema そのものではなく engine 固有の型検査**（語を借りているだけ）。

pip 依存を持たない配布方針（issue #6）で jsonschema を使わない。見る語は type / enum / const /
required / properties / additionalProperties / items / minItems / maxItems / minimum / maximum /
minLength / pattern だけで、これ以外は無視する。本家と意味が違う点を明記する:
  - enum / const は値だけでなく真偽値かどうかも見る（True を [0, 1] に一致させない）
  - minLength は**前後の空白を除いた長さ**（空白だけの返答を「在る」と数えないため）
この schema は役に貼るプロンプトにも「返答の形」として載るので、意味の差はここに書いて 1 か所にする。
エラーの一覧を返す（空なら合格）。
"""
import re


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
        for k, v in value.items():
            if k in props:
                errs += validate_schema(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
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
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: 形が合わない（{schema['pattern']}）")
    return errs


def _is_type(v, t):
    return {
        "object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
        "boolean": isinstance(v, bool), "integer": isinstance(v, int) and not isinstance(v, bool),
        "number": isinstance(v, (int, float)) and not isinstance(v, bool), "null": v is None,
    }.get(t, False)
