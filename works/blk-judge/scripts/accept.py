# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判定役の返答の受け付け（judge-accept）。ラインの盤面（$ARTIFACTS_DIR/board/state.json）が在れば、本線と同じ受け付け——盤面の
p2.diagnose の done（judgetake.accept。rolekit.main_accept）——に通し、無ければ（ブロックを単独で回した）v1 の check_judge。
どちらも拒否は終了コード 0 の 1 行 {"ok": false, "reason", "reason_file", "done", …}（理由の本文は reason_file のパスにだけ。R44）。
done は輪を抜ける旗（通った時か 3 回目の拒否。R50: max_iterations に当てて run を落とさない）。回す側の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-judge の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import judgetake  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402
from accept import check_judge  # noqa: E402


def main() -> int:
    board = script_io.board_dir()
    if board is None:
        return 2
    if judgetake.on_line(board):
        return rolekit.main_accept(judgetake.NODE, snapshot_name=judgetake.TREE_FILE,
                                   give_up_after=judgetake.GIVE_UP_AFTER, after=judgetake.finish)
    return script_io.main(check_judge, finish=lambda out: judgetake.with_done(board, out))


if __name__ == "__main__":
    sys.exit(main())
