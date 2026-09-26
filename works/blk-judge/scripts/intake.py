"""依頼の受け付け。INPUTS_REQUEST が指す JSON のファイル（cwd＝対象リポジトリの根からの相対か絶対）を読み、
check_request（graphloops の add と同じ規則）に通して盤面（$ARTIFACTS_DIR/board/）の request.json に積む。

- 通れば {"ok": true, "reason": "", "request": <読んだパス>} を 1 行出して 0
- ファイルが読めない・JSON として読めない・規則が拒む: 標準エラーに理由を 1 行出して 1（run を AI の前で止める）
- 環境変数が欠けた（ARTIFACTS_DIR は空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from accept import check_request  # noqa: E402

REQUEST_ENV = "INPUTS_REQUEST"
ARTIFACTS_ENV = "ARTIFACTS_DIR"


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _stop(reason: str) -> int:
    print(f"依頼を受け付けない: {_one_line(reason)}", file=sys.stderr)
    return 1


def main() -> int:
    missing = [n for n in (REQUEST_ENV, ARTIFACTS_ENV) if not os.environ.get(n)]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    rel = os.environ[REQUEST_ENV]
    path = Path.cwd() / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return _stop(f"依頼のファイル {rel} が読めない（{type(e).__name__}: {e}）")
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        return _stop(f"依頼のファイル {rel} が JSON として読めない（{e}）")
    board = Path(os.environ[ARTIFACTS_ENV]) / "board"
    r = check_request(items, board, f"人の依頼（{rel}）")
    if not r["ok"]:
        return _stop(f"{rel}: {r['reason']}")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": True, "reason": "", "request": rel}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
