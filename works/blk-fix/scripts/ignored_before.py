# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役を起こす前の、git が無視するファイルを控える（blk-fix の節 ignored-before。輪の前に 1 回だけ）。

cwd（対象リポジトリの根）の git ls-files --others --ignored --exclude-standard を、盤面（$ARTIFACTS_DIR/board/）の
fix-ignored-before.json に書く（core の record_ignored）。修正の後の節 clean は、これに無かった物だけを消す。
- 書けた: {"ok": true, "count", "file"} を 1 行出して 0
- ARTIFACTS_DIR が無い・空: 標準エラーに名前を出して 2
- git が効かない・書けない: 標準エラーに理由を 1 行出して 1（修正役の前で止める。控えが無いと後始末ができない）
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from accept import record_ignored  # noqa: E402
from engine.util import Reject  # noqa: E402


def main() -> int:
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    try:
        out = record_ignored(Path(artifacts) / "board", Path.cwd())
    except (Reject, OSError) as e:
        print(f"ignored-before: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
