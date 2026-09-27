#!/usr/bin/env python3
"""書いた事実を、書いたその瞬間に 1 行残す（PostToolUse:Edit|Write|NotebookEdit。包み claude-adapter が足す）。

書く役の受け付け（writes.py）が、版からの変更をこの記録と突き合わせ、編集の道具で書いていない変更（Bash の python - <<・
cat >・sed -i など）を拒む。record-read.py は graphloops の写しで boards() だけを替える約束なので、同じ形の別の台本にした。
置き場はコマンドの 1 つ目の引数（adapter.reads_dir。包みが cwd ごとに分けて渡す）。置き場が無ければ 1 バイトも書かない。
残すのは書いた後の中身の sha で、中身は写さない。読めない入力・書けない置き場でも道具は止めない。
"""
import hashlib
import json
import os
import pathlib
import stat
import sys
import time

TOOLS = ("Edit", "Write", "NotebookEdit")
LOG = "writes.jsonl"   # adapter.WRITES_LOG と同じ名


def main():
    if len(sys.argv) < 2 or not sys.argv[1] or not pathlib.Path(sys.argv[1]).is_dir():
        return 0
    try:
        d = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(d, dict) or d.get("tool_name") not in TOOLS:
        return 0
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(path, str) or not path:
        return 0
    real = os.path.realpath(path)
    try:
        st = os.stat(real)
        sha = hashlib.sha256(pathlib.Path(real).read_bytes()).hexdigest() if stat.S_ISREG(st.st_mode) else None
    except OSError:
        sha = None
    row = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_id": d.get("session_id"),
                      "agent_id": d.get("agent_id"), "tool_name": d["tool_name"], "path": real, "file_sha": sha,
                      "tool_use_id": d.get("tool_use_id")}, ensure_ascii=False)
    try:
        with open(pathlib.Path(sys.argv[1]) / LOG, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
