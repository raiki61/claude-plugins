# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""書き手の出した物を確かめる初見の読み手の支度（report_roles.write_cold_prep）: 書き手の返答の頭だけを、初見の読み手の指示書
（report.cold_check の写し）の本文の穴に入れて描く。出口 {prompt_file, prompt}（prompt は道具の無い読み手の指示に貼る）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import report_roles  # noqa: E402

INPUTS = ("INPUTS_WRITER",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_report.py が見る）


def run(board, repo, env):
    return report_roles.write_cold_prep(board, env["INPUTS_WRITER"])


if __name__ == "__main__":
    sys.exit(report_roles.script_main(run, INPUTS))
