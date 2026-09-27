# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""2 回目の差分の審査役（p3.delta_review2）の返答を盤面に渡す節（refix.main_accept_review(2)。3 回目の拒否で done・give_up。R50）。読むだけの役なので cut2 が
撮った写しと比べる。検査は写しの delta_review_output（手直しが fixed と言う穴を 1 件ずつ検算）。義務（loop.delta_owed2）は
受けた後の settle で盤面の機械の節 p3.delta_owed2 が組む。中身の拒否は 0 の 1 行、回す側の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV")   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）

if __name__ == "__main__":
    sys.exit(refix.main_accept_review(2))
