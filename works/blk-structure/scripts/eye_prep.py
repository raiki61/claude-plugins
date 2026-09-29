# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造の目の支度（lib/eye.prep）。structure.json（INPUTS_STRUCTURE_FILE）から指示書を描き、{prompt, prompt_file, attempt} を
1 行出して 0。前の回が拒まれていれば、その理由を指示書の頭に置く（同じ会話で出し直させる）。
structure.json が読めない（配線の誤り）: 標準エラーに理由を 1 行出して 1
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import eye  # noqa: E402

STRUCTURE_ENV = "INPUTS_STRUCTURE_FILE"
INPUTS = (STRUCTURE_ENV,)   # 裁定 TA16: 読む INPUTS_* の組


def main() -> int:
    try:
        out = eye.prep(os.environ.get(STRUCTURE_ENV, ""))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"eye_prep.py: structure.json が読めない: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
