# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役を起こす前に、run が宣言した包みの形（start の控えの adapter）を読む（ci_role.fence）。包みを宣言した run は切符を見て進み、
包み無しの run は知らせ note を残して進む。宣言が読めない・切符が無ければ盤面を止めて go: false（YAML が役の輪を飛ばす）。
出口 {go, reason, note}。節が任せ先に落ちて待っていないなら 2（ci_role.script_main）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import ci_role  # noqa: E402

INPUTS = ("INPUTS_NODE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_ci.py が見る）


def run(board, repo, env):
    return ci_role.fence(board, env["INPUTS_NODE"], repo)


if __name__ == "__main__":
    sys.exit(ci_role.script_main(run, INPUTS))
