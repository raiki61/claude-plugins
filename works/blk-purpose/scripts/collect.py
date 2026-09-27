# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目的の文のブロックの出口を組む。輪（purpose-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた purpose.json を読み、
{"ok", "purpose_file", "purpose_text", "source"} を 1 行出して 0。判定役は purpose_file（目的の返答の全部）を読む。

- source が「目的不明」でも ok: true（目的の出典が無いことを決めたのであって、ブロックの失敗ではない）
- purpose.json が無い・読めない・写しの型に合わない: 標準エラーに理由を 1 行出して 1（受け付けを通らずに輪を抜けたことになる）
- ARTIFACTS_DIR が欠けた（空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from purpose import read_purpose  # noqa: E402
from engine.util import Reject  # noqa: E402  purpose の後（purpose を読むと写しの graphloops が sys.path に入る）

ARTIFACTS_ENV = "ARTIFACTS_DIR"


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    try:
        path, obj = read_purpose(Path(os.environ[ARTIFACTS_ENV]) / "board")
    except Reject as e:
        print(" ".join(str(e).split()), file=sys.stderr)
        return 1
    out = {"ok": True, "purpose_file": str(path), "purpose_text": obj["purpose_text"], "source": obj["source"]}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
