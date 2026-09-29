#!/bin/sh
# works/dev/real-run.sh [<dir>]
#
# ライン darkfactory を本物の AI で 1 回回す（費用が掛かる。回す前に持ち主の了承を取る）。
#   1. 模型は WORKS_DEV_MODEL（ここでは埋めない）。既定を解いて隔離した Archon の設定（$WORKS_DEV_HOME/archon-home/config.yaml）に
#      書くのは archon.sh（認証を使う実行のたび）。承認・続きのコマンドにも同じ指定（未設定なら空と、start の時の既定）を付けて出す。
#   2. mktarget.sh で <dir>（省略時は一時フォルダ）に使い捨ての対象を作り、<dir>.origin.git を origin に付ける
#      （Archon は run ごとに切る worktree の元を remote から取るため）。
#   3. その中で archon.sh workflow run darkfactory を前景で回す。人の関所で run は止まって戻る。
#   4. run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）を出す。
#      テストの緑赤とログのパスは、止まる直前に出る関所の文面にある。
# 認証は起こし役 .shared/core/auth_launch.py の check が拾う（順は起こし役が持つ。値は出さない）。
# 隔離した HOME からは ~/.local/bin/claude を自動で見つけられないので、CLAUDE_BIN_PATH を
# 隔離の前に解いて渡す（設定済みならそのまま）。開発の家の既定・claude の解決・入力 adapter の値は launch.py env が持つ。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
# 起こすのは start だけなので、start の時の既定の釘（続きの行だけが置く）は利用者の殻に残っていても受けない
unset WORKS_MODEL_PINNED

# 開発の家・対象・origin が Claude Code の一時フォルダの下なら、認証を確かめる前・何かを作る前に止まる（guard.sh）
. "$DEV_DIR/guard.sh"
works_dev_launch_env real-run.sh --claude
export WORKS_DEV_HOME WORKS_DEV_MODEL
works_dev_abs_claude_config
works_dev_refuse_claude_tmp real-run.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
if [ "$#" -ge 1 ]; then
  works_dev_refuse_claude_tmp real-run.sh "対象" "$1"
  works_dev_refuse_claude_tmp real-run.sh "origin" "$1.origin.git"
else
  works_dev_refuse_claude_tmp real-run.sh "対象の置き場（TMPDIR）" "${TMPDIR:-/tmp}/works-real.x"
fi

# 対象を作る前に、起こし役の check で認証を確かめ、無ければその 1 行の案内で止まる。拾った出どころの名は捨てる
# （名の行は archon.sh が出す）
python3 -I "$(cd "$DEV_DIR/.." && pwd -P)/.shared/core/auth_launch.py" check --for real-run.sh \
  --user-home "$HOME" --user-config "${CLAUDE_CONFIG_DIR:-}" >/dev/null || exit $?

CLAUDE_BIN_PATH="$WORKS_LAUNCH_CLAUDE"
if [ -z "$CLAUDE_BIN_PATH" ]; then
  echo "real-run.sh: claude の実行ファイルが PATH に無い。CLAUDE_BIN_PATH に絶対パスを設定する" >&2
  exit 2
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
# 包みを入れない run は adapter=optional（launch.py env の WORKS_LAUNCH_ADAPTER_MODE。h-judge が包みの無い run を止めないように。報告に出る）
sh "$DEV_DIR/archon.sh" workflow run darkfactory \
  --input request=request_ok.json --input test_cmd="python3 -m unittest -q" --input adapter="$WORKS_LAUNCH_ADAPTER_MODE"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# run id・状態・修正の差分がある worktree・次に打つコマンドを出す（lib.sh）
. "$DEV_DIR/lib.sh"
# 起動が落ちても run が在れば続きの行を出す（控えと herdr の枠の集計も lib.sh の同じ口で）。終了コードは起動のまま（起動が 0 の時だけ show の結果）
show_status=0
works_dev_show_started real-run.sh "$DEV_DIR/archon.sh" "$DIR" || show_status=$?
[ "$run_status" -ne 0 ] && exit "$run_status"
exit "$show_status"
