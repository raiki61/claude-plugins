# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""範囲の相談の確かめの節（blk-fix の節 fix-consult-check・fix-ruled-consult-check。答えの節の後・締める節の前。中身は consult.settle）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）・INPUTS_ANSWER（答えの節の出力の JSON。飛ばされた周は null）・INPUTS_PASS
（first か ruled）・INPUTS_ANSWER_NODE（答えの節の名。記録に残す）。
頼みの節が相談の周と決めた周だけ、答えを頼みごとに確かめ（許すのは頼んだ物の中だけ）、1 頼み 1 行を盤面の trace
（conflict.ASKED_OP）に書き、修正役が読む答えのファイルを書く。{consulted, turn, answer_file, counts} を 1 行出して 0
（相談の周でなければ consulted: false で何も書かない）。後ろの締める節と受け付けは consulted を読んで、その周を回さない。
- 環境変数の欠け・盤面が開けない・思わぬ誤り: 標準エラーに 1 行出して 2（rolekit.script_main）
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import consult  # noqa: E402
import entry  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_ANSWER", "INPUTS_PASS", "INPUTS_ANSWER_NODE")


def _json(text: str):
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None


def run(board, repo, env):
    b = entry.open_board(Path(board))
    return consult.settle(b, _json(env["INPUTS_ANSWER"]), env["INPUTS_PASS"], env["INPUTS_ANSWER_NODE"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
