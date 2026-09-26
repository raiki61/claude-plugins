#!/usr/bin/env python3
"""graphloops の入口。中身は engine/（実行基盤。ループの中身を知らない）にある。

使い方（回す側が呼ぶ順）:
    loop.py init   --loop research-loop --request @依頼.md [--document 文書] [--input k=v ...] [--thickness 標準]
                   [--decider <graph の thickness.deciders の値>] [--unattended] [--stop-after-round N] [--dir <置き場>] [--validator <path>]
                   [--unfenced-delegates <理由>]   # 任せ先を sandbox で縛らない（人が明示したときだけ）
    loop.py next   [--dir] [--accept-tree-change 理由]   # 走らせてよい節をプロンプトごと JSON で返す（何度呼んでもよい。P1 後の作業ツリー突合を自分の変更として通すときは理由を添える）
    loop.py launch [--node <節>] [--dir]                # launch を持つ節（役・任せ先・走らせるだけの engine_run）を engine が起こし、返答を置き場へ書いて受け付けまで済ませる（背景実行に回し、手番を終えずに前景で出力を見に行く。任せ先は sandbox の中）
    loop.py done   --node <節[鍵]> (--output <返答.json> | --stdin | 置き場 out_path) [--agent-id <id>] [--accept-tree-change 理由]
    loop.py skip   --node <節> --reason <理由>          # optional の節を省く（報告に「省略」と載る）
    loop.py answer --text <答え> [--note <本文>] [--detail <json>]  # 人に聞く番のとき（本文は次の周の再審に渡る。--detail は rules が受ける構造の値）
    loop.py stop   --reason <理由>                       # 走っている run を人がその時点で止める（理由は記録に残り、graph が宣言する後始末の節——報告——だけが走る）
    loop.py thicken --to <段> --reason <理由>           # 段の昇格（降格は不可。段名は graph の thickness.tiers）
    loop.py add    --file <items.json> --reason <理由>   # ループの外で得たものを記録へ（rules の add が受ける）
    loop.py patch  --path <[record.]記録の欄 | state.<盤面の欄>> (--file <json> | --delete) --reason   # 記録（既定）か盤面の手当て——書くか消す（痕跡が残る最終手段）
    loop.py status [--dir] / loop.py record [--dir] / loop.py finalize [--dir]
    loop.py intake (--what <1 行> [--dir] | --export <file> [--all] [--with-stderr] | --send | --set-url <URL>) [--data-dir]
                                                     # 踏んだ問題を利用者の環境に残す手の口（非 0 の終わりは engine が自動で残す）

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
from engine import intake, util  # noqa: E402
from engine.role_run import StopSignal, install_stop_handlers  # noqa: E402
from engine.util import BoardConflict, Reject, die  # noqa: E402


def main():
    # prog を sys.argv[0] から明示する: 既定は __main__ の名前から引くので、同じプロセスで呼ぶ口（テストの土台）では
    # 「python -m pytest」になり、2 つの口の使い方の文がずれた（Python 3.14 の argparse）
    p = argparse.ArgumentParser(prog=pathlib.Path(sys.argv[0]).name, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
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
    s.add_argument("--unfenced-delegates", metavar="REASON",
                   help="任せ先（delegate）を sandbox で縛らず、回す側が Agent ツールで起こす（人が run ごとに明示したときだけ。理由は盤面に残る）")
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
    s.add_argument("--detail", help="答えに添える構造の値の JSON のファイル（受ける形は rules の answer_detail。受けない loop では拒む）")
    s.set_defaults(fn=c.cmd_answer)

    s = sub.add_parser("stop", help="走っている run を人がその時点で止める（人に聞いていない時点でも。理由は必須で記録に残る。起こし中の役の子は木ごと止める）")
    s.add_argument("--dir")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_stop)

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
    s.add_argument("--file")
    s.add_argument("--delete", action="store_true", help="在る辞書の鍵を消す（--file と排他）")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=c.cmd_patch)

    s = sub.add_parser("intake", help="踏んだ問題を利用者の環境に 1 行残す・まとめて書き出す・届け先へ送る（commands/intake.md）")
    s.add_argument("--data-dir", help="残す置き場（手順書の本文が ${CLAUDE_PLUGIN_DATA} を渡す。無ければ engine の置き場から導く）")
    m = s.add_mutually_exclusive_group(required=True)
    m.add_argument("--what", help="手で残す 1 行の説明（500 字で切る）")
    m.add_argument("--export", metavar="FILE", help="まだ手渡していない行を 1 ファイル（JSONL）に書き出す")
    m.add_argument("--send", action="store_true", help="まだ手渡していない行を届け先へ送る（届け先が無ければ手元に残すだけ）")
    m.add_argument("--set-url", metavar="URL", help="届け先を設定する（空で消す）")
    s.add_argument("--dir", help="--what に run の番号・周を添える盤面")
    s.add_argument("--all", action="store_true", help="--export で、手渡した行も含めて全部を書き出す")
    s.add_argument("--with-stderr", action="store_true", help="--export で標準エラーの頭（残していれば）も書き出す")
    s.set_defaults(fn=c.cmd_intake)

    a = p.parse_args()
    install_stop_handlers()   # 全コマンド——next・done の builtin も子（テスト一式）を起こす
    a.fn(a)


def cli():
    """入口の全体（sys.argv を読み、例外を終了コードに直して SystemExit で抜ける）。子プロセスとして起こす口と、
    テストの土台（graphloops/tests/py/glharness.py）が同じプロセスで呼ぶ口の 2 つが、この 1 本を通る。

    非 0 で終わる呼び出しは、終わる前に利用者の環境へ 1 行残す（engine/intake.py。残す処理は何が起きても終了コードと
    標準エラーを変えない）。exit 1 の日常の拒否も残す——同じ鍵の件数が「どの拒否が多いか」になる"""
    try:
        main()
    except Reject as e:
        intake.failed(sys.argv[1:], 1, e, e.__traceback__, str(e))
        die(str(e), 1)
    except BoardConflict as e:
        intake.failed(sys.argv[1:], 2, e, e.__traceback__, e.msg)
        die(e.msg, 2)
    except StopSignal as e:
        intake.failed(sys.argv[1:], 128 + e.signum, e, e.__traceback__, f"止める信号 {e.signum} を受けた")
        sys.exit(128 + e.signum)   # 生きている子は信号の口（kill_all）が止めてある
    except SystemExit as e:
        if e.code not in (0, None):
            intake.failed(sys.argv[1:], e.code, e, e.__traceback__, util.LAST_DIE)
        raise
    except Exception as e:  # 契約: 想定外は 2（盤面が読めない側）に倒す
        intake.failed(sys.argv[1:], 2, e, e.__traceback__, str(e))
        die(f"想定外の例外（{type(e).__name__}）: {e}")


if __name__ == "__main__":
    cli()
