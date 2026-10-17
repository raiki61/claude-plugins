#!/usr/bin/env bash
# coldread ゲートの 1 ケース実行。run.sh の expect_output から呼ぶ。
# 使い方: coldread-case.sh <config_dir> <reader_cmd|-> <command_string> [gh_cmd]
# ゲートの stdout をそのまま出す。空(=素通し)なら ALLOW_EMPTY を出す。終了コードはゲートに従う。
# gh_cmd は画面(投稿先のスレッド)を取る gh の代役(COLDREAD_GH_CMD)。省かれたら `exit 1`——
# 既定を実物の gh にすると、テストの `gh issue comment 1` がこのリポジトリの issue 1 を実際に
# 取りに行く(ネットワークと認証に依存し、CI では毎回失敗の待ち時間になる)。
# 環境変数 COLDREAD_TEST_SESSION が有れば payload の session_id に入れる(連続 deny を session ごとに
# 数える検査用)。無ければ呼び出しごとに別の session にする——同じ投稿の書き直しは、2 回目から前の回の指摘と
# 差分を読み手に渡し、3 回目から知らせが付くので、session を共有すると、似た本文を続けて流す検査の判定が前の検査に引きずられる。COLDREAD_GATE が有ればそのフック本体を使う(cache に版が並ぶ形を模す検査用)。
# COLDREAD_TEST_CWD が有れば payload の cwd に入れる(相対パスの本文ファイルを、フックの入力の cwd で解く検査用)。
set -uo pipefail
cfg=$1 reader=$2 cmd=$3 gh=${4:-exit 1}
PY_BIN=$(command -v python3 || command -v python)
gate=${COLDREAD_GATE:-"$(dirname "$0")/../gates/hooks/coldread-gate.py"}
payload=$("$PY_BIN" -c 'import json,sys,os
d={"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}
d["session_id"]=os.environ.get("COLDREAD_TEST_SESSION") or os.urandom(8).hex()
c=os.environ.get("COLDREAD_TEST_CWD")
if c: d["cwd"]=c
print(json.dumps(d))' "$cmd")
if [ "$reader" = "-" ]; then
    out=$(printf '%s' "$payload" | CLAUDE_CONFIG_DIR="$cfg" COLDREAD_GH_CMD="$gh" "$PY_BIN" "$gate")
else
    out=$(printf '%s' "$payload" | CLAUDE_CONFIG_DIR="$cfg" COLDREAD_READER_CMD="$reader" COLDREAD_GH_CMD="$gh" "$PY_BIN" "$gate")
fi
rc=$?
[ -z "$out" ] && out=ALLOW_EMPTY
printf '%s\n' "$out"
exit $rc
