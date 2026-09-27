# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目 1 つを今起こすか（eyes.route）。出口 {go, node, why, stopped} を 1 行。知らない役・周の番号が読めないは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import eyes  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_ROUND")


def run(board, repo, env):
    return eyes.route(board, env["INPUTS_ROLE"], env["INPUTS_ROUND"])


if __name__ == "__main__":
    sys.exit(eyes.script_main(run, INPUTS))
