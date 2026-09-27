# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-pr の節 pr-snap: 任せ先の役 pr-check を起こす前に、作業ツリーの写しと役への渡し物を今の周の作業ファイルに置く
（prcheck.snapshot）。出口 {ok, snapshot_file, brief_file}。回す側の誤りは終了コード 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))
import prcheck  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い（ARTIFACTS_DIR と cwd だけ）

if __name__ == "__main__":
    sys.exit(prcheck.main_snapshot())
