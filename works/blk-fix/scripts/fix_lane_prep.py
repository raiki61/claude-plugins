# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の並べの枝の支度（blk-fix の節 fix-lane-prep-<n>。枝の輪の中で役 fix-lane-<n> の前。中身は fixlanes.lane_prep）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）・INPUTS_LANE（枝の番号）。枝の今の項目の回ごとの指示書（前の回を拒んだ理由と
項目の決まりのファイルの名指し。範囲の相談の答えが来た回は答えのファイルを名指す続きの指示書）を書き、包みが読む 2 つの印（項目が
替わると会話を切る単位の鍵・枝の単位の worktree）を置いて {"prompt_file", "go": true} を 1 行出して 0。
枝が済んでいる（締めが止めた枝を含む。Archon の resume は済みと記録していない枝の輪を 1 周目から回し直す）なら、何も書かずに
{"prompt_file": "", "go": false}（役の節は when: で飛び、確かめが輪を抜ける）。
枝の控えが読めない・単位の worktree の指しが切った時と違う・環境変数の欠け: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixlanes  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_LANE",)


def run(board, repo, env):
    return fixlanes.lane_prep(board, env["INPUTS_LANE"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
