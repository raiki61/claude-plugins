"""同じ run の中の案の直し（依頼 226）。裁定 fix_plan_item の単位は次の run へ持ち越さず、同じ run の中で案に戻す。
直しを終えられなかった単位の道は 1 本だけ: 待つ行（conflict の状態 WAITING）を諦めた行（GAVE_UP）にし、ask_human の道
（conflict.asked・human_lines。最後の関所と次の run の依頼に裁定の文を字のまま載せる）に合流させる。

- STOP_BY: この模块が盤面を止める時の by
- CLOSE_WHY・HALTED_WHY: 諦めた理由（conflict.REPLAN_WHY に置く。HALTED_WHY は止まった盤面で締める時で、by・reason は盤面の止めの物）
- UNSETTLED: 締めた後に待つ行が残った時の BoardGap の文
- close(b, why): 待つ行の全部を諦めた行にし、id を返す（待つ行が無ければ何もせず []）
- close_at(board_dir): 盤面を allow_halted で開き、止まっていれば HALTED_WHY、そうでなければ CLOSE_WHY で close。何度呼んでも
  同じ（2 度目は待つ行が無い）。報告の組み立ては必ず走るので、修正の段が落ちて h-rejudge が飛ばされた run でも待つ行が落ちない
- HAND_REFUSED: 1 回目に受け付けた返答の控えを盤面が受けない時の止めの文
- hand_held(board_dir, repo): 盤面が止まっておらず、今の周の p3.fix を受けておらず、1 回目に受け付けた返答の控え
  （conflict.held_reply。待つ単位が在る間に修正の受け付けが盤面に渡さずに置いた物）が在れば、bash_writes を外した控えを
  recount.accept_fix で盤面に渡して真。盤面が受けなければ盤面を止めて（HAND_REFUSED・by STOP_BY）偽。渡す物が無ければ偽
- settle(board_dir, repo): h-rejudge の頭で呼ぶ。1. close_at。2. hand_held。3. 待つ行が残れば BoardGap(UNSETTLED)。
  返り {"closed": [id…], "handed": hand_held の返り}

層 L3。entry・conflict・recount を読み、report と blk の lib は import しない（report がこの模块を呼ぶ向きだけ）。期限・回数の上限は持たない。
"""
from __future__ import annotations

import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import conflict  # noqa: E402
import entry  # noqa: E402
import recount  # noqa: E402
import writes  # noqa: E402
from board import BoardGap  # noqa: E402

STOP_BY = "works:replan"
CLOSE_WHY = "同じ run の中で案の直しを終えられなかった（案の段に戻るのは 1 run に 1 回）"
HALTED_WHY = "run が止まった（{by}: {reason}）ので、案の直しを終えなかった"
UNSETTLED = "案の直しを待つ単位を残したまま修正の段を抜けようとした: {ids}"
HAND_REFUSED = "1 回目に受け付けた修正の返答を盤面が受けない: {reason}"
_ENDED_BY = "stop_after_round"   # 1 周の run が周を締めた盤面の halted.by（普通の終わりで、止めたと読まない）


def close(b, why: str) -> list[str]:
    """待つ行（conflict.waiting）の全部を諦めた行（GAVE_UP・理由 why）にし、その id を返す。待つ行が無ければ何もせず []"""
    ids = [r["id"] for r in conflict.waiting(b)]
    if ids:
        conflict.set_replan(b, ids, conflict.GAVE_UP, why=why)
    return ids


def _stop_of(b) -> dict | None:
    """盤面の止め（state.stop か、周の締めでない state.halted）。止まっていなければ None"""
    st = b.state
    if st.get("stop"):
        return st["stop"]
    halted = st.get("halted") or {}
    return halted if halted and halted.get("by") != _ENDED_BY else None


def close_at(board_dir) -> list[str]:
    """盤面を allow_halted で開き、止まっていれば HALTED_WHY（盤面の止めの by・reason）、そうでなければ CLOSE_WHY で close"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    stop = _stop_of(b)
    why = HALTED_WHY.format(by=stop.get("by") or "", reason=stop.get("reason") or "") if stop else CLOSE_WHY
    return close(b, why)


def hand_held(board_dir, repo) -> bool:
    """1 回目に受け付けた返答の控えを盤面に渡す。盤面が止まっている・今の周の p3.fix を受けた（held_reply が None）・控えが
    無いなら何もせず偽。渡して盤面が受ければ真、受けなければ盤面を止めて（by STOP_BY）偽。何度呼んでも渡すのは 1 度"""
    board_dir = pathlib.Path(board_dir)
    b = entry.open_board(board_dir, allow_halted=True)
    if b.state.get("stop") or b.state.get("halted"):   # 周の締めの halted も（盤面はもう返答を受けない）
        return False
    held, _ = conflict.held_reply(b)
    if held is None:
        return False
    reply = {k: v for k, v in held.items() if k != writes.FIELD}
    out = recount.accept_fix(reply, board_dir, "", pathlib.Path(repo))
    if out.get("ok") is True:
        return True
    reason = " ".join(str(out.get("reason") or "").split())
    entry.open_board(board_dir, allow_halted=True).stop(HAND_REFUSED.format(reason=reason), by=STOP_BY)
    return False


def settle(board_dir, repo) -> dict:
    """h-rejudge の頭（修正の段を抜ける所）の締め。待つ行を諦めた行にし、1 回目に受け付けた返答の控えを盤面に渡し
    （hand_held）、それでも待つ行が残れば BoardGap（UNSETTLED）"""
    closed = close_at(board_dir)
    handed = hand_held(board_dir, repo)
    left = conflict.waiting(entry.open_board(pathlib.Path(board_dir), allow_halted=True))
    if left:
        raise BoardGap(UNSETTLED.format(ids="、".join(r["id"] for r in left)))
    return {"closed": closed, "handed": handed}
