# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""世界の解のブロックの出口（lib/worldblk.finish）。判断の行を世界の解の行のファイルに書き、
{ok, world_file, status, reason, classes, dropped} を 1 行出して 0。後段が読んでよいのは world_file だけ。
落ちた段が在っても線を止めない（ok は真で、status: failed と reason）。環境変数の欠け・思わぬ誤りは標準エラーに 1 行出して 2
（rolekit.script_main）
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402  （core を sys.path に足すのもここ）
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い


def run(board, repo, env):
    return worldblk.finish(worldblk.place(board))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
