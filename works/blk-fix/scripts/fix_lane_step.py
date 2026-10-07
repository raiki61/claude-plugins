# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の並べの枝の確かめ（blk-fix の節 fix-lane-step-<n>。枝の輪の中で範囲の相談の確かめの節の後。中身は fixlanes.lane_step）。

読む環境変数: INPUTS_REPLY（役 fix-lane-<n> の返答の JSON）・INPUTS_LANE（枝の番号）・INPUTS_CONSULTED（範囲の相談の確かめの節の
consulted。true ならこの回は相談の周で、返答を確かめない）・INPUTS_BASE_REV・INPUTS_TDD_STATE（輪の状態。空は実行器の無い run）・
ARTIFACTS_DIR（盤面は その下の board/）。受け付けと同じ事実の確かめ（凍ったテスト・書き込みの出どころ・食い違いの申し出の形・この
項目の直す義務の単位・承認済みの修正案の範囲・変更に当たる試験）を枝の単位の worktree に当てる。通れば枝の次の項目へ、同じ項目の
3 回目の拒否で項目を諦め（差分を盤面に控えて木を項目の頭に戻す）、項目が尽きるか回数の上限で done（輪はこれで抜ける）。
出口は {"ok", "done", "consulted", "reason", "item", "reason_file"} の 1 行と 0。拒否の理由の本文は盤面の reject-fix_lane_step-<連番>.txt
と、次の回ごとの指示書（fix-lane-prep-<n>）に載る。最後の結果の控えには書かない（枝の拒否は run の落ちた理由ではない）。
環境変数が欠けた・枝の控えが読めない・枝が済んだ後に呼んだ・git が効かない: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

from board import BoardGap  # noqa: E402
import entry  # noqa: E402
import fixlanes  # noqa: E402
import querytest  # noqa: E402
import script_io  # noqa: E402
import tddloop  # noqa: E402
from leftovers import Unreadable  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_LANE", "INPUTS_CONSULTED", "INPUTS_BASE_REV", "INPUTS_TDD_STATE")
REQUIRED = ("INPUTS_REPLY", "INPUTS_LANE")   # 空でない物（ほかは空でよい）


def main() -> int:
    missing = [n for n in REQUIRED if not os.environ.get(n)] + [n for n in INPUTS[2:] if n not in os.environ]
    if missing:
        print(f"fix-lane-step: 環境変数が無い・空: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        reply = json.loads(os.environ["INPUTS_REPLY"])
    except ValueError:
        reply = None   # 読めない返答は確かめが拒む（出し直しの回数に数える）
    try:
        out = fixlanes.lane_step(board, os.environ["INPUTS_LANE"], reply, Path.cwd(),
                                 consulted=os.environ["INPUTS_CONSULTED"].strip().lower() == "true",
                                 base_rev=os.environ["INPUTS_BASE_REV"], tdd_state=os.environ["INPUTS_TDD_STATE"],
                                 try_query=lambda k, lines: querytest.judge_hits(entry.open_board(board).record["units"])(k, lines))
    except (fixlanes.Broken, tddloop.Broken, Unreadable, OSError, BoardGap) as e:
        print(f"fix-lane-step: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    return script_io.emit_result(board, "fix_lane_step", out, last=False)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
