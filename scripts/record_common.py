#!/usr/bin/env python3
"""検証器 4 本（<loop>-record.py）が共有する土台——契約の 3 値を守る口と、記録を読む口。

**なぜ共有できるか。** 検証器は graphloops の find_validator が
`scripts/<loop>-record.py` としてプラグインの中から解決する（`<PLUGIN>_ROOT` → 同じリポジトリ →
インストール済みキャッシュ）。どの経路でも `scripts/` ごと在るので、隣を import できる。
以前は「1 本ずつ配る前提で共有モジュールを持たない」として写していたが、**写しは黙って割れた**
（実測 2026-09-14: `fail` が `_rows` より後ろに在る本が 1 つあり、契約の 3 値のうち exit 2 が潰れて
未処理例外の exit 1 になっていた）。順序の不変条件はここに 1 回だけ在ればよい。

**代償**（承知の上で受ける）: `--validator /どこか/自作.py` で外のファイルを指すときは、この本文も
隣に置くことになる。単体で持ち出せる性質が 1 つ減る。

契約の 3 値: 0 = 収束 / 1 = 阻害要因あり / 2 = 記録が不正。**`fail` はこのファイルの先頭に置く**
——`_rows` と `_tables` はインポート時に呼ばれるので、`fail` が後ろに在ると属性の書き忘れが
NameError（未処理例外の exit 1）になり、「記録が不正」と「阻害要因あり」の区別が付かなくなる。
"""
import json
import sys

def fail(msg):
    print(f"記録が不正: {msg}", file=sys.stderr)
    sys.exit(2)

def load(path):
    """記録を読む。**読めないことは記録の不正（2）で、発行阻害（1）ではない。**"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"{path}: 開けない（{e.strerror}）")
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON として読めない（{e}）")
    except UnicodeDecodeError as e:
        fail(f"{path}: UTF-8 として読めない（{e}）")

def _rows(what, cls, rows):
    """状態の表を組む。**属性の書き忘れをここで落とす。** 素の namedtuple で組むと、書き忘れは TypeError に
    なるが**末尾の例外境界より前（インポート時）**なので未処理例外の exit 1 になり、「阻害要因あり」と
    区別が付かない——契約の 3 値が 1 つ潰れる。

    4 本の検証器が同じ物を呼ぶ（以前は本ごとの写しで、順序が割れて実際に潰れた）。
    """
    out = {}
    for name, args in rows.items():
        try:
            out[name] = cls(*args)
        except TypeError as e:
            fail(f"{what} の '{name}' の行が不完全（属性の書き忘れ）: {e}")
    return out

def _tables(what, build):
    """プロンプトに貼る表を組む。**組み立ての失敗をここで落とす。**

    module 直下で素に組むと、`v.fields[0]` の IndexError や `ORIGIN_NOTE[…]` の KeyError が
    **末尾の例外境界より前（インポート時）**に起き、未処理例外の exit 1 になる——契約の 3 値
    （0 収束・1 阻害要因あり・2 記録が不正）のうち exit 2 が潰れ、「記録が不正」と「阻害要因あり」の
    区別が付かない。`_rows` が表の行について既にやっていることを、表の**組み立て**にも当てる。
    """
    try:
        return build()
    except (IndexError, KeyError, TypeError) as e:
        fail(f"{what} の組み立てに失敗（正本の表と写しが割れている）: {e!r}")

def require_str(rec, key, where):
    v = rec.get(key)
    if not isinstance(v, str) or not v.strip():
        fail(f"{where}: '{key}' が空か文字列でない")
    return v

def require_int(rec, key, where, minimum=0):
    v = rec.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        fail(f"{where}: '{key}' が {minimum} 以上の整数でない")
    return v

def not_applicable(v):
    """「該当なし」の共通形。理由なしの該当なしは認めない。"""
    return (
        isinstance(v, dict)
        and v.get("status") == "not_applicable"
        and isinstance(v.get("reason"), str)
        and v["reason"].strip()
    )
