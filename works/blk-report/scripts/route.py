# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の節が盤面で ready かを見る（report_roles.route）。出口 {next, node, why}（next が空なら輪を飛ばす）。
止めた盤面・検証器の関所が通らない・まだ周の途中も 0 で next 空。配線の誤り（環境変数の欠け・知らない役・BoardGap）だけ 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import report_roles  # noqa: E402

INPUTS = ("INPUTS_ROLE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_report.py が見る）


def run(board, repo, env):
    return report_roles.route(board, env["INPUTS_ROLE"])


if __name__ == "__main__":
    sys.exit(report_roles.script_main(run, INPUTS))
