# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""事前審査の壁打ちの出口（planblk.converge_check）。抜け方が again でない・今の往復の役が諦めた・盤面が止まった時に done
（外の輪 converge-loop の until_bash が読む）。replan ならいつも done。止めた盤面でも開ける。出口 {ok, done, outcome, record_file}。盤面が開けないなら 2"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_REPLAN",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）
# 無くても欠けに数えない入力（後から足した replan。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_REPLAN"})


def run(board, repo, env):
    return planblk.converge_check(board, os.environ.get("INPUTS_REPLAN", ""))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL)))
