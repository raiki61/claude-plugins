# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの出口（returns。計画 P1 Task 34）。中身は report.final_result（.shared/core/report.py）: 機械の報告の出口の欄を
全部残し、最後の報告のファイルを選ぶ（AI の報告が ok なら report-ai.md、そうでなければ機械の report.md）。結末は替えない。

読む環境変数（Archon が節の with: から JSON の文字列で渡す。どれも在ること）:
- INPUTS_MACHINE: 機械の報告の節 report の出口（必ず JSON のオブジェクト）
- INPUTS_AI:      AI の報告のブロック（blk-report）の collect の出口。文字列 null と空は「回らなかった」。回ったが失敗した節の
                  出口が JSON で読めなければ、機械の報告を選び、読めなかった事実を ai_report.reason に書く（黙らない）
出口:
- final_result の結果を 1 行の JSON で出して 0
- 環境変数が欠けた・INPUTS_MACHINE が読めない・形が違う: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

INPUTS = ("INPUTS_MACHINE", "INPUTS_AI")
NULL = "null"


def _line(text) -> str:
    return " ".join(str(text).split())


def main() -> int:
    missing = [n for n in INPUTS if n not in os.environ]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        machine = json.loads(os.environ["INPUTS_MACHINE"])
    except json.JSONDecodeError as e:
        print(f"result: INPUTS_MACHINE が JSON として読めない: {_line(e)}", file=sys.stderr)
        return 2
    raw = os.environ["INPUTS_AI"].strip()
    ai = None
    if raw not in ("", NULL):
        try:
            ai = json.loads(raw)
        except json.JSONDecodeError as e:
            ai = {"ok": False, "reason": f"AI の報告の出口が JSON として読めない（{_line(e)}。頭: {raw[:200]!r}）"}
        if not isinstance(ai, dict):
            ai = {"ok": False, "reason": f"AI の報告の出口が JSON のオブジェクトでない（{type(ai).__name__}）"}
    import report
    from board import BoardGap
    try:
        out = report.final_result(machine, ai)
    except BoardGap as e:
        print(f"result: {_line(e)}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
