#!/usr/bin/env python3
"""graphloops の入口。中身は engine/（実行基盤。ループの中身を知らない）にある。

使い方（回す側が呼ぶ順）:
    loop.py init   --loop research-loop --request @依頼.md [--document 文書] [--input k=v ...] [--thickness 標準]
                   [--decider <graph の thickness.deciders の値>] [--unattended] [--stop-after-round N] [--dir <置き場>] [--validator <path>]
    loop.py next   [--dir] [--accept-tree-change 理由]   # 走らせてよい節をプロンプトごと JSON で返す（何度呼んでもよい。P1 後の作業ツリー突合を自分の変更として通すときは理由を添える）
    loop.py launch [--node <節>] [--dir]                # launch を持つ節（役・走らせるだけの engine_run）を engine が起こし、返答を置き場へ書いて受け付けまで済ませる（背景実行に回し、手番を終えずに前景で出力を見に行く）
    loop.py done   --node <節[鍵]> (--output <返答.json> | --stdin | 置き場 out_path) [--agent-id <id>] [--accept-tree-change 理由]
    loop.py skip   --node <節> --reason <理由>          # optional の節を省く（報告に「省略」と載る）
    loop.py answer --text <答え> [--note <本文>]         # 人に聞く番のとき（本文は次の周の再審に渡る）
    loop.py thicken --to <段> --reason <理由>           # 段の昇格（降格は不可。段名は graph の thickness.tiers）
    loop.py add    --file <items.json> --reason <理由>   # ループの外で得たものを記録へ（rules の add が受ける）
    loop.py patch  --path <record の欄 | state.<盤面の欄>> --file <json> --reason   # 記録（既定）か盤面の手当て（痕跡が残る最終手段）
    loop.py status [--dir] / loop.py record [--dir] / loop.py finalize [--dir]
    loop.py allow-checks [--note <誰が何を見て承認したか>]   # 人が打つ: 対象リポジトリの宣言（.review-checks.json）を承認する

置き場（--dir 省略時）: `$(git rev-parse --git-dir)/graphloops/<loop>/<run-id>/`。作業ツリーの外
（`git status --porcelain` に映らない）で、リポジトリごとに残る。`current` がいちばん新しい run を指す。

終了コード: 0 = 受け付けた / 1 = 受け付けない（返答が型に合わない・節が待ち状態でない等。直して
呼び直す） / 2 = 盤面・グラフ・引数が読めない
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

from engine import commands as c  # noqa: E402
from engine.role_run import StopSignal, install_stop_handlers  # noqa: E402
from engine.util import BoardConflict, Reject, die  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--loop", default="research-loop")
    s.add_argument("--graph")
    s.add_argument("--request", required=True, help="依頼文（@file で読む）")
    s.add_argument("--document", help="対象の文書")
    s.add_argument("--input", action="append", help="ループ固有の入力 k=v（何度でも）")
    s.add_argument("--thickness", help="段（graph の thickness.tiers のどれか）")
    s.add_argument("--decider", help="段を誰が決めたか（graph の thickness.deciders の default か downgrade）")
    s.add_argument("--unattended", action="store_true")
    s.add_argument("--stop-after-round", type=int, help="この周の締め（記録・収束の判定）の後で、次の周を開かずに止める（1 以上）")
    s.add_argument("--dir")
    s.add_argument("--validator")
    s.add_argument("--lang")
    s.set_defaults(fn=c.cmd_init)

    for name, fn in (("next", c.cmd_next), ("status", c.cmd_status), ("record", c.cmd_record), ("finalize", c.cmd_finalize)):
        s = sub.add_parser(name)
        s.add_argument("--dir")
        s.set_defaults(fn=fn)
    sub.choices["next"].add_argument("--accept-tree-change", help="P1 の前後の作業ツリー突合が『変わっている』と止めたとき、自分の変更なら理由を添えて通す（痕跡は process.git_mismatches）")

    s = sub.add_parser("launch")
    s.add_argument("--dir")
    s.add_argument("--node", help="1 節だけ起こす（省くと、いま起こせる launch を持つ節を全部並列に起こす）")
    s.set_defaults(fn=c.cmd_launch)

    s = sub.add_parser("relaunch", help="待っている instance を起こし直す（新しい試行を書いてから、engine が起こした前の試行の子を木ごと止める。試行の回数と理由を盤面と trace に残す）")
    s.add_argument("--dir")
    s.add_argument("--node", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_relaunch)

    s = sub.add_parser("done")
    s.add_argument("--dir")
    s.add_argument("--node", required=True)
    s.add_argument("--output")
    s.add_argument("--stdin", action="store_true", help="返答を標準入力で渡す（明示したときだけ読む——閉じないパイプで止まらないため）")
    s.add_argument("--agent-id", help="役の agent の id（同じ agent を続ける節のために残す）")
    s.add_argument("--accept-tree-change")
    s.set_defaults(fn=c.cmd_done)

    s = sub.add_parser("skip")
    s.add_argument("--dir")
    s.add_argument("--node", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_skip)

    s = sub.add_parser("answer")
    s.add_argument("--dir")
    s.add_argument("--text", required=True)
    s.add_argument("--note", help="人の答えの本文（次の周の再審に渡る）")
    s.set_defaults(fn=c.cmd_answer)

    s = sub.add_parser("thicken")
    s.add_argument("--dir")
    s.add_argument("--to", required=True, help="上げる先の段（graph の thickness.tiers のどれか。engine が下げる向きを拒む）")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_thicken)

    s = sub.add_parser("add")
    s.add_argument("--dir")
    s.add_argument("--file", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_add)

    s = sub.add_parser("patch")
    s.add_argument("--dir")
    s.add_argument("--path", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_patch)

    s = sub.add_parser("allow-checks", help="人が打つ: リポジトリのルートの .review-checks.json の中身を承認する（engine は承認した中身の語だけを走らせる）")
    s.add_argument("--note", default="", help="誰が何を見て承認したか（承認の一覧に残る）")
    s.set_defaults(fn=c.cmd_allow_checks)

    a = p.parse_args()
    install_stop_handlers()   # 全コマンド——next・done の builtin も子（テスト一式）を起こす
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except Reject as e:
        die(str(e), 1)
    except BoardConflict as e:
        die(e.msg, 2)
    except StopSignal as e:
        sys.exit(128 + e.signum)   # 生きている子は信号の口（kill_all）が止めてある
    except SystemExit:
        raise
    except Exception as e:  # 契約: 想定外は 2（盤面が読めない側）に倒す
        die(f"想定外の例外（{type(e).__name__}）: {e}")
