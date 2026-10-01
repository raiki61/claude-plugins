# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ブロックの境（lenses.exit_。trigger_rule all_done）。集め役の出口（落ちた・走らなかった集め役は null）が ok なら ok: true、
そうでなければ盤面を止めて（by works:lens）ok: false。後ろの境の節は止まった盤面を見て stop を返す"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import lenses  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_COLLECTED",)


def run(board, repo, env):
    raw = env["INPUTS_COLLECTED"].strip()
    try:
        collected = None if raw in ("", "null") else json.loads(raw)
    except ValueError:
        collected = {"ok": False, "reason": f"集め役の出口が JSON でない: {raw[:200]}"}
    return lenses.exit_(board, collected)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
