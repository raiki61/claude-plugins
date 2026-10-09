# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""言い直す役の受け付け（lib/worldblk.classes_accept）。返答（INPUTS_REPLY）を入口の控えと照らし、通れば言い直しの行を書く。
{ok, done, give_up, reason, attempt} を 1 行出して 0。拒否は例外でなく ok: false（done は 3 回目の拒否で真になり、輪を抜ける。
max_iterations で線を落とさない）。返答が JSON でない時も拒否として返す。入口の控えが無い（配線の誤り）: 1。ARTIFACTS_DIR が欠けた: 2
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402

REPLY_ENV = "INPUTS_REPLY"
INPUTS = (REPLY_ENV,)   # 裁定 TA16: 読む INPUTS_* の組


def main() -> int:
    art = os.environ.get("ARTIFACTS_DIR")
    if not art:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    out_dir = Path(art) / worldblk.OUT_DIR
    try:
        reply = json.loads(os.environ.get(REPLY_ENV, ""))
    except json.JSONDecodeError:
        reply = None
    try:
        out = worldblk.classes_accept(out_dir, reply)
    except worldblk.WorldGap as e:
        print(f"classes_accept.py: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
