# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""依頼の型の確かめと、作業ツリーの写し。INPUTS_REQUEST が指す JSON のファイル（cwd＝対象リポジトリの根からの相対か絶対。findings の配列か
{findings, pr, issue} の形を request_parts で解く）を読み、findings を check_request（graphloops の add と同じ規則）に使い捨ての置き場で通す——盤面の request.json には積まない（積むのは判定の
ブロックの intake だけ。ここで積むと同じ依頼が 2 度積まれる）。続けて、実測役を起こす前の作業ツリーの姿（共通の tree_state。バイトコードは除く）を
盤面の premises-snapshot.json に置く。受け付け（check_premises）はこれと今の作業ツリーを比べる。型を確かめた依頼の行は
premises-request.json に控える（受け付けの check_claims と collect が依頼の measured の行を読む）。
何より先に（盤面が止まっていても）、盤面に前の呼び出しが残した premises.json を消す——受け付けが 3 回とも拒んだ時に collect が
古い制約を拾って ok を出さないように（graphloops の once の『凍った出力の再利用』は線 A の b.done から付く。ここでは作らない）。
受け付けの拒否の控え（rolekit.with_done の rejects-p0.premises.json）も同じ所で消す（前の呼び出しの拒否を数えない）。
ラインの盤面がもう止まっていれば（前のブロック——並行 PR の任せ先——が諦めて止めた）、残りを消した後は何もせずに go: false を出す
（輪は when で飛び、実測役を起こさない。collect が ok: false の出口を組む）。

- 通れば {"ok": true, "reason": "", "request": <読んだパス>, "go": true} を 1 行出して 0
- ファイルが読めない・JSON として読めない・規則が拒む・作業ツリーの写しが取れない: 標準エラーに理由を 1 行出して 1（run を AI の前で止める）
- 環境変数が欠けた（ARTIFACTS_DIR は空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

from accept import check_request, tree_state  # noqa: E402
from engine.util import Reject  # noqa: E402
from ghreads import request_parts  # noqa: E402
from premises import PREMISES_FILE, PREMISES_NODE, PREMISES_REQUEST_FILE, PREMISES_SNAPSHOT_FILE  # noqa: E402
import conflict  # noqa: E402
import rolekit  # noqa: E402
import conflict  # noqa: E402

REQUEST_ENV = "INPUTS_REQUEST"
INPUTS = (REQUEST_ENV,)   # 裁定 TA16: 読む INPUTS_* の組
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
    board.mkdir(parents=True, exist_ok=True)
    (board / PREMISES_FILE).unlink(missing_ok=True)   # 前の呼び出しの残り。collect が拾えるのはこの呼び出しの受け付けが書いた物だけ（止まった盤面でも）
    rolekit.clear_rejects(board, PREMISES_NODE)
    stopped = rolekit.line_stopped(board)
    if stopped:
        return _emit({"ok": True, "reason": f"盤面が止まっている（{_one_line(stopped)}）——実測役を起こさない", "request": rel,
                      "go": False})
    items = []   # 変更から入った run の空の依頼（実測する依頼の行が無い）
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
            items = request_parts(doc)["findings"]
        except ValueError as e:
            return _stop(f"依頼のファイル {rel} の形: {e}")
        with tempfile.TemporaryDirectory() as scratch:   # 規則に通すだけ。積んだ request.json は捨てる
            r = check_request(items, Path(scratch), f"人の依頼（{rel}）")
        if not r["ok"]:
            return _stop(f"{rel}: {r['reason']}")
    try:
        snap = tree_state(Path.cwd(), bytecode=False)
    except (Reject, OSError) as e:
        return _stop(f"作業ツリーの写しが取れない（{e}）")
    (board / PREMISES_SNAPSHOT_FILE).write_text(json.dumps(snap, ensure_ascii=False) + "\n", encoding="utf-8")
    (board / PREMISES_REQUEST_FILE).write_text(json.dumps(items, ensure_ascii=False) + "\n", encoding="utf-8")   # 受け付けの check_claims が読む
    return _emit({"ok": True, "reason": "", "request": rel, "go": True})


def _emit(out: dict) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
