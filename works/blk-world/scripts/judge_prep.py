# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判断する役の支度（lib/worldblk.judge_prep）。言い直しの行・控えに当たった類・照らして残った抜き書きから、依頼の行ごとの材料を
1 度だけ組んで指示書を描き、{prompt, prompt_file, attempt} を 1 行出して 0。前の回が拒まれていれば、その理由を頭に置く。
控えが無い（配線の誤り）: 1。ARTIFACTS_DIR が欠けた: 2
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
        out = worldblk.judge_prep(out_dir)
    except worldblk.WorldGap as e:
        print(f"judge_prep.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
