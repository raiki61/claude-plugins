# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の作業ツリーの写しを今の周の <役>-snapshot.json に置く（planblk.snap）。節が待っていなければ写しを
置かずに go: false（輪を飛ばす）。出口 {ok, go, snapshot_file}。盤面が開けない・git が効かないなら 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_ROLE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）


def run(board, repo, env):
    return planblk.snap(board, env["INPUTS_ROLE"], repo)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
