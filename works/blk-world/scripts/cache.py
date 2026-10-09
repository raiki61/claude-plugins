# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""控えを引く（lib/worldblk.plan）。言い直しの行から、語の直しだけの行を飛ばし、類を上限まで取り、run をまたぐ控えに当たった類は
集めず、残りを集める類にする（web が off なら集めない）。{collect_due, judge_due, prompt}（prompt は集める役の指示書）を 1 行出して 0。
言い直しが通らなかった run では両方偽。入口の控えが無い（配線の誤り）: 1。ARTIFACTS_DIR が欠けた: 2
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
        out = worldblk.plan(out_dir, time.time())
    except worldblk.WorldGap as e:
        print(f"cache.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
