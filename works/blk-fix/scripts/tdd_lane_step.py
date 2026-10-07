# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の並べの枝の確かめ（blk-fix の節 tdd-lane-step-<n>。枝の輪の中で役 tdd-lane-<n> の後。中身は tddlanes.lane_step）。

読む環境変数: INPUTS_REPLY（役 tdd-lane-<n> の返答の JSON。役が飛ばされた周は null か空）・INPUTS_STATE_FILE（tdd-start の state_file）・INPUTS_LANE（枝の番号）・
ARTIFACTS_DIR（盤面は その下の board/）。赤・緑は機械だけが決める（tddloop.step を枝の単位の worktree で回す）。段を確かめる前に、
前の段の後から変わったファイルを run の作業ツリーの書き込みの記録（包みが単位の worktree の実パスで残す）と返答の欄 bash_writes に
突き合わせる。食い違いの申し出は欄と単位だけ見て枝の控えに書く（盤面を読む確かめと盤面への積みは tdd-join）。
出口は {"ok", "done"（枝の単位が全部済んだ。輪はこれで抜ける）, "reason", "phase", "unit_key", "reason_file"} の 1 行と 0。
拒否の理由の本文は盤面の reject-tdd_lane_step-<連番>.txt と、次の回ごとの指示書（tdd-lane-prep-<n>）に載る。最後の結果の控えには
書かない（輪の拒否は run の落ちた理由ではない）。単位の worktree の指しが切った時と違えば、枝を済みにして done で抜ける（輪を落とさず、
tdd-join が枝の単位を順に戻す）。
枝が済んでいる（締めが済んだ・枝の控えが done。Archon の resume が済みと記録していない枝の輪を回し直した）時に役が飛ばされた周
（返答が null）は、何も動かさずに {"ok": true, "done": true, "phase": "done"} を出す。
環境変数が欠けた・状態が読めない・並べの周でない・済んだ枝に返答が来た・git が効かない: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402
from leftovers import Unreadable  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_STATE_FILE", "INPUTS_LANE")


def main() -> int:
    missing = [n for n in INPUTS if n not in os.environ or (n != "INPUTS_REPLY" and not os.environ[n])]
    if missing:
        print(f"tdd-lane-step: 環境変数が無い・空: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:   # 役が飛ばされた周（支度が go: false。resume で回し直された済んだ枝）は null か空
        reply = json.loads(os.environ["INPUTS_REPLY"]) if os.environ["INPUTS_REPLY"].strip() else None
    except ValueError:
        reply = None   # 読めない返答は step が拒む（出し直しの回数に数える）
    try:
        out = tddlanes.lane_step(os.environ["INPUTS_STATE_FILE"], os.environ["INPUTS_LANE"], reply, Path.cwd())
    except (tddloop.Broken, Unreadable, OSError) as e:
        print(f"tdd-lane-step: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    return script_io.emit_result(board, "tdd_lane_step", out, last=False)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
