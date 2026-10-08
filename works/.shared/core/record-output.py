#!/usr/bin/env python3
"""下請けの会話が親の節の返答の道具に書いた返答を、書いたその瞬間に 1 行残す（PostToolUse:StructuredOutput。包み
claude-adapter が足す）。

組み込みの skill code-review は fork（下請けの会話）で走り、節の --json-schema が足す道具 StructuredOutput を継いで、所見を
そこへ書いて終わる。親の Skill の結果は『Skill execution completed』だけで、所見は親に届かない（実測と拾い方は diverted.py の頭）。
ここは入力に agent_id が在る呼び出し（下請けの中。親の節の自分の返答は agent_id が無い）だけを、入力のまま残す。PostToolUse は
道具が成った時だけ起きるので、残る入力は節の schema の検査を通った物。置き場はコマンドの 1 つ目の引数（adapter.reads_dir。
包みが cwd ごとに分けて渡す）。置き場が無ければ 1 バイトも書かない。読めない入力・書けない置き場でも道具は止めない。
"""
import datetime
import json
import os
import pathlib
import sys

TOOL = "StructuredOutput"
LOG = "outputs.jsonl"   # diverted.OUTPUTS_LOG と同じ名


def main():
    if len(sys.argv) < 2 or not sys.argv[1] or not pathlib.Path(sys.argv[1]).is_dir():
        return 0
    try:
        d = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not (isinstance(d, dict) and d.get("tool_name") == TOOL and d.get("agent_id")
            and isinstance(d.get("tool_input"), dict)):
        return 0
    row = json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                      "session_id": d.get("session_id"), "agent_id": d["agent_id"], "agent_type": d.get("agent_type"),
                      "tool_use_id": d.get("tool_use_id"), "input": d["tool_input"]}, ensure_ascii=False)
    try:   # 1 回の write で足す（同時に終わる下請けの行が混ざらないように。所見の入力は数十 KB になりうる）
        fd = os.open(str(pathlib.Path(sys.argv[1]) / LOG), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (row + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
