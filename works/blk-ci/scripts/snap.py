# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の本物の作業ツリーの姿と、テストを走らせる写し（ci_role.snapshot）を盤面の今の周の ci-snapshot-<節>.json に置く。
出口 {ok, snapshot_file, copy_dir}。節が任せ先に落ちて待っていない・git が効かないなら 2（ci_role.script_main）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import ci_role  # noqa: E402

INPUTS = ("INPUTS_NODE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_ci.py が見る）


def run(board, repo, env):
    return ci_role.snapshot(board, env["INPUTS_NODE"], repo)


if __name__ == "__main__":
    sys.exit(ci_role.script_main(run, INPUTS))
