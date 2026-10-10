# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口を組む（specblk.collect）。固まった仕様を盤面の r<N>/spec.json に写し、{ok, reason, spec_file, tests, approved_by,
approval_note, frozen_rev, requirements, acceptance, faces, handled} を出す。固まっていなければ理由つきで ok false（諦めた輪は盤面を止める）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    return specblk.collect(board, repo)


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
