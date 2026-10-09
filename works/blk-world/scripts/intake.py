# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""世界の解のブロックの入口（lib/worldblk.intake）。依頼のファイル（INPUTS_REQUEST。cwd からの相対か絶対。空なら依頼の行の無い run）・
目的の文のファイル（INPUTS_PURPOSE_FILE。任意）・run をまたぐ控えの置き場（INPUTS_CACHE_ROOT。空なら包みの家の下）・web の切り替え
（INPUTS_WEB。on・off、空は on）を読み、$ARTIFACTS_DIR/world/ を置き直して入口の控えを書き、{due, findings, reason} を 1 行出して 0。
依頼や目的の文が読めない時も止めない（reason に残し due は偽。出口が status: failed にする）。ARTIFACTS_DIR が欠けた（空も欠け）: 2
"""
import json
import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402

REQUEST_ENV = "INPUTS_REQUEST"
PURPOSE_ENV = "INPUTS_PURPOSE_FILE"
CACHE_ENV = "INPUTS_CACHE_ROOT"
WEB_ENV = "INPUTS_WEB"
INPUTS = (REQUEST_ENV, PURPOSE_ENV, CACHE_ENV, WEB_ENV)   # 裁定 TA16: 読む INPUTS_* の組


def main() -> int:
    art = os.environ.get("ARTIFACTS_DIR")
    if not art:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    out = worldblk.intake(Path(art) / worldblk.OUT_DIR, request=os.environ.get(REQUEST_ENV, ""),
                          purpose_file=os.environ.get(PURPOSE_ENV, ""), cache_root=os.environ.get(CACHE_ENV, ""),
                          web=os.environ.get(WEB_ENV, ""), cwd=Path.cwd(), env=os.environ, now=time.time())
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
