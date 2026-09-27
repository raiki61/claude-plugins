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
works_dev_abs_claude_config
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
# 包みを入れない run（WORKS_DEV_ADAPTER が 1 でない）は adapter=optional（h-judge が包みの無い run を止めないように。報告に出る）
if [ "${WORKS_DEV_ADAPTER:-}" = 1 ]; then ADAPTER_MODE=""; else ADAPTER_MODE="optional"; fi
sh "$DEV_DIR/archon.sh" workflow run darkfactory \
  --input request=request_ok.json --input test_cmd="python3 -m unittest -q" --input adapter="$ADAPTER_MODE"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# run id・状態・修正の差分がある worktree・次に打つコマンドを出す（lib.sh）
. "$DEV_DIR/lib.sh"
works_dev_show_run real-run.sh "$DEV_DIR/archon.sh" "$DIR"
exit "$run_status"
