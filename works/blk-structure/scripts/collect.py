# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造のブロックの出口を組む。段 A が書いた structure.json（INPUTS_STRUCTURE_FILE）と design.jsonl（INPUTS_DESIGN_FILE）を
確かめ、{ok, structure_file, design_file, status, wall_s} を 1 行出して 0。後段が読んでよいのはこの 2 本のファイルだけ。

- ok は実測が落ちても true（status: failed と structure.json の reason で分かる。線を止めない）
- wall_s は段 A の壁時計の秒（structure.json の timing）
- 2 本のどちらかが無い・structure.json が読めない（配線の誤り）: 標準エラーに理由を 1 行出して 1
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

STRUCTURE_ENV = "INPUTS_STRUCTURE_FILE"
DESIGN_ENV = "INPUTS_DESIGN_FILE"
INPUTS = (STRUCTURE_ENV, DESIGN_ENV)   # 裁定 TA16: 読む INPUTS_* の組


def main() -> int:
    structure, design = Path(os.environ.get(STRUCTURE_ENV, "")), Path(os.environ.get(DESIGN_ENV, ""))
    try:
        doc = json.loads(structure.read_text(encoding="utf-8"))
        if not design.is_file():
            raise OSError(f"設計の行のファイルが無い: {design}")
        status, wall = doc["status"], doc["timing"]["wall_s"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"collect.py: 出力の 2 本が揃わない: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": True, "structure_file": str(structure), "design_file": str(design), "status": status,
                      "wall_s": wall}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
