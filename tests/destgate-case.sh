#!/usr/bin/env bash
# destgate の 1 ケース実行。run.sh の expect_output から呼ぶ。
# 使い方: destgate-case.sh <config_dir> <cwd> <command_string>
# ゲートの stdout をそのまま出す。空(=素通し)なら ALLOW_EMPTY を出す。終了コードはゲートに従う。
set -uo pipefail
cfg=$1 wd=$2 cmd=$3
PY_BIN=$(command -v python3 || command -v python)
payload=$("$PY_BIN" -c 'import json,sys; print(json.dumps({"tool_name":"Bash","cwd":sys.argv[2],"tool_input":{"command":sys.argv[1]}}))' "$cmd" "$wd")
out=$(printf '%s' "$payload" | CLAUDE_CONFIG_DIR="$cfg" "$PY_BIN" "$(dirname "$0")/../gates/hooks/dest-gate.py")
rc=$?
[ -z "$out" ] && out=ALLOW_EMPTY
printf '%s\n' "$out"
exit $rc
