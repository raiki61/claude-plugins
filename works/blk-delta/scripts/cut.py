"""差分を切る節（accept.cut_delta）。修正が触った物を、審査役が読む形で盤面（$ARTIFACTS_DIR/board/）に置く:
fix.diff（修正の差分）と delta-snapshot.json（切った時の作業ツリーの写し。受け付けが突き合わせる。Ruling R3）。
出口: {"ok": true, "files": [触ったファイル], "diff_file": <fix.diff のパス>} を 1 行。
base_rev が空なら repo の HEAD（Ruling R2）。版が引けない・git が効かないときは標準エラーに理由を出して 1
（審査役を起こさずに run を止める）。環境変数が欠けたときは 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402

import script_io  # noqa: E402
from accept import Reject, cut_delta  # noqa: E402


def main() -> int:
    missing = [n for n in (script_io.BASE_REV_ENV, script_io.ARTIFACTS_ENV) if n not in os.environ]
    if script_io.ARTIFACTS_ENV not in missing and not os.environ[script_io.ARTIFACTS_ENV]:
        missing.append(script_io.ARTIFACTS_ENV)   # 空だと盤面が対象リポジトリの board/ になる
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = cut_delta(board, os.environ[script_io.BASE_REV_ENV], Path.cwd())
    except Reject as e:
        print(f"差分を切れない: {e}", file=sys.stderr)
        return 1
    script_io._emit(out)
    return 0


sys.exit(main())
