# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""依頼の受け付け。INPUTS_REQUEST が指す JSON のファイル（cwd＝対象リポジトリの根からの相対か絶対。findings の配列か
{findings, pr, issue} の形を carry.parts で解く）を読み、findings を check_request（graphloops の add と同じ規則）に通して盤面（$ARTIFACTS_DIR/board/）の request.json に積む。
続けて、判定役を起こす前の作業ツリーの姿（共通の tree_state。HEAD と枝も持つ。R47）を盤面の judge-snapshot.json に置く。受け付け（check_judge）は
これと今の作業ツリーを比べる（Ruling R14。依頼のファイルが対象の中で未追跡でも、判定役が変えていなければ通る）。
写しを置くのと同じ所で、盤面に前の呼び出しが残した judgment.json を消す——受け付けが 3 回とも拒んだ時に collect が
古い判定を拾って ok を出さないように。

- 通れば {"ok": true, "reason": "", "request": <読んだパス>} を 1 行出して 0
- ラインが依頼を持たずに変更から入った run（conflict.change_only）では INPUTS_REQUEST の空を受け、依頼を積まずに写しだけを置く
  （request は空。判定役は素材の欄で差分を読む）
- ファイルが読めない・JSON として読めない・規則が拒む・作業ツリーの写しが取れない: 標準エラーに理由を 1 行出して 1（run を AI の前で止める）
- 環境変数が欠けた（ARTIFACTS_DIR は空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

import conflict  # noqa: E402
import script_io  # noqa: E402

from accept import JUDGE_SNAPSHOT_FILE, JUDGMENT_FILE, check_request, tree_state  # noqa: E402
from engine.util import Reject  # noqa: E402
import carry  # noqa: E402  （次の run への持ち越しの形の住処。依頼の容器を解く）

REQUEST_ENV = "INPUTS_REQUEST"
ARTIFACTS_ENV = "ARTIFACTS_DIR"


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _stop(reason: str) -> int:
    print(f"依頼を受け付けない: {_one_line(reason)}", file=sys.stderr)
    return 1


def main() -> int:
    board = Path(os.environ.get(ARTIFACTS_ENV) or ".") / "board"
    rel = os.environ.get(REQUEST_ENV, "")
    no_request = REQUEST_ENV in os.environ and not rel and conflict.change_only(board)
    missing = [n for n in (REQUEST_ENV, ARTIFACTS_ENV) if not os.environ.get(n) and not (n == REQUEST_ENV and no_request)]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not no_request:
        path = Path.cwd() / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return _stop(f"依頼のファイル {rel} が読めない（{type(e).__name__}: {e}）")
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            return _stop(f"依頼のファイル {rel} が JSON として読めない（{e}）")
        try:
            items = carry.parts(doc)[carry.FINDINGS]
        except ValueError as e:
            return _stop(f"依頼のファイル {rel} の形: {e}")
        r = check_request(items, board, f"人の依頼（{rel}）")
        if not r["ok"]:
            return _stop(f"{rel}: {r['reason']}")
    try:
        snap = tree_state(Path.cwd())
    except (Reject, OSError) as e:
        return _stop(f"作業ツリーの写しが取れない（{e}）")
    (board / JUDGMENT_FILE).unlink(missing_ok=True)   # 前の呼び出しの残り。collect が拾えるのはこの呼び出しの受け付けが書いた物だけ
    own = script_io.scope_dir(board)   # 盤面の今の include の置き場（受け付けの check_judge が同じ口で読む）
    own.mkdir(parents=True, exist_ok=True)
    (own / JUDGE_SNAPSHOT_FILE).write_text(json.dumps(snap, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": True, "reason": "", "request": rel}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
