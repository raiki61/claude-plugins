# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""世界の解のブロックの出口（lib/worldblk.finish）。判断の行を世界の解の行のファイルに書き、web で照らした類の定石を run をまたぐ
控えに足し、{ok, world_file, status, reason, classes, cached, skipped, dropped} を 1 行出して 0。後段が読んでよいのは world_file だけ。
落ちた段が在っても線を止めない（ok は真で、status: failed と reason）。ARTIFACTS_DIR が欠けた: 2
"""
import json
import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402

INPUTS = ()   # 裁定 TA16: 読む INPUTS_* の組（無い）


def main() -> int:
    art = os.environ.get("ARTIFACTS_DIR")
    if not art:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    out_dir = Path(art) / worldblk.OUT_DIR
    try:
        out = worldblk.finish(out_dir, time.time())
    except worldblk.WorldGap as e:
        print(f"collect.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
