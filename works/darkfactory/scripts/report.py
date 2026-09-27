# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの最後にいつも走る報告の節（P1 計画 Task 27・〔線A計〕T15。裁定 TA16）。中身は report.build（.shared/core/report.py）。
1 本目の finish の欄を保ったまま、機械が組む短い報告 report.md と、次の run に渡す依頼の下書き next-request.json を盤面に書く。

読む環境変数（Archon が節の with: から JSON の文字列で渡す。どれも在ること。文字列 null と空は None＝その節は走らなかった）:
- INPUTS_JUDGED: 判定のブロックの出口（{ok, open_units, need_fix, judgment_file, one_shot}）
- INPUTS_TESTS:  最後のテスト（blk-tests の final）の出口（{ok, green, log, …}）
- INPUTS_START:  start の出口（無ければ盤面の r1 の start の控え）
- INPUTS_MID:    境の節 h-mid の出口（{go, mid_note, …}。中の検査の枠の行）
- INPUTS_CI:     CI の任せ先の役のブロック（blk-ci）の collect の出口（{ok, reason, note, …}。包み無しの知らせ）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）・WORKFLOW_ID（Archon の出来事を読む run。空なら start の控えの run_id）
出口:
- report.build の結果を 1 行の JSON で出して 0（record_invalid・止めた run も 0。結末で知らせる）
- 盤面が開けない（BoardGap・写しの Reject）: 標準エラーに理由を 1 行出して 1。標準出力には何も出さない
- 環境変数が欠けた・JSON が読めない・オブジェクトでない・思わぬ誤り: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

# 裁定 TA16: 読む INPUTS_* の組（YAML の with: の鍵と突き合わせる）
INPUTS = ("INPUTS_JUDGED", "INPUTS_TESTS", "INPUTS_START", "INPUTS_MID", "INPUTS_CI")
NULL = "null"   # 飛ばされた節の出力（if_skipped: null）が届く字
RUN_ID_ENV = "WORKFLOW_ID"


class Broken(Exception):
    pass


def _line(text) -> str:
    return " ".join(str(text).split())


def _json_or_none(name: str):
    raw = os.environ[name].strip()
    if raw in ("", NULL):
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Broken(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）") from None
    if not isinstance(doc, dict):
        raise Broken(f"{name} が JSON のオブジェクトでない（{type(doc).__name__}）")
    return doc


def main() -> int:
    missing = [n for n in INPUTS if n not in os.environ]
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        missing.append(script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        judged, tests, start, mid, ci = (_json_or_none(n) for n in INPUTS)
    except Broken as e:
        print(f"report: {_line(e)}", file=sys.stderr)
        return 2
    import reads
    import report
    from board import BoardGap
    from engine.util import Reject
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    run_id = os.environ.get(RUN_ID_ENV, "")
    try:
        if not (board / "state.json").is_file():
            raise BoardGap(f"盤面 {board} が無い（start の前に落ちた run か、works の run でない）")
        out = report.build(board.resolve(), judged=judged, tests=tests, start=start, mid=mid, ci=ci, run_id=run_id,
                           events=reads.events_for(run_id))
    except (BoardGap, Reject) as e:
        print(f"報告を組めない（{type(e).__name__}）: {_line(e)}", file=sys.stderr)
        return 1
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"report の内部の誤り: {type(e).__name__}: {_line(e)}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
