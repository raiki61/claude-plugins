# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""blk-pr の節 pr-accept: 任せ先の役 pr-check の返答を受け付ける（rolekit.main_accept に take を渡す。拒否は理由の本文を
盤面の reject-take_p0_parallel_pr-<連番>.txt に書き、この周の拒否の控えに積み、3 回目の拒否で done・give_up。R50）。take の順は
1. check_no_post（works だけの検査。TA25 で accept.py には足さない）: conflicts[].handed_over が真の行が在れば拒む
   （このラインは担当の PR へ申し送りを投稿しない。持ち主の決定 2026-09-27: 案 (a)）
2. prcheck.take: 読むだけの役が作業ツリーを変えていないか → 盤面の done（写しの schema と規則）
中身の拒否は終了コード 0 の 1 行（reason_file つき。指示書は reason_file だけを $LOOP_PREV で差し込む）。回す側の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))
import prcheck  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_REPLY",)
NO_POST = "このラインは申し送りを投稿しない（持ち主の決定 2026-09-27）。下書きを note に書き handed_over を false にせよ: "


def check_no_post(reply: dict) -> list:
    """conflicts[].handed_over が真の行の pr の一覧（空なら通す）。形の崩れは型の検査（盤面の done）に任せる"""
    rows = reply.get("conflicts") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        return []
    return [str(c.get("pr")) for c in rows if isinstance(c, dict) and c.get("handed_over")]


def take(board, reply: dict, repo) -> dict:
    posted = check_no_post(reply)
    if posted:
        return {"ok": False, "reason": NO_POST + ", ".join(posted)}
    return prcheck.take(board, reply, repo)


def main() -> int:
    return rolekit.main_accept(prcheck.NODE, reply_env=INPUTS[0], take=take)


if __name__ == "__main__":
    sys.exit(main())
