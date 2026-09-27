# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""関所を開くか・文（specblk.ask。線 A の境の節の at gate と同じ手順）。盤面の問い spec.approve を関所の文にし、
r<N>/gate.md にも置く。止め札が在れば盤面を止める。出口 {ask, stop, gate_text, why}。run の id は環境変数 WORKFLOW_ID"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    run_id = os.environ.get(specblk.RUN_ID_ENV) or ""
    if not run_id:
        raise specblk.BoardGap(f"環境変数 {specblk.RUN_ID_ENV} が無い（関所の文の run の id）")
    return specblk.ask(board, repo, run_id)


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
