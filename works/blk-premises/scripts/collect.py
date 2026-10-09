# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""前提の実測のブロックの出口を組む（中身は premises.collect）。輪（premises-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた
premises.json を読み、{ok, premises_file, constraints_file, constraints_summary, constraints, measured, hypotheses, claims,
claims_hypothesis, reads_file} を 1 行出して 0。

- constraints_summary: 判定役に貼る要約。1 行 1 制約で「- [実測|仮説] <text>（測り方: <measured_how>）」。
  実行したコマンドと出力（measured_output）は載せない（全文は constraints_file）。制約 0 件なら決まった 1 文
- premises.json が無い（前の呼び出しの残りは intake が消すので、在ればこの呼び出しの受け付けが書いた物）:
  - ラインの盤面で、受け付けが 3 回とも拒んで輪を抜けた（rolekit.given_up_reason）: 最後の拒否の文で盤面を止め（by premises.STOP_BY）、
    ok: false と空の欄を出して 0（線が止まった盤面を見て判定役を起こさない。R50）
  - ラインの盤面がもう止まっている（intake が go: false で輪を飛ばした）: ok: false と空の欄を出して 0
  - それ以外（単独の run・配線の誤り）: 標準エラーに理由（諦めたなら最後の拒否の文）を 1 行出して 1
- premises.json が読めない・形が崩れている: 標準エラーに理由を 1 行出して 1
- ARTIFACTS_DIR が欠けた（空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

import premises  # noqa: E402
import rolekit  # noqa: E402

ARTIFACTS_ENV = "ARTIFACTS_DIR"
INPUTS = ()   # 裁定 TA16: 読む INPUTS_* の組（無い）
EMPTY = {"ok": False, "premises_file": "", "constraints_file": "", "constraints_summary": "", "constraints": 0, "measured": 0,
         "hypotheses": 0, "claims": 0, "claims_hypothesis": 0, "reads_file": ""}


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    board = Path(os.environ[ARTIFACTS_ENV]) / "board"
    try:
        out = premises.collect(board)
    except premises.Broken as e:
        missing = not (board / premises.PREMISES_FILE).exists()
        why = rolekit.given_up_reason(board, premises.PREMISES_NODE) if missing else ""
        if missing and rolekit.on_line(board) and (why or rolekit.line_stopped(board)):
            if why:
                rolekit.stop_line(board, why, by=premises.STOP_BY)
            out = EMPTY
        else:
            print(" ".join((f"{why}——{e}" if why else str(e)).split()), file=sys.stderr)
            return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
