"""JSON のファイルを、読む側が書きかけを見ないように書く口。層 L1（works の物を何も知らない）。

- write_json(path, doc) -> None: 隣の <名>.tmp に、UTF-8・字のまま（ensure_ascii=False）・2 字下げ・末尾の改行で書いてから、
  os.replace で差し替える。盤面の控えや報告のように、別の節やスクリプトがすぐ読むファイルに使う
"""
from __future__ import annotations

import json
import os
import pathlib


def write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
