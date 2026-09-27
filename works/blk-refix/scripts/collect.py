# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-refix の出口を組む節（refix.collect_refix）: {ok, handled_file, review2_file, owed2, fixed2, files, reads_file}
（review2_file は 2 回目の審査を回さなかった run では空。fixed2 は報告の次の run の依頼の下書きへ渡す数。T15）。
手直し 1・審査 2・手直し 2 のどれかが 3 回とも拒まれて輪を抜けたら、最後の拒否の文で盤面を止めて ok: false（refix.REFIX_BY）。
拒否が足りずに手直しの返答が盤面の今の周に無ければ標準エラーに 1 行で 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.collect_refix(board)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))   # 諦めた出口の ok: false は配線の誤りでない（refix.script_main でなく）
