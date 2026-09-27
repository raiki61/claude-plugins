# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-delta の節 review-reads: 審査役 review の読んだ証拠を今の周の reads-review.json に書く（reads.main_for。線 A Task 6。
受け付けの条件にはしない）。読むべきパスは INPUTS_MUST（JSON の配列。cut の出口の must）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ("INPUTS_MUST",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）

if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    import reads  # noqa: E402  （線 A Task 6 の物。入るまでこの節は走らせない——YAML は Task 17）
    if refix.own_module(reads, __file__):
        print("core に reads.py（線 A Task 6）が無い: 読んだ証拠を集められない", file=sys.stderr)
        sys.exit(2)
    sys.exit(reads.main_for(*refix.READS["review"]))
