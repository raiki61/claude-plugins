# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の並べの枝の輪を起こすか（blk-fix の節 tdd-fork。輪 tdd-loop の後。中身は tddlanes.fork）。

読む環境変数: INPUTS_STATE_FILE（tdd-start の state_file。実行器の無い run は空）。盤面は読まない（実行器の無い run・模擬実行でも走る）。
輪の状態の段が lanes（振り分けの直後に tddlanes.plan が枝を切った）なら {"go": true, "lanes": <枝の数>, "lane_<n>": true…}、
ほかは go: false と全部の lane_<n> が false を 1 行出して 0。枝の輪 tdd-lane-<n> は lane_<n> を when: で読み、tdd-join は go を読む。
状態が読めない・目録の枝の番号が 1..MAX_LANES の連番でない: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import tddlanes  # noqa: E402
import tddloop  # noqa: E402

INPUTS = ("INPUTS_STATE_FILE",)


def main() -> int:
    if INPUTS[0] not in os.environ:
        print(f"tdd-fork: 環境変数が無い: {INPUTS[0]}", file=sys.stderr)
        return 2
    try:
        out = tddlanes.fork(os.environ[INPUTS[0]].strip())
    except (tddloop.Broken, OSError) as e:
        print(f"tdd-fork: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
