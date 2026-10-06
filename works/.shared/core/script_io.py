"""受け付けのスクリプト（各ブロックの scripts/*.py）の入口。Archon の口を読み、中身の関数を呼び、1 行の JSON を出す。

main(fn) が読む環境変数:
- INPUTS_REPLY（名前は reply_env で替えられる）: 役の返答。節の `with: {reply: {from: "$節.output"}}` で JSON の文字列が届く
- INPUTS_BASE_REV: 周の頭で固めた版。空は「その場の HEAD を使う」の意味（Ruling R2）で、欠けとは扱わない
- ARTIFACTS_DIR: run の成果物の置き場。盤面は その下の board/（無ければ作る）
呼ぶ形は fn(reply: dict, board: Path, base_rev: str, repo: Path) -> dict。repo は cwd（Archon は対象リポジトリで起こす）。
出口: fn の結果を ensure_ascii=False の 1 行の JSON で標準出力に出し、0 で終わる（拒否 {"ok": false, "reason": …} も 0）。
返答が JSON として読めない・JSON のオブジェクトでないときは fn を呼ばずに ok: false を出して 0。
出口は 1 本（emit_result。main を通らない受け付けの入口も盤面を board_dir で引いてこれを通す）で、どの結果にも reason_file を足す。拒否（ok が true でない）なら reason の本文を盤面の
scope の根（scope_dir。include の中なら <盤面>/<include の名>/、線の最上段なら盤面の根）の reject-<fn の名>-<連番>.txt に
UTF-8 で字のまま書いてその絶対パスを、通れば空の文字列を入れる。どの結果も、scope の根の accept-last.json の
自分の行に最後の結果として上書きする（note_last。出し直して通った拒否は残らない。報告の段が run の終わりに ok でない行を
前の run の落ちた理由に集める）。
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

switch_on(value, name) は部品の切り替えの入力（on・off。空は on）を真偽に読む口（線が run ごとに機能を切って比べる。ほかの語は ValueError）。

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
import datetime
import json
import os
import pathlib
import re
import sys

sys.dont_write_bytecode = True   # 念押し（上の注意: この物自身の .pyc を止めるのは import する側）

import flow_adapter  # noqa: E402  （流れの道具の口。層 L1・標準ライブラリだけ）

BASE_REV_ENV = "INPUTS_BASE_REV"
ARTIFACTS_ENV = flow_adapter.ARTIFACTS_ENV
BOARD_DIR = "board"
REJECT_PREFIX = "reject-"
ACCEPT_LAST = "accept-last.json"   # scope の根の受け付けの最後の結果 {<fn の名>: {ok, reason_file, reason, at}}（note_last が上書き）


SWITCH_ON, SWITCH_OFF = "on", "off"   # 部品の切り替えの入力の語（線が run ごとに機能を切る口。空は on）


def switch_on(value, name: str) -> bool:
    """部品の切り替えの入力（on か off。空・None・文字列 null は on＝今どおり）を真偽にする。ほかの語は名を言って ValueError
    （黙って on にも off にも倒さない）"""
    word = "" if value is None else str(value).strip()
    if word in ("", "null", SWITCH_ON):
        return True
    if word == SWITCH_OFF:
        return False
    raise ValueError(f"入力 {name}={word!r} は {SWITCH_ON} か {SWITCH_OFF}（空は {SWITCH_ON}）")


def _emit(obj) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"   # json.dumps は改行を \n に書くので必ず 1 行
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")                # 場所の設定が ASCII でも日本語で落ちない
    out.write(line)
    out.flush()


def reject_name(fn, n) -> str:
    """拒否の理由のファイルの名 reject-<fn の名>-<n>.txt。fn は関数（その __name__）か名前の文字列。n に "*" を渡せば glob。
    名の綴りはここだけ"""
    return f"{REJECT_PREFIX}{safe_fn(fn)}-{n}.txt"


def scope_dir(board: pathlib.Path) -> pathlib.Path:
    """盤面 board の今の scope の根（board / flow_adapter.current_scope()。線の最上段なら board そのもの）。周をまたぐ部品の
    私物（拒否の理由・後始末の控えなど、盤面の根に書いていた物）の置き場。作らない"""
    return pathlib.Path(board) / flow_adapter.current_scope()


def last_reject(board, fn) -> str:
    """盤面 board の今の scope の根（scope_dir）に fn の受け付けが書いた一番新しい拒否の理由のファイル（連番の一番大きい物。
    無ければ空。連番の所が数字でない名は採らない）。ほかの scope の物は見ない"""
    head, _, tail = reject_name(fn, "*").partition("*")

    def n(p):
        num = p.name[len(head):-len(tail)] if p.name.startswith(head) and p.name.endswith(tail) else ""
        return int(num) if num.isdigit() else None
    got = sorted((n(p), str(p)) for p in scope_dir(board).glob(head + "*" + tail) if n(p) is not None)
    return got[-1][1] if got else ""


def _write_reason(board: pathlib.Path, fn, reason: str) -> str:
    """拒否の理由の本文を盤面の今の scope の根（scope_dir）の新しいファイルに書き、その絶対パスを返す（受け付けごと・書くたびに
    別の名前）。board は board_dir が解決して $ の柵を当てた値。ここでもう一度 resolve すると柵を当てていない字を返すので、しない
    （scope の名は英数字・_・- だけ。$ を足さない）。fn は関数（その __name__ を使う）か名前の文字列"""
    home = scope_dir(board)
    home.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        p = home / reject_name(fn, n)
        try:
            with open(p, "x", encoding="utf-8", newline="") as f:
                f.write(reason)
            return str(p)
        except FileExistsError:
            n += 1


def safe_fn(fn) -> str:
    """fn（関数ならその __name__、または名前の文字列）をファイルの名・控えの鍵に使える字にした物（reject_name と同じ綴り）"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", (fn if isinstance(fn, str) else getattr(fn, "__name__", "")) or "fn")


