# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""境の節（線 A の仕様 2 節・計画 Task 10a・裁定 TA1）。中身は halt.edge（.shared/core/halt.py）。ラインの中で at を替えて使う
（h-plan・h-gate・h-fix・h-mid・h-midgate・h-review・h-refix・h-tests）。いつも走る節で、when: を持たない。

読む環境変数（Archon が節の with: から渡す。どれも在ること）:
- INPUTS_AT（halt.AT の語）・INPUTS_ADAPTER（start の adapter）・INPUTS_MID_GATE（start の mid_gate。空は always）
- INPUTS_JUDGED（h-plan だけ: 判定のブロックの出口）・INPUTS_GATE（h-fix は policy-gate、h-review は mid-gate の出口）・
  INPUTS_MID（h-midgate だけ: blk-tests の mid の出口）。どれも JSON のオブジェクトの文字列で、飛ばされた節は
  `{from: …, if_skipped: null}` の文字列 null（空も同じ）＝「開かなかった・走らなかった」。語の入力の null は空と同じ
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）・WORKFLOW_ID（関所の文の run の id。空も欠け）
出口:
- halt.edge の結果 {ok, stop, go, ask, gate_text, judgment_file, open_units, plan_file, notes, why} を 1 行の JSON で出して 0
- 環境変数が欠けた・JSON が読めない・オブジェクトでない・盤面の誤り（BoardGap・Reject）・盤面のパスが $ を含む・思わぬ誤り:
  標準出力に何も出さず、標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

# 裁定 TA16: 読む INPUTS_* の組（Task 17 の試験が YAML の with: の鍵と突き合わせる）
INPUTS = ("INPUTS_AT", "INPUTS_JUDGED", "INPUTS_GATE", "INPUTS_MID", "INPUTS_ADAPTER", "INPUTS_MID_GATE")
JSON_INPUTS = {"INPUTS_JUDGED": "judged", "INPUTS_GATE": "gate", "INPUTS_MID": "mid"}
NULL = "null"   # 飛ばされた節の出力（if_skipped: null）が届く字
RUN_ID_ENV = "WORKFLOW_ID"
NON_EMPTY = (script_io.ARTIFACTS_ENV, RUN_ID_ENV)


class Broken(Exception):
    pass


def _line(text) -> str:
    return " ".join(str(text).split())


def _word(name: str) -> str:
    v = os.environ[name]
    return "" if v.strip() == NULL else v.strip()


def _obj(name: str):
    raw = os.environ[name]
    if raw.strip() in ("", NULL):
        return None
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Broken(f"{name} が JSON として読めない（{e}）: {raw[:200]!r}") from None
    if v is not None and not isinstance(v, dict):
        raise Broken(f"{name} が JSON のオブジェクトでない（{type(v).__name__}）")
    return v


def main() -> int:
    missing = [n for n in (*INPUTS, *NON_EMPTY) if n not in os.environ]
    missing += [n for n in NON_EMPTY if n in os.environ and not os.environ[n]]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = (Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR).resolve()
    if "$" in str(board):   # 返りのパス（plan_file など）が Archon の置き換えに通らないように（script_io と同じ柵）
        print(f"{script_io.ARTIFACTS_ENV} が $ を含む（返りのパスが置き換えに通る）: {board}", file=sys.stderr)
        return 2
    try:
        import halt
        from board import BoardGap
        from engine.util import Reject
    except Exception as e:
        print(f"境の節の部品を読み込めない: {type(e).__name__}: {_line(e)}", file=sys.stderr)
        return 2
    try:
        kw = {key: _obj(name) for name, key in JSON_INPUTS.items()}
        out = halt.edge(board, _word("INPUTS_AT"), Path.cwd(), run_id=os.environ[RUN_ID_ENV],
                        adapter_mode=_word("INPUTS_ADAPTER"), mid_gate=_word("INPUTS_MID_GATE"), **kw)
    except Broken as e:
        print(f"境の節の入力が崩れている: {_line(e)}", file=sys.stderr)
        return 2
    except (BoardGap, Reject) as e:
        print(f"盤面の誤り（{type(e).__name__}）: {_line(e)}", file=sys.stderr)
        return 2
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"境の節の内部の誤り: {type(e).__name__}: {_line(e)}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
