# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""出口（eyes.collect）。入口の周の箱で目の状態を見て、EXIT_FIELDS の並びの 1 行。人に聞いていれば止めずに asking。
目が残れば盤面を止めて ok: false。盤面が読めない・環境変数の欠けは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import eyes  # noqa: E402

INPUTS = ("INPUTS_ROUND",)


def run(board, repo, env):
    return eyes.collect(board, env["INPUTS_ROUND"])


if __name__ == "__main__":
    sys.exit(eyes.script_main(run, INPUTS))
