# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""波及の一覧の節（planblk.make_ripple。線の木の段 1）。stage units は修正案の役の前に単位の key の名を、stage items は往復ごとの
事前審査の前に盤面の項目の欄ごとに、git grep で呼び出し元と試験を引いて今の周に置く。出口 {ok, ripple_file}（作らなかった時は
空）。replan なら作らない。盤面が開けない・stage が違うなら 2"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_STAGE", "INPUTS_REPLAN")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）
# 無くても欠けに数えない入力（後から足した replan。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_REPLAN"})


def run(board, repo, env):
    return planblk.make_ripple(board, repo, env["INPUTS_STAGE"], os.environ.get("INPUTS_REPLAN", ""))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL)))
