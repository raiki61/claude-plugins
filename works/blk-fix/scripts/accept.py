"""修正役の返答の受け付け（blk-fix の節 fix-accept）。

core の check_fix（changes[].unit_key が盤面の judgment.json の直す義務の単位を覆うか）に通し、結果に changes を足して出す。
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が盤面の changes.json に書く）。拒んだときの changes は空。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import script_io  # noqa: E402
from accept import check_fix  # noqa: E402


def accept_fix(reply, board, base_rev, repo):
    r = check_fix(reply, board, base_rev, repo)
    return {**r, "changes": reply["changes"] if r["ok"] else []}


sys.exit(script_io.main(accept_fix))
