# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判定役を起こす前の支度（judgebrief.brief）: 盤面から本線の判定の「入力」の節（凍結した目的・素材・P1 の所見・前の決定・
依頼・差分）を描いて今の周の judge-materials.md に書き、{ok, materials_file} を 1 行出して 0。ラインの盤面が無ければ（ブロックを
単独で回した）materials_file は空。盤面の p2.diagnose が待っていない・描けない・環境変数の欠けは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-judge の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import judgebrief  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い（盤面だけを読む）


def run(board, repo, env):
    return judgebrief.brief(board, repo)


if __name__ == "__main__":
    # fence: 材料のファイルのパスは指示書へ Archon の置き換えで貼られるので、$ を含む置き場を 2 で断る
    sys.exit(rolekit.script_main(run, INPUTS, fence=True))