def note_last(board, fn, out: dict) -> None:
    """受け付け fn の最後の結果を、盤面 board の今の scope の根（scope_dir）の accept-last.json の自分の行
    {ok, reason_file, reason, at} に上書きで残す（出し直して通れば ok が真の行で上書きされ、通った拒否は消える）。
    報告の段が run の終わりに ok でない行だけを「前の run の落ちた理由」に集める。どの受け付けの出口も 1 回呼ぶ。
    reason は reason_file を持たない口（拒否の文を作業ファイルに積む口）のための本文の写し。書けない控えは捨てない
    （OSError・形の違うファイルは黙って作り直さずに投げる）"""
    home = scope_dir(pathlib.Path(board))
    home.mkdir(parents=True, exist_ok=True)
    path = home / ACCEPT_LAST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path} の形が違う（{{<fn の名>: {{ok, reason_file, reason, at}}}}）")
    ok = out.get("ok") is True
    doc[safe_fn(fn)] = {"ok": ok, "reason_file": "" if ok else str(out.get("reason_file") or ""),
                        "reason": "" if ok else str(out.get("reason", "")),
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def board_dir():
    """ARTIFACTS_DIR の下の盤面を一度だけ resolve した値（シンボリックリンクを辿り、相対なら cwd を足す）。
    ARTIFACTS_DIR が欠け・空、または解決した後のパスが $ を含むときは標準エラーに名前を出して None（呼ぶ側は 2 で終わる）。
    main と、main を通らない受け付けの入口（rolekit.main_accept など）が同じ柵をここで当てる"""
    root = flow_adapter.artifact_root()
    if root is None:
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return None
    board = (root / BOARD_DIR).resolve()   # 柵も fn も reason_file もこの値から
    if "$" in str(board):
        print(f"{ARTIFACTS_ENV} が $ を含む（reason_file のパスが置き換えに通る）: {board}", file=sys.stderr)
        return None
    return board


def emit_result(board: pathlib.Path, fn, out: dict, *, last: bool = True) -> int:
    """受け付けの出口（1 本）: out に reason_file を足し（拒否なら reason の本文を盤面の scope の根の reject-<fn の名>-<連番>.txt に
    字のまま書いてその絶対パス、通れば空）、1 行の JSON を出して 0 を返す。board は board_dir が返した値。
    fn は関数か名前の文字列（ファイルの名前に使う）。
    main を通らない受け付けの入口もここを通す（_emit を直に呼ぶと
    reason_file が出ず、指示書が理由の本文を $LOOP_PREV で貼るしかなくなる）。
    last が偽なら最後の結果の控え（note_last）に書かない: 拒否や投げ出しが run の落ちた理由でなく次の役への引き渡しになる
    受け付け（blk-fix の TDD の輪の tdd-step）が使う"""
    out = dict(out)
    if out.get("ok") is True:
        out["reason_file"] = ""
    else:
        board.mkdir(parents=True, exist_ok=True)
        out["reason_file"] = _write_reason(board, fn, str(out.get("reason", "")))
    if last:
        note_last(board, fn, out)
    _emit(out)
    return 0


def later_output(first: str, later) -> str:
    """飛ばされうる後の節の出力（with: の {from: "$x.output", if_skipped: null}。飛ばされれば文字列 null か空）が在ればそれ、
    無ければ first（どちらも JSON の文字列のまま）。修正の輪の後に 2 回目の修正の輪が走った run の受け付けの出力を選ぶ"""
    if isinstance(later, str) and later.strip() not in ("", "null"):
        return later
    return first


def main(fn, reply_env: str = "INPUTS_REPLY", *, finish=None) -> int:
    """環境変数を読み fn(reply, board, base_rev, repo) を呼んで 1 行の JSON を出す。終了コードを返す（0 か 2）。
    finish(out) -> out は出す前に全部の出口（読めない返答の拒否も）に当てる（blk-fix の fix-accept が輪を抜ける旗 done を足す）"""
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
    return emit_result(board, fn, out)
