# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造の目の受け付け（lib/eye.accept）。目の返答（INPUTS_REPLY）を structure.json（INPUTS_STRUCTURE_FILE）と突き合わせ、通れば
design.jsonl（INPUTS_DESIGN_FILE）に行を書く。{ok, done, give_up, reason, attempt} を 1 行出して 0。
拒否は例外でなく ok: false（done は 3 回目の拒否で真になり、輪を抜ける。max_iterations で線を落とさない）。
返答が JSON でない時も拒否として返す。structure.json が読めない・design.jsonl を書けない（配線の誤り）: 標準エラーに 1 行出して 1
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import eye  # noqa: E402

STRUCTURE_ENV = "INPUTS_STRUCTURE_FILE"
DESIGN_ENV = "INPUTS_DESIGN_FILE"
REPLY_ENV = "INPUTS_REPLY"
INPUTS = (STRUCTURE_ENV, DESIGN_ENV, REPLY_ENV)   # 裁定 TA16: 読む INPUTS_* の組


def main() -> int:
    raw = os.environ.get(REPLY_ENV, "")
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError:
        reply = None
    try:
        out = eye.accept(os.environ.get(STRUCTURE_ENV, ""), os.environ.get(DESIGN_ENV, ""), reply)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"eye_accept.py: structure.json が読めないか design.jsonl を書けない: {e}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
