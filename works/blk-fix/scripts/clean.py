# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役が残した、git が無視するファイルを消す（blk-fix の節 clean。輪の後、テストの節の前）。

修正役はテストを回すので、__pycache__ などの git が無視する生成物を残す。差分（fix.diff）には載らないが、後のテストの節の
緑赤を左右する（自分食いの run で、バイトコードが無いことを見る試験が偽の赤になった）。盤面の fix-ignored-before.json
（節 ignored-before の控え）に無かった物だけを消す（leftovers の remove_new_ignored。前から在った .venv などの中身と、前から
在ったフォルダは残す）。控えと消した物のファイルは盤面の今の scope の根の物（2 回目の修正の段の include は 1 回目の物を上書きしない）。
- 消した（0 本も含む）: 全件を盤面の fix-removed.json に書き、{"ok": true, "count": 件数, "file": そのパス} を 1 行出して 0。
  stdout の大きさは件数によらない（実行器は出力の上限を越えた子を殺す）。collect が件数とファイルを出口に通す
- ARTIFACTS_DIR が無い・空: 標準エラーに名前を出して 2
- 控えが無い・読めない・git が効かない・消せない: 標準エラーに理由を 1 行出して 1（生成物の残る木でテストを回さない）
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
import json  # noqa: E402
import os  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
from leftovers import Unreadable, remove_new_ignored  # noqa: E402   .shared/core の模块（V13）

INPUTS = ()   # 読む入力は無い（置き場は今の scope の根。script_io.scope_dir）


def main() -> int:
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        print("環境変数が無い: ARTIFACTS_DIR", file=sys.stderr)
        return 2
    try:
        out = remove_new_ignored(Path(artifacts) / "board", Path.cwd())
    except (Unreadable, OSError, ValueError) as e:   # ValueError は include の名が scope の決まりに外れる（script_io.scope_dir）
        print(f"clean: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
