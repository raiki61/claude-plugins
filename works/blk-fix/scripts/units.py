# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""並べた項目を締める（blk-fix の節 fix-units。修正の輪の中で役 fix の後・受け付け fix-accept の前。依頼 243 の並べ。中身は unitlanes.settle）。

修正役の支度（fix-prep）が範囲の重ならない項目に単位の worktree を切った周だけ働く（控えは盤面の今の周の作業ファイル
fixrules.UNITS_FILE）。修正役が当てるコマンドを走らせなかった項目は機械が run の作業ツリーへ当て、当てた項目の単位の worktree での
書き込みの記録を run の作業ツリーへ写し（writes.carry。受け付けが下請けの Edit を記録の無い変更と読まないように）、当たらなかった
項目の差分を盤面の作業ファイル fixrules.UNITS_KEPT の下に残し、単位の worktree を片付ける。盤面の trace に fixrules.UNITS_OP の
1 行を残す。受け付けの決まりは変えず、受け付けは当てた後の作業ツリーを見る。
- 控えが無い（並べなかった周・済んだ控え）: {"ok": true, "ran": false} を 1 行出して 0
- 締めた: {"ok": true, "ran": true, applied, machine, conflict, unmerged, carried} を 1 行出して 0（当たらない項目が在っても run は
  止めない。直しは盤面に残り、その単位の変更の欠けは受け付けが見る）
- 環境変数の欠け・盤面が開けない・git が効かない: 標準エラーに 1 行出して 2（rolekit.script_main）
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import entry  # noqa: E402
import fixrules  # noqa: E402
import rolekit  # noqa: E402
import unitlanes  # noqa: E402
import writes  # noqa: E402

INPUTS = ()   # 読む入力は無い（控えは盤面の今の周の作業ファイル）


def run(board, repo, env):
    b = entry.open_board(Path(board))
    out = unitlanes.settle(b.work(fixrules.UNITS_FILE), repo, writes.sink(repo), b.work(fixrules.UNITS_KEPT))
    if out.get("ran"):
        b.trace(fixrules.UNITS_OP, node="fix-units", **{k: v for k, v in out.items() if k != "ran"})
    return {"ok": True, **out}


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
