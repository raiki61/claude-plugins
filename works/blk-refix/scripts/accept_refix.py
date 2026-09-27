# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""手直しの役（p3.delta_fix・p3.delta_fix2。INPUTS_PASS で 1 か 2）の返答を盤面に渡す節（refix.accept_fix）。
受け付けの検査は写しの delta_fix_output（義務の全部に key ごとに 1 度だけ fixed か declared。fixed には触ったファイル）。
受けた後の settle で、盤面の機械の節 p3.fix_delta2（条件 delta_fixed）が手直しだけの差分を切る。中身の拒否は 0 の 1 行
（reason_file つき）、回す側の誤り（往復の番号の誤り・印の無い試行・止めた run・環境変数の欠け）は 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_PASS")   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）

if __name__ == "__main__":
    import os
    try:
        n = refix.pass_of(os.environ.get(INPUTS[2], ""))
    except refix.BoardGap as e:
        print(f"{INPUTS[2]}: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(refix.main_accept_fix(n))
