# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""集め役（lenses.collect。trigger_rule all_done）。レンズの節の出口（走らなかった・落ちた節は null）で lens.json を埋め、
落ちたレンズ・起こさなかったレンズも理由つきで記録して ok: true。控えが無い（振り分けが落ちた）・読めなければ ok: false と理由"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import lenses  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_SILENT_FAILURE_HUNTER",)   # lenses.input_name の並び（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return lenses.collect(board, env)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
