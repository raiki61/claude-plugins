"""計画の段の部品（線 A の仕様 2 節・3.1。計画 Task 10a・11）。標準ライブラリだけ。

今ここに在る物:
- gate_text(asking, *, run_id): 盤面の問い（state.pending_human。写しの RL の human_gate が立てる周の途中の問い）を、
  人が Archon の関所 policy-gate で読む文にする（答え方の 1 行つき）。境の節 h-gate が返りの gate_text と r<N>/gate.md に使う
"""

RUN_ID_HOLE = "<id>"   # run の id を知らない呼び手の文に入れる穴


def gate_text(asking: dict, *, run_id: str = RUN_ID_HOLE) -> str:
    """盤面の問い {node, kinds, question, items, options, in_round} を関所の文にする。項目は 1 行ずつ、問いの文と種類はそのまま。
    最後に答え方: `archon workflow respond <id> continue "<通す範囲と条件>"`（一言は記録の process.human_items に残り、修正役に届く）・
    `archon workflow respond <id> stop "<理由>"`・`archon workflow reject <id> --reason "<理由>"`（stop と同じ）。
    approve は continue と、reject は stop と同じに扱う（台帳 R32）"""
    if not isinstance(asking, dict):
        raise TypeError(f"盤面の問いが dict でない: {type(asking).__name__}")
    kinds = [str(k) for k in asking.get("kinds") or []]
    items = [str(x) for x in asking.get("items") or []]
    rid = run_id or RUN_ID_HOLE
    lines = [f"修正の前の関所（盤面の問い {asking.get('node') or '（節の名が無い）'}・種類: {'・'.join(kinds) or '（無し）'}）", ""]
    lines += [str(asking.get("question") or "（問いの文が無い）"), "", f"項目（{len(items)} 件）:"]
    lines += [f"- {x}" for x in items] or ["- （無し）"]
    lines += ["", "答え方（approve は continue と、reject は stop と同じ）:",
              f'- 通す: archon workflow respond {rid} continue "<通す範囲と条件>"'
              "（一言は記録の process.human_items に残り、修正役に届く）",
              f'- 止める: archon workflow respond {rid} stop "<理由>"'
              f'（archon workflow reject {rid} --reason "<理由>" でも止まる。報告は出る）']
    return "\n".join(lines) + "\n"
