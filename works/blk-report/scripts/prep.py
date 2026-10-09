# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""書き手を起こす前の支度（report_roles.prep）: 本線の指示書を盤面の値で描き、拒否の後なら前の拒否の文を頭に置き、
作業ツリーの写しを取り、起こした印を置く。出口 {prompt_file, attempt, node, facts_file, already}。
facts_file は書き手の数の出どころ"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import report_roles  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_MACHINE_REPORT")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_report.py が見る）


def run(board, repo, env):
    return report_roles.prep(board, env["INPUTS_ROLE"], repo, machine_report=env["INPUTS_MACHINE_REPORT"])


if __name__ == "__main__":
    sys.exit(report_roles.script_main(run, INPUTS))
