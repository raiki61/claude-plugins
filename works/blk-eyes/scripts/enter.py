# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""入口（eyes.enter）: p4.assemble が今の周に済んでいるかを確かめ、目を起こす前の作業ツリーの写しを撮る。
出口 {ok, round, stopped, asking, ready, snapshot_file, why} を 1 行。p4.assemble が済んでいない・環境変数の欠けは標準エラーに 1 行で 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import eyes  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_eyes.py が見る）


def run(board, repo, env):
    return eyes.enter(board, repo)


if __name__ == "__main__":
    sys.exit(eyes.script_main(run, INPUTS))
