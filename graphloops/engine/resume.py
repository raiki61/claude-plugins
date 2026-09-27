"""init --stop-after-round N で止めた run を、次の周へ進める口（loop.py resume）。

止め（suspend）と再開（resume）を対にする形は Argo Workflows の suspend / `argo resume` と同じ。受けるのは周の数で止めた run
（halted.by が stop_after_round）だけで、人が止めた run（answer stop・loop.py stop）と無人の規則が止めた run は受けない
——それは Argo の stop / terminate に当たり、続ける対象でない。周を開くのは既存の唯一の口 advance.open_next_round。
新しい止め周を必須にする（今の N のままだと開いた直後に止まり、止め時が曖昧になる）。回し手（loop.py run）はこの口を打たない。
"""
from .advance import open_next_round
from .board import Board
from .util import Reject, dump, now


def cmd_resume(a, d):
    """d は盤面の置き場（入口が解決して渡す）。痕跡は state.resumes（finalize が記録の process.resumes に写す）と trace"""
    reason = (a.reason or "").strip()
    if not reason:
        raise Reject("続ける理由が空——--reason に、なぜ次の周へ進めるかを書け（盤面と記録に残る）")
    if (a.stop_after_round is None) == (not a.no_stop_after_round):
        raise Reject("次の止め周を 1 つ決めよ: --stop-after-round N（今の周より大きい N）か --no-stop-after-round（止めずに回す）のどちらか 1 つ")
    b = Board(d)
    h = b.state.get("halted") or {}
    if h.get("by") != "stop_after_round":
        why = f"halted.by が {h.get('by')}" if h else "止まっていない"
        raise Reject(f"続けられるのは init --stop-after-round で止めた run だけ（{why}）——人や無人の規則が止めた run は続けない。"
                     "新しい run で始めよ")
    n = a.stop_after_round
    if n is not None and n <= b.round:
        raise Reject(f"--stop-after-round {n} は今の周（{b.round}）以下——次に止める周は {b.round + 1} 以上")
    b.allow_halted = True
    b.state.setdefault("resumes", []).append({"at": now(), "round": b.round, "reason": reason, "prev_halted": h,
                                              "prev_stop_after_round": b.state.get("stop_after_round"), "stop_after_round": n})
    b.state.pop("halted")
    b.state["status"] = "running"
    if n is None:
        b.state.pop("stop_after_round", None)
    else:
        b.state["stop_after_round"] = n
    if not open_next_round(b, h.get("node")):
        raise Reject("次の周を開けなかった（止め周の検査が今の周で止めた）——盤面は書いていない")
    b.trace("resume", round=b.round, reason=reason, stop_after_round=n)
    b.save()
    print(dump({"resumed": {"round": b.round, "stop_after_round": n, "reason": reason},
                "how": "次の周を開いた。続きは loop.py run（か next）"}))
