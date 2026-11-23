"""JSON Schema の小さな照合し。type・required・properties・additionalProperties（schema の形の物だけ）・items・enum だけを解く。

外のパッケージ（jsonschema）を入れないための、試験の中だけのツール。schema の側でこの 6 つ以外の鍵を使うなら、ここも足す。
"""

import json
import pathlib

TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}


def _is(v, t):
    if isinstance(t, list):
        return any(_is(v, x) for x in t)
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    return isinstance(v, TYPES[t])


def check(obj, schema, where="$"):
    errs = []
    t = schema.get("type")
    if t is not None and not _is(obj, t):
        return [f"{where}: 型が {t} で無い（{type(obj).__name__}）"]
    if "enum" in schema and obj not in schema["enum"]:
        errs.append(f"{where}: {obj!r} は {schema['enum']} のどれでも無い")
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{where}: {k} が無い")
        for k, sub in schema.get("properties", {}).items():
            if k in obj:
                errs += check(obj[k], sub, f"{where}.{k}")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):   # 鍵が名前などで決まっていない表（名 → 値）の値の形
            for k, v in obj.items():
                if k not in schema.get("properties", {}):
                    errs += check(v, extra, f"{where}.{k}")
    if isinstance(obj, list) and "items" in schema:
        for i, v in enumerate(obj):
            errs += check(v, schema["items"], f"{where}[{i}]")
    return errs


def schema(name):
    """works-dispatch/dispatch/schemas/<name>.schema.json を読む。"""
    p = pathlib.Path(__file__).resolve().parent.parent / "schemas" / f"{name}.schema.json"
    return json.loads(p.read_text(encoding="utf-8"))
