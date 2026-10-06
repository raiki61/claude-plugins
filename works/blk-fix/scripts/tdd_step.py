# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の機械の確かめ（blk-fix の節 tdd-step。輪の中で役 tdd の後。中身は tddloop.step）。

読む環境変数: INPUTS_REPLY（役 tdd の返答の JSON）・INPUTS_STATE_FILE（tdd-start の state_file）・ARTIFACTS_DIR（盤面は その下の board/）。
赤・緑は機械だけが決める（役の申告では決まらない）。段を確かめる前に、前の段の後から変わったファイルを書き込みの記録と返答の欄
bash_writes に突き合わせる（writes.check。無ければ拒む）。食い違いの申し出（phase conflict。並べの周は単位の下請けの申し出のうち確かめを通った物の全部）が通れば、盤面の控え（conflict.park）に積む。出口は {"ok", "done", "reason", "phase", "reason_file"} の 1 行と 0。
拒否の理由の本文は盤面の reject-tdd_step-<連番>.txt（script_io.emit_result）と、次の指示書（tdd-prep）に載る。
受け付けの最後の結果の控え（accept-last.json）には書かない: 輪の拒否・投げ出しは修正役への引き渡しで、run の落ちた理由ではない
（書くと後の修正役の受け付けが通っても ok 偽の行が残って次の run の prior_failures に載り、単位ごとの結果も上書きで混ざる）。
輪は done の印で抜ける（until_bash。R50）。
環境変数が欠けた・状態が読めない・輪が済んだ後に呼んだ・git が効かない: 標準エラーに 1 行出して 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

from board import BoardGap  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import querytest  # noqa: E402
import script_io  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402
from leftovers import Unreadable  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_STATE_FILE")


def main() -> int:
    missing = [n for n in INPUTS if not os.environ.get(n)]
    if missing:
        print(f"tdd-step: 環境変数が無い・空: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    try:
        reply = json.loads(os.environ["INPUTS_REPLY"])
    except ValueError:
        reply = None   # 読めない返答は step が拒む（出し直しの回数に数える）
    try:
        out = tddloop.step(os.environ["INPUTS_STATE_FILE"], reply, Path.cwd(),   # query の申し出は判定者の問いを当てて確かめる
                           try_query=lambda k, lines: querytest.judge_hits(entry.open_board(board).record["units"])(k, lines),
                           lanes=tddlanes)   # 並べの口（tddlanes が tddloop を import するので、輪には節が渡す）
        items = [i for i in [out.pop("conflict", None)] if i is not None] + (out.pop("conflicts", None) or [])
        if items:   # 止めた申し出（並べの周は単位ごとの申し出の全部）を盤面の控えと trace に積む（裁定の輪が読む）
            conflict.park(entry.open_board(board), items, source="tdd")
        out.pop("writes", None)   # 記録の無い run は輪の後の fix-accept が盤面の trace に積む（同じ worktree の同じ記録）
    except (tddloop.Broken, Unreadable, OSError, BoardGap) as e:
        print(f"tdd-step: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    return script_io.emit_result(board, "tdd_step", out, last=False)   # 輪の拒否・投げ出しは修正役への引き渡し（落ちた理由に数えない）


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
