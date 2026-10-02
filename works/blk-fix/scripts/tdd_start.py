# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の頭（blk-fix の節 tdd-start。中身は tddloop.start）。

読む環境変数: INPUTS_TDD_SUITE（テストの実行器。空は「無い run」）・INPUTS_OPEN_UNITS（直す義務の単位の key の JSON の配列）・
INPUTS_TEST_CMD（run のテストのコマンド。線の入力 test_cmd。空は走らせない）・ARTIFACTS_DIR（実行器が在る時だけ使う。盤面は
その下の board/）。
- 実行器が無い: 何も書かずに {"go": false, "reason", "suite": "", "state_file": "", "summary_file": ""} を 1 行出して 0
  （輪は飛ばされ、修正役が全部の単位を今どおり直す）
- 実行器が無い・走らない・元の結末が取れない: go: false と理由を 1 行出して 0（同じく今どおり）
- 在る: 一式を 1 回走らせて元の結末を取り、盤面の tdd-<k>/state.json を書いて go: true。test_cmd が在れば、実行器が
  そのコマンドを包んだ物でない限り 1 回走らせ、緑の後に毎回確かめる関門を開く（元から赤・走らないなら関門を切り、理由を状態に残す）
- 環境変数が欠けた・open_units が読めない・盤面が在るのに直す義務から外れた単位（答え待ち・ask_human）が読めない・
  盤面のパスが $ を含む・git が効かない: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402
import tddloop  # noqa: E402
from leftovers import Unreadable  # noqa: E402

INPUTS = ("INPUTS_TDD_SUITE", "INPUTS_OPEN_UNITS", "INPUTS_TEST_CMD")


def main() -> int:
    missing = [n for n in INPUTS if n not in os.environ]
    if missing:
        print(f"tdd-start: 環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    suite = os.environ["INPUTS_TDD_SUITE"]
    board = script_io.board_dir() if suite.strip() else Path("-")   # 実行器が無い run は盤面を読まない
    if board is None:
        return 2
    try:
        out = tddloop.start(board, Path.cwd(), suite, os.environ["INPUTS_OPEN_UNITS"], test_cmd=os.environ["INPUTS_TEST_CMD"])
    except (tddloop.Broken, Unreadable, OSError) as e:
        print(f"tdd-start: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
