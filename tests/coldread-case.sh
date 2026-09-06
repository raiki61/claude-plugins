#!/usr/bin/env bash
# coldread ゲートの 1 ケース実行。run.sh の expect_output から呼ぶ。
# 使い方: coldread-case.sh <config_dir> <reader_cmd|-> <command_string> [gh_cmd]
# ゲートの stdout をそのまま出す。空(=素通し)なら ALLOW_EMPTY を出す。終了コードはゲートに従う。
# gh_cmd は画面(投稿先のスレッド)を取る gh の代役(COLDREAD_GH_CMD)。省かれたら `exit 1`——
# 既定を実物の gh にすると、テストの `gh issue comment 1` がこのリポジトリの issue 1 を実際に
# 取りに行く(ネットワークと認証に依存し、CI では毎回失敗の待ち時間になる)。
set -uo pipefail
cfg=$1 reader=$2 cmd=$3 gh=${4:-exit 1}
PY_BIN=$(command -v python3 || command -v python)
payload=$("$PY_BIN" -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$cmd")
if [ "$reader" = "-" ]; then
    out=$(printf '%s' "$payload" | CLAUDE_CONFIG_DIR="$cfg" COLDREAD_GH_CMD="$gh" "$PY_BIN" "$(dirname "$0")/../gates/hooks/coldread-gate.py")
else
    out=$(printf '%s' "$payload" | CLAUDE_CONFIG_DIR="$cfg" COLDREAD_READER_CMD="$reader" COLDREAD_GH_CMD="$gh" "$PY_BIN" "$(dirname "$0")/../gates/hooks/coldread-gate.py")
fi
rc=$?
[ -z "$out" ] && out=ALLOW_EMPTY
printf '%s\n' "$out"
exit $rc
