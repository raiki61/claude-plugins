# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""範囲の相談の頼みの節（blk-fix の節 fix-consult・fix-ruled-consult。修正の輪の中で役の後・答えの節の前。中身は consult.ask）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）・INPUTS_REPLY（役の返答の JSON）・INPUTS_PLAN_SESSION（相談の相手の会話の
印の名。空は相手の無い run で、頼みは聞けない行になる）・INPUTS_PASS（first か ruled）・INPUTS_ANSWER_NODE（答えの節の名。記録に残す）。
返答に consult が在れば、頼みごとに機械の先の確かめをして盤面の今の scope の周の状態に積み、聞く頼みが在れば相手の会話の id を
包みの置き場へ写して答えの節の指示書を書く。{consulted, go, prompt_file, turn, spent} を 1 行出して 0。
- consulted: この周は相談の周（受け付けと締める節は回さない）。go: 答えの節を起こす。spent: 相談の枠を使い切った（受け付けが拒む）
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

INPUTS = ("INPUTS_REPLY", "INPUTS_PLAN_SESSION", "INPUTS_PASS", "INPUTS_ANSWER_NODE")


def _json(text: str):
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None


def run(board, repo, env):
    b = entry.open_board(Path(board))
    return consult.ask(b, repo, _json(env["INPUTS_REPLY"]), env["INPUTS_PLAN_SESSION"], env["INPUTS_PASS"],
                       env["INPUTS_ANSWER_NODE"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
