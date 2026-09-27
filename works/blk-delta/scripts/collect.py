# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""輪の後ろで出口を組む節（refix.collect_delta）。1 本目の {ok, faces, review_file, diff_file} に owed（手直しが答える義務の数。
盤面の機械の節 p3.delta_owed が組んだ loop.delta_owed）・fix_rev（修正後に固めた版）・reads_file を足して 1 行。
数えるのは盤面の今の周に受けた返答だけ（前の周・前の試みの返答は数えない）。3 回とも拒まれて受けていなければ、最後の拒否の
文で盤面を止めて ok: false（refix.DELTA_BY）。拒否が足りずに受けていなければ標準エラーに 1 行で 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.collect_delta(board)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))   # 諦めた出口の ok: false は配線の誤りでない（refix.script_main でなく）
