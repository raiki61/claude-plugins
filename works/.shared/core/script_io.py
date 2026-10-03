"""受け付けのスクリプト（各ブロックの scripts/*.py）の入口。Archon の口を読み、中身の関数を呼び、1 行の JSON を出す。

main(fn) が読む環境変数:
- INPUTS_REPLY（名前は reply_env で替えられる）: 役の返答。節の `with: {reply: {from: "$節.output"}}` で JSON の文字列が届く
- INPUTS_BASE_REV: 周の頭で固めた版。空は「その場の HEAD を使う」の意味（Ruling R2）で、欠けとは扱わない
- ARTIFACTS_DIR: run の成果物の置き場。盤面は その下の board/（無ければ作る）
呼ぶ形は fn(reply: dict, board: Path, base_rev: str, repo: Path) -> dict。repo は cwd（Archon は対象リポジトリで起こす）。
出口: fn の結果を ensure_ascii=False の 1 行の JSON で標準出力に出し、0 で終わる（拒否 {"ok": false, "reason": …} も 0）。
返答が JSON として読めない・JSON のオブジェクトでないときは fn を呼ばずに ok: false を出して 0。
出口は 1 本（emit_result。main を通らない受け付けの入口も盤面を board_dir で引いてこれを通す）で、どの結果にも reason_file を足す。拒否（ok が true でない）なら reason の本文を盤面の
reject-<fn の名>-<連番>.txt に UTF-8 で字のまま書いてその絶対パスを、通れば空の文字列を入れる。
盤面のパスは board_dir で一度だけ resolve し（シンボリックリンクを辿り、相対なら cwd を足す）、下の $ の柵も、fn へ渡す board も、
reason_file も、その同じ解決した後の値から作る（検査した字と外へ出す字を揃える。正規化してから検査する）。
次の周の役へ理由を届けるのは reason_file の方。指示書は $LOOP_PREV.<役>-accept.output.reason_file だけを差し込み、
役に Read させる。Archon は $LOOP_PREV で貼った中身をもう一度変数・節の参照の置き換えに通すので、役の返答から
派生した reason の本文（$ARTIFACTS_DIR や $<節>.output.<欄> を含みうる）を貼ると黙って化けるか OutputRefError で
run が落ちる。$LOOP_PREV で渡してよいのは、評価器が読み直しても変わらない固定の形の値（$ を含まないパス）だけ。
reason は記録のために残す。
環境変数が欠けたとき（ARTIFACTS_DIR は空も欠けと同じ。空だと盤面が対象リポジトリの board/ になる）と、
盤面を解決した後のパスが $ を含むとき（reason_file のパスが置き換えに通ってしまう。ARTIFACTS_DIR の字そのものに
$ が無くても、リンクの先や相対パスの cwd から現れうる）だけ、標準エラーに名前を出して 2
（標準出力には何も出さない）。

ブロックのスクリプトは、次の前置きをそのまま写し、最後の 2 行の関数だけを替える:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（下の注意）
import script_io  # noqa: E402
from accept import check_judge  # noqa: E402

sys.exit(script_io.main(check_judge))
```

- 頭の `# /// script` の塊（PEP 723。ファイルの頭、docstring より前）は、uv に対象の project を拾わせないため。Archon は
  script の節を `uv run <パス>`（cwd は対象の worktree）で起こすので、塊が無いと対象が pyproject.toml を持つとき uv が
  worktree に .venv と uv.lock を作り、対象を sync・build する（`tests/test_script_headers.py` が見る）。
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
import re
import sys

sys.dont_write_bytecode = True   # 念押し（上の注意: この物自身の .pyc を止めるのは import する側）

BASE_REV_ENV = "INPUTS_BASE_REV"
ARTIFACTS_ENV = "ARTIFACTS_DIR"
BOARD_DIR = "board"
REJECT_PREFIX = "reject-"
TAG_FORM = re.compile(r"^[A-Za-z0-9_-]+$")   # 回の印の字（ファイルの名の 1 段に入れる）


def tagged(name: str, tag: str) -> str:
    """回の印 tag をファイルの名 name の拡張子の前に足した名（`a.md` → `a.<tag>.md`。拡張子が無ければ尾に足す）。tag が空なら
    name のまま。同じ周に同じ役を 2 度起こす段（blk-fix の 2 回目の修正の段）が、1 回ごとのファイルの名を分ける唯一の決まり
    （blk-fix の fixrules.tagged はこれ。core の conflict と拒否の理由の名もこれで作る）。tag が英数字・_・- でなければ ValueError"""
    if not tag:
        return name
    if not TAG_FORM.match(tag):
        raise ValueError(f"回の印 {tag!r} は英数字・_・- だけ")
    stem, dot, ext = name.rpartition(".")
    return f"{stem}.{tag}.{ext}" if dot and stem and "/" not in ext else f"{name}.{tag}"


def _emit(obj) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"   # json.dumps は改行を \n に書くので必ず 1 行
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")                # 場所の設定が ASCII でも日本語で落ちない
    out.write(line)
    out.flush()


def _write_reason(board: pathlib.Path, fn, reason: str, tag: str = "") -> str:
    """拒否の理由の本文を盤面の新しいファイルに書き、その絶対パスを返す（受け付けごと・書くたびに別の名前）。
    board は board_dir が解決して $ の柵を当てた値。ここでもう一度 resolve すると柵を当てていない字を返すので、しない。
    fn は関数（その __name__ を使う）か名前の文字列。tag は回の印（tagged。reject-<名>-<連番>.<tag>.txt）"""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", (fn if isinstance(fn, str) else getattr(fn, "__name__", "")) or "fn")
    n = 1
    while True:
        p = board / tagged(f"{REJECT_PREFIX}{name}-{n}.txt", tag)
        try:
            with open(p, "x", encoding="utf-8", newline="") as f:
                f.write(reason)
            return str(p)
        except FileExistsError:
            n += 1


def board_dir():
    """ARTIFACTS_DIR の下の盤面を一度だけ resolve した値（シンボリックリンクを辿り、相対なら cwd を足す）。
    ARTIFACTS_DIR が欠け・空、または解決した後のパスが $ を含むときは標準エラーに名前を出して None（呼ぶ側は 2 で終わる）。
    main と、main を通らない受け付けの入口（rolekit.main_accept など）が同じ柵をここで当てる"""
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return None
    board = (pathlib.Path(os.environ[ARTIFACTS_ENV]) / BOARD_DIR).resolve()   # 柵も fn も reason_file もこの値から
    if "$" in str(board):
        print(f"{ARTIFACTS_ENV} が $ を含む（reason_file のパスが置き換えに通る）: {board}", file=sys.stderr)
        return None
    return board


def emit_result(board: pathlib.Path, fn, out: dict, *, tag: str = "") -> int:
    """受け付けの出口（1 本）: out に reason_file を足し（拒否なら reason の本文を盤面の reject-<fn の名>-<連番>.txt に
    字のまま書いてその絶対パス、通れば空）、1 行の JSON を出して 0 を返す。board は board_dir が返した値。
    fn は関数か名前の文字列（ファイルの名前に使う）。tag は回の印（空でなければ名の拡張子の前に .<tag>。tagged）。
    main を通らない受け付けの入口もここを通す（_emit を直に呼ぶと
    reason_file が出ず、指示書が理由の本文を $LOOP_PREV で貼るしかなくなる）"""
    out = dict(out)
    if out.get("ok") is True:
        out["reason_file"] = ""
    else:
        board.mkdir(parents=True, exist_ok=True)
        out["reason_file"] = _write_reason(board, fn, str(out.get("reason", "")), tag)
    _emit(out)
    return 0


def later_output(first: str, later) -> str:
    """飛ばされうる後の節の出力（with: の {from: "$x.output", if_skipped: null}。飛ばされれば文字列 null か空）が在ればそれ、
    無ければ first（どちらも JSON の文字列のまま）。修正の輪の後に 2 回目の修正の輪が走った run の受け付けの出力を選ぶ"""
    if isinstance(later, str) and later.strip() not in ("", "null"):
        return later
    return first


def main(fn, reply_env: str = "INPUTS_REPLY", *, finish=None, tag: str = "") -> int:
    """環境変数を読み fn(reply, board, base_rev, repo) を呼んで 1 行の JSON を出す。終了コードを返す（0 か 2）。
    finish(out) -> out は出す前に全部の出口（読めない返答の拒否も）に当てる（blk-fix の fix-accept が輪を抜ける旗 done を足す）。
    tag は拒否の理由のファイルの名の回の印（emit_result）"""
    missing = [n for n in (reply_env, BASE_REV_ENV, ARTIFACTS_ENV) if n not in os.environ]
    if ARTIFACTS_ENV not in missing and not os.environ[ARTIFACTS_ENV]:
        missing.append(ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = board_dir()
    if board is None:
        return 2
    board.mkdir(parents=True, exist_ok=True)
    raw = os.environ[reply_env]
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError as e:
        out = {"ok": False, "reason": f"返答が JSON として読めない: {e}（頭: {raw[:200]!r}）"}
    else:
        if not isinstance(reply, dict):
            out = {"ok": False, "reason": f"返答が JSON のオブジェクトでない（{type(reply).__name__}）"}
        else:
            out = dict(fn(reply, board, os.environ[BASE_REV_ENV], pathlib.Path.cwd()))
    if finish is not None:
        out = dict(finish(out))
    return emit_result(board, fn, out, tag=tag)
