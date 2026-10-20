#!/usr/bin/env python3
"""入口の --queue-run（works-dispatch の外のツールが、メインブランチへ入れる列に並んで 1 つのコマンドを走らせる）。dispatch.py の一部で、
landing.py と同じ入口の層に置く。

`dispatch.py [--repo <代表の clone>] --queue-run -- <コマンド> [<引数> ...]` は、打った場所（か --repo）の会社の形の [land] の queue の列
（nodes/landqueue.py）に申し出て、先頭を取ってからコマンドを打った場所で走らせ、終わったら列を抜けて次に渡す。--land と同じ列なので、
同じ clone（worktree を含む）で同時に走る --land とも 1 本ずつ通る。
- コマンドはシェルを通さずに起動し、標準入出力と環境はそのまま渡す。列で待つ間の行と止めた訳は標準エラーに出す（標準出力はコマンドの物）。
- 終了の値はコマンドの物。シグナルで落ちたら 128 + その番号（シェルと同じ）。コマンドを走らせる前に止めたときは、GNU の env・nice と
  同じに分ける: 列に入れない（会社の形が読めない・[land] に queue が無い・列のフォルダを書けない）は 125、コマンドが在るのに起動できない
  は 126、コマンドが見つからないは 127。
- 札は名乗らない（--land-order の order に当たらず、申し出た順で通る）。待つ長さに上限は置かない（期限を足さない決まり D5）。
"""

import errno
import subprocess
import sys

import gitx
import landorder
from nodes import landqueue

QUEUE_FAILED = 125   # 列に入れずコマンドを走らせなかった（GNU の env が自分の誤りで返す値と同じ）


def _say(line):
    print(line, file=sys.stderr, flush=True)


def main(repo, command, ports, config_path=None, run=subprocess.call):
    """--queue-run -- <コマンド>。列の先頭を取ってから command（引数の並び）を run で走らせ、その終了の値を返す。"""
    if not command:
        _say("止めた: --queue-run の後に -- と走らせるコマンドを書く（例 --queue-run -- git push origin HEAD:master）")
        return 2
    try:
        queue, why = landorder.place(repo, ports, config_path)
    except (OSError, gitx.GitError) as e:
        queue, why = None, f"会社の形を読めない（{e}）"
    if queue is None:
        _say(f"止めた: メインブランチへ入れる列に入れない: {why}。コマンドは走らせていない")
        return QUEUE_FAILED
    try:
        t = landqueue.turn(queue, say=_say)
        t.__enter__()
    except OSError as e:
        _say(f"止めた: メインブランチへ入れる列（{queue}）に入れない: {e}。コマンドは走らせていない")
        return QUEUE_FAILED
    except KeyboardInterrupt:
        return 130
    try:
        code = run(command)
    except OSError as e:
        _say(f"止めた: コマンド {command[0]} を起動できない（{e}）")
        code = 127 if e.errno == errno.ENOENT else 126
    except KeyboardInterrupt:
        code = 130
    finally:
        t.__exit__(None, None, None)
    return 128 - code if code < 0 else code
