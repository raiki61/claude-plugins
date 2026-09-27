# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""2 回目の差分の審査役（手直しだけの差分）を起こす前の支度（refix.cut(n=2)。blk-refix の節 cut2）。
差分を切るのは盤面の機械の節 p3.fix_delta2（loop.fix_delta.rev → 手直しの後の作業ツリー）で、ここは盤面の loop.fix_delta2 の
ファイルと触ったファイルを出し、役に見せる材料（手直しの handled）を review2-brief.json に書き、写し（review2-snapshot.json）を
撮り、起こした印を置く。出口 {"ok": true, "files", "diff_file", "rev", "brief_file", "must"}。配線の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.cut(board, 2, repo)


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
