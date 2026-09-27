# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目的の文のブロックの出口を組む。輪（purpose-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた purpose.json を読み、
{"ok", "purpose_file", "purpose_text", "source"} を 1 行出して 0。判定役は purpose_file（目的の返答の全部）を読む。

- source が「目的不明」でも ok: true（目的の出典が無いことを決めたのであって、ブロックの失敗ではない）
- purpose.json が無く、ラインの盤面で受け付けが 3 回とも拒んで輪を抜けた（rolekit.given_up_reason）: 最後の拒否の文で盤面を
  止め（by purpose.STOP_BY）、ok: false と空の欄を出して 0（境の節 h-mat が止まった盤面を見て後ろの役を起こさない。R50）
- それ以外で purpose.json が無い・読めない・写しの型に合わない: 標準エラーに理由（諦めたなら最後の拒否の文）を 1 行出して 1
- ARTIFACTS_DIR が欠けた（空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from purpose import NODE, PURPOSE_FILE, STOP_BY, read_purpose  # noqa: E402
from engine.util import Reject  # noqa: E402  purpose の後（purpose を読むと写しの graphloops が sys.path に入る）
import rolekit  # noqa: E402

ARTIFACTS_ENV = "ARTIFACTS_DIR"


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    board = Path(os.environ[ARTIFACTS_ENV]) / "board"
    try:
        path, obj = read_purpose(board)
    except Reject as e:
        why = "" if (board / PURPOSE_FILE).exists() else rolekit.given_up_reason(board, NODE)
        if not (why and rolekit.on_line(board)):
            print(" ".join((f"{why}——{e}" if why else str(e)).split()), file=sys.stderr)
            return 1
        rolekit.stop_line(board, why, by=STOP_BY)
        out = {"ok": False, "purpose_file": "", "purpose_text": "", "source": ""}
    else:
        out = {"ok": True, "purpose_file": str(path), "purpose_text": obj["purpose_text"], "source": obj["source"]}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
