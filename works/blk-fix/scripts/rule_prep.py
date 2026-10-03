# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""裁定役の指示書（blk-fix の節 rule-prep。裁定の輪の中で役 rule の前。中身は ruling.prep）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）と run の値 INPUTS_JUDGMENT_FILE・INPUTS_POLICY_PATH（空でよい）。
作業ツリーの姿を控え（読むだけの役の見張り）、申し出の控え・判定・依頼・持ち主の決まりを組んだ指示書を盤面の今の周の
prompt-rule.md（今の scope の周の置き場）に書き、{prompt_file, iteration} を 1 行出して 0。出し直しなら前の拒否の理由のファイルを 1 行目で名指す（R44）。
環境変数の欠け・裁く申し出が無い・思わぬ誤り: 標準エラーに 1 行出して 2（rolekit.script_main）。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import rolekit  # noqa: E402
import ruling  # noqa: E402

INPUTS = ("INPUTS_JUDGMENT_FILE", "INPUTS_POLICY_PATH")


def run(board, repo, env):
    return ruling.prep(board, repo, {n[len("INPUTS_"):].lower(): env[n] for n in INPUTS})


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
