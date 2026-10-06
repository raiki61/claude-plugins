# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の並べの枝の支度（blk-fix の節 tdd-lane-prep-<n>。枝の輪の中で役 tdd-lane-<n> の前。中身は tddlanes.lane_prep）。

読む環境変数: INPUTS_STATE_FILE（tdd-start の state_file）・INPUTS_LANE（枝の番号）と run の値 INPUTS_JUDGMENT_FILE・
INPUTS_PLAN_FILE・INPUTS_POLICY_PATH・INPUTS_NOTES_FILE（空でよい）。枝の今の単位の決まりのファイル（盤面の tdd-<k>/lane-<n>-<j>.md）と
回ごとの指示書（tdd-<k>/lane-<n>.next.md）を書き、包みが読む 2 つの印（単位の鍵と、枝の役の cwd にする単位の worktree）を run ごとの
置き場に置いて、{"prompt_file"} を 1 行出して 0。役はそのパスを Read する（理由の本文を $LOOP_PREV で貼らない。R44）。
環境変数が欠けた・状態が読めない・並べの周でない・枝が無い・枝が済んでいる・単位の worktree の指しが切った時と違う: 標準エラーに
1 行出して 2。brief の控えが壊れていれば盤面を止めて 2。修正の形 g3 の座の写しが固定と違えば 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import tddlanes  # noqa: E402
import tddloop  # noqa: E402

INPUTS = ("INPUTS_STATE_FILE", "INPUTS_LANE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE")


def main() -> int:
    lack = [n for n in INPUTS if n not in os.environ] + [n for n in INPUTS[:2] if not os.environ.get(n)]
    if lack:
        print(f"tdd-lane-prep: 環境変数が無い・空: {', '.join(dict.fromkeys(lack))}", file=sys.stderr)
        return 2
    values = {n[len("INPUTS_"):].lower(): os.environ[n] for n in INPUTS[2:]}
    try:
        out = tddlanes.lane_prep(os.environ[INPUTS[0]], os.environ[INPUTS[1]], values)
    except (tddloop.Broken, OSError) as e:
        print(f"tdd-lane-prep: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
