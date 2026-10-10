# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の支度（specblk.prep）: 本線の指示書を engine と同じ描き方で描き（前の拒否が在れば頭に）、読むだけの役は作業ツリーの
写しを置き、起こした印を置く。出口 {prompt_file, attempt, out_path, node, already}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ("INPUTS_ROLE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    return specblk.prep(board, env["INPUTS_ROLE"], repo)


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
