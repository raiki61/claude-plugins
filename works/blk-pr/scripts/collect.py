# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-pr の節 collect: 受け付けた返答から出口 {ok, pr_file, conflicts, drafts, material_status, reads_file} を組む
（prcheck.collect。drafts は申し送りの下書き note を持つ交差の件数）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))
import prcheck  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い（ARTIFACTS_DIR だけ）

if __name__ == "__main__":
    sys.exit(prcheck.main_collect())
