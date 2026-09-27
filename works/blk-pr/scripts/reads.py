# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-pr の節 pr-reads: 任せ先の役 pr-check の読んだ証拠を今の周の reads-pr-check.json に書く（reads.main_for。線 A Task 6。
受け付けの条件にはしない）。読むべきパスは INPUTS_MUST（JSON の配列）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))
import prcheck  # noqa: E402

INPUTS = ("INPUTS_MUST",)

if __name__ == "__main__":
    import reads  # noqa: E402  （線 A Task 6 の物。入るまでこの節は走らせない——YAML は Task 17）
    sys.exit(reads.main_for(*prcheck.READS))
