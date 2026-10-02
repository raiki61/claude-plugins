# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の支度（planblk.prep）: 本線の指示書を engine の描き方で描き（rolekit.render_prompt）、起こした印を置く。
出口 {prompt_file, attempt, out_path, node, already}"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_EXCLUDED_FILE", "INPUTS_REPLAN")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）
# 無くても欠けに数えない入力（後から足した replan。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_REPLAN"})


def run(board, repo, env):
    return planblk.prep(board, env["INPUTS_ROLE"], repo, env["INPUTS_EXCLUDED_FILE"], os.environ.get("INPUTS_REPLAN", ""))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL)))
