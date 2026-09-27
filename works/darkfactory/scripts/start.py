# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの入口の節 start（線 A の仕様 4 節。計画 Task 7）。中身は entry.start（.shared/core/entry.py）。

読む環境変数（Archon が節の with: から渡す。どれも在ること。値の空は既定の意味）:
- INPUTS_REQUEST（依頼のファイル。相対なら cwd＝対象の根から）・INPUTS_TEST_CMD・INPUTS_THICKNESS・INPUTS_GATES・
  INPUTS_MID_GATE・INPUTS_ADAPTER・INPUTS_POLICY_MD
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）・WORKFLOW_ID（切符の run_id。空も欠け）
出口:
- 通れば entry.start の結果を 1 行の JSON で出して 0
- 入力を受けない（entry.InputRefused。CI・並行 PR の engine の拒みも含む）: 標準エラーに理由を 1 行出して 1
  （AI を起こす前に run を止める。1 本目の intake と同じ）。標準出力には何も出さない
- 環境変数が欠けた・盤面の誤り（BoardGap・Reject）: 標準エラーに 1 行出して 2
- 止められた（tree_run.Stopped。テストのコマンドは木ごと止めた）: 128+信号
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402

import script_io  # noqa: E402

# 裁定 TA16: 読む INPUTS_* の組と raw の鍵（Task 17 の試験が YAML の with: の鍵と突き合わせる）
INPUTS = {"INPUTS_REQUEST": "request", "INPUTS_TEST_CMD": "test_cmd", "INPUTS_THICKNESS": "thickness",
          "INPUTS_GATES": "gates", "INPUTS_MID_GATE": "mid_gate", "INPUTS_ADAPTER": "adapter",
          "INPUTS_POLICY_MD": "policy_md"}
RUN_ID_ENV = "WORKFLOW_ID"
NON_EMPTY = (script_io.ARTIFACTS_ENV, RUN_ID_ENV)


def _line(text) -> str:
    return " ".join(str(text).split())


def main() -> int:
    missing = [n for n in (*INPUTS, *NON_EMPTY) if n not in os.environ]
    missing += [n for n in NON_EMPTY if n in os.environ and not os.environ[n]]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    import entry
    import tree_run
    from board import BoardGap
    from engine.util import Reject
    raw = {key: os.environ[name] for name, key in INPUTS.items()}
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = entry.start(board, Path.cwd(), raw, run_id=os.environ[RUN_ID_ENV])
    except entry.InputRefused as e:
        print(f"run を始めない: {_line(e)}", file=sys.stderr)
        return 1
    except (BoardGap, Reject) as e:
        print(f"盤面の誤り: {_line(e)}", file=sys.stderr)
        return 2
    except tree_run.Stopped as e:
        print(f"止められた（信号 {e.signum}）。テストのコマンドは木ごと止めた", file=sys.stderr)
        return 128 + e.signum
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
