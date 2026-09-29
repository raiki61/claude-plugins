# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造の境の節 h-structure（中身は line_edge.structure_edge）。構造のブロックの出口を受け、盤面の根に控え（core の structmark）を
書く。planning がこの節を待ち、修正案の指示書の頭がその控えから構造の目の行か「構造の目の行なしで計画した（理由）」を貼る。

読む環境変数（Archon が節の with: から渡す）:
- INPUTS_STRUCTURED: 構造のブロックの出口の JSON（`{from: …, if_skipped: null}`。飛ばされた・落ちた節は文字列 null か空）
- INPUTS_PLAN_GO: h-plan の go（字の false なら計画を起こさない周で、控えを書かずに status skipped）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）
出口:
- {ok, status: ok|failed|skipped, reason, design_file, wall_s} を 1 行の JSON で出して 0。構造のブロックの落ちも、自分の読み書きの失敗も
  status failed と理由で返す（節を落とさない。落ちた節は h-gate を飛ばし、計画なしで修正へ進ませない）
- 環境変数が欠けた・INPUTS_STRUCTURED が JSON でない（配線の誤り）: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

INPUTS = ("INPUTS_STRUCTURED", "INPUTS_PLAN_GO")
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
    raw = os.environ["INPUTS_STRUCTURED"].strip()
    try:
        structured = None if raw in ("", NULL) else json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INPUTS_STRUCTURED が JSON として読めない（{' '.join(str(e).split())}）: {raw[:200]!r}", file=sys.stderr)
        return 2
    import line_edge
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    script_io._emit(line_edge.structure_edge(board, structured, os.environ["INPUTS_PLAN_GO"].strip() != "false"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
