# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""1 回目の差分の審査役を起こす前の支度（refix.cut(n=1)。blk-delta の節 cut）。
差分を切るのは盤面の機械の節 p3.fix_delta（写しの RL の fix_delta。修正を受けた後の settle）で、ここは盤面の loop.fix_delta の
ファイルと触ったファイルを出し、役に見せる材料（事前審査の穴と修正役の plan_faces）を review1-brief.json に書き、読むだけの役の
前の作業ツリーの写し（review1-snapshot.json）を撮り、起こした印を置く。前の試みの自分の出力は先に消す。
出口: {"ok": true, "files", "diff_file", "rev", "brief_file", "must"} を 1 行。盤面に今の周の差分が無い・審査の節が待っていない・
環境変数の欠け・止めた run は標準エラーに 1 行で 2（配線の誤り。TA19）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.cut(board, 1, repo)


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
