# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正のブロックの出口を集める（blk-fix の節 collect。returns の節）。

読む環境変数:
- INPUTS_ACCEPTED: 輪（fix-loop）の出力 = 最後の周の fix-accept の出力（{ok, reason, changes} の JSON の文字列）
- INPUTS_CHANGED: assert-changed の出力（{ok, files} の JSON の文字列）
- ARTIFACTS_DIR: 盤面はその下の board/
受け付けた changes を盤面の changes.json（{"changes": [...]}）に書き、{"ok": true, "files", "changes_file"} を 1 行出して 0。
受け付けが通っていない・入力が読めないときは、標準エラーに理由を 1 行出して 2（何も書かない）。標準ライブラリだけ。
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

CHANGES_FILE = "changes.json"


class Unreadable(Exception):
    pass


def env_json(name):
    raw = os.environ.get(name)
    if raw is None:
        raise Unreadable(f"環境変数が無い: {name}")
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Unreadable(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）")
    if not isinstance(v, dict):
        raise Unreadable(f"{name} が JSON のオブジェクトでない（{type(v).__name__}）")
    return v


def collect():
    accepted, changed = env_json("INPUTS_ACCEPTED"), env_json("INPUTS_CHANGED")
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        raise Unreadable("環境変数が無い: ARTIFACTS_DIR")
    if accepted.get("ok") is not True:
        raise Unreadable(f"受け付けが通っていない（{accepted.get('reason')!r}）")
    changes = accepted.get("changes")
    if not isinstance(changes, list) or not changes:
        raise Unreadable("受け付けの出力に changes が無い")
    files = changed.get("files")
    if changed.get("ok") is not True or not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise Unreadable(f"assert-changed の出力に files が無い（{changed!r}）")
    board = pathlib.Path(artifacts) / "board"
    board.mkdir(parents=True, exist_ok=True)
    path = board / CHANGES_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"changes": changes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True, "files": files, "changes_file": str(path)}


def main():
    try:
        out = collect()
    except Unreadable as e:
        print(f"collect: {e}".replace("\n", " "), file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
