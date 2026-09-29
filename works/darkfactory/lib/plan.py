"""計画の段の部品（線 A の仕様 2 節・3.1。計画 Task 10a・11）。標準ライブラリと core の answer（答えの行）・gatemarks（問いの台帳の問いの答え方）だけ。

今ここに在る物:
- gate_text(asking, *, run_id): 盤面の問い（state.pending_human。写しの RL の human_gate が立てる周の途中の問い。項目には
  gatemarks が足す問いの台帳の問いも載る）を、
  人が Archon の関所 policy-gate で読む文にする（冒頭 3 行と答え方の行つき。組み立ては gatemarks.gate_text）。境の節 h-gate が
  返りの gate_text と r<N>/gate.md に使う
"""
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import answer  # noqa: E402,F401  （答えの行。組み立ては gatemarks.gate_text が引く）
import gatemarks  # noqa: E402

RUN_ID_HOLE = "<id>"   # run の id を知らない呼び手の文に入れる穴


def gate_text(asking: dict, *, run_id: str = RUN_ID_HOLE) -> str:
    """盤面の問い {node, kinds, question, items, options, in_round} を関所の文にする（組み立ては仕様の関所と同じ gatemarks.gate_text:
    冒頭 3 行（起きたこと・決めてほしいこと・推し）→ 台帳の問いへの答え方 → 問いの文の引用と読み替えの 1 行 → 項目 → 答え方）。
    答え方は起動の殻の答えの行（answer.line）で continue "<通す範囲と条件>"（一言は run の記録に残り、修正役に届く）と stop "<理由>"。
    人が決める関所なので、答えるのは依頼者（/works を回す Claude は聞いて写す）"""
    return gatemarks.gate_text(asking, run_id=run_id or RUN_ID_HOLE, node=gatemarks.GATE_NODE,
                               record_name="process.human_items")
