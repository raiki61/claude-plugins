# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""1 回目の差分の審査役（p3.delta_review）の返答を盤面に渡す節（refix.accept_review(n=1)。entry.main_take と同じ約束）。
読むだけの役なので、cut が撮った写しと今の作業ツリーを先に比べる。受け付けの検査は写しの delta_review_output（触ったファイルの
今の姿に在る字列・事前審査だけの kind を拒む・塞いだと言われた穴を 1 件ずつ検算）。中身の拒否は終了コード 0 の 1 行
（reason_file つき。裁定 R44）、回す側の誤り（印の無い試行・止めた run・環境変数の欠け）は 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV")   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）

if __name__ == "__main__":
    sys.exit(refix.main_accept_review(1))
