# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目を起こす前の支度（eyes.prep）: engine と同じ描き方で指示書を描き、起こした印を置く。出口 {prompt, prompt_file, node, attempt,
already, role_def, role_def_missing} を 1 行（指示書 commands/<役>.md が prompt を直の参照で貼る）。待っていない目は 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import eyes  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_ROUND")


def run(board, repo, env):
    return eyes.prep(board, env["INPUTS_ROLE"], env["INPUTS_ROUND"], repo)


if __name__ == "__main__":
    sys.exit(eyes.script_main(run, INPUTS))
