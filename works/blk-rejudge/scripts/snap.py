# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前の作業ツリーの写しを盤面の今の周の rejudge-snapshot.json に置く（受け付けが読むだけの役の変化を見る）。
出口 {ok, snapshot_file}。git が効かない・盤面が開けないなら 2（rejudge.script_main）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import rejudge  # noqa: E402

INPUTS = ()   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_rejudge.py が見る）


def run(board, repo, env):
    return rejudge.snap(board, repo)


if __name__ == "__main__":
    sys.exit(rejudge.script_main(run, INPUTS))
