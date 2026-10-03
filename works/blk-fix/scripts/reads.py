# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-fix の節 fix-reads: 修正役 fix の読んだ証拠を今の周の reads-fix.json に書く（reads.main_for。線 A Task 6。
受け付けの条件にはしない。collect が reads_file で出口に出す）。読むべきパスは INPUTS_MUST（JSON の配列）と、fix-prep が
今の周に組んだ指示書（fixrules.reads_more。輪の外の節は輪の中の出力を引けないので盤面の置き場から。回の印 INPUTS_PASS_TAG の
指示書）。出来事を引く include の名は core の reads が今の節の居場所から引く（ブロックは知らない）。
回の印が在れば、書く先は reads-fix.<印>.json（役の名 fix.<印>。recount.reads_role。1 回目の reads-fix.json を上書きしない）。
brief の控え（briefs.json）が壊れている・凍結の印と食い違えば、盤面を止めて 2（欄の控え plan-fields.json は読まない）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixrules  # noqa: E402
import recount  # noqa: E402

INPUTS = ("INPUTS_MUST", "INPUTS_PASS_TAG")
# 無くても欠けに数えない入力（依頼 226 で後から足した回の印。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_PASS_TAG"})

if __name__ == "__main__":
    import os  # noqa: E402
    import reads  # noqa: E402  （線 A Task 6 の物。入るまでこの節は走らせない——YAML は Task 17）
    _, loop, node = recount.READS
    tag = os.environ.get("INPUTS_PASS_TAG", "")
    sys.exit(reads.main_for(recount.reads_role(tag), loop, node,
                            more=fixrules.reads_more))
