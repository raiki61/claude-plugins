# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの出口を組む（ci_role.collect）: 写しを消し、節を受けていれば {ok: true, status, green, pr_go}、受けていなければ
盤面を止めて ok: false。出口 {ok, reason, node, status, green, pr_go}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import ci_role  # noqa: E402

INPUTS = ("INPUTS_NODE",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_ci.py が見る）


def run(board, repo, env):
    return ci_role.collect(board, env["INPUTS_NODE"])


if __name__ == "__main__":
    sys.exit(ci_role.script_main(run, INPUTS))
