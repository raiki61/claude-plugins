# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の指示書（blk-fix の節 tdd-prep。輪の中で役 tdd の前。中身は tddloop.prep）。

読む環境変数: INPUTS_STATE_FILE（tdd-start の state_file）。今の段・今の単位・前の回に拒んだ理由を状態の置き場の next.md に書き、
{"prompt_file"} を 1 行出して 0。役はそのパスを Read する（理由の本文を $LOOP_PREV で貼らない。R44）。
状態が読めない・輪が済んでいる: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import tddloop  # noqa: E402

INPUTS = ("INPUTS_STATE_FILE",)


def main() -> int:
    if not os.environ.get("INPUTS_STATE_FILE"):
        print("tdd-prep: 環境変数が無い・空: INPUTS_STATE_FILE", file=sys.stderr)
        return 2
    try:
        out = tddloop.prep(os.environ["INPUTS_STATE_FILE"])
    except (tddloop.Broken, OSError) as e:
        print(f"tdd-prep: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
