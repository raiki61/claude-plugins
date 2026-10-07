# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の並べを締める（blk-fix の節 fix-join。枝の輪 fix-lane-loop-<n> の全部の後・修正の輪の前。中身は fixlanes.join）。

読む環境変数: ARTIFACTS_DIR（盤面は その下の board/）。枝ごとに、通った項目の差分（単位の worktree と base の差分）を run の作業
ツリーへ 3 方向で当て（同じ試験のファイルに足しただけの食い違いは枝の順に並べて合わせる）、書き込みの記録を写す。当たらない枝・
諦めた項目・回さなかった項目は修正役の輪に戻し（差分は盤面に控える）、枝の食い違いの申し出は当てた後の作業ツリーで確かめ直して
盤面の控え（conflict.park）に積む。結末を盤面の作業ファイル fix-lanes-out.json と修正役が読む fix-lanes.md に書き、trace に
fix_lanes_settled の 1 行を残し、単位の worktree を片付ける。出口は {"ok", "merged", "back", "parked", "shared", "union"} の 1 行と 0。
この周の結末が在る（締めが済んだ後に、Archon の resume が落ちた枝の輪に依る締めを回し直した）なら、作業ツリーを戻さず、残った単位の
worktree だけ片付けて、結末に残した出口をそのまま出す。
環境変数の欠け・目録が読めない・git が効かない: 標準エラーに 1 行出して 2（rolekit.script_main）。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import entry  # noqa: E402
import fixlanes  # noqa: E402
import querytest  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ()


def run(board, repo, env):
    return fixlanes.join(board, repo,   # query の申し出は判定者の問いを当てて確かめる
                         try_query=lambda k, lines: querytest.judge_hits(entry.open_board(board).record["units"])(k, lines))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
