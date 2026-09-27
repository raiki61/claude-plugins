# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（planblk.main_accept → rolekit.main_accept → entry.take）。拒否（読めない返答・写しの規則・
作業ツリーの変化）は {ok: false, reason_file} で 0、3 回目の拒否で done・give_up（輪を抜ける）。出口 {ok, done, give_up, reason, reason_file, node, …}"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）


if __name__ == "__main__":
    if "INPUTS_ROLE" not in os.environ:
        print("環境変数が無い: INPUTS_ROLE", file=sys.stderr)
        sys.exit(2)
    try:
        planblk.role_node(os.environ["INPUTS_ROLE"])
    except planblk.BoardGap as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    sys.exit(planblk.main_accept(os.environ["INPUTS_ROLE"]))
