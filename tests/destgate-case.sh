#!/usr/bin/env bash
# destgate の 1 ケース実行。run.sh の expect_output から呼ぶ。
# 使い方: destgate-case.sh <config_dir> <cwd> <command_string> [<名前>=<値>…]
# ゲートの stdout をそのまま出す。空(=素通し)なら ALLOW_EMPTY を出す。終了コードはゲートに従う。
# 呼び手の環境の GIT_CONFIG_*（git の設定を環境で足す変数）は外してからゲートを起動する。ゲートは環境にそれが在れば -R の無い
# 投稿の宛先を不明にするので、試験を回す側の環境で答えが変わる（tests/mutate.py の写しは GIT_CONFIG_COUNT で git の自動の後始末を
# 切るので、2026-10-31 の mutation.yml の run 41202847506 で、壊していない写しの destgate の検査が 17 件赤になった）。
# 4 つ目からの <名前>=<値> は、外した後にゲートの環境へ足す（GIT_CONFIG_* が在る形の検査に使う）
set -uo pipefail
cfg=$1 wd=$2 cmd=$3
shift 3
for a in "$@"; do
    [[ "$a" == [A-Za-z_]*=* ]] || { echo "destgate-case.sh: 4 つ目からは <名前>=<値> だけを渡す: $a" >&2; exit 2; }
done
drop=()
while IFS= read -r v; do
    [[ "$v" == GIT_CONFIG* ]] && drop+=(-u "$v")
done < <(compgen -e)
PY_BIN=$(command -v python3 || command -v python)
payload=$("$PY_BIN" -c 'import json,sys; print(json.dumps({"tool_name":"Bash","cwd":sys.argv[2],"tool_input":{"command":sys.argv[1]}}))' "$cmd" "$wd")
out=$(printf '%s' "$payload" | env ${drop[@]+"${drop[@]}"} CLAUDE_CONFIG_DIR="$cfg" "$@" "$PY_BIN" "$(dirname "$0")/../gates/hooks/dest-gate.py")
rc=$?
[ -z "$out" ] && out=ALLOW_EMPTY
printf '%s\n' "$out"
exit $rc
