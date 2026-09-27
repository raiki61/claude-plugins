# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の返答の受け付け（blk-fix の節 fix-accept）。順は
1. check_unique_units（works だけの検査。TA25 で accept.py には足さない）: 同じ unit_key を 2 行に分けた返答を拒む
   （1 本目の決まり。写しの fix_covers_open_units は重なりを拒まない）
2. recount.accept_fix: 盤面の done("p3.fix")。写しの fix_covers_open_units が判定役の class_query を修正前の版と修正後の
   作業ツリーで数え直す（仕様 3.2）。通れば 1 本目の出口のための changes（unit_key・files・what）を足す
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が今の周の changes.json に書く）。拒んだときの changes は空。
中身の拒否は終了コード 0 の {"ok": false, "reason", "reason_file", "changes": []} を 1 行。回す側の誤りは 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import recount  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV")
DUPLICATE = "同じ unit_key を 2 行以上に分けた（直した単位ごとにちょうど 1 行。1 つの単位が複数のファイルに及ぶなら files に並べよ）: "


def check_unique_units(reply: dict) -> list:
    """changes[] に 2 度以上現れる unit_key（現れた順。空なら通す）。形の崩れは型の検査（盤面の done）に任せる"""
    rows = reply.get("changes") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return []
    seen, dup = set(), []
    for c in rows:
        k = c.get("unit_key") if isinstance(c, dict) else None
        if isinstance(k, str):
            if k in seen and k not in dup:
                dup.append(k)
            seen.add(k)
    return dup


def accept_fix(reply, board, base_rev, repo):
    dup = check_unique_units(reply)
    if dup:
        return {"ok": False, "reason": DUPLICATE + " / ".join(dup), "changes": []}
    return recount.accept_fix(reply, board, base_rev, repo)


if __name__ == "__main__":
    sys.exit(recount.main_accept(accept_fix))
