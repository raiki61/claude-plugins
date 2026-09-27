# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口を組む（material.collect）。回した後も待っている素材集めの節が在れば盤面を止めて ok: false。
出口 {ok, reason, ran, skipped, materials, snapshot, exit_file}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意。Ruling R7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))                # ブロックの芯（lib/material.py）
import material  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ）


def run(board, repo, env):
    return material.collect(board)


if __name__ == "__main__":
    sys.exit(material.script_main(run, INPUTS))
