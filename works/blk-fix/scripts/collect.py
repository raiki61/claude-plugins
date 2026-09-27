# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正のブロックの出口を集める（blk-fix の節 collect。returns の節）。

読む環境変数:
- INPUTS_ACCEPTED: 輪（fix-loop）の出力 = 最後の周の fix-accept の出力（{ok, reason, changes, …} の JSON の文字列）
- INPUTS_CHANGED: assert-changed の出力（{ok, files} の JSON の文字列）
- INPUTS_CLEANED: clean の出力（{ok, removed} の JSON の文字列。修正役が残した git が無視するファイルのうち消した物）
- ARTIFACTS_DIR: 盤面はその下の board/
中身は recount.collect: 受け付けた changes を今の周の changes.json（{"changes": [...]}）に書き、1 本目の欄
{"ok": true, "files", "changes_file", "removed"} に、盤面から fix_file・not_done・coverage・reads_file を足して 1 行出して 0。
受け付けが通っていない・入力が読めない・盤面が今の周の p3.fix を受けていないときは、標準エラーに理由を 1 行出して 2（何も書かない）。
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import recount  # noqa: E402
from board import BoardGap  # noqa: E402  （BoardMismatch も含む）

INPUTS = ("INPUTS_ACCEPTED", "INPUTS_CHANGED", "INPUTS_CLEANED")


def env_json(name):
    raw = os.environ.get(name)
    if raw is None:
        raise recount.Unreadable(f"環境変数が無い: {name}")
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise recount.Unreadable(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）")
    if not isinstance(v, dict):
        raise recount.Unreadable(f"{name} が JSON のオブジェクトでない（{type(v).__name__}）")
    return v


def collect():
    accepted, changed, cleaned = (env_json(n) for n in INPUTS)
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        raise recount.Unreadable("環境変数が無い: ARTIFACTS_DIR")
    removed = cleaned.get("removed")
    if cleaned.get("ok") is not True or not isinstance(removed, list) or not all(isinstance(f, str) for f in removed):
        raise recount.Unreadable(f"clean の出力に removed が無い（{cleaned!r}）")
    out = recount.collect(pathlib.Path(artifacts) / "board", accepted, changed)
    return {**out, "removed": removed}


def main():
    try:
        out = collect()
    except (recount.Unreadable, BoardGap) as e:
        print(f"collect: {e}".replace("\n", " "), file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
