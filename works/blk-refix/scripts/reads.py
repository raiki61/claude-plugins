# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-refix の節 refix-reads: この周に受けた手直し 2 回と 2 回目の審査の役ごとに、読んだ証拠を reads-<役>.json に書く
（refix.reads_all → reads.collect。線 A Task 6。受け付けの条件にはしない）。機械が渡したパスは各役の支度の brief と差分
（refix.must）。出来事は WORKFLOW_ID の run から（reads.events_for）。出口 {"ok": true, "reads_files": {役: パス}}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    import os
    import reads  # noqa: E402  （線 A Task 6 の物。入るまでこの節は走らせない——YAML は Task 17）
    if refix.own_module(reads, __file__):
        raise refix.BoardGap("core に reads.py（線 A Task 6）が無い: 読んだ証拠を集められない")
    return refix.reads_all(board, reads, os.environ.get("WORKFLOW_ID", ""))


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
