# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""実測役の返答の受け付け。拒否も終了コード 0 で {"ok": false, "reason": …, "reason_file": …} を 1 行出す（script_io の docstring）。順:
1. check_claims（works だけの検査。裁定 TA25・計画 P1 Task 24）: 依頼の行のうち measured を持つ物（premises.claims）ごとに、
   その where を text にそのまま含む制約が在るか。無ければ拒む（依頼者の測った値を、測り直さずに判定役へ渡さない）。
   依頼の行は intake が盤面に控えた premises-request.json から読む。控えが無ければ確かめられないので拒む（fail closed）
2. premises.check_premises（作業ツリーと HEAD → 型 → 写しの measured_needs_output。通れば盤面の premises.json）
出口に輪を抜ける旗 done を足す（rolekit.with_done: 通った時か、この呼び出しの 3 回目の拒否。R50）
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import script_io  # noqa: E402
from premises import PREMISES_NODE, PREMISES_REQUEST_FILE, check_premises, claims, request_items  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV")   # 裁定 TA16: 読む INPUTS_* の組


def check_claims(reply: dict, items: list) -> list:
    """依頼の実測（measured を持つ行）のうち、where を text にそのまま含む制約が返答に無い物の where の一覧（空なら通る）。
    測り直せずに kind 仮説へ落とした制約も、where を text に含めば通る（仮説の数は collect の claims_hypothesis）"""
    cs = reply.get("constraints") if isinstance(reply, dict) else None
    texts = [c["text"] for c in cs if isinstance(c, dict) and isinstance(c.get("text"), str)] if isinstance(cs, list) else []
    return [c["where"] for c in claims(items) if not any(c["where"] in t for t in texts)]


def accept_premises(reply: dict, board: Path, base_rev: str, repo: Path) -> dict:
    items = request_items(board)
    if items is None:
        return {"ok": False, "reason": f"盤面に依頼の控え {PREMISES_REQUEST_FILE} が無い（intake が走っていない）——依頼の実測を"
                                       "測り直したかを確かめられない", "constraints_file": ""}
    missing = check_claims(reply, items)
    if missing:
        return {"ok": False, "reason": f"依頼の実測を測り直した制約が無い: {'・'.join(missing)}。text に where をそのまま入れよ"
                                       "（この作業ツリーで測り直せなければ kind: 仮説 に落とし、text に where と測れない理由を書く）",
                "constraints_file": ""}
    return check_premises(reply, board, base_rev, repo)


def with_done(out: dict) -> dict:
    return rolekit.with_done(script_io.board_dir(), PREMISES_NODE, out)


if __name__ == "__main__":
    sys.exit(script_io.main(accept_premises, finish=with_done))
