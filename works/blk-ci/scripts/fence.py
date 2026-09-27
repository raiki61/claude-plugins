# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前に、包みが Archon の起動の道に在り切符が在るかを見る（ci_role.fence）。無ければ盤面を止めて go: false
（YAML が役の輪を飛ばす）。出口 {go, reason}。節が任せ先に落ちて待っていないなら 2（ci_role.script_main）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import ci_role  # noqa: E402

INPUTS = ("INPUTS_NODE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_ci.py が見る）


def run(board, repo, env):
    return ci_role.fence(board, env["INPUTS_NODE"], repo)   # 包みの道は os.environ（Archon が継ぐ env）から


if __name__ == "__main__":
    sys.exit(ci_role.script_main(run, INPUTS))
