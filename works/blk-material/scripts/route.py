# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""素材集めの役のうち回す物を決める（material.route）。盤面を settle し、ready の節の役に真を立て、役を起こす前の作業ツリーの姿を
周に 1 度置く。包みを宣言した run（adapter 空）で切符が無ければ盤面を止めて stopped。
出口 {ok, stopped, why, snapshot_file, <役>: bool…}（役の欄は material.route_key）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意。Ruling R7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))                # ブロックの芯（lib/material.py）
import material  # noqa: E402

INPUTS = ("INPUTS_ADAPTER",)   # 読む INPUTS_*（YAML の with: の鍵と同じ）


def run(board, repo, env):
    return material.route(board, repo, env["INPUTS_ADAPTER"])


if __name__ == "__main__":
    sys.exit(material.script_main(run, INPUTS))
