# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口（planblk.collect）。役の節が待ったまま（3 回とも拒まれた）なら盤面を止めて ok: false・gave_up。
出口 {ok, plan_file, review_file, asks_human, gate_kinds, reads_file, gave_up, reason_file}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）


def run(board, repo, env):
    return planblk.collect(board)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
