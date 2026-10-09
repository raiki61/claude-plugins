# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""世界の解の境の節 h-world（中身は line_edge.world_edge。計画 docs/plans/2026-10-09-world-solution.md の W7）。世界の解のブロックの
出口を受け、盤面の根に控え（core の worldmark）を書く。判定がこの節を待ち、判定の支度・修正案の頭・関所はその控えから行を読む。

読む環境変数（Archon が節の with: から渡す）:
- INPUTS_WORLDED: 世界の解のブロックの出口の JSON（`{from: …, if_skipped: null}`。飛ばされた・落ちた節は文字列 null か空）
- INPUTS_WORLD_GO: h-mat の world_go（字の false なら段を回さない周で、控えを書かずに status skipped）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）
出口:
- {ok, status: ok|failed|skipped, reason, world_file} を 1 行の JSON で出して 0。段の落ちも、自分の読み書きの失敗も status failed と
  理由で返す（節を落とさない。判定は行なしで進む）
- 環境変数が欠けた・INPUTS_WORLDED が JSON でない（配線の誤り）: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

INPUTS = ("INPUTS_WORLDED", "INPUTS_WORLD_GO")
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
    raw = os.environ["INPUTS_WORLDED"].strip()
    try:
        worlded = None if raw in ("", NULL) else json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INPUTS_WORLDED が JSON として読めない（{' '.join(str(e).split())}）: {raw[:200]!r}", file=sys.stderr)
        return 2
    import line_edge
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    script_io._emit(line_edge.world_edge(board, worlded, os.environ["INPUTS_WORLD_GO"].strip() != "false"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
