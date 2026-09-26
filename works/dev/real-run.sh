#!/bin/sh
# works/dev/real-run.sh [<dir>]
#
# ライン darkfactory を本物の AI で 1 回回す（費用が掛かる。回す前に持ち主の了承を取る）。
#   1. 模型は WORKS_DEV_MODEL（既定は opus）。隔離した Archon の設定（$WORKS_DEV_HOME/archon-home/config.yaml）に
#      書くのは archon.sh（認証を使う実行のたび）。承認・続きのコマンドにも同じ模型を付けて出す。
#   2. mktarget.sh で <dir>（省略時は一時フォルダ）に使い捨ての対象を作り、<dir>.origin.git を origin に付ける
#      （Archon は run ごとに切る worktree の元を remote から取るため）。
#   3. その中で archon.sh workflow run darkfactory を前景で回す。人の関所で run は止まって戻る。
#   4. run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）を出す。
#      テストの緑赤とログのパスは、止まる直前に出る関所の文面にある。
# 認証は archon.sh と同じ（CLAUDE_CODE_OAUTH_TOKEN か WORKS_KEYCHAIN_ITEM。既定の口座は無い）。
# 隔離した HOME からは ~/.local/bin/claude を自動で見つけられないので、CLAUDE_BIN_PATH を
# 隔離の前に解いて渡す（設定済みならそのまま）。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DEV_HOME="${WORKS_DEV_HOME:-${TMPDIR:-/tmp}/works-dev}"
WORKS_DEV_MODEL="${WORKS_DEV_MODEL:-opus}"
export WORKS_DEV_HOME WORKS_DEV_MODEL

# 開発の家・対象・origin が Claude Code の一時フォルダの下なら、認証を確かめる前・何かを作る前に止まる（guard.sh）
. "$DEV_DIR/guard.sh"
works_dev_refuse_claude_tmp real-run.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
if [ "$#" -ge 1 ]; then
  works_dev_refuse_claude_tmp real-run.sh "対象" "$1"
  works_dev_refuse_claude_tmp real-run.sh "origin" "$1.origin.git"
else
  works_dev_refuse_claude_tmp real-run.sh "対象の置き場（TMPDIR）" "${TMPDIR:-/tmp}/works-real.x"
fi

# 対象を作る前に、認証が無いことを 1 行で知らせて止まる（archon.sh と同じ規則）。
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${WORKS_KEYCHAIN_ITEM:-}" ]; then
  echo "real-run.sh: 認証が無い。CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する" >&2
  exit 2
fi

if [ -z "${CLAUDE_BIN_PATH:-}" ]; then
  CLAUDE_BIN_PATH="$(command -v claude || true)"
  case "$CLAUDE_BIN_PATH" in /*) ;; *) CLAUDE_BIN_PATH="" ;; esac   # 関数・別名は実行ファイルでない
  if [ -z "$CLAUDE_BIN_PATH" ]; then
    echo "real-run.sh: claude の実行ファイルが PATH に無い。CLAUDE_BIN_PATH に絶対パスを設定する" >&2
    exit 2
  fi
fi
export CLAUDE_BIN_PATH

if [ "$#" -ge 1 ]; then
  DIR="$(sh "$DEV_DIR/mktarget.sh" "$1")"
else
  DIR="$(sh "$DEV_DIR/mktarget.sh" "$(mktemp -d "${TMPDIR:-/tmp}/works-real.XXXXXX")")"
fi
echo "対象: $DIR"

# Archon は run ごとに worktree を切り、その元を remote から fetch する（remote の無いリポジトリでは
# 切れずに止まる）。対象の外に裸のリポジトリを作って origin にする（対象の作業ツリーは汚さない）。
ORIGIN="$DIR.origin.git"
git init -q --bare "$ORIGIN"
git -C "$DIR" remote add origin "$ORIGIN"
git -C "$DIR" push -q origin HEAD
git -C "$DIR" fetch -q origin
git -C "$DIR" remote set-head origin -a >/dev/null

cd "$DIR"
set +e
sh "$DEV_DIR/archon.sh" workflow run darkfactory \
  --input request=request_ok.json --input test_cmd="python3 -m unittest -q"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# 一番新しい darkfactory の run を引き、run id・状態・修正の差分がある worktree と、次に打つコマンドを出す
# （問い合わせは認証が要らないので認証を読ませない）。修正は対象（$DIR）ではなく、Archon が run ごとに切った
# worktree の中にある。関所の文面の「テストのログ」の行が、テストの出力のファイル。
WORKS_DEV_NO_AUTH=1 sh "$DEV_DIR/archon.sh" workflow runs --json 2>/dev/null |
  DIR="$DIR" ARCHON_SH="$DEV_DIR/archon.sh" python3 -c '
import json, os, sys
runs = [r for r in json.load(sys.stdin).get("runs", []) if r.get("workflow_name") == "darkfactory"]
if not runs:
    sys.exit("real-run.sh: darkfactory の run が見つからない")
r = runs[0]
# 承認・続きも AI の節を回すので、認証（CLAUDE_CODE_OAUTH_TOKEN か WORKS_KEYCHAIN_ITEM）を設定した殻で打つ
go = "cd {} && WORKS_DEV_HOME={} WORKS_DEV_MODEL={} CLAUDE_BIN_PATH={} sh {} workflow".format(
    os.environ["DIR"], os.environ["WORKS_DEV_HOME"], os.environ["WORKS_DEV_MODEL"], os.environ["CLAUDE_BIN_PATH"],
    os.environ["ARCHON_SH"])
print("run id:", r.get("id"))
print("状態:", r.get("status"))
print("修正の差分がある worktree:", r.get("working_path"))
print("進める（承認するとその場で続きを回す）:", go, "approve", r.get("id"))
print("止める:", go, "reject", r.get("id"))
print("失敗や中断から続ける:", go, "resume", r.get("id"))
'
exit "$run_status"
