# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""輪の後ろで出口を組む節。受け付けた審査の返答（盤面の delta-review.json）から
{"ok": true, "faces": <穴の数>, "review_file": <delta-review.json のパス>, "diff_file": <fix.diff のパス>} を 1 行。
review_file と diff_file は run の後に人が見る物（審査の返答と、審査した修正の差分。差分は節 cut が切った物）。
輪は受け付けが通ったときだけ抜けるので、返答が盤面に無い・読めないのは壊れた run——標準エラーに理由を出して 1。
ARTIFACTS_DIR が欠けたときは 2。"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402
from accept import DELTA_REVIEW_FILE, DIFF_FILE  # noqa: E402


def main() -> int:
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        print(f"環境変数が無い: {script_io.ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    p = board / DELTA_REVIEW_FILE
    try:
        faces = json.loads(p.read_text(encoding="utf-8"))["faces"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"受け付けた審査の返答 {p} が読めない（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    script_io._emit({"ok": True, "faces": len(faces), "review_file": str(p), "diff_file": str(board / DIFF_FILE)})
    return 0


sys.exit(main())
