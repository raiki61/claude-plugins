# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""次に回す再審の役を決める（rejudge.route）。盤面の ready だけで決め、判定役の会話の続きの役なら先に会話を確かめる。
確かめられなければ盤面を止めて stopped。出口 {next, node, why, stopped}（next が空なら回さない）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import rejudge  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_rejudge.py が見る）


def run(board, repo, env):
    return rejudge.route(board, repo)


if __name__ == "__main__":
    sys.exit(rejudge.script_main(run, INPUTS))
