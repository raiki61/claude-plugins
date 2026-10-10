# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""web の役の支度（lib/worldblk.judge_prep）。言い直しの行の問題の類・作業・検索語・依頼の解き方から、依頼の行ごとの材料を
1 度だけ組んで指示書を描き（依頼の行の本文は貼らない）、{prompt, prompt_file} を 1 行出して 0。前の回が拒まれていれば、その理由を
頭に置く。置き場の控えが無い・環境変数の欠け・思わぬ誤りは標準エラーに 1 行出して 2（rolekit.script_main）
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402  （core を sys.path に足すのもここ）
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い


def run(board, repo, env):
    return worldblk.judge_prep(worldblk.place(board))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
