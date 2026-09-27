# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口（report_roles.collect）。report を受けていれば 来歴の 1 行＋書き手の本文＋機械の事実 を盤面の report-ai.md に
書いて ok。受けていなければ、なぜ無いか・受けた分・機械の事実を付けた報告を書いて ok: false（報告の節が 1 つも出ていなければ書かない）。
出口 {ok, reason, report_file, text_file, human_items_file, facts_file, cold_check, record_invalid}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import report_roles  # noqa: E402

INPUTS = ("INPUTS_MACHINE_REPORT",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_report.py が見る）


def run(board, repo, env):
    return report_roles.collect(board, machine_report=env["INPUTS_MACHINE_REPORT"])


if __name__ == "__main__":
    sys.exit(report_roles.script_main(run, INPUTS))
