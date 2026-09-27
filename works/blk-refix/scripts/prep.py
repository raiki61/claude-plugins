# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""手直しの役を起こす前の支度（refix.prep_fix。blk-refix の節 refix-prep・refix2-prep。INPUTS_PASS で 1 か 2）。
義務（盤面の機械の節 p3.delta_owed・p3.delta_owed2 が組んだ loop.delta_owed・delta_owed2）と差分のパスを refix<n>-brief.json に
書き、起こした印を置く。前の試みの自分の出力は先に消す。出口 {"ok": true, "owed", "diff_file", "brief_file", "must"} を 1 行。
手直しの節が待っていない・義務が無い・往復の番号の誤り・環境変数の欠けは標準エラーに 1 行で 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import refix  # noqa: E402

INPUTS = ("INPUTS_PASS",)   # 読む INPUTS_*（YAML の with: の鍵と同じ。TA16）


def run(board, repo, env):
    return refix.prep_fix(board, refix.pass_of(env["INPUTS_PASS"]), repo)


if __name__ == "__main__":
    sys.exit(refix.script_main(run, INPUTS))
