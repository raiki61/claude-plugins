# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-pr の節 collect: 受け付けた返答から出口 {ok, pr_file, conflicts, drafts, material_status, reads_file} を組む
（prcheck.collect。drafts は申し送りの下書き note を持つ交差の件数）。任せ先の役が 3 回とも拒まれて輪を抜けたなら、
最後の拒否の文で盤面を止めて ok: false（rolekit.gave_up。by は prcheck.STOP_BY）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))
import prcheck  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い（ARTIFACTS_DIR だけ）


def gave_up(board) -> str:
    return rolekit.gave_up(board, prcheck.NODE, by=prcheck.STOP_BY)


if __name__ == "__main__":
    sys.exit(prcheck.main_collect(gave_up))
