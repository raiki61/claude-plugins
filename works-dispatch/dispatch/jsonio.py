"""ノードの入出力の JSON。出力の頭には版のフィールド `schema: 1` を置き、読む側は知らない版を読んだら止まる（設計書のセクション 4）。"""

import json
import sys

SCHEMA_VERSION = 1


class SchemaVersionError(Exception):
    """知らない版の JSON を読んだ。"""


def dump(obj, out):
    """obj を JSON で書く。out が None なら標準出力。schema が無ければ 1 を足す。"""
    body = {"schema": SCHEMA_VERSION, **obj} if "schema" not in obj else obj
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    if out is None:
        sys.stdout.write(text)
        return
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)


def load(path):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA_VERSION:
        got = obj.get("schema") if isinstance(obj, dict) else type(obj).__name__
        raise SchemaVersionError(f"{path}: schema が {SCHEMA_VERSION} で無い（{got}）")
    return obj
