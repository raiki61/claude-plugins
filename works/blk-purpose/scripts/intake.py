# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目的の役を起こす前の確かめ。AI を起こす前に止められる物をここで止める:

1. 盤面（$ARTIFACTS_DIR/board/）に目的の文 purpose.json が既に在れば止める（graph の p0.purpose の once）
2. INPUTS_REQUEST が指す依頼のファイル（cwd＝対象リポジトリの根からの相対か絶対）が UTF-8 の文として読めるか
3. INPUTS_CONSTRAINTS_FILE が空でなければ、前提の実測（blk-premises が置く p0.premises の返答）を読み、写しの
   p0.premises の型と post_check に通す（purpose.check_constraints）。空なら前提の実測は無い
4. 依頼が前の run の判断（欄 prior_failures）を持てば、それを外した写しを盤面の今の include の置き場の purpose-request.json に置き、
   役にはその写しのパスを渡す（ghreads.without_prior。目的の文は前の run の判断を知らない別の目の入力になるので、指示書の頼みで
   なく機械で外す）。持たない依頼（配列の形・欄の無い object・JSON でない物）は、そのパスのまま渡す
5. 目的の役を起こす前の作業ツリーの姿（accept.tree_state。HEAD・枝つき。裁定 R47）を盤面の purpose-snapshot.json に置く。
   受け付けは今の作業ツリーとこれを比べる（依頼のファイルが対象の中で未追跡でも、役が変えていなければ通る）。
   受け付けの拒否の控え（rolekit.with_done の rejects-p0.purpose.json）も同じ所で消す（前の呼び出しの拒否を数えない）

- 通れば {"ok": true, "reason": "", "request": <役に渡す依頼のパス（4 の写しか元のパス）>, "constraints_file": <前提のパス（無ければ空）>}
  を 1 行出して 0
- どれかが通らない: 標準エラーに理由を 1 行出して 1（run を AI の前で止める）
- ラインが依頼を持たずに変更から入った run（conflict.change_only）では INPUTS_REQUEST の空を受け、依頼を読まない
- 環境変数が欠けた（ARTIFACTS_DIR は空も欠け。INPUTS_REQUEST は上の run の外で空も欠け。INPUTS_CONSTRAINTS_FILE は空を「無し」と読む）:
  標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from purpose import NODE, REQUEST_COPY, SNAPSHOT_FILE, check_constraints, refuse_if_frozen, tree_state  # noqa: E402
import conflict  # noqa: E402
import ghreads  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402
import conflict  # noqa: E402
from engine.util import Reject  # noqa: E402  purpose の後（purpose を読むと写しの graphloops が sys.path に入る）

REQUEST_ENV = "INPUTS_REQUEST"
CONSTRAINTS_ENV = "INPUTS_CONSTRAINTS_FILE"
ARTIFACTS_ENV = "ARTIFACTS_DIR"


def _stop(reason: str) -> int:
    print(f"目的の役を起こさない: {' '.join(str(reason).split())}", file=sys.stderr)
    return 1


def _without_prior(text: str):
    """依頼の文から前の run の判断を外した object（外す物が無い・JSON でなければ None）"""
    try:
        return ghreads.without_prior(json.loads(text))
    except json.JSONDecodeError:
        return None


def main() -> int:
    board = Path(os.environ.get(ARTIFACTS_ENV) or ".") / "board"
    rel = os.environ.get(REQUEST_ENV, "")
    no_request = REQUEST_ENV in os.environ and not rel and conflict.change_only(board)
    missing = [n for n in (REQUEST_ENV, ARTIFACTS_ENV) if not os.environ.get(n) and not (n == REQUEST_ENV and no_request)]
    missing += [CONSTRAINTS_ENV] if CONSTRAINTS_ENV not in os.environ else []
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        refuse_if_frozen(board)
    except Reject as e:
        return _stop(str(e))
    bare = None
    try:
        if not no_request:
            bare = _without_prior((Path.cwd() / rel).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return _stop(f"依頼のファイル {rel} が読めない（{type(e).__name__}: {e}）")
    cf = os.environ[CONSTRAINTS_ENV]
    if cf:
        try:
            obj = json.loads((Path.cwd() / cf).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            return _stop(f"前提の実測のファイル {cf} が読めない（{type(e).__name__}: {e}）")
        except json.JSONDecodeError as e:
            return _stop(f"前提の実測のファイル {cf} が JSON として読めない（{e}）")
        try:
            check_constraints(obj, board)
        except Reject as e:
            return _stop(f"{cf}: {e}")
    try:
        snap = tree_state(Path.cwd())
    except (Reject, OSError) as e:
        return _stop(f"作業ツリーの写しが取れない（{e}）")
    board.mkdir(parents=True, exist_ok=True)
    rolekit.clear_rejects(board, NODE)
    own = script_io.scope_dir(board)   # 盤面の今の include の置き場（受け付けが同じ口で読む）
    own.mkdir(parents=True, exist_ok=True)
    (own / SNAPSHOT_FILE).write_text(json.dumps(snap, ensure_ascii=False) + "\n", encoding="utf-8")
    given = rel
    if bare is not None:
        copy = own / REQUEST_COPY
        copy.write_text(json.dumps(bare, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        given = str(copy.resolve())
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": True, "reason": "", "request": given, "constraints_file": cf}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
