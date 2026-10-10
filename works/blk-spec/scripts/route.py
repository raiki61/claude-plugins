# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の輪を回すか（specblk.route）。盤面の ready だけで決め、止まった盤面・止め札なら go false。書く役の route は、仕様の道でない
run（spec.write が na）・CI の前に差した配線の誤りを 2 で落とす。出口 {go, node, why}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ("INPUTS_ROLE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    return specblk.route(board, env["INPUTS_ROLE"], repo)


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
