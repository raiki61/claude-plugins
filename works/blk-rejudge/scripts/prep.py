# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の支度（rejudge.prep）: 指示書を描き、単位の写しを置き、起こした印を置く。
出口 {prompt_file, attempt, out_path, node, already}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import rejudge  # noqa: E402

INPUTS = ("INPUTS_ROLE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_rejudge.py が見る）


def run(board, repo, env):
    return rejudge.prep(board, env["INPUTS_ROLE"], repo)


if __name__ == "__main__":
    sys.exit(rejudge.script_main(run, INPUTS))
