# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""直しの後の構造の境の節（中身は line_edge.after_edge。計画 2026-10-09-clean-whole の Task 2.5）。直しの後に 2 度目に差し込んだ
構造のブロックの出口を受け、修正案の外れの訳を足して盤面の根に控え（core の structmark の structure-after.json）を書く。報告・
最後の関所・独立の目の頭・結末の残りの数えがその控えを読む。

読む環境変数（Archon が節の with: から渡す）:
- INPUTS_MEASURED: 直しの後の構造のブロックの出口の JSON（`{from: …, if_skipped: null}`。飛ばされた・落ちた節は文字列 null か空）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）
出口:
- {ok, status: ok|failed, reason} を 1 行の JSON で出して 0。ブロックの落ちも自分の読み書きの失敗も status failed と理由で返す
  （節を落とさない。線を止めない）
- 環境変数が欠けた・INPUTS_MEASURED が JSON でない（配線の誤り）: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

INPUTS = ("INPUTS_MEASURED",)
NULL = "null"


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    missing = [n for n in INPUTS if n not in os.environ]
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        missing.append(script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    raw = os.environ["INPUTS_MEASURED"].strip()
    try:
        measured = None if raw in ("", NULL) else json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INPUTS_MEASURED が JSON として読めない（{' '.join(str(e).split())}）: {raw[:200]!r}", file=sys.stderr)
        return 2
    import line_edge
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    script_io._emit(line_edge.after_edge(board, measured))
    return 0


if __name__ == "__main__":
    sys.exit(main())
