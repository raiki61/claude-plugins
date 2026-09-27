# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の支度（material.prep）: 本線の指示書を盤面から描き（拒否の後は理由を頭に）、起こした印を置く。
出口 {prompt_file, prompt_text, attempt, out_path, node, already, stopped}（prompt_text は道具を持たない役だけ。
盤面が止まっていれば描かず stopped: true——役の節は when: で飛ぶ）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意。Ruling R7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))                # ブロックの芯（lib/material.py）
import material  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_PURPOSE_FILE")   # 読む INPUTS_*（YAML の with: の鍵と同じ）


def run(board, repo, env):
    return material.prep(board, env["INPUTS_ROLE"], repo, env["INPUTS_PURPOSE_FILE"])


if __name__ == "__main__":
    sys.exit(material.script_main(run, INPUTS))
