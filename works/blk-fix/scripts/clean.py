# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役が残した、git が無視するファイルを消す（blk-fix の節 clean。輪の後、テストの節の前）。

修正役はテストを回すので、__pycache__ などの git が無視する生成物を残す。差分（fix.diff）には載らないが、後のテストの節の
緑赤を左右する（自分食いの run で、バイトコードが無いことを見る試験が偽の赤になった）。盤面の fix-ignored-before.json
（節 ignored-before の控え）に無かった物だけを消す（core の remove_new_ignored。前から在った .venv などは残す）。
- 消した（0 本も含む）: {"ok": true, "removed": [消したパス]} を 1 行出して 0。collect が出口に並べて人に見せる
- ARTIFACTS_DIR が無い・空: 標準エラーに名前を出して 2
- 控えが無い・読めない・git が効かない・消せない: 標準エラーに理由を 1 行出して 1（生成物の残る木でテストを回さない）
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from accept import remove_new_ignored  # noqa: E402
from engine.util import Reject  # noqa: E402


def main() -> int:
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    try:
        out = remove_new_ignored(Path(artifacts) / "board", Path.cwd())
    except (Reject, OSError) as e:
        print(f"clean: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
