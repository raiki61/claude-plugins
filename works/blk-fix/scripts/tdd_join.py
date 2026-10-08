# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の並べを締める（blk-fix の節 tdd-join。枝の輪 tdd-lane-<n> の全部の後。中身は tddlanes.join）。

読む環境変数: INPUTS_STATE_FILE（tdd-start の state_file）・ARTIFACTS_DIR（盤面は その下の board/）。枝ごとに、緑まで済んだ単位の
赤を確かめ直し、書き込みの記録を突き合わせ、差分を run の作業ツリーへ 3 方向で当て、当てた後の木で緑をもう 1 度確かめる。済まなかった・
当たらない・当てた後に赤い単位は順の単位に戻し（輪 tdd-rest が最初の段から回す）、単位の worktree を片付ける。枝の食い違いの申し出は
盤面の確かめ（conflict.problems）を通った物を盤面の控え（lanekit.park）に積む。
出口は {"go"（順に回す単位が残る。輪 tdd-rest が when: で読む）, "done", "phase", "merged", "back"} の 1 行と 0。
締めが済んだ後にもう 1 度呼ばれた（Archon の resume が、落ちた枝の輪に依る締めを回し直した）時は、締めた時の出口をそのまま出す
（盤面・作業ツリーを動かさない。申し出は出口を保存した後に積み、積めたら出口から消す。保存と積みの間で落ちた締めの再生は、
積んでいない申し出だけを積む。積んだ後の再生は積まない）。
環境変数が欠けた・状態が読めない・並べの周でない・git が効かない: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

from board import BoardGap  # noqa: E402
import entry  # noqa: E402
import lanekit  # noqa: E402
import querytest  # noqa: E402
import script_io  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402
from leftovers import Unreadable  # noqa: E402

INPUTS = ("INPUTS_STATE_FILE",)


def main() -> int:
    if not os.environ.get(INPUTS[0]):
        print(f"tdd-join: 環境変数が無い・空: {INPUTS[0]}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        out = tddlanes.join(os.environ[INPUTS[0]], Path.cwd(),   # query の申し出は判定者の問いを当てて確かめる
                            try_query=lambda k, lines: querytest.judge_hits(entry.open_board(board).record["units"])(k, lines),
                            # 枝の申し出のうち確かめを通った物を盤面の控えと trace に積む（裁定の輪が読む。lanekit.park）
                            park=lambda items: lanekit.park(entry.open_board(board), items, "tdd"))
        out.pop("conflicts")
    except (tddloop.Broken, Unreadable, OSError, BoardGap) as e:
        print(f"tdd-join: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
