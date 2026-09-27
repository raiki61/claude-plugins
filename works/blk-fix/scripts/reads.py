# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-fix の節 fix-reads: 修正役 fix の読んだ証拠を今の周の reads-fix.json に書く（reads.main_for。線 A Task 6。
受け付けの条件にはしない。collect が reads_file で出口に出す）。読むべきパスは INPUTS_MUST（JSON の配列）と、fix-prep が
今の周に組んだ指示書（fixrules.reads_more。輪の外の節は輪の中の出力を引けないので盤面の置き場から）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixrules  # noqa: E402
import recount  # noqa: E402

INPUTS = ("INPUTS_MUST",)

if __name__ == "__main__":
    import reads  # noqa: E402  （線 A Task 6 の物。入るまでこの節は走らせない——YAML は Task 17）
    sys.exit(reads.main_for(*recount.READS, more=fixrules.reads_more))
