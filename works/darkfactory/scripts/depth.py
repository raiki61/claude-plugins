# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""深さの節 h-depth（at decide）と h-redepth（at raise）。中身は darkfactory/lib/depth.py の node（計画 docs/plans/2026-10-06-variable-depth.md）。

読む環境変数（Archon が節の with: から渡す。どれも在ること）:
- INPUTS_AT: decide（修正の前。単位ごとの深さを決めて盤面の根の depth.json に書く）か raise（修正の後。信号で標準へ上げる）
- INPUTS_OPEN_UNITS: 直す義務の単位の key の JSON の配列（h-fix の出口。raise では読まない）
- INPUTS_TDD_SUITE: 線の入力 tdd_suite（機械の確かめの有無に数える。raise では読まない）
- INPUTS_REPLANNED・INPUTS_REJUDGED: 同じ run の案の直し・判定への異議の再審が走ったか（字の true。decide では読まない）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）
出口: depth.NODE_FIELDS の 1 行の JSON で 0（盤面が読めない時も標準へ倒して 0）。環境変数が欠けた・at が語の外は標準エラーに 1 行で 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402

import script_io  # noqa: E402

INPUTS = ("INPUTS_AT", "INPUTS_OPEN_UNITS", "INPUTS_TDD_SUITE", "INPUTS_REPLANNED", "INPUTS_REJUDGED")


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
    import depth
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = depth.node(board, os.environ["INPUTS_AT"].strip(), open_units=os.environ["INPUTS_OPEN_UNITS"],
                         tdd_suite=os.environ["INPUTS_TDD_SUITE"],
                         replanned=os.environ["INPUTS_REPLANNED"].strip() == "true",
                         rejudged=os.environ["INPUTS_REJUDGED"].strip() == "true")
    except ValueError as e:
        print(f"depth: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
