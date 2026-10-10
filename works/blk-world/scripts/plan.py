# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""類を決める（lib/worldblk.plan）。言い直しの行から、類を上限まで取る。{judge_due}（web の役を起こすか）を 1 行出して 0。
言い直しが通らなかった run では偽。置き場の控えが無い・環境変数の欠け・思わぬ誤りは標準エラーに 1 行出して 2（rolekit.script_main）
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402  （core を sys.path に足すのもここ）
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い


def run(board, repo, env):
    return worldblk.plan(worldblk.place(board))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
