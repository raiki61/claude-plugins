# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目の返答の受け付け（eyes.accept）。拒否も終了コード 0 で {ok: false, done, give_up, skipped, reason, node, reason_file} を 1 行
（reason_file は拒否の理由の本文のファイル。裁定 R44）。3 回目の拒否で done（輪を抜ける。裁定 R50）。配線の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import eyes  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY")


def run(board, repo, env):
    return eyes.accept(board, env["INPUTS_ROLE"], env["INPUTS_REPLY"], repo)


if __name__ == "__main__":
    sys.exit(eyes.script_main(run, INPUTS))
