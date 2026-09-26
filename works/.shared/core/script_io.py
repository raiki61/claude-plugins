"""受け付けのスクリプト（各ブロックの scripts/*.py）の入口。Archon の口を読み、中身の関数を呼び、1 行の JSON を出す。

main(fn) が読む環境変数:
- INPUTS_REPLY（名前は reply_env で替えられる）: 役の返答。節の `with: {reply: {from: "$節.output"}}` で JSON の文字列が届く
- INPUTS_BASE_REV: 周の頭で固めた版。空は「その場の HEAD を使う」の意味（Ruling R2）で、欠けとは扱わない
- ARTIFACTS_DIR: run の成果物の置き場。盤面は その下の board/（無ければ作る）
呼ぶ形は fn(reply: dict, board: Path, base_rev: str, repo: Path) -> dict。repo は cwd（Archon は対象リポジトリで起こす）。
出口: fn の結果を ensure_ascii=False の 1 行の JSON で標準出力に出し、0 で終わる（拒否 {"ok": false, "reason": …} も 0）。
返答が JSON として読めない・JSON のオブジェクトでないときは fn を呼ばずに ok: false を出して 0。
環境変数が欠けたとき（ARTIFACTS_DIR は空も欠けと同じ。空だと盤面が対象リポジトリの board/ になる）だけ、
標準エラーに名前を出して 2（標準出力には何も出さない）。

ブロックのスクリプトは、次の前置きをそのまま写し、最後の 2 行の関数だけを替える:

```python
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（下の注意）
import script_io  # noqa: E402
from accept import check_judge  # noqa: E402

sys.exit(script_io.main(check_judge))
```

- `sys.dont_write_bytecode = True` は import する側が立てる。Python は import した物の .pyc を、その物の中の行が動く前に書く。
  だから script_io.py や accept.py の中で立てても、その物自身の __pycache__ は止まらない（ここで下に立てるのは、
  script_io を先に import した後で import される物のための念押し）。
- `.shared/core` は sys.path の頭（0 番）に入れる。スクリプト自身のフォルダが sys.path[0] に在るので、スクリプトの名前が
  accept.py だと、後ろに足したのでは `import accept` がスクリプト自身を読む（Ruling R7）。
- pack の根は `Path(__file__).resolve().parents[2]`（<根>/<blk>/scripts/<名>.py）。Archon は run ごとに pack を写して写しから起こす。
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 念押し（上の注意: この物自身の .pyc を止めるのは import する側）

BASE_REV_ENV = "INPUTS_BASE_REV"
ARTIFACTS_ENV = "ARTIFACTS_DIR"
BOARD_DIR = "board"


def _emit(obj) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"   # json.dumps は改行を \n に書くので必ず 1 行
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")                # 場所の設定が ASCII でも日本語で落ちない
    out.write(line)
    out.flush()


def main(fn, reply_env: str = "INPUTS_REPLY") -> int:
    """環境変数を読み fn(reply, board, base_rev, repo) を呼んで 1 行の JSON を出す。終了コードを返す（0 か 2）"""
    missing = [n for n in (reply_env, BASE_REV_ENV, ARTIFACTS_ENV) if n not in os.environ]
    if ARTIFACTS_ENV not in missing and not os.environ[ARTIFACTS_ENV]:
        missing.append(ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    raw = os.environ[reply_env]
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError as e:
        _emit({"ok": False, "reason": f"返答が JSON として読めない: {e}（頭: {raw[:200]!r}）"})
        return 0
    if not isinstance(reply, dict):
        _emit({"ok": False, "reason": f"返答が JSON のオブジェクトでない（{type(reply).__name__}）"})
        return 0
    board = pathlib.Path(os.environ[ARTIFACTS_ENV]) / BOARD_DIR
    board.mkdir(parents=True, exist_ok=True)
    _emit(fn(reply, board, os.environ[BASE_REV_ENV], pathlib.Path.cwd()))
    return 0
