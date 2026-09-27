# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口を組む（rejudge.collect）。回した後も再審の節が ready のまま（3 回とも拒まれた・段の順のずれ）なら
盤面を止めて ok: false。出口 {ok, reason, passes, verdicts, unsettled, new_open_units, unnamed_changed, diff_file, reads_file}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import rejudge  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_rejudge.py が見る）


def run(board, repo, env):
    return rejudge.collect(board)


if __name__ == "__main__":
    sys.exit(rejudge.script_main(run, INPUTS))
