"""計画の段の部品（線 A の仕様 2 節・3.1。計画 Task 10a・11）。標準ライブラリと core の answer（答えの行）だけ。

今ここに在る物:
- gate_text(asking, *, run_id): 盤面の問い（state.pending_human。写しの RL の human_gate が立てる周の途中の問い）を、
  人が Archon の関所 policy-gate で読む文にする（答え方の 1 行つき）。境の節 h-gate が返りの gate_text と r<N>/gate.md に使う
"""
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import answer  # noqa: E402

RUN_ID_HOLE = "<id>"   # run の id を知らない呼び手の文に入れる穴


def gate_text(asking: dict, *, run_id: str = RUN_ID_HOLE) -> str:
    """盤面の問い {node, kinds, question, items, options, in_round} を関所の文にする。項目は 1 行ずつ、問いの文と種類はそのまま。
    最後に答え方: 起動の殻の答えの行（answer.line）で continue "<通す範囲と条件>"（一言は記録の process.human_items に残り、
    修正役に届く）と stop "<理由>"。人が決める関所なので、答えるのは依頼者（/works を回す Claude は聞いて写す）"""
    if not isinstance(asking, dict):
        raise TypeError(f"盤面の問いが dict でない: {type(asking).__name__}")
    kinds = [str(k) for k in asking.get("kinds") or []]
    items = [str(x) for x in asking.get("items") or []]
    rid = run_id or RUN_ID_HOLE
    lines = [f"修正の前の関所（盤面の問い {asking.get('node') or '（節の名が無い）'}・種類: {'・'.join(kinds) or '（無し）'}）", ""]
    lines += [str(asking.get("question") or "（問いの文が無い）"), "", f"項目（{len(items)} 件）:"]
    lines += [f"- {x}" for x in items] or ["- （無し）"]
    lines += ["", "答え方（人が決める関所。依頼者に聞いて、その言葉で答える）:",
              f"- 通す: {answer.line(rid, 'continue', '<通す範囲と条件>')}"
              "（一言は記録の process.human_items に残り、修正役に届く）",
              f"- 止める: {answer.line(rid, 'stop', '<理由>')}（報告は出る）"]
    return "\n".join(lines) + "\n"
