# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""関所の答えを盤面に渡す（specblk.answer）。INPUTS_GATE は関所 spec-gate の出口（{decision, text} の JSON の文字列。
飛ばされた関所は null）。approve・continue は continue（その後の settle で spec.freeze が走る）、stop・reject は stop。
出口 {answered, decision, stop, why}。知らない語・形の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ("INPUTS_GATE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    return specblk.answer(board, specblk.parse_gate(env["INPUTS_GATE"]))


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
