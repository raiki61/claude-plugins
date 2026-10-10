# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""裁定の輪を回すか（blk-fix の節 conflict-check。修正の輪の後。中身は ruling.check）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）。今の周に裁かれていない食い違いの申し出（修正役か TDD の輪の役が返し、
名指しが現物に在った物）が在れば {go: true, count, file}、無ければ {go: false, count: 0, file: ""} を 1 行出して 0。
裁定の輪（rule-loop）と 2 回目の修正役（fix-ruled-loop）の when: はこの欄だけを読む。回す側の誤りは標準エラーに 1 行で 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import rolekit  # noqa: E402
import ruling  # noqa: E402

INPUTS = ()   # 読む INPUTS_* は無い（盤面の控えだけを読む）


def run(board, repo, env):
    return ruling.check(board)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run))
