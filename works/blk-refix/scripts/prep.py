# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""手直しの役を起こす前の支度（refix.prep_fix。blk-refix の節 refix-prep・refix2-prep。INPUTS_PASS で 1 か 2）。
義務（盤面の機械の節 p3.delta_owed・p3.delta_owed2 が組んだ loop.delta_owed・delta_owed2）と差分のパスを refix<n>-brief.json に
書き、役の指示書を lib/refixrules.py で組んで（書く役の決まりの正本の全節・手直しの決まり・run の値）書き、起こした印を置く。
前の試みの自分の出力は先に消す。出口 {"ok": true, "owed", "diff_file", "brief_file", "prompt_file", "must"} を 1 行。
手直しの節が待っていない・義務が無い・往復の番号の誤り・環境変数の欠け・決まりの穴に値が無いのは標準エラーに 1 行で 2。
1 回目の brief には承認済みの修正案の項目 plan_items・直す裁定が広げたパス ruled_paths・審査の準拠の落ちた行 compliance も
載り、修正案の欄の控えが凍結の印と食い違えば、盤面を手直しの段の印で止めて控えを名指し、標準エラーに 1 行で 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402
import refixrules  # noqa: E402

INPUTS = ("INPUTS_PASS", "INPUTS_POLICY_PATH")   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.prep_fix(board, refix.pass_of(env["INPUTS_PASS"]), repo, prompt=refixrules.build,
                          values={"policy_path": env["INPUTS_POLICY_PATH"]})


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
