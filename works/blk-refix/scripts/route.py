# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-refix の分かれ道（refix.route。節 route1・route2）。盤面の待っている節と義務の数だけで決める:
{"review2": 2 回目の審査の節が待っているか, "refix2": 2 回目の手直しの節が待っているか, "owed", "owed2"}。後ろの when: はこの欄だけを
読む。3 往復目は無い（写しの DELTA_PASSES は 2 回まで）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.route(board)


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
