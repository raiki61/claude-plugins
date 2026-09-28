# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（report_roles.accept）。拒否（写しの規則・表のセルの書式・読むだけの役の作業ツリーの変化・読めない返答）は
0 で {ok: false, done, give_up, reason, reason_file}（3 回目の拒否で done——輪の抜ける印）。通れば {ok: true, done: true, …}。
初見検査を受けた後に記録が検証器を通らなかったら record_invalid: true（report の節は出ない）。書き手の輪では INPUTS_COLD に
書き手の頭を読んだ初見の読み手の返答が来る。確かめるかは役で決まる（書き手の輪だけ。空の返答は読めない返答として
確かめを通らない。ほかの輪の空は見ない）。配線の誤りだけ 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import report_roles  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY", "INPUTS_COLD")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_report.py が見る）


def run(board, repo, env):
    return report_roles.accept(board, env["INPUTS_ROLE"], env["INPUTS_REPLY"], repo, cold=env["INPUTS_COLD"])


if __name__ == "__main__":
    sys.exit(report_roles.script_main(run, INPUTS, take="report"))
