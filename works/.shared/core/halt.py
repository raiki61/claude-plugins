"""外から止める口（線 A の仕様 5.3）。今ここに在るのは止め札だけ（標準ライブラリと写しの engine.util だけ）。

止め札は盤面の STOP（{reason, by, at} の JSON）。置くのは dev/stop.sh（人）で、見るのは境の節。見た境の節は盤面の
DiskBoard.stop(理由, by) を呼び、後ろの段を飛ばして report を必ず走らせる（a2695cf の cmd_stop と同じ意味: 理由は必須・
記録に残す・報告は出す・下流だけを走らせない）。走っている AI の節とブロックの中の出し直しの輪は次の境まで走りきる（試し P12）。

- place(board_dir, reason, by): 止め札を置く。最初の理由が正で、2 度目からは上書きせず trace にだけ積む
- seen(board_dir): 止め札の中身（無ければ None）
"""
import json
import os
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from engine.util import now  # noqa: E402

STOP_FILE = "STOP"
TRACE_OP = "stop_flag"


def _trace(board: pathlib.Path, **kw) -> None:
    """盤面の trace.jsonl に 1 行足す（DiskBoard.trace と同じ行の形 {t, op, …}）"""
    with open(board / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "op": TRACE_OP, **kw}, ensure_ascii=False) + "\n")


def place(board_dir, reason: str, by: str) -> dict:
    """止め札を置く。理由が空・空白だけなら書かずに {ok: False, reason: "理由が要る"}（by が空も同じく書かない）。
    STOP が無ければ {reason, by, at} を一時ファイルに書いてから STOP の名で出し {ok: True, first: True}。
    既に在れば上書きせず {ok: True, first: False}。どちらも trace に 1 行（op stop_flag・reason・by・first）。

    一時ファイルから出すのに os.replace でなく os.link を使う: link は「無ければ作る」を 1 手で行うので、
    2 人が同時に置いても後の方が先の理由を上書きしない（最初の理由が正）。読む側からは replace と同じく、
    STOP は無いか中身が全部在るかのどちらか"""
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        return {"ok": False, "reason": "理由が要る"}
    by = by.strip() if isinstance(by, str) else ""
    if not by:
        return {"ok": False, "reason": "止めた人（by）が要る"}
    board = pathlib.Path(board_dir)
    fd, tmp = tempfile.mkstemp(dir=board, prefix=f".{STOP_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"reason": reason, "by": by, "at": now()}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        try:
            os.link(tmp, board / STOP_FILE)
            first = True
        except FileExistsError:
            first = False
    finally:
        os.unlink(tmp)
    _trace(board, reason=reason, by=by, first=first)
    return {"ok": True, "first": first}


def seen(board_dir):
    """STOP の中身 {reason, by, at}。無ければ None。
    在るのに読めない・理由が無い（人が手で置いた等）なら、読めない旨を理由にした dict を返す——STOP を置いた人の意図は
    止めることなので、読めないからといって走り続けない"""
    path = pathlib.Path(board_dir) / STOP_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        doc = json.loads(text)
        why = None if isinstance(doc, dict) else "JSON のオブジェクトでない"
    except ValueError as e:
        doc, why = None, f"JSON として読めない（{e}）"
    if why is None and not (isinstance(doc.get("reason"), str) and doc["reason"].strip()):
        why = "理由（reason）が無い"
    if why:
        by = doc.get("by") if isinstance(doc, dict) else None
        return {"reason": f"止め札 {path} が読めない: {why}", "by": by, "at": None, "unreadable": True}
    return {"reason": doc["reason"].strip(), "by": doc.get("by"), "at": doc.get("at")}
